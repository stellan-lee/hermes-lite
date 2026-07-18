"""Tests for retained Codex and custom auxiliary-model paths."""
import base64
import json
import time
from unittest.mock import patch

from agent.auxiliary_client import (
    _build_call_kwargs, _is_model_not_found_error, _is_payment_error,
    _is_rate_limit_error, _normalize_aux_provider, _read_codex_access_token,
)


def _jwt(claims):
    enc=lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{enc({'alg':'none'})}.{enc(claims)}.sig"


def test_normalize_retained_providers():
    assert _normalize_aux_provider("codex") == "openai-codex"
    assert _normalize_aux_provider("openai-codex") == "openai-codex"
    assert _normalize_aux_provider("custom") == "custom"


def test_custom_call_omits_default_output_cap():
    kwargs = _build_call_kwargs(
        provider="custom", model="local-model",
        messages=[{"role":"user","content":"hi"}],
        max_tokens=1234, base_url="http://localhost:8080/v1",
    )
    assert "max_tokens" not in kwargs
    assert "max_completion_tokens" not in kwargs


def test_read_codex_token_from_auth_store():
    with patch(
        "hermes_cli.auth._read_codex_tokens",
        return_value={"tokens": {"access_token": "token"}},
    ):
        assert _read_codex_access_token() == "token"


def test_expired_codex_token_is_rejected():
    token=_jwt({"exp":int(time.time())-60})
    with patch(
        "hermes_cli.auth._read_codex_tokens",
        return_value={"tokens": {"access_token": token}},
    ):
        assert _read_codex_access_token() is None


def test_missing_auth_store_returns_none():
    with patch("hermes_cli.auth._read_codex_tokens", side_effect=OSError):
        assert _read_codex_access_token() is None


class ApiError(Exception):
    def __init__(self,status_code,message):
        self.status_code=status_code; super().__init__(message)


def test_error_classifiers():
    assert _is_payment_error(ApiError(402,"payment required"))
    assert _is_rate_limit_error(ApiError(429,"too many requests"))
    assert _is_model_not_found_error(ApiError(404,"model does not exist"))
    assert not _is_rate_limit_error(ApiError(500,"server error"))
