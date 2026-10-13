"""Per-tool timing in ``build_snapshot`` is log-only: same snapshot, same call order, same
exceptions, and the log carries only a tool id, a status and a duration (never a payload).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import structlog

from cfi.analyst import tools as tools_module
from cfi.analyst.snapshot import build_snapshot
from cfi.analyst.universe import TOOLS
from cfi.core.config import Settings

AS_OF = datetime(2026, 9, 28, tzinfo=UTC)
TIMING_EVENT = "analyst_snapshot_tool_timing"

# Captured from the unmodified ``build_snapshot`` with the fake tool results below.
BASELINE_SNAPSHOT_ID = "97bb174eb9651710325f97e3a4122254b3ca1087c7ec4182999da7d0a1733fc4"
BASELINE_TOOL_ORDER = [
    "get_market_data",
    "get_institutional_flows",
    "get_whale_activity",
    "get_retail_activity",
    "get_derivatives",
    "get_liquidity",
    "get_macro",
    "get_market_structure",
    "calculate_divergence",
    "get_market_regime",
    "find_historical_similar_periods",
    "get_anomalies",
    "get_capital_rotation",
    "check_data_quality",
]


class SentinelError(Exception):
    pass


class HardStop(BaseException):  # stands in for SoftTimeLimitExceeded-style signals
    pass


def _patch_tools(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> None:
    for tool_def in TOOLS:
        if tool_def.tool_id == "check_data_quality":
            continue

        async def fake(*_a: Any, _tool_id: str = tool_def.tool_id, **_k: Any) -> dict[str, Any]:
            order.append(_tool_id)
            return {
                "tool_id": _tool_id,
                "status": "ok",
                "data": {"reading": "42", "n": {"x": "1.5"}},
                "error": None,
            }

        monkeypatch.setattr(tools_module, tool_def.tool_id, fake)


async def _build(settings: Settings) -> Any:
    return await build_snapshot(
        engine=object(),
        settings=settings,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question="What changed?",
    )


async def test_snapshot_is_identical_to_the_untimed_baseline(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    order: list[str] = []
    _patch_tools(monkeypatch, order)
    snap = await _build(settings)
    assert snap.snapshot_id == BASELINE_SNAPSHOT_ID
    assert snap.tools_called == BASELINE_TOOL_ORDER
    assert order == BASELINE_TOOL_ORDER[:-1]  # execution order unchanged (13 sequential tools)


async def test_one_timing_event_per_awaited_tool_in_order_with_no_payload(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    order: list[str] = []
    _patch_tools(monkeypatch, order)
    with structlog.testing.capture_logs() as captured:
        await _build(settings)
    events = [e for e in captured if e["event"] == TIMING_EVENT]
    assert [e["tool_id"] for e in events] == BASELINE_TOOL_ORDER[:-1]
    for e in events:
        assert set(e) <= {"event", "log_level", "tool_id", "elapsed_ms", "status"}
        assert isinstance(e["elapsed_ms"], float)
        assert e["elapsed_ms"] >= 0
        assert e["status"] == "ok"


async def test_a_tool_exception_propagates_unchanged_and_stops_later_tools(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    order: list[str] = []
    _patch_tools(monkeypatch, order)
    boom = SentinelError("boom")

    async def raises(*_a: Any, **_k: Any) -> dict[str, Any]:
        order.append("get_derivatives")
        raise boom

    monkeypatch.setattr(tools_module, "get_derivatives", raises)
    with structlog.testing.capture_logs() as captured, pytest.raises(SentinelError) as excinfo:
        await _build(settings)
    assert excinfo.value is boom
    assert order == BASELINE_TOOL_ORDER[:5]  # nothing after the failing tool ran
    events = [e for e in captured if e["event"] == TIMING_EVENT]
    assert [e["tool_id"] for e in events] == BASELINE_TOOL_ORDER[:5]
    assert events[-1]["status"] == "raised"


async def test_base_exceptions_such_as_time_limit_signals_pass_through(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    order: list[str] = []
    _patch_tools(monkeypatch, order)
    stop = HardStop()

    async def raises(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise stop

    monkeypatch.setattr(tools_module, "get_anomalies", raises)
    with pytest.raises(HardStop) as excinfo:
        await _build(settings)
    assert excinfo.value is stop
