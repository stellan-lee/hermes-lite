"""Regression tests for the pre-Marlow installer migration."""

from pathlib import Path
import shlex
import subprocess


REPO_ROOT = Path(__file__).parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install.sh"


def _installer_function(name: str, next_marker: str) -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    start = f"{name}() {{\n"
    _, found, rest = text.partition(start)
    assert found, f"{name}() not found in installer"
    body, found, _ = rest.partition(next_marker)
    assert found, f"end marker for {name}() not found"
    return start + body.rstrip() + "\n}\n"


def _run_bash(script: str) -> None:
    subprocess.run(["bash", "-c", script], check=True, text=True)


def test_legacy_state_is_copied_without_source_or_overwrites(tmp_path):
    legacy_home = tmp_path / ".hermes"
    marlow_home = tmp_path / ".marlow"
    legacy_home.mkdir()
    marlow_home.mkdir()

    (legacy_home / "config.yaml").write_text("legacy: true\n", encoding="utf-8")
    (legacy_home / "auth.json").write_text('{"token":"secret"}\n', encoding="utf-8")
    (legacy_home / "sessions").mkdir()
    (legacy_home / "sessions" / "one.json").write_text("{}\n", encoding="utf-8")
    (legacy_home / "bin").mkdir()
    (legacy_home / "bin" / "uv").write_text("old helper\n", encoding="utf-8")
    (legacy_home / "hermes-agent" / ".git").mkdir(parents=True)
    (legacy_home / ".update_output.txt").write_text("stale\n", encoding="utf-8")
    (marlow_home / "config.yaml").write_text("marlow: true\n", encoding="utf-8")

    function = _installer_function(
        "migrate_legacy_hermes_state",
        "\n}\n\nretire_legacy_hermes_launcher()",
    )
    script = f"""
set -e
MARLOW_HOME={shlex.quote(str(marlow_home))}
LEGACY_HERMES_HOME={shlex.quote(str(legacy_home))}
MARLOW_HOME_EXPLICIT=false
log_info() {{ :; }}
log_success() {{ :; }}
{function}
migrate_legacy_hermes_state
migrate_legacy_hermes_state
"""
    _run_bash(script)

    assert (marlow_home / "config.yaml").read_text() == "marlow: true\n"
    assert (marlow_home / "auth.json").read_text() == '{"token":"secret"}\n'
    assert (marlow_home / "sessions" / "one.json").exists()
    assert not (marlow_home / "bin").exists()
    assert not (marlow_home / "hermes-agent").exists()
    assert not (marlow_home / ".update_output.txt").exists()
    marker = marlow_home / ".legacy-migration-complete"
    assert marker.exists()
    assert marker.stat().st_mode & 0o777 == 0o600
    assert (legacy_home / "auth.json").exists(), "legacy state must remain recoverable"


def test_explicit_marlow_home_disables_automatic_migration(tmp_path):
    legacy_home = tmp_path / ".hermes"
    marlow_home = tmp_path / "custom-home"
    legacy_home.mkdir()
    (legacy_home / "config.yaml").write_text("legacy: true\n", encoding="utf-8")

    function = _installer_function(
        "migrate_legacy_hermes_state",
        "\n}\n\nretire_legacy_hermes_launcher()",
    )
    script = f"""
set -e
MARLOW_HOME={shlex.quote(str(marlow_home))}
LEGACY_HERMES_HOME={shlex.quote(str(legacy_home))}
MARLOW_HOME_EXPLICIT=true
log_info() {{ :; }}
log_success() {{ :; }}
{function}
migrate_legacy_hermes_state
"""
    _run_bash(script)

    assert not marlow_home.exists()


def test_project_owned_legacy_launcher_is_backed_up(tmp_path):
    command_dir = tmp_path / "bin"
    command_dir.mkdir()
    launcher = command_dir / "hermes"
    launcher.write_text(
        "#!/usr/bin/python\nfrom marlow_cli.main import main\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    function = _installer_function(
        "retire_legacy_hermes_launcher",
        "\n}\n\n# Decide where the repo checkout",
    )
    script = f"""
set -e
log_info() {{ :; }}
log_warn() {{ :; }}
{function}
retire_legacy_hermes_launcher {shlex.quote(str(command_dir))}
"""
    _run_bash(script)

    assert not launcher.exists()
    assert (command_dir / "hermes.marlow-migration-backup").exists()


def test_unrelated_hermes_command_is_not_touched(tmp_path):
    command_dir = tmp_path / "bin"
    command_dir.mkdir()
    launcher = command_dir / "hermes"
    launcher.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
    launcher.chmod(0o755)

    function = _installer_function(
        "retire_legacy_hermes_launcher",
        "\n}\n\n# Decide where the repo checkout",
    )
    script = f"""
set -e
log_info() {{ :; }}
log_warn() {{ :; }}
{function}
retire_legacy_hermes_launcher {shlex.quote(str(command_dir))}
"""
    _run_bash(script)

    assert launcher.exists()
    assert not (command_dir / "hermes.marlow-migration-backup").exists()
