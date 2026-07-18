"""Regression tests for the ``auto`` → main-model-first policy.

Prior to this change, aggregator users (OpenRouter / Nous Portal) had aux
tasks routed through a cheap provider-side default (Gemini Flash) while
non-aggregator users got their main model.  This made behavior inconsistent
and surprising — users picked Claude but got Gemini Flash summaries.

The current policy: ``auto`` means "use my main chat model" for every user,
regardless of provider type.  Explicit per-task overrides in ``config.yaml``
(``auxiliary.<task>.provider``) still win.  The cheap fallback chain only
runs when the main provider has no working client.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch



# ── Text aux tasks — _resolve_auto ──────────────────────────────────────────


class TestResolveAutoMainFirst:
    """_resolve_auto() must prefer main provider + main model for every user."""








# ── Vision — resolve_vision_provider_client ─────────────────────────────────


class TestResolveVisionMainFirst:
    """Vision auto-detection prefers the main provider first."""










# ── Constant cleanup ────────────────────────────────────────────────────────


def test_aggregator_providers_constant_removed():
    """The dead _AGGREGATOR_PROVIDERS constant should no longer live in the module.

    Removed when the main-first policy made the aggregator-skip guard obsolete.
    """
    import agent.auxiliary_client as aux_mod

    assert not hasattr(aux_mod, "_AGGREGATOR_PROVIDERS"), (
        "_AGGREGATOR_PROVIDERS was removed when _resolve_auto stopped "
        "treating aggregators specially. If you re-added it, the main-first "
        "policy may have regressed."
    )
