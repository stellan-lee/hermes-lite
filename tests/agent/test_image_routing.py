"""Tests for retained per-turn image routing."""
from agent.image_routing import (
    _coerce_capability_bool, _coerce_mode, _explicit_aux_vision_override,
    build_native_content_parts, extract_image_refs,
)


def test_coerce_modes():
    assert _coerce_mode(" NATIVE ")=="native"
    assert _coerce_mode("bad")=="auto"


def test_capability_bool_parses_yaml_values():
    assert _coerce_capability_bool("true") is True
    assert _coerce_capability_bool("off") is False
    assert _coerce_capability_bool("maybe") is None


def test_custom_aux_vision_endpoint_is_explicit():
    cfg={"auxiliary":{"vision":{"provider":"custom","base_url":"http://localhost:8080/v1"}}}
    assert _explicit_aux_vision_override(cfg) is True


def test_extract_image_refs_from_media_tags(tmp_path):
    image=tmp_path/"a.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n")
    paths, urls=extract_image_refs(f"look {image}")
    assert str(image) in paths
    assert urls == []


def test_build_native_parts_includes_text_and_image(tmp_path):
    image=tmp_path/"a.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n")
    parts, skipped=build_native_content_parts("look",[str(image)])
    assert skipped == []
    assert any(part.get("type")=="text" for part in parts)
    assert any(part.get("type")=="image_url" for part in parts)
