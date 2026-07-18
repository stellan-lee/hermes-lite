"""Tests for the lightweight status report's canonical model config."""

from types import SimpleNamespace

from hermes_cli import status


def test_configured_model_reads_canonical_fields():
    assert status._configured_model(
        {
            "model": {
                "default": "qwen/qwen3-coder-30b",
                "provider": "lmstudio",
                "base_url": "http://127.0.0.1:1234/v1",
            }
        }
    ) == (
        "qwen/qwen3-coder-30b",
        "lmstudio",
        "http://127.0.0.1:1234/v1",
    )


def test_configured_model_rejects_removed_legacy_shapes():
    assert status._configured_model({"model": "qwen3:latest"}) == ("", "auto", "")
    assert status._configured_model({"model": {"name": "qwen3:latest"}}) == (
        "",
        "auto",
        "",
    )


def test_show_status_displays_custom_endpoint_and_codex(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(status, "get_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(status, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        status,
        "load_config",
        lambda: {
            "model": {
                "default": "qwen3:latest",
                "provider": "custom",
                "base_url": "http://localhost:8080/v1",
            }
        },
    )
    import hermes_cli.auth as auth

    monkeypatch.setattr(
        auth,
        "get_codex_auth_status",
        lambda: {"logged_in": True, "auth_store": "file"},
    )

    status.show_status(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Provider:     custom" in out
    assert "Model:        qwen3:latest" in out
    assert "Endpoint:     http://localhost:8080/v1" in out
    assert "Codex OAuth:" in out and "logged in" in out
