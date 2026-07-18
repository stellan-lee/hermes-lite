import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

moa = importlib.import_module("tools.mixture_of_agents_tool")


def test_moa_defaults_are_well_formed():
    # MoA defaults to independent calls through the current retained runtime.
    assert isinstance(moa.REFERENCE_MODELS, list)
    assert len(moa.REFERENCE_MODELS) >= 1
    assert set(moa.REFERENCE_MODELS) == {"active"}
    assert moa.AGGREGATOR_MODEL == "active"


@pytest.mark.asyncio
async def test_reference_model_retry_warnings_avoid_exc_info_until_terminal_failure(monkeypatch):
    warn = MagicMock()
    err = MagicMock()

    monkeypatch.setattr(
        moa, "async_call_llm", AsyncMock(side_effect=RuntimeError("rate limited"))
    )
    monkeypatch.setattr(moa.logger, "warning", warn)
    monkeypatch.setattr(moa.logger, "error", err)

    model, message, success = await moa._run_reference_model_safe(
        "active", "hello", max_retries=2
    )

    assert model == "active"
    assert success is False
    assert "failed after 2 attempts" in message
    assert warn.call_count == 2
    assert all(call.kwargs.get("exc_info") is None for call in warn.call_args_list)
    err.assert_called_once()
    assert err.call_args.kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_moa_top_level_error_logs_single_traceback_on_aggregator_failure(monkeypatch):
    monkeypatch.setattr(
        moa,
        "_run_reference_model_safe",
        AsyncMock(return_value=("active", "ok", True)),
    )
    monkeypatch.setattr(
        moa,
        "_run_aggregator_model",
        AsyncMock(side_effect=RuntimeError("aggregator boom")),
    )
    monkeypatch.setattr(
        moa,
        "_debug",
        SimpleNamespace(log_call=MagicMock(), save=MagicMock(), active=False),
    )

    err = MagicMock()
    monkeypatch.setattr(moa.logger, "error", err)

    result = json.loads(
        await moa.mixture_of_agents_tool(
            "solve this",
            reference_models=["active"],
        )
    )

    assert result["success"] is False
    assert "Error in MoA processing" in result["error"]
    err.assert_called_once()
    assert err.call_args.kwargs.get("exc_info") is True
