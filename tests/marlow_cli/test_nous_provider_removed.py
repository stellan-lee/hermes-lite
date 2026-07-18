"""Regression tests for the removal of the official Nous Portal model provider.

The Nous Portal provider was removed as a user-facing / routable model
provider. These tests pin that removal at the provider-selection,
registration, overlay and catalog surfaces so the provider can't silently
creep back in.

Note: the low-level Nous *credential* subsystem (``marlow auth add nous``,
the Portal subscription / Tool Gateway, dashboard auth, ``marlow proxy``
adapter) is intentionally retained as an internal API and is NOT asserted
against here.
"""

import json
from pathlib import Path


def test_not_a_canonical_provider_menu_entry():
    from marlow_cli.models import CANONICAL_PROVIDERS, _PROVIDER_LABELS

    slugs = {p.slug for p in CANONICAL_PROVIDERS}
    assert "nous" not in slugs
    assert "nous" not in _PROVIDER_LABELS


def test_not_in_provider_groups():
    from marlow_cli.models import PROVIDER_GROUPS

    members = {m for _g, (_l, _d, ms) in PROVIDER_GROUPS.items() for m in ms}
    assert "nous" not in PROVIDER_GROUPS
    assert "nous" not in members


def test_no_cli_overlay_or_label():
    from marlow_cli.providers import MARLOW_OVERLAYS, _LABEL_OVERRIDES, get_provider

    assert "nous" not in MARLOW_OVERLAYS
    assert "nous" not in _LABEL_OVERRIDES
    # nous is not in models.dev either, so it should not resolve at all.
    assert get_provider("nous") is None


def test_not_an_aggregator_in_normalizer():
    from marlow_cli.model_normalize import _AGGREGATOR_PROVIDERS

    assert "nous" not in _AGGREGATOR_PROVIDERS


def test_not_in_bundled_model_catalog():
    repo_root = Path(__file__).resolve().parents[2]
    catalog = json.loads(
        (repo_root / "marlow_cli" / "data" / "model-catalog.json").read_text()
    )
    assert "nous" not in catalog.get("providers", {})


def test_provider_profile_not_registered():
    from providers import get_provider_profile

    assert get_provider_profile("nous") is None
    assert get_provider_profile("nous-portal") is None
