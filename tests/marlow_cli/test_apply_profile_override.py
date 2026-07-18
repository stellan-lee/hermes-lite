"""Regression tests for _apply_profile_override MARLOW_HOME guard (issue #22502).

When MARLOW_HOME is set to the marlow root (e.g. systemd hardcodes
MARLOW_HOME=/root/.marlow), _apply_profile_override must still read
active_profile and update MARLOW_HOME to the profile directory.

When MARLOW_HOME is already a profile directory (.../profiles/<name>),
_apply_profile_override must trust it and return without re-reading
active_profile (child-process inheritance contract).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path



def _run_apply_profile_override(
    tmp_path, monkeypatch, *, marlow_home: str | None, active_profile: str | None,
    argv: list[str] | None = None,
):
    """Run _apply_profile_override in isolation.

    Returns the value of os.environ["MARLOW_HOME"] after the call,
    or None if unset.
    """
    marlow_root = tmp_path / ".marlow"
    marlow_root.mkdir(parents=True, exist_ok=True)

    if active_profile is not None:
        (marlow_root / "active_profile").write_text(active_profile)

    if active_profile and active_profile != "default":
        (marlow_root / "profiles" / active_profile).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if marlow_home is not None:
        monkeypatch.setenv("MARLOW_HOME", marlow_home)
    else:
        monkeypatch.delenv("MARLOW_HOME", raising=False)

    monkeypatch.setattr(sys, "argv", argv or ["marlow", "gateway", "start"])

    from marlow_cli.main import _apply_profile_override
    _apply_profile_override()

    return os.environ.get("MARLOW_HOME")


class TestApplyProfileOverrideMarlowHomeGuard:
    """Regression guard for issue #22502.

    Verifies that MARLOW_HOME pointing to the marlow root does NOT suppress
    the active_profile check, while MARLOW_HOME already pointing to a
    profile directory IS trusted as-is.
    """

    def test_marlow_home_at_root_with_active_profile_is_redirected(
        self, tmp_path, monkeypatch
    ):
        """MARLOW_HOME=/root/.marlow + active_profile=coder must redirect
        MARLOW_HOME to .../profiles/coder.

        Bug scenario from #22502: systemd sets MARLOW_HOME to the marlow root
        and the user switches to a profile via `marlow profile use`.
        Before the fix, the guard returned early and active_profile was ignored.
        """
        marlow_root = tmp_path / ".marlow"
        marlow_root.mkdir(parents=True, exist_ok=True)

        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            marlow_home=str(marlow_root),
            active_profile="coder",
        )

        assert result is not None, "MARLOW_HOME must be set after profile redirect"
        assert "profiles" in result, (
            f"Expected MARLOW_HOME to point into profiles/ dir, got: {result!r}"
        )
        assert result.endswith("coder"), (
            f"Expected MARLOW_HOME to end with 'coder', got: {result!r}"
        )

    def test_marlow_home_already_profile_dir_is_trusted(self, tmp_path, monkeypatch):
        """MARLOW_HOME=.../profiles/coder must not be overridden even when
        active_profile says something different.

        Preserves the child-process inheritance contract: a subprocess spawned
        with MARLOW_HOME already set to a specific profile must stay in that
        profile.
        """
        marlow_root = tmp_path / ".marlow"
        profile_dir = marlow_root / "profiles" / "coder"
        profile_dir.mkdir(parents=True, exist_ok=True)

        (marlow_root / "active_profile").write_text("other")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("MARLOW_HOME", str(profile_dir))
        monkeypatch.setattr(sys, "argv", ["marlow", "gateway", "start"])

        from marlow_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("MARLOW_HOME") == str(profile_dir), (
            "MARLOW_HOME must remain unchanged when already pointing to a profile dir"
        )

    def test_marlow_home_unset_reads_active_profile(self, tmp_path, monkeypatch):
        """Classic case: MARLOW_HOME unset + active_profile=coder must set
        MARLOW_HOME to the profile directory (existing behaviour must not regress).
        """
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            marlow_home=None,
            active_profile="coder",
        )

        assert result is not None
        assert "coder" in result

    def test_marlow_home_unset_default_profile_no_redirect(self, tmp_path, monkeypatch):
        """active_profile=default must not redirect MARLOW_HOME."""
        marlow_root = tmp_path / ".marlow"
        marlow_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("MARLOW_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", ["marlow", "gateway", "start"])
        (marlow_root / "active_profile").write_text("default")

        from marlow_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("MARLOW_HOME") is None
