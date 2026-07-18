"""Tests for the retained Codex image-generation plugin path."""

import json

from agent.image_gen_provider import ImageGenProvider
from tools import image_generation_tool


class FakeCodexProvider(ImageGenProvider):
    @property
    def name(self):
        return "codex"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        return {
            "success": True,
            "image": "/tmp/codex-test.png",
            "provider": "codex",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }


def test_dispatch_routes_to_codex_provider(monkeypatch):
    monkeypatch.setattr(image_generation_tool, "_discover_providers", lambda: None)
    monkeypatch.setattr(
        "agent.image_gen_registry.get_active_provider",
        lambda: FakeCodexProvider(),
    )
    payload = json.loads(
        image_generation_tool._handle_image_generate(
            {"prompt": "draw cat", "aspect_ratio": "square"}
        )
    )
    assert payload["success"] is True
    assert payload["provider"] == "codex"
    assert payload["aspect_ratio"] == "square"


def test_dispatch_reports_no_available_provider(monkeypatch):
    monkeypatch.setattr(image_generation_tool, "_discover_providers", lambda: None)
    monkeypatch.setattr("agent.image_gen_registry.get_active_provider", lambda: None)
    payload = json.loads(
        image_generation_tool._handle_image_generate({"prompt": "draw cat"})
    )
    assert payload["success"] is False
    assert payload["error_type"] == "provider_unavailable"
