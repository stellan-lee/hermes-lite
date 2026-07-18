"""Tests for agent/image_gen_registry.py — provider registration & active lookup."""

from __future__ import annotations

import pytest

from agent import image_gen_registry
from agent.image_gen_provider import ImageGenProvider


class _FakeProvider(ImageGenProvider):
    def __init__(self, name: str, available: bool = True):
        self._name = name
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt, aspect_ratio="landscape", **kw):
        return {"success": True, "image": f"{self._name}://{prompt}"}


@pytest.fixture(autouse=True)
def _reset_registry():
    image_gen_registry._reset_for_tests()
    yield
    image_gen_registry._reset_for_tests()


class TestRegisterProvider:
    def test_register_and_lookup(self):
        provider = _FakeProvider("fake")
        image_gen_registry.register_provider(provider)
        assert image_gen_registry.get_provider("fake") is provider

    def test_rejects_non_provider(self):
        with pytest.raises(TypeError):
            image_gen_registry.register_provider("not a provider")  # type: ignore[arg-type]

    def test_rejects_empty_name(self):
        class Empty(ImageGenProvider):
            @property
            def name(self) -> str:
                return ""

            def generate(self, prompt, aspect_ratio="landscape", **kw):
                return {}

        with pytest.raises(ValueError):
            image_gen_registry.register_provider(Empty())

    def test_reregister_overwrites(self):
        a = _FakeProvider("same")
        b = _FakeProvider("same")
        image_gen_registry.register_provider(a)
        image_gen_registry.register_provider(b)
        assert image_gen_registry.get_provider("same") is b

    def test_list_is_sorted(self):
        image_gen_registry.register_provider(_FakeProvider("zeta"))
        image_gen_registry.register_provider(_FakeProvider("alpha"))
        names = [p.name for p in image_gen_registry.list_providers()]
        assert names == ["alpha", "zeta"]


class TestGetActiveProvider:
    def test_single_provider_autoresolves(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        image_gen_registry.register_provider(_FakeProvider("solo"))
        active = image_gen_registry.get_active_provider()
        assert active is not None and active.name == "solo"

    def test_none_on_multi_without_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        image_gen_registry.register_provider(_FakeProvider("first"))
        image_gen_registry.register_provider(_FakeProvider("second"))
        assert image_gen_registry.get_active_provider() is None

    def test_explicit_config_wins(self, tmp_path, monkeypatch):
        import yaml

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"image_gen": {"provider": "second"}})
        )
        image_gen_registry.register_provider(_FakeProvider("first"))
        image_gen_registry.register_provider(_FakeProvider("second"))
        active = image_gen_registry.get_active_provider()
        assert active is not None and active.name == "second"

    def test_missing_configured_provider_falls_back(self, tmp_path, monkeypatch):
        import yaml

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"image_gen": {"provider": "missing"}})
        )
        image_gen_registry.register_provider(_FakeProvider("only"))
        active = image_gen_registry.get_active_provider()
        assert active is not None and active.name == "only"

    def test_none_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        assert image_gen_registry.get_active_provider() is None
