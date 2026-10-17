"""``build_snapshot`` opens one memo scope per build: the snapshot (id, 14 tools, fields) is
unchanged, reuse is visible in a log-only event, and nothing survives into the next build."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog

from cfi.analyst import tools as tools_module
from cfi.analyst.universe import TOOLS
from cfi.core import pit_memo
from cfi.core.config import Settings
from cfi.core.pit_memo import pit_read, pit_revision_window
from tests.integration import test_alert_evaluate_seeded_benchmark as bench
from tests.unit.test_analyst_snapshot_timing import (
    AS_OF,
    BASELINE_SNAPSHOT_ID,
    BASELINE_TOOL_ORDER,
    _build,
    _patch_tools,
)

EVENT = "analyst_snapshot_pit_memo"


def _patch_regime_and_similarity_reads(monkeypatch: pytest.MonkeyPatch, reads: list[int]) -> None:
    engine_marker = object()

    async def shared_read() -> dict[str, str]:
        reads.append(1)
        return {"v": "1"}

    for tool_id in ("get_market_regime", "find_historical_similar_periods"):

        async def fake(*_a: Any, _tool_id: str = tool_id, **_k: Any) -> dict[str, Any]:
            await pit_read("x", engine_marker, AS_OF, AS_OF, call=shared_read)
            return {
                "tool_id": _tool_id,
                "status": "ok",
                "data": {"reading": "42", "n": {"x": "1.5"}},
                "error": None,
            }

        monkeypatch.setattr(tools_module, tool_id, fake)


async def test_snapshot_unchanged_and_regime_similarity_reads_shared(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    order: list[str] = []
    _patch_tools(monkeypatch, order)
    reads: list[int] = []
    _patch_regime_and_similarity_reads(monkeypatch, reads)
    with structlog.testing.capture_logs() as captured:
        snap = await _build(settings)
    assert snap.snapshot_id == BASELINE_SNAPSHOT_ID
    assert snap.tools_called == BASELINE_TOOL_ORDER
    assert {t.tool_id for t in TOOLS} == set(snap.tools_called)  # all 14 declared tools
    assert len(reads) == 1  # two tools asked, one real read
    [event] = [e for e in captured if e["event"] == EVENT]
    assert (event["hits"], event["misses"]) == (1, 1)


async def test_nothing_is_reused_between_builds(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_tools(monkeypatch, [])
    reads: list[int] = []
    _patch_regime_and_similarity_reads(monkeypatch, reads)
    await _build(settings)
    await _build(settings)
    assert len(reads) == 2  # one real read per build, never carried over


_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)
_ROW = {"event_time": _LONG_AGO, "available_at": _LONG_AGO, "ingested_at": _LONG_AGO, "revision": 0}


async def _window_request(family: str, as_of: datetime, engine: object, rows: int) -> None:
    async def load(_s: datetime, _e: datetime, _c: datetime) -> list[dict[str, Any]]:
        return [dict(_ROW) for _ in range(rows)]

    async def direct() -> list[dict[str, Any]]:
        return []

    await pit_revision_window(
        (family,),
        engine,
        start=_LONG_AGO,
        end=_LONG_AGO + timedelta(days=1),
        as_of=as_of,
        knowledge_time=as_of,
        load=load,
        direct=direct,
    )


async def test_event_reports_the_real_revision_window_counters(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """window_hits / window_loads / window_fallbacks on the event are the scope's own counters:
    a served request, an SQL fill, a request past the cutoff and a row-budget exhaustion."""
    _patch_tools(monkeypatch, [])
    engine_marker = object()
    monkeypatch.setattr(pit_memo, "MAX_WINDOW_ROWS", 1)

    async def fake(*_a: Any, **_k: Any) -> dict[str, Any]:
        await _window_request("a", _LONG_AGO + timedelta(hours=1), engine_marker, 1)  # load + hit
        await _window_request("a", _LONG_AGO + timedelta(hours=2), engine_marker, 1)  # hit
        await _window_request("c", datetime.now(UTC) + timedelta(days=1), engine_marker, 1)  # SQL
        await _window_request("b", _LONG_AGO + timedelta(hours=1), engine_marker, 2)  # over budget
        await _window_request("b", _LONG_AGO + timedelta(hours=2), engine_marker, 2)  # now disabled
        return {"tool_id": "get_market_regime", "status": "ok", "data": {}, "error": None}

    monkeypatch.setattr(tools_module, "get_market_regime", fake)
    with structlog.testing.capture_logs() as captured:
        await _build(settings)
    [event] = [e for e in captured if e["event"] == EVENT]
    assert event["window_hits"] == 2
    assert event["window_loads"] == 2  # family "a" once; family "b" once (its load was refused)
    assert event["window_fallbacks"] == 3  # past the cutoff; over budget; disabled afterwards


async def test_event_window_counters_are_zero_without_window_reads(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_tools(monkeypatch, [])
    with structlog.testing.capture_logs() as captured:
        await _build(settings)
    [event] = [e for e in captured if e["event"] == EVENT]
    assert (event["window_hits"], event["window_loads"], event["window_fallbacks"]) == (0, 0, 0)


def test_benchmark_report_block_carries_the_window_counters() -> None:
    event = {
        "event": EVENT,
        "hits": 4,
        "misses": 5,
        "uncached": 0,
        "hits_by_name": {"x": 4},
        "misses_by_name": {"x": 5},
        "window_hits": 11,
        "window_loads": 3,
        "window_fallbacks": 2,
        "not_a_report_field": 1,
    }
    run = bench.Run(wall_seconds=1.0, result=None, events=[event])  # type: ignore[arg-type]
    assert bench.pit_memo_block(run) == {k: event[k] for k in bench.PIT_MEMO_REPORT_KEYS}
    assert {"window_hits", "window_loads", "window_fallbacks"} <= set(bench.PIT_MEMO_REPORT_KEYS)
