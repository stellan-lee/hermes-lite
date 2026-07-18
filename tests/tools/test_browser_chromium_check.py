"""Tests for Chromium-presence detection in browser_tool.

Regression guard for the "browser tool advertised but Chromium missing"
class of bug — where ``agent-browser`` CLI is discoverable but no
Chromium build is on disk, causing every browser_* tool call to hang
for the full command timeout before surfacing a useless error.
"""

import os

import pytest

from tools import browser_tool as bt


@pytest.fixture(autouse=True)
def _reset_chromium_cache():
    bt._cached_chromium_installed = None
    yield
    bt._cached_chromium_installed = None


class TestChromiumSearchRoots:
    def test_respects_playwright_browsers_path_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        roots = bt._chromium_search_roots()
        assert str(tmp_path) == roots[0]

    def test_ignores_playwright_browsers_path_zero(self, monkeypatch):
        # Playwright treats "0" as "skip browser download" — not a real path.
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
        roots = bt._chromium_search_roots()
        assert "0" not in roots

    def test_always_includes_default_ms_playwright_cache(self, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        roots = bt._chromium_search_roots()
        home = os.path.expanduser("~")
        assert any(r == os.path.join(home, ".cache", "ms-playwright") for r in roots)


class TestChromiumInstalled:
    def test_true_when_plain_chromium_on_path(self, monkeypatch):
        monkeypatch.delenv("AGENT_BROWSER_EXECUTABLE_PATH", raising=False)
        monkeypatch.setattr(
            bt.shutil,
            "which",
            lambda name: "/usr/bin/chromium" if name == "chromium" else None,
        )

        assert bt._chromium_installed() is True

    def test_true_when_chromium_dir_present(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        (tmp_path / "chromium-1208").mkdir()
        assert bt._chromium_installed() is True

    def test_true_when_headless_shell_present(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        (tmp_path / "chromium_headless_shell-1208").mkdir()
        assert bt._chromium_installed() is True




    def test_result_cached(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        (tmp_path / "chromium-1208").mkdir()
        assert bt._chromium_installed() is True
        # Delete after first call — cached True should still return True.
        (tmp_path / "chromium-1208").rmdir()
        assert bt._chromium_installed() is True


class TestCheckBrowserRequirementsChromium:

    def test_local_mode_with_chromium_returns_true(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bt, "_find_agent_browser", lambda: "/usr/local/bin/agent-browser")
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        (tmp_path / "chromium-1208").mkdir()

        assert bt.check_browser_requirements() is True

class TestRunBrowserCommandChromiumGuard:
    """Verify _run_browser_command fails fast (no timeout hang) when
    Chromium is missing in local mode.
    """
