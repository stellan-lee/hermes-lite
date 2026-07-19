"""Single-user OAuth 2.1 authorization server for Marlow's MCP endpoint."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Optional
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


MCP_OAUTH_SCOPE = "marlow:mcp"
ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
AUTHORIZATION_REQUEST_TTL_SECONDS = 10 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 5 * 60
MAX_LOGIN_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 5 * 60
MAX_REGISTRATIONS_PER_HOUR = 10
REGISTRATION_WINDOW_SECONDS = 60 * 60
MAX_OAUTH_FORM_BODY_BYTES = 8 * 1024
MAX_REGISTRATION_BODY_BYTES = 32 * 1024
MAX_OAUTH_FORM_FIELDS = 32


class _RequestBodyTooLarge(ValueError):
    pass


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_response(content: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return _json_response(
        {"error": error, "error_description": description},
        status_code=status_code,
    )


async def _read_limited_body(request: Request, maximum: int) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if parsed_length > maximum:
            raise _RequestBodyTooLarge

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise _RequestBodyTooLarge
        body.extend(chunk)
    return bytes(body)


async def _read_form(request: Request) -> dict[str, str]:
    body = await _read_limited_body(request, MAX_OAUTH_FORM_BODY_BYTES)
    parsed = parse_qs(
        body.decode("utf-8"),
        keep_blank_values=True,
        max_num_fields=MAX_OAUTH_FORM_FIELDS,
    )
    if any(len(values) != 1 for values in parsed.values()):
        raise ValueError("duplicate form parameter")
    return {key: values[0] for key, values in parsed.items()}


class MarlowOAuthProvider:
    """Persistent public-client OAuth provider with opaque hashed tokens."""

    def __init__(self, *, database_path: Path, public_url: str, password: str):
        self.database_path = database_path
        self.public_url = public_url.rstrip("/")
        # Pydantic's AnyHttpUrl canonicalizes an origin-only issuer with a
        # trailing slash. Publish that exact identifier in every OAuth
        # metadata document so strict RFC 8414 clients do not reject discovery.
        self.issuer_url = f"{self.public_url}/"
        self.resource_url = f"{self.public_url}/mcp"
        self._password = password
        self._lock = threading.RLock()
        self._failed_logins: dict[str, Deque[float]] = defaultdict(deque)
        self._registrations: dict[str, Deque[float]] = defaultdict(deque)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.database_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oauth_authorization_requests (
                    request_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(client_id) REFERENCES oauth_clients(client_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                    code_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    redirect_uri_explicit INTEGER NOT NULL,
                    code_challenge TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(client_id) REFERENCES oauth_clients(client_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                    token_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(client_id) REFERENCES oauth_clients(client_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                    token_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(client_id) REFERENCES oauth_clients(client_id)
                        ON DELETE CASCADE
                );
                """
            )
        os.chmod(self.database_path, 0o600)

    def _prune_expired(self, conn: sqlite3.Connection, now: int) -> None:
        conn.execute(
            "DELETE FROM oauth_authorization_requests WHERE expires_at < ?", (now,)
        )
        conn.execute(
            "DELETE FROM oauth_authorization_codes WHERE expires_at < ?", (now,)
        )
        conn.execute("DELETE FROM oauth_access_tokens WHERE expires_at < ?", (now,))
        conn.execute("DELETE FROM oauth_refresh_tokens WHERE expires_at < ?", (now,))

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row["metadata_json"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("OAuth client_id is required")
        if (
            client_info.token_endpoint_auth_method != "none"
            or client_info.client_secret
        ):
            raise ValueError("Marlow OAuth only supports public clients")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO oauth_clients(client_id, metadata_json, created_at) "
                "VALUES (?, ?, ?)",
                (
                    client_info.client_id,
                    client_info.model_dump_json(),
                    int(time.time()),
                ),
            )

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if params.resource != self.resource_url:
            raise AuthorizeError(
                error="invalid_request",
                error_description="resource must match the Marlow MCP URL",
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError(
                error="invalid_request",
                error_description="invalid PKCE S256 code challenge",
            )
        scopes = params.scopes or [MCP_OAUTH_SCOPE]
        if set(scopes) != {MCP_OAUTH_SCOPE}:
            raise AuthorizeError(
                error="invalid_scope",
                error_description=f"only {MCP_OAUTH_SCOPE} is supported",
            )
        if client.client_id is None:
            raise AuthorizeError(
                error="invalid_request",
                error_description="client_id is required",
            )

        request_id = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + AUTHORIZATION_REQUEST_TTL_SECONDS
        payload = {
            "state": params.state,
            "scopes": scopes,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        }
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, int(time.time()))
            conn.execute(
                "INSERT INTO oauth_authorization_requests"
                "(request_id, client_id, params_json, expires_at) VALUES (?, ?, ?, ?)",
                (request_id, client.client_id, json.dumps(payload), expires_at),
            )
        return f"{self.public_url}/oauth/consent?request_id={request_id}"

    def get_authorization_request(
        self, request_id: str
    ) -> tuple[OAuthClientInformationFull, dict[str, Any]] | None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, now)
            row = conn.execute(
                "SELECT r.params_json, c.metadata_json "
                "FROM oauth_authorization_requests r "
                "JOIN oauth_clients c ON c.client_id = r.client_id "
                "WHERE r.request_id = ? AND r.expires_at >= ?",
                (request_id, now),
            ).fetchone()
        if row is None:
            return None
        client = OAuthClientInformationFull.model_validate_json(row["metadata_json"])
        return client, json.loads(row["params_json"])

    def complete_authorization(self, request_id: str) -> str | None:
        now = int(time.time())
        code = secrets.token_urlsafe(32)
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, now)
            row = conn.execute(
                "SELECT client_id, params_json FROM oauth_authorization_requests "
                "WHERE request_id = ? AND expires_at >= ?",
                (request_id, now),
            ).fetchone()
            if row is None:
                return None
            params = json.loads(row["params_json"])
            deleted = conn.execute(
                "DELETE FROM oauth_authorization_requests WHERE request_id = ?",
                (request_id,),
            )
            if deleted.rowcount != 1:
                return None
            conn.execute(
                "INSERT INTO oauth_authorization_codes"
                "(code_hash, client_id, scopes_json, redirect_uri, "
                "redirect_uri_explicit, code_challenge, resource, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _token_digest(code),
                    row["client_id"],
                    json.dumps(params["scopes"]),
                    params["redirect_uri"],
                    int(params["redirect_uri_provided_explicitly"]),
                    params["code_challenge"],
                    params["resource"],
                    now + AUTHORIZATION_CODE_TTL_SECONDS,
                ),
            )
        return construct_redirect_uri(
            params["redirect_uri"],
            code=code,
            state=params.get("state"),
        )

    def deny_authorization(self, request_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT params_json FROM oauth_authorization_requests "
                "WHERE request_id = ? AND expires_at >= ?",
                (request_id, int(time.time())),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM oauth_authorization_requests WHERE request_id = ?",
                (request_id,),
            )
        params = json.loads(row["params_json"])
        return construct_redirect_uri(
            params["redirect_uri"],
            error="access_denied",
            error_description="The Marlow owner denied access",
            state=params.get("state"),
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, now)
            row = conn.execute(
                "SELECT * FROM oauth_authorization_codes "
                "WHERE code_hash = ? AND expires_at >= ?",
                (_token_digest(authorization_code), now),
            ).fetchone()
        if row is None or row["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=json.loads(row["scopes_json"]),
            expires_at=float(row["expires_at"]),
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=bool(row["redirect_uri_explicit"]),
            resource=row["resource"],
        )

    def _issue_token_pair(
        self,
        conn: sqlite3.Connection,
        *,
        client_id: str,
        scopes: list[str],
        family_id: Optional[str] = None,
    ) -> OAuthToken:
        now = int(time.time())
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        family = family_id or secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO oauth_access_tokens"
            "(token_hash, client_id, scopes_json, resource, family_id, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _token_digest(access_token),
                client_id,
                json.dumps(scopes),
                self.resource_url,
                family,
                now + ACCESS_TOKEN_TTL_SECONDS,
            ),
        )
        conn.execute(
            "INSERT INTO oauth_refresh_tokens"
            "(token_hash, client_id, scopes_json, family_id, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _token_digest(refresh_token),
                client_id,
                json.dumps(scopes),
                family,
                now + REFRESH_TOKEN_TTL_SECONDS,
            ),
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        if client.client_id is None:
            raise TokenError("invalid_client", "client_id is required")
        with self._lock, self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM oauth_authorization_codes "
                "WHERE code_hash = ? AND client_id = ?",
                (_token_digest(authorization_code.code), client.client_id),
            )
            if deleted.rowcount != 1:
                raise TokenError("invalid_grant", "authorization code was already used")
            return self._issue_token_pair(
                conn,
                client_id=client.client_id,
                scopes=authorization_code.scopes,
            )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, now)
            row = conn.execute(
                "SELECT * FROM oauth_refresh_tokens "
                "WHERE token_hash = ? AND expires_at >= ?",
                (_token_digest(refresh_token), now),
            ).fetchone()
        if row is None or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=row["expires_at"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if client.client_id is None:
            raise TokenError("invalid_client", "client_id is required")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT family_id FROM oauth_refresh_tokens "
                "WHERE token_hash = ? AND client_id = ?",
                (_token_digest(refresh_token.token), client.client_id),
            ).fetchone()
            if row is None:
                raise TokenError("invalid_grant", "refresh token was already used")
            family_id = row["family_id"]
            conn.execute(
                "DELETE FROM oauth_access_tokens WHERE family_id = ?", (family_id,)
            )
            conn.execute(
                "DELETE FROM oauth_refresh_tokens WHERE family_id = ?", (family_id,)
            )
            return self._issue_token_pair(
                conn,
                client_id=client.client_id,
                scopes=scopes,
                family_id=family_id,
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            self._prune_expired(conn, now)
            row = conn.execute(
                "SELECT * FROM oauth_access_tokens "
                "WHERE token_hash = ? AND expires_at >= ? AND resource = ?",
                (_token_digest(token), now, self.resource_url),
            ).fetchone()
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=row["expires_at"],
            resource=row["resource"],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Implement the MCP SDK TokenVerifier protocol."""
        return await self.load_access_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        digest = _token_digest(token.token)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT family_id FROM oauth_access_tokens WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT family_id FROM oauth_refresh_tokens WHERE token_hash = ?",
                    (digest,),
                ).fetchone()
            if row is not None:
                conn.execute(
                    "DELETE FROM oauth_access_tokens WHERE family_id = ?",
                    (row["family_id"],),
                )
                conn.execute(
                    "DELETE FROM oauth_refresh_tokens WHERE family_id = ?",
                    (row["family_id"],),
                )

    def login_allowed(self, client_key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            attempts = self._failed_logins[client_key]
            while attempts and now - attempts[0] > LOGIN_FAILURE_WINDOW_SECONDS:
                attempts.popleft()
            return len(attempts) < MAX_LOGIN_FAILURES

    def verify_password(self, client_key: str, candidate: str) -> bool:
        if not self.login_allowed(client_key):
            return False
        valid = hmac.compare_digest(
            candidate.encode("utf-8"), self._password.encode("utf-8")
        )
        with self._lock:
            if valid:
                self._failed_logins.pop(client_key, None)
            else:
                self._failed_logins[client_key].append(time.monotonic())
        return valid

    def registration_allowed(self, client_key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            attempts = self._registrations[client_key]
            while attempts and now - attempts[0] > REGISTRATION_WINDOW_SECONDS:
                attempts.popleft()
            return len(attempts) < MAX_REGISTRATIONS_PER_HOUR

    def record_registration(self, client_key: str) -> None:
        with self._lock:
            self._registrations[client_key].append(time.monotonic())


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _consent_html(
    *,
    request_id: str,
    client_name: str,
    scopes: list[str],
    redirect_uri: str,
    error: str | None = None,
) -> str:
    error_html = (
        f'<p class="error">{html.escape(error)}</p>' if error is not None else ""
    )
    scope_items = "".join(f"<li>{html.escape(scope)}</li>" for scope in scopes)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorize Marlow</title>
  <style>
    body {{ font: 16px system-ui, sans-serif; max-width: 34rem; margin: 4rem auto;
            padding: 0 1rem; color: #1f2937; background: #f8fafc; }}
    main {{ background: white; padding: 2rem; border-radius: 12px;
            box-shadow: 0 8px 30px #0f172a1a; }}
    input {{ box-sizing: border-box; width: 100%; padding: .75rem; margin: .5rem 0 1rem; }}
    .actions {{ display: flex; gap: .75rem; }}
    button {{ padding: .7rem 1rem; border-radius: 8px; border: 0; cursor: pointer; }}
    .approve {{ color: white; background: #2563eb; }}
    .deny {{ color: #334155; background: #e2e8f0; }}
    .error {{ color: #b91c1c; }}
  </style>
</head>
<body><main>
  <h1>Authorize Marlow</h1>
  <p><strong>{html.escape(client_name)}</strong> is requesting access to this Marlow server.</p>
  <p>The result will return to <code>{html.escape(redirect_uri)}</code>. Only approve
     if you started this request from a client you trust.</p>
  <ul>{scope_items}</ul>
  {error_html}
  <form method="post" action="/oauth/consent">
    <input type="hidden" name="request_id" value="{html.escape(request_id, quote=True)}">
    <label for="password">Marlow OAuth password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <div class="actions">
      <button class="approve" type="submit" name="action" value="approve">Authorize</button>
      <button class="deny" type="submit" name="action" value="deny" formnovalidate>Deny</button>
    </div>
  </form>
</main></body></html>"""


def _consent_response(
    body: str,
    *,
    status_code: int = 200,
    extra_headers: Optional[dict[str, str]] = None,
) -> HTMLResponse:
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'"
        ),
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    headers.update(extra_headers or {})
    return HTMLResponse(body, status_code=status_code, headers=headers)


def install_oauth_routes(server: Any, provider: MarlowOAuthProvider) -> None:
    """Install ChatGPT-compatible OAuth endpoints on a FastMCP server."""

    from mcp.server.auth.handlers.authorize import AuthorizationHandler

    authorization_handler = AuthorizationHandler(provider)

    @server.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def authorization_metadata(_request: Request) -> Response:
        return _json_response({
            "issuer": provider.issuer_url,
            "authorization_endpoint": f"{provider.public_url}/authorize",
            "token_endpoint": f"{provider.public_url}/token",
            "registration_endpoint": f"{provider.public_url}/register",
            "revocation_endpoint": f"{provider.public_url}/revoke",
            "scopes_supported": [MCP_OAUTH_SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
        })

    @server.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def protected_resource_metadata(_request: Request) -> Response:
        return _json_response({
            "resource": provider.resource_url,
            "authorization_servers": [provider.issuer_url],
            "scopes_supported": [MCP_OAUTH_SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "Marlow MCP",
        })

    @server.custom_route("/register", methods=["POST"])
    async def register(request: Request) -> Response:
        key = _client_key(request)
        if not provider.registration_allowed(key):
            return JSONResponse(
                {
                    "error": "temporarily_unavailable",
                    "error_description": "client registration rate limit exceeded",
                },
                status_code=429,
                headers={"Cache-Control": "no-store", "Retry-After": "3600"},
            )
        try:
            raw_body = await _read_limited_body(request, MAX_REGISTRATION_BODY_BYTES)
            body = json.loads(raw_body)
            metadata = OAuthClientMetadata.model_validate(body)
        except _RequestBodyTooLarge:
            return _oauth_error(
                "invalid_client_metadata",
                "client registration request is too large",
                status_code=413,
            )
        except (ValueError, ValidationError):
            return _oauth_error("invalid_client_metadata", "invalid client metadata")

        auth_method = metadata.token_endpoint_auth_method or "none"
        if auth_method != "none":
            return _oauth_error(
                "invalid_client_metadata",
                "only token_endpoint_auth_method=none is supported",
            )
        if not {"authorization_code", "refresh_token"}.issubset(
            set(metadata.grant_types)
        ):
            return _oauth_error(
                "invalid_client_metadata",
                "grant_types must include authorization_code and refresh_token",
            )
        if "code" not in metadata.response_types:
            return _oauth_error(
                "invalid_client_metadata", "response_types must include code"
            )

        for redirect_uri in metadata.redirect_uris or []:
            parsed = urlparse(str(redirect_uri))
            loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
                or (
                    parsed.scheme != "https"
                    and not (parsed.scheme == "http" and loopback)
                )
            ):
                return _oauth_error(
                    "invalid_redirect_uri",
                    "redirect URIs must use HTTPS or loopback HTTP",
                )

        requested_scopes = set((metadata.scope or MCP_OAUTH_SCOPE).split())
        if requested_scopes != {MCP_OAUTH_SCOPE}:
            return _oauth_error(
                "invalid_client_metadata", f"only {MCP_OAUTH_SCOPE} is supported"
            )
        metadata.token_endpoint_auth_method = "none"
        metadata.scope = MCP_OAUTH_SCOPE
        client = OAuthClientInformationFull(
            **metadata.model_dump(),
            client_id=secrets.token_urlsafe(24),
            client_secret=None,
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=None,
        )
        try:
            await provider.register_client(client)
        except sqlite3.IntegrityError:
            return _oauth_error("invalid_client_metadata", "client registration failed")
        provider.record_registration(key)
        return _json_response(
            client.model_dump(mode="json", exclude_none=True), status_code=201
        )

    @server.custom_route("/authorize", methods=["GET"])
    async def authorize(request: Request) -> Response:
        return await authorization_handler.handle(request)

    @server.custom_route("/oauth/consent", methods=["GET", "POST"])
    async def consent(request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request_id", "")
            pending = provider.get_authorization_request(request_id)
            if pending is None:
                return HTMLResponse("Authorization request expired", status_code=400)
            client, params = pending
            return _consent_response(
                _consent_html(
                    request_id=request_id,
                    client_name=client.client_name or "ChatGPT",
                    scopes=params["scopes"],
                    redirect_uri=params["redirect_uri"],
                ),
            )

        try:
            form = await _read_form(request)
        except _RequestBodyTooLarge:
            return _consent_response("Request too large", status_code=413)
        except (UnicodeDecodeError, ValueError):
            return _consent_response("Invalid form request", status_code=400)
        request_id = str(form.get("request_id", ""))
        action = str(form.get("action", ""))
        pending = provider.get_authorization_request(request_id)
        if pending is None:
            return HTMLResponse("Authorization request expired", status_code=400)
        client, params = pending
        if action == "deny":
            redirect = provider.deny_authorization(request_id)
            if redirect is None:
                return HTMLResponse("Authorization request expired", status_code=400)
            return RedirectResponse(redirect, status_code=303)

        key = _client_key(request)
        if not provider.login_allowed(key):
            return _consent_response(
                _consent_html(
                    request_id=request_id,
                    client_name=client.client_name or "ChatGPT",
                    scopes=params["scopes"],
                    redirect_uri=params["redirect_uri"],
                    error="Too many failed attempts. Try again later.",
                ),
                status_code=429,
                extra_headers={"Retry-After": "300"},
            )
        password = str(form.get("password", ""))
        if action != "approve" or not provider.verify_password(key, password):
            return _consent_response(
                _consent_html(
                    request_id=request_id,
                    client_name=client.client_name or "ChatGPT",
                    scopes=params["scopes"],
                    redirect_uri=params["redirect_uri"],
                    error="Invalid password.",
                ),
                status_code=401,
            )
        redirect = provider.complete_authorization(request_id)
        if redirect is None:
            return HTMLResponse("Authorization request expired", status_code=400)
        return RedirectResponse(redirect, status_code=303)

    @server.custom_route("/token", methods=["POST"])
    async def token(request: Request) -> Response:
        try:
            form = await _read_form(request)
        except _RequestBodyTooLarge:
            return _oauth_error("invalid_request", "token request is too large", 413)
        except (UnicodeDecodeError, ValueError):
            return _oauth_error("invalid_request", "invalid token request")
        client_id = str(form.get("client_id", ""))
        client = await provider.get_client(client_id)
        if client is None:
            return _oauth_error("invalid_client", "unknown client", status_code=401)
        if str(form.get("resource", "")) != provider.resource_url:
            return _oauth_error(
                "invalid_target", "resource must match the Marlow MCP URL"
            )

        grant_type = str(form.get("grant_type", ""))
        if grant_type == "authorization_code":
            raw_code = str(form.get("code", ""))
            code = await provider.load_authorization_code(client, raw_code)
            if code is None or code.expires_at < time.time():
                return _oauth_error("invalid_grant", "invalid authorization code")
            if code.resource != provider.resource_url:
                return _oauth_error(
                    "invalid_grant", "authorization code audience mismatch"
                )
            redirect_uri = str(form.get("redirect_uri", ""))
            expected_redirect = (
                str(code.redirect_uri) if code.redirect_uri_provided_explicitly else ""
            )
            if redirect_uri != expected_redirect:
                return _oauth_error("invalid_grant", "redirect_uri mismatch")
            verifier = str(form.get("code_verifier", ""))
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                return _oauth_error("invalid_grant", "invalid PKCE verifier")
            challenge = (
                base64
                .urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
                .decode("ascii")
                .rstrip("=")
            )
            if not hmac.compare_digest(challenge, code.code_challenge):
                return _oauth_error("invalid_grant", "invalid PKCE verifier")
            try:
                tokens = await provider.exchange_authorization_code(client, code)
            except TokenError as exc:
                return _oauth_error(exc.error, exc.error_description or "token error")
        elif grant_type == "refresh_token":
            raw_refresh = str(form.get("refresh_token", ""))
            refresh = await provider.load_refresh_token(client, raw_refresh)
            if refresh is None or (
                refresh.expires_at is not None and refresh.expires_at < time.time()
            ):
                return _oauth_error("invalid_grant", "invalid refresh token")
            scopes = str(form.get("scope", "")).split() or refresh.scopes
            if not set(scopes).issubset(refresh.scopes):
                return _oauth_error("invalid_scope", "scope exceeds original grant")
            try:
                tokens = await provider.exchange_refresh_token(client, refresh, scopes)
            except TokenError as exc:
                return _oauth_error(exc.error, exc.error_description or "token error")
        else:
            return _oauth_error("unsupported_grant_type", "unsupported grant_type")

        return _json_response(tokens.model_dump(mode="json", exclude_none=True))

    @server.custom_route("/revoke", methods=["POST"])
    async def revoke(request: Request) -> Response:
        try:
            form = await _read_form(request)
        except _RequestBodyTooLarge:
            return _oauth_error(
                "invalid_request", "revocation request is too large", 413
            )
        except (UnicodeDecodeError, ValueError):
            return _oauth_error("invalid_request", "invalid revocation request")
        client_id = str(form.get("client_id", ""))
        client = await provider.get_client(client_id)
        if client is None:
            return _oauth_error("invalid_client", "unknown client", status_code=401)
        raw_token = str(form.get("token", ""))
        stored: AccessToken | RefreshToken | None = await provider.load_access_token(
            raw_token
        )
        if stored is None:
            stored = await provider.load_refresh_token(client, raw_token)
        if stored is not None and stored.client_id == client_id:
            await provider.revoke_token(stored)
        return Response(status_code=200, headers={"Cache-Control": "no-store"})
