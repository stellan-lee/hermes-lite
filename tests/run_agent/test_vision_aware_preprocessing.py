"""Tests for the vision-aware image preprocessing in run_agent.py.

Covers:

* ``_prepare_messages_for_non_vision_model`` — the mirror method for the
  chat.completions / codex_responses paths. Same contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from run_agent import AIAgent


def _make_agent() -> AIAgent:
    """Build a bare-bones AIAgent instance without running __init__.

    Avoids the heavy provider/credential setup for these pure-method tests.
    """
    agent = object.__new__(AIAgent)
    agent.provider = "custom"
    agent.model = "local-vision-model"
    agent._image_text_fallback_cache = {}
    return agent


IMG_PARTS_USER_MSG = {
    "role": "user",
    "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ],
}

PLAIN_USER_MSG = {"role": "user", "content": "hello, no images here"}


# ─── _prepare_messages_for_non_vision_model ──────────────────────────────────


class TestPrepareMessagesForNonVision:
    def test_no_images_passes_through(self):
        agent = _make_agent()
        msgs = [PLAIN_USER_MSG]
        out = agent._prepare_messages_for_non_vision_model(msgs)
        assert out is msgs

    def test_vision_capable_passes_through(self):
        """For vision-capable models on chat.completions path, provider handles pixels."""
        agent = _make_agent()
        agent.provider = "custom"
        agent.model = "local-vision-model"
        with patch.object(agent, "_model_supports_vision", return_value=True):
            out = agent._prepare_messages_for_non_vision_model([IMG_PARTS_USER_MSG])
        assert out[0]["content"][1]["type"] == "image_url"

    def test_non_vision_strips_images(self):
        agent = _make_agent()
        agent.provider = "custom"
        agent.model = "local-text-model"
        with patch.object(agent, "_model_supports_vision", return_value=False), \
             patch.object(
                 agent,
                 "_describe_image_for_text_fallback",
                 return_value="[Image description: a dog]",
             ):
            out = agent._prepare_messages_for_non_vision_model([IMG_PARTS_USER_MSG])
        content = out[0]["content"]
        assert isinstance(content, str)
        assert "[Image description: a dog]" in content
        assert "image_url" not in content

    def test_multiple_messages_with_mixed_content(self):
        agent = _make_agent()
        agent.model = "local-text-model"
        msgs = [
            {"role": "user", "content": "first turn"},
            {"role": "assistant", "content": "ack"},
            IMG_PARTS_USER_MSG,
        ]
        with patch.object(agent, "_model_supports_vision", return_value=False), \
             patch.object(
                 agent,
                 "_describe_image_for_text_fallback",
                 return_value="[Image: thing]",
             ):
            out = agent._prepare_messages_for_non_vision_model(msgs)
        # First two messages unchanged (no images), third stripped.
        assert out[0]["content"] == "first turn"
        assert out[1]["content"] == "ack"
        assert isinstance(out[2]["content"], str)
        assert "[Image: thing]" in out[2]["content"]


# ─── _model_supports_vision ──────────────────────────────────────────────────


class TestModelSupportsVision:
    def test_missing_provider_or_model_returns_false(self):
        agent = _make_agent()
        agent.provider = ""
        agent.model = "local-vision-model"
        assert agent._model_supports_vision() is False
        agent.provider = "custom"
        agent.model = ""
        assert agent._model_supports_vision() is False

    def test_unknown_custom_model_returns_false(self):
        agent = _make_agent()
        with patch("marlow_cli.config.load_config", return_value={}):
            assert agent._model_supports_vision() is False

    def test_codex_model_supports_vision(self):
        agent = _make_agent()
        agent.provider = "openai-codex"
        agent.model = "gpt-5.4"
        with patch("marlow_cli.config.load_config", return_value={}):
            assert agent._model_supports_vision() is True

    def test_top_level_model_override_wins(self):
        agent = _make_agent()
        agent.provider = "custom"
        agent.model = "my-llava"
        with patch("marlow_cli.config.load_config", return_value={"model": {"supports_vision": True}}):
            assert agent._model_supports_vision() is True

    def test_per_provider_per_model_override_wins(self):
        agent = _make_agent()
        agent.provider = "custom"
        agent.model = "my-llava"
        cfg = {"providers": {"custom": {"models": {"my-llava": {"supports_vision": True}}}}}
        with patch("marlow_cli.config.load_config", return_value=cfg):
            assert agent._model_supports_vision() is True

    def test_named_custom_provider_resolved_via_config_provider(self):
        # Named custom providers get runtime self.provider rewritten to
        # "custom" while the config keeps the original name under
        # model.provider. The override must still resolve.
        agent = _make_agent()
        agent.provider = "custom"
        agent.model = "my-llava"
        cfg = {
            "model": {"provider": "my-vllm", "default": "my-llava"},
            "providers": {"my-vllm": {"models": {"my-llava": {"supports_vision": True}}}},
        }
        with patch("marlow_cli.config.load_config", return_value=cfg):
            assert agent._model_supports_vision() is True

    def test_override_false_disables_codex_vision(self):
        agent = _make_agent()
        agent.provider = "openai-codex"
        agent.model = "gpt-5.4"
        with patch("marlow_cli.config.load_config", return_value={"model": {"supports_vision": False}}):
            assert agent._model_supports_vision() is False
