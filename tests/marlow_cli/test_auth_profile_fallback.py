"""Tests for cross-profile auth fallback.

When ``MARLOW_HOME`` points to a named profile, provider auth state falls back
to the global-root ``auth.json`` when the profile has no entry.

See the #18594 follow-up report: profile workers couldn't see providers
authenticated only at the global root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    """Set up a global root + an active profile under Path.home()/.marlow/profiles/coder.

    * Path.home() -> tmp_path
    * Global root -> tmp_path/.marlow            (has its own auth.json fixture)
    * Profile     -> tmp_path/.marlow/profiles/coder   (active, MARLOW_HOME points here)

    This mirrors the real "named profile mounted under the default root"
    layout that profile users actually have on disk.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    global_root = tmp_path / ".marlow"
    global_root.mkdir()
    profile_dir = global_root / "profiles" / "coder"
    profile_dir.mkdir(parents=True)
    monkeypatch.setenv("MARLOW_HOME", str(profile_dir))
    return {"global": global_root, "profile": profile_dir}


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


def _make_auth_store(*, providers: dict | None = None) -> dict:
    return {"version": 1, "providers": providers or {}}


# ---------------------------------------------------------------------------
# get_provider_auth_state — singleton fallback
# ---------------------------------------------------------------------------


def test_provider_auth_state_falls_back_to_global_when_profile_has_none(profile_env):
    from marlow_cli.auth import get_provider_auth_state

    _write(
        profile_env["global"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {
                    "tokens": {"access_token": "global", "refresh_token": "rt"}
                },
            }
        ),
    )
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    state = get_provider_auth_state("openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "global"


def test_provider_auth_state_profile_wins_when_present(profile_env):
    from marlow_cli.auth import get_provider_auth_state

    _write(
        profile_env["global"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "global"}},
            }
        ),
    )
    _write(
        profile_env["profile"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "profile"}},
            }
        ),
    )

    state = get_provider_auth_state("openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "profile"


def test_provider_auth_state_returns_none_when_neither_has_it(profile_env):
    from marlow_cli.auth import get_provider_auth_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={}))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    assert get_provider_auth_state("openai-codex") is None


# ---------------------------------------------------------------------------
# _load_provider_state — internal global fallback
# ---------------------------------------------------------------------------


def test_load_provider_state_falls_back_to_global(profile_env):
    """When the loaded profile store has no provider entry, fall back to global."""
    from marlow_cli.auth import _load_auth_store, _load_provider_state

    _write(
        profile_env["global"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {
                    "tokens": {"access_token": "global", "refresh_token": "rt"}
                },
            }
        ),
    )
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "global"


def test_load_provider_state_profile_wins_over_global(profile_env):
    from marlow_cli.auth import _load_auth_store, _load_provider_state

    _write(
        profile_env["global"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "global"}},
            }
        ),
    )
    _write(
        profile_env["profile"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "profile"}},
            }
        ),
    )

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "profile"


def test_load_provider_state_returns_none_when_neither_has_it(profile_env):
    from marlow_cli.auth import _load_auth_store, _load_provider_state

    _write(profile_env["global"] / "auth.json", _make_auth_store(providers={}))
    _write(profile_env["profile"] / "auth.json", _make_auth_store(providers={}))

    auth_store = _load_auth_store()
    assert _load_provider_state(auth_store, "openai-codex") is None


def test_load_provider_state_classic_mode_no_fallback(tmp_path, monkeypatch):
    """In classic mode there is no global to fall back to; behavior is unchanged."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    marlow_home = tmp_path / "classic"
    marlow_home.mkdir()
    monkeypatch.setenv("MARLOW_HOME", str(marlow_home))

    _write(
        marlow_home / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "classic"}},
            }
        ),
    )

    from marlow_cli.auth import _load_auth_store, _load_provider_state

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "classic"
    # Absent providers still return None.
    assert _load_provider_state(auth_store, "missing") is None


def test_load_provider_state_malformed_global_does_not_break_profile(profile_env):
    """A corrupt global auth.json must not break profile reads."""
    (profile_env["global"] / "auth.json").write_text("{not valid json")
    _write(
        profile_env["profile"] / "auth.json",
        _make_auth_store(
            providers={
                "openai-codex": {"tokens": {"access_token": "profile"}},
            }
        ),
    )

    from marlow_cli.auth import _load_auth_store, _load_provider_state

    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    assert state is not None
    assert state["tokens"]["access_token"] == "profile"
