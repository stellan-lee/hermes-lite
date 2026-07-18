"""Mandatory safety boundary for durable work experience text.

Experience is injected into later model requests, so its redaction policy is
intentionally stricter than logging redaction and cannot be disabled by user
configuration.  Call :func:`sanitize_for_storage` immediately before hashing
or writing text and :func:`sanitize_for_return` immediately before returning
stored text to a caller.  Both functions perform the complete pipeline.

This module is deliberately independent of ``experience.models``.  Enum-like
values are accepted through their ``.value`` attribute so models and storage
can use these helpers without creating an import cycle.
"""

from __future__ import annotations

import math
import ntpath
import posixpath
import re
import unicodedata
from collections import Counter
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit, urlunsplit

from agent.redact import redact_sensitive_text
from tools.threat_patterns import INVISIBLE_CHARS, scan_for_threats


REDACTED = "[REDACTED]"
DEFAULT_MAX_CHARS = 16_384
MAX_ALLOWED_CHARS = 65_536

_SENSITIVITY_RANK = {
    "normal": 0,
    "private_repo": 1,
    "local_only": 2,
    "blocked": 3,
}
_EGRESS_RANK = {
    "local_only": 0,
    "same_provider_trust_domain": 1,
    "explicit_any_provider": 2,
}

_URL_RE = re.compile(
    r"(?P<url>(?:(?:git\+)?https?|wss?|ftp|ssh|git)://[^\s<>{}\[\]\"']+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Z0-9._%+-]+)@([A-Z0-9.-]+\.[A-Z]{2,63})(?![\w.-])",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+[1-9]\d{6,14}|(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]\d{3}[-. ]\d{4})(?![\w.])"
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----[\s\S]*?"
    r"(?:-----END(?: [A-Z0-9]+)* PRIVATE KEY-----|\Z)",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"(?im)\b(authorization|proxy-authorization)\s*:\s*(?:bearer|basic|token)?\s*[^\s,;]+"
)
_LABELLED_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|password|passwd|credential|private[_-]?key|secret)\b"
    r"(\s*[=:]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_KNOWN_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:sk[-_][A-Za-z0-9_-]{10,}|github_pat_[A-Za-z0-9_]{10,}|"
    r"gh[pousr]_[A-Za-z0-9]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}|pypi-[A-Za-z0-9_-]{10,}|"
    r"npm_[A-Za-z0-9]{10,}|hf_[A-Za-z0-9]{10,})(?![A-Za-z0-9_-])"
)
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z0-9][A-Za-z0-9_+/=-]{31,})(?![A-Za-z0-9_])")
_MASKED_TOKEN_RE = re.compile(r"(?<!\w)[A-Za-z0-9_.-]{2,16}\.\.\.[A-Za-z0-9_-]{2,8}(?!\w)")
_ABS_POSIX_TEXT_RE = re.compile(
    r"(?<![\w:/~])/(?!/)(?:[^/\s]+/)+[^/\s,;:!?\"'<>()\[\]{}]+"
)
_ABS_WINDOWS_TEXT_RE = re.compile(
    r"(?i)(?<![\w])(?:[A-Z]:[\\/](?:[^\\/\s]+[\\/])+[^\\/\s,;:!?\"'<>()\[\]{}]+)"
)
_UNC_TEXT_RE = re.compile(
    r"(?<![\w:])(?:\\\\|//)(?:[^\\/\s]+[\\/])+[^\\/\s,;:!?\"'<>()\[\]{}]+"
)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9a-f]{2}", re.IGNORECASE)
_TRUST_DOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9._:/-]{0,126}[a-z0-9])?")

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token", "refreshtoken", "refresh_token", "id_token", "token",
        "api_key", "apikey", "client_secret", "password", "auth", "jwt",
        "session", "secret", "key", "code", "signature", "sig", "policy",
        "credential", "awsaccesskeyid", "googleaccessid", "key-pair-id",
        "x-amz-signature", "x-amz-credential", "x-goog-signature",
    }
)
_PRESIGN_KEY_PREFIXES = ("x-amz-", "x-goog-")


class ExperienceSafetyError(ValueError):
    """Base class for rejected experience content or policy values."""


class ExperienceThreatError(ExperienceSafetyError):
    """Raised when durable text contains a strict threat pattern."""

    def __init__(self, findings: list[str] | tuple[str, ...], field_name: str = "text"):
        self.findings = tuple(findings)
        safe_field = re.sub(r"[^A-Za-z0-9_.-]", "_", str(field_name))[:64] or "text"
        super().__init__(
            f"Experience field {safe_field!r} rejected by strict threat scan: "
            + ", ".join(self.findings)
        )


class ExperienceEgressError(ExperienceSafetyError):
    """Raised when an item cannot be disclosed to the current provider."""


def _scalar(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw.strip().lower() if isinstance(raw, str) else ""


def validate_sensitivity(value: object) -> str:
    """Return a canonical sensitivity string, rejecting unknown values."""
    normalized = _scalar(value)
    if normalized not in _SENSITIVITY_RANK:
        raise ExperienceSafetyError("Unknown experience sensitivity")
    return normalized


def validate_egress_policy(value: object) -> str:
    """Return a canonical egress policy string, rejecting unknown values."""
    normalized = _scalar(value)
    if normalized not in _EGRESS_RANK:
        raise ExperienceSafetyError("Unknown experience egress policy")
    return normalized


def merge_sensitivity(current: object, proposed: object) -> str:
    """Return the more restrictive value; untrusted input cannot downgrade it."""
    current_value = validate_sensitivity(current)
    proposed_value = validate_sensitivity(proposed)
    return max((current_value, proposed_value), key=_SENSITIVITY_RANK.__getitem__)


def normalize_trust_domain(value: object) -> str:
    """Canonicalize a non-secret provider trust-domain identifier."""
    normalized = _scalar(value)
    if not normalized or not _TRUST_DOMAIN_RE.fullmatch(normalized):
        raise ExperienceSafetyError("Invalid provider trust domain")
    return normalized


def is_egress_allowed(
    sensitivity: object,
    egress_policy: object,
    producer_trust_domain: object | None,
    current_trust_domain: object | None,
    current_provider_is_local: bool,
    max_egress_policy: object | None = None,
) -> bool:
    """Fail-closed disclosure check for an experience item.

    Locality is an explicit caller assertion; it is never inferred from a
    magic trust-domain value.  ``private_repo`` items may be sent only to the
    producer's trust domain (or kept local), even when the item says
    ``explicit_any_provider``.  A project ``max_egress_policy`` can only make
    the item policy more restrictive.
    """
    try:
        sensitivity_value = validate_sensitivity(sensitivity)
        policy_value = validate_egress_policy(egress_policy)
        if max_egress_policy is not None:
            ceiling = validate_egress_policy(max_egress_policy)
            policy_value = min((policy_value, ceiling), key=_EGRESS_RANK.__getitem__)
    except ExperienceSafetyError:
        return False

    if sensitivity_value == "blocked":
        return False
    if current_provider_is_local is True:
        return True
    if current_provider_is_local is not False or sensitivity_value == "local_only":
        return False
    if policy_value == "local_only":
        return False

    try:
        current_domain = normalize_trust_domain(current_trust_domain)
    except ExperienceSafetyError:
        return False

    producer_domain = ""
    if producer_trust_domain is not None:
        try:
            producer_domain = normalize_trust_domain(producer_trust_domain)
        except ExperienceSafetyError:
            return False

    same_domain = bool(producer_domain) and producer_domain == current_domain
    if sensitivity_value == "private_repo" and not same_domain:
        return False
    if policy_value == "same_provider_trust_domain":
        return same_domain
    return policy_value == "explicit_any_provider"


def require_egress_allowed(*args: object, **kwargs: object) -> None:
    """Raise :class:`ExperienceEgressError` when disclosure is denied."""
    if not is_egress_allowed(*args, **kwargs):
        raise ExperienceEgressError("Experience item is not eligible for provider egress")


def _entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _bounded_unquote(value: str) -> str:
    """Decode nested URL escapes to a small fixed point."""

    decoded = value
    for _ in range(8):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _looks_secret(value: str) -> bool:
    decoded = _bounded_unquote(value)
    if len(decoded) < 32:
        return False
    # Hashes and other opaque identifiers belong in typed provenance fields,
    # not generic model-visible prose.  Character-class heuristics are easy to
    # evade with lowercase-only credentials, so entropy is the hard boundary.
    return _entropy(decoded) >= 3.5


def _sanitize_query(query: str) -> str:
    parts = re.split(r"([&;])", query)
    pairs = parts[::2]
    if len(pairs) > 64:
        return f"query={REDACTED}"
    decoded_keys = [
        _bounded_unquote(pair.partition("=")[0]).lower() for pair in pairs
    ]
    # Presigned URLs are all-or-nothing credentials, so redact every query
    # value when a provider signature field is present. Ordinary sensitive
    # fields (for example ``access_token``) redact only their own value; a
    # benign sibling such as ``ok=1`` remains useful structural context.
    presigned = any(
        key.startswith(_PRESIGN_KEY_PREFIXES) for key in decoded_keys
    )
    sanitized_pairs: list[str] = []
    for pair, key in zip(pairs, decoded_keys):
        raw_key, separator, value = pair.partition("=")
        decoded_value = _bounded_unquote(value)
        sensitive = (
            presigned
            or key in _SENSITIVE_QUERY_KEYS
            or key.startswith(_PRESIGN_KEY_PREFIXES)
            or _looks_secret(key)
            or bool(_EMAIL_RE.search(key))
            or bool(_PHONE_RE.search(key))
            or bool(_PERCENT_ESCAPE_RE.search(key))
            or _looks_secret(value)
            or bool(_EMAIL_RE.search(decoded_value))
            or bool(_PHONE_RE.search(decoded_value))
            or bool(_PERCENT_ESCAPE_RE.search(decoded_value))
        )
        sanitized_pairs.append(
            f"{raw_key}={REDACTED}" if separator and sensitive else pair
        )
    result: list[str] = []
    for index, pair in enumerate(sanitized_pairs):
        result.append(pair)
        separator_index = (index * 2) + 1
        if separator_index < len(parts):
            result.append(parts[separator_index])
    return "".join(result)


def normalize_experience_url(url: str, *, max_chars: int = 4096) -> str:
    """Strip URL userinfo and redact signed, sensitive, or opaque query data."""
    if not isinstance(url, str):
        raise TypeError("url must be a string")
    if not url or len(url) > max_chars:
        raise ExperienceSafetyError("Experience URL is empty or too long")
    try:
        parts = urlsplit(url)
        if not parts.scheme or not parts.hostname:
            raise ValueError
        host = parts.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        netloc = f"{host}:{port}" if port is not None else host
    except (TypeError, ValueError):
        raise ExperienceSafetyError("Invalid experience URL") from None
    query = _sanitize_query(parts.query) if parts.query else ""
    # Fragments are not required for structural recall and commonly carry
    # OAuth/reset credentials, including short values that entropy heuristics
    # cannot identify reliably.
    fragment = REDACTED if parts.fragment else ""
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, query, fragment))


def _normalize_urls_in_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = match.group("url")
        trailing = ""
        while url and url[-1] in ".,;!?)":
            trailing = url[-1] + trailing
            url = url[:-1]
        try:
            return normalize_experience_url(url) + trailing
        except ExperienceSafetyError:
            return "[REDACTED URL]" + trailing

    return _URL_RE.sub(replace, text)


def normalize_experience_path(path: str, *, repository_root: str | None = None) -> str:
    """Return a lexical, privacy-safe display path without filesystem access."""
    if not isinstance(path, str):
        raise TypeError("path must be a string")
    value = path.strip()
    if not value or "\x00" in value:
        raise ExperienceSafetyError("Invalid experience path")
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith(
        ("\\\\", "//")
    )
    path_module = ntpath if windows else posixpath
    normalized = path_module.normpath(value)
    if repository_root:
        root = path_module.normpath(repository_root)
        try:
            if path_module.commonpath((root, normalized)) == root:
                relative = path_module.relpath(normalized, root)
                return "." if relative == "." else relative.replace("\\", "/")
        except ValueError:
            pass
    if path_module.isabs(normalized):
        name = (PureWindowsPath(normalized) if windows else PurePosixPath(normalized)).name
        return f"<absolute>/{name or 'path'}"
    if normalized == ".." or normalized.startswith(("../", "..\\")):
        name = (PureWindowsPath(normalized) if windows else PurePosixPath(normalized)).name
        return f"<outside>/{name or 'path'}"
    return normalized.replace("\\", "/")


def _normalize_paths_in_text(text: str, repository_root: str | None) -> str:
    if repository_root:
        root = repository_root.rstrip("/\\")
        if root:
            text = re.sub(re.escape(root) + r"(?=$|[/\\])", "<repo>", text)
    def redact_path(match: re.Match[str]) -> str:
        return normalize_experience_path(match.group(0))

    # URL normalization runs next, so avoid matching URL path components and
    # redact standalone absolute paths even when no repository root is known.
    text = _UNC_TEXT_RE.sub(redact_path, text)
    text = _ABS_WINDOWS_TEXT_RE.sub(redact_path, text)
    return _ABS_POSIX_TEXT_RE.sub(redact_path, text)


def _sanitize(
    text: str,
    *,
    field_name: str,
    max_chars: int,
    repository_root: str | None,
) -> str:
    if not isinstance(text, str):
        raise TypeError("experience text must be a string")
    if not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_ALLOWED_CHARS:
        raise ExperienceSafetyError("Invalid experience text size limit")
    if len(text) > max_chars:
        raise ExperienceSafetyError("Experience text exceeds its size limit")

    # Normalize controls before scanning so NUL/control insertion cannot split
    # a threat phrase. Known invisible injection characters are remembered and
    # rejected even though all remaining format/control characters are removed.
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    invisible_findings = [
        f"invisible_unicode_U+{ord(ch):04X}"
        for ch in set(cleaned) & INVISIBLE_CHARS
    ]
    cleaned = "".join(
        ch
        for ch in cleaned
        if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf"}
    )
    cleaned = _normalize_paths_in_text(cleaned, repository_root)
    cleaned = _normalize_urls_in_text(cleaned)
    cleaned = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", cleaned)
    cleaned = _AUTH_RE.sub(lambda m: f"{m.group(1)}: {REDACTED}", cleaned)
    cleaned = _LABELLED_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", cleaned)
    cleaned = _KNOWN_SECRET_RE.sub(REDACTED, cleaned)
    cleaned = _TOKEN_RE.sub(lambda m: REDACTED if _looks_secret(m.group(1)) else m.group(1), cleaned)
    cleaned = _EMAIL_RE.sub(REDACTED, cleaned)
    cleaned = _PHONE_RE.sub(REDACTED, cleaned)
    cleaned = _SSN_RE.sub(REDACTED, cleaned)

    # The shared helper is always forced, regardless of the process-wide
    # logging opt-out.  Collapse its partial debug masks at this durable
    # boundary so no credential prefix/suffix is retained.
    cleaned = redact_sensitive_text(cleaned, force=True)
    cleaned = _MASKED_TOKEN_RE.sub(REDACTED, cleaned)

    findings = list(
        dict.fromkeys(
            [*sorted(invisible_findings), *scan_for_threats(cleaned, scope="strict")]
        )
    )
    if findings:
        raise ExperienceThreatError(findings, field_name)
    if len(cleaned) > max_chars:
        raise ExperienceSafetyError("Sanitized experience text exceeds its size limit")
    return cleaned


def sanitize_for_storage(
    text: str,
    *,
    field_name: str = "text",
    max_chars: int = DEFAULT_MAX_CHARS,
    repository_root: str | None = None,
) -> str:
    """Force-sanitize and strictly scan one field immediately before write."""
    return _sanitize(
        text, field_name=field_name, max_chars=max_chars, repository_root=repository_root
    )


def sanitize_for_return(
    text: str,
    *,
    field_name: str = "text",
    max_chars: int = DEFAULT_MAX_CHARS,
    repository_root: str | None = None,
) -> str:
    """Repeat the full safety boundary before returning stored text."""
    return _sanitize(
        text, field_name=field_name, max_chars=max_chars, repository_root=repository_root
    )


# Compact compatibility names for later service/runtime integration.
sanitize_experience_text = sanitize_for_storage
sanitize_url = normalize_experience_url
normalize_path = normalize_experience_path


class ExperienceSafety:
    """Stateless namespace for callers that prefer a component-style API."""

    sanitize_for_storage = staticmethod(sanitize_for_storage)
    sanitize_for_return = staticmethod(sanitize_for_return)
    normalize_url = staticmethod(normalize_experience_url)
    normalize_path = staticmethod(normalize_experience_path)
    merge_sensitivity = staticmethod(merge_sensitivity)
    is_egress_allowed = staticmethod(is_egress_allowed)


__all__ = [
    "DEFAULT_MAX_CHARS",
    "ExperienceEgressError",
    "ExperienceSafety",
    "ExperienceSafetyError",
    "ExperienceThreatError",
    "REDACTED",
    "is_egress_allowed",
    "merge_sensitivity",
    "normalize_experience_path",
    "normalize_experience_url",
    "normalize_path",
    "normalize_trust_domain",
    "require_egress_allowed",
    "sanitize_experience_text",
    "sanitize_for_return",
    "sanitize_for_storage",
    "sanitize_url",
    "validate_egress_policy",
    "validate_sensitivity",
]
