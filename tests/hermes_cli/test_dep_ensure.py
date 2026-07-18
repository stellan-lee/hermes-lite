"""Tests for the retained POSIX dependency bootstrapper."""

from unittest.mock import patch


def test_ensure_dependency_skips_when_present():
    from hermes_cli.dep_ensure import ensure_dependency

    with patch("hermes_cli.dep_ensure.shutil.which", return_value="/usr/bin/node"):
        assert ensure_dependency("node", interactive=False) is True


def test_ensure_dependency_returns_false_when_missing_noninteractive():
    from hermes_cli.dep_ensure import ensure_dependency

    with patch("hermes_cli.dep_ensure.shutil.which", return_value=None), patch(
        "hermes_cli.dep_ensure._find_install_script", return_value=(None, None)
    ):
        assert ensure_dependency("node", interactive=False) is False


def test_ensure_dependency_rejects_unknown_dependency():
    from hermes_cli.dep_ensure import ensure_dependency

    assert ensure_dependency("unknown", interactive=False) is False


def test_find_install_script_from_checkout(tmp_path):
    from hermes_cli.dep_ensure import _find_install_script

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    expected = scripts_dir / "install.sh"
    expected.write_text("#!/bin/bash", encoding="utf-8")
    assert _find_install_script(tmp_path / "hermes_cli", tmp_path) == (expected, "bash")


def test_find_install_script_from_wheel(tmp_path):
    from hermes_cli.dep_ensure import _find_install_script

    scripts_dir = tmp_path / "hermes_cli" / "scripts"
    scripts_dir.mkdir(parents=True)
    expected = scripts_dir / "install.sh"
    expected.write_text("#!/bin/bash", encoding="utf-8")
    assert _find_install_script(tmp_path / "hermes_cli", tmp_path) == (expected, "bash")


def test_find_install_script_returns_none_when_missing(tmp_path):
    from hermes_cli.dep_ensure import _find_install_script

    assert _find_install_script(tmp_path / "x", tmp_path / "y") == (None, None)


def test_has_system_browser_checks_posix_names():
    from hermes_cli.dep_ensure import _has_system_browser

    with patch("hermes_cli.dep_ensure.shutil.which") as mock_which:
        mock_which.side_effect = lambda name: "/usr/bin/chromium" if name == "chromium" else None
        assert _has_system_browser() is True


def test_has_hermes_agent_browser_paths(tmp_path):
    from hermes_cli.dep_ensure import _has_hermes_agent_browser

    for relative in ("node/bin/agent-browser", "node_modules/.bin/agent-browser"):
        candidate = tmp_path / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("#!/bin/sh", encoding="utf-8")
        with patch("hermes_constants.get_hermes_home", return_value=tmp_path):
            assert _has_hermes_agent_browser() is True
        candidate.unlink()


def test_ensure_dependency_runs_bash_installer(tmp_path):
    from hermes_cli.dep_ensure import ensure_dependency

    script = tmp_path / "install.sh"
    script.write_text("#!/bin/bash", encoding="utf-8")
    checks = iter((False, True))
    with patch("hermes_cli.dep_ensure._DEP_CHECKS", {"node": lambda: next(checks)}), patch(
        "hermes_cli.dep_ensure._find_install_script", return_value=(script, "bash")
    ), patch("hermes_cli.dep_ensure.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert ensure_dependency("node", interactive=False) is True
    assert mock_run.call_args.args[0] == ["bash", str(script), "--ensure", "node"]
