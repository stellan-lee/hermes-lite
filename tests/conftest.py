from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    for name in (
        "HERMES_CONFIG",
        "HERMES_MODEL",
        "HERMES_BASE_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    return home
