"""Phase 52: a flagged-state alert is auto-resolved ONLY on explicit clearance evidence.

Missing items, failed/unavailable tools, unavailable readings, degraded or conflicting data are
unknown, not cleared. Pure/in-memory: ``cleared_dedup_keys`` is a pure function of a Snapshot and
``_auto_resolve_cleared`` is driven through a fake repository."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from cfi.alerts.rules import cleared_dedup_keys, evaluate_all
from cfi.alerts.service import AlertService
from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS
from cfi.analyst.snapshot import Snapshot

NOW = datetime(2026, 10, 19, tzinfo=UTC)
DIV = ALERT_TYPE_TOOL_IDS["divergence"]
ANO = ALERT_TYPE_TOOL_IDS["anomaly"]
ROT = ALERT_TYPE_TOOL_IDS["capital_rotation"]
OK_Q = {"status": "ok"}


def _snapshot(raw: dict[str, Any], *, has_conflicts: bool = False) -> Snapshot:
    return Snapshot(
        snapshot_id="x",
        snapshot_version="analyst_snapshot.v1",
        created_at=NOW,
        as_of=NOW,
        knowledge_time=NOW,
        question=None,
        tools_called=list(raw),
        fields=[],
        field_index={},
        raw=raw,
        data_quality_state="ok",
        has_conflicts=has_conflicts,
    )


def _tool(data: dict[str, Any], status: str = "ok") -> dict[str, Any]:
    return {"status": status, "data": data}


def _div(is_divergent: bool | None, quality: str = "ok") -> dict[str, Any]:
    leg = {"data_quality": {"status": quality}}
    comparison = {
        "comparison_id": "c1",
        "asset": "BTC",
        "is_divergent": is_divergent,
        "observed_quadrant": "q",
        "metric_a": leg,
        "metric_b": leg,
    }
    return _tool({"comparisons": [comparison]})


def _ano(band: str, *, status: str = "ok", quality: str = "ok") -> dict[str, Any]:
    item = {
        "metric_id": "m1",
        "asset": "BTC",
        "band": band,
        "status": status,
        "data_quality": {"status": quality},
    }
    return _tool({"anomalies": [item]})


def _rot(edge: str) -> dict[str, Any]:
    pair = {
        "from_node": {"node_id": "a"},
        "to_node": {"node_id": "b"},
        "inferred_capital_rotation": {"status": edge, "hypothesis": "h"},
    }
    return _tool({"pairs": [pair]})


def _cleared(raw: dict[str, Any], **kw: Any) -> frozenset[str]:
    return cleared_dedup_keys(_snapshot(raw, **kw))


# ------------------------------------------------------------------ explicit clearance


def test_confirmed_clearance_is_recognised_for_all_three_types() -> None:
    raw = {DIV: _div(False), ANO: _ano("normal"), ROT: _rot("no_rotation_signal")}
    assert _cleared(raw) == {"divergence:c1", "anomaly:m1", "capital_rotation:a->b"}


def test_a_still_flagged_item_is_a_candidate_and_never_cleared() -> None:
    raw = {DIV: _div(True), ANO: _ano("extreme_high"), ROT: _rot("possible_rotation")}
    assert _cleared(raw) == frozenset()
    assert {c.dedup_key for c in evaluate_all(_snapshot(raw))} == {
        "divergence:c1",
        "anomaly:m1",
        "capital_rotation:a->b",
    }


# ------------------------------------------------------------------ unknown is not cleared


@pytest.mark.parametrize(
    "raw",
    [
        {},  # no tool ran at all
        {DIV: _tool({}, status="error"), ANO: _tool({}, status="error"), ROT: _tool({}, "error")},
        {DIV: {"status": "ok", "data": None}, ANO: {"status": "ok", "data": None}},
        {DIV: _tool({"comparisons": []}), ANO: _tool({"anomalies": []}), ROT: _tool({"pairs": []})},
        {DIV: _tool({}), ANO: _tool({}), ROT: _tool({})},  # keys absent
    ],
)
def test_missing_or_failed_source_clears_nothing(raw: dict[str, Any]) -> None:
    assert _cleared(raw) == frozenset()


def test_unavailable_readings_are_not_clearance() -> None:
    raw = {DIV: _div(None), ANO: _ano("unavailable"), ROT: _rot("unavailable")}
    assert _cleared(raw) == frozenset()


@pytest.mark.parametrize("status", ["insufficient_data", "unavailable", "not_applicable"])
def test_unusable_anomaly_component_is_not_clearance(status: str) -> None:
    assert _cleared({ANO: _ano("normal", status=status)}) == frozenset()


@pytest.mark.parametrize("quality", ["degraded", "missing", "partial", "stale"])
def test_degraded_item_quality_is_insufficient_evidence(quality: str) -> None:
    raw = {DIV: _div(False, quality=quality), ANO: _ano("normal", quality=quality)}
    assert _cleared(raw) == frozenset()


def test_absent_item_quality_is_not_evidence() -> None:
    div = copy.deepcopy(_div(False))
    del div["data"]["comparisons"][0]["metric_a"]
    ano = copy.deepcopy(_ano("normal"))
    del ano["data"]["anomalies"][0]["data_quality"]
    assert _cleared({DIV: div, ANO: ano}) == frozenset()


@pytest.mark.parametrize("quality", ["degraded", "stale", "conflicting", "partial"])
def test_untrusted_tool_level_quality_clears_nothing(quality: str) -> None:
    rot = copy.deepcopy(_rot("no_rotation_signal"))
    rot["data"]["data_quality"] = {"status": quality}
    assert _cleared({ROT: rot}) == frozenset()


def test_conflicting_snapshot_clears_nothing() -> None:
    raw = {DIV: _div(False), ANO: _ano("normal"), ROT: _rot("no_rotation_signal")}
    assert _cleared(raw, has_conflicts=True) == frozenset()


# ------------------------------------------------------------------ the service decision


class FakeRepo:
    def __init__(self, entries: dict[str, list[tuple[str, int]]]) -> None:
        self.entries = entries
        self.resolved: list[int] = []

    async def active_entries_with_prefix(self, prefix: str) -> list[tuple[str, int]]:
        return self.entries.get(prefix.rstrip(":"), [])

    async def resolve(self, alert_id: int, *, now: datetime) -> None:
        self.resolved.append(alert_id)


def _run(
    entries: dict[str, list[tuple[str, int]]],
    cleared: frozenset[str],
    seen: dict[str, set[str]] | None = None,
) -> tuple[int, list[int]]:
    svc = object.__new__(AlertService)
    repo = FakeRepo(entries)
    svc.repo = repo  # type: ignore[assignment]
    seen_keys: dict[str, set[str]] = {
        "divergence": set(),
        "anomaly": set(),
        "capital_rotation": set(),
    }
    seen_keys.update(seen or {})
    count = asyncio.run(svc._auto_resolve_cleared(seen_keys, cleared, now=NOW))
    return count, repo.resolved


ENTRIES = {
    "divergence": [("divergence:c1", 1)],
    "anomaly": [("anomaly:m1", 2)],
    "capital_rotation": [("capital_rotation:a->b", 3)],
}


def test_service_resolves_only_explicitly_cleared_alerts() -> None:
    count, resolved = _run(ENTRIES, frozenset({"divergence:c1", "capital_rotation:a->b"}))
    assert (count, sorted(resolved)) == (2, [1, 3])  # the anomaly (unknown) is held


def test_service_holds_every_alert_when_nothing_is_cleared() -> None:
    assert _run(ENTRIES, frozenset()) == (0, [])


def test_service_never_resolves_a_key_that_is_still_flagged() -> None:
    count, resolved = _run(ENTRIES, frozenset({"anomaly:m1"}), seen={"anomaly": {"anomaly:m1"}})
    assert (count, resolved) == (0, [])


def test_service_ignores_clearance_for_keys_with_no_active_alert() -> None:
    assert _run({}, frozenset({"divergence:c1"})) == (0, [])
