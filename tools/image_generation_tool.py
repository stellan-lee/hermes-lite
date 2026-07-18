"""Provider-neutral image generation tool.

Bundled backends register through the plugin framework.  This distribution
ships the Codex OAuth provider; user and project plugins can register other
providers against the same interface.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.image_gen_provider import DEFAULT_ASPECT_RATIO, normalize_reference_images
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

VALID_ASPECT_RATIOS = ("landscape", "square", "portrait")

IMAGE_GENERATE_SCHEMA = {
    "name": "image_generate",
    "description": (
        "Generate an image from text, or edit source images when the active "
        "provider supports editing. The backend and model are user-configured."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The image request or edit instruction."},
            "aspect_ratio": {
                "type": "string",
                "enum": list(VALID_ASPECT_RATIOS),
                "default": DEFAULT_ASPECT_RATIO,
            },
            "image_url": {
                "type": "string",
                "description": "Optional source image URL or absolute local path to edit.",
            },
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional additional source or reference images.",
            },
        },
        "required": ["prompt"],
    },
}


def _discover_providers() -> None:
    from hermes_cli.plugins import _ensure_plugins_discovered

    _ensure_plugins_discovered()


def check_image_generation_requirements() -> bool:
    """Return whether at least one registered image provider is available."""
    try:
        from agent.image_gen_registry import list_providers

        _discover_providers()
        return any(provider.is_available() for provider in list_providers())
    except Exception:
        return False


def _handle_image_generate(args: dict[str, Any], **_kwargs: Any) -> str:
    prompt = args.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return tool_error("prompt is required for image generation")

    try:
        from agent.image_gen_registry import get_active_provider

        _discover_providers()
        provider = get_active_provider()
    except Exception as exc:
        logger.debug("Image provider discovery failed: %s", exc)
        provider = None

    if provider is None:
        return json.dumps(
            {
                "success": False,
                "image": None,
                "error": (
                    "No available image generation provider. Configure "
                    "image_gen.provider or install an image-generation plugin."
                ),
                "error_type": "provider_unavailable",
            }
        )

    call_args: dict[str, Any] = {
        "prompt": prompt.strip(),
        "aspect_ratio": args.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
    }
    image_url = args.get("image_url")
    if isinstance(image_url, str) and image_url.strip():
        call_args["image_url"] = image_url.strip()
    references = normalize_reference_images(args.get("reference_image_urls"))
    if references:
        call_args["reference_image_urls"] = references

    try:
        result = provider.generate(**call_args)
    except Exception as exc:
        logger.warning("Image provider %s failed: %s", provider.name, exc)
        return json.dumps(
            {
                "success": False,
                "image": None,
                "error": f"Provider '{provider.name}' failed: {exc}",
                "error_type": "provider_exception",
            }
        )

    if not isinstance(result, dict):
        return json.dumps(
            {
                "success": False,
                "image": None,
                "error": "Image provider returned a non-object result",
                "error_type": "provider_contract",
            }
        )
    return json.dumps(result)


registry.register(
    name="image_generate",
    toolset="image_gen",
    schema=IMAGE_GENERATE_SCHEMA,
    handler=_handle_image_generate,
    check_fn=check_image_generation_requirements,
    emoji="🎨",
)
