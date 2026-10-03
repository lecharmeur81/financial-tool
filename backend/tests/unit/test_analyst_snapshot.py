"""The immutable evidence snapshot (Phase 21): the flattener's envelope/nesting rules, and
``build_snapshot``'s own invariants — every declared tool called exactly once, a stable hash, and
data-quality/conflict state threaded through from ``check_data_quality``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from cfi.analyst import tools as tools_module
from cfi.analyst.snapshot import SnapshotField, _flatten, build_snapshot
from cfi.analyst.universe import KNOWN_PLATFORM_LIMITATIONS, TOOLS
from cfi.core.config import Settings
from cfi.core.errors import ComputationError

AS_OF = datetime(2026, 9, 28, tzinfo=UTC)


def test_flatten_envelope_dict_is_promoted_as_one_field() -> None:
    out: list[SnapshotField] = []
    _flatten(
        "get_market_data.assets.BTC.price_close",
        {"value": "65000.00", "unit": "usd", "evidence_category": "observed_data", "source": "x"},
        out,
        source_default="get_market_data",
    )
    assert len(out) == 1
    f = out[0]
    assert f.field_id == "get_market_data.assets.BTC.price_close"
    assert f.display == "65000.00"
    assert f.value == Decimal("65000.00")
    assert f.evidence_category == "observed_data"
    assert f.source == "x"


def test_flatten_plain_dict_recurses_into_each_key() -> None:
    out: list[SnapshotField] = []
    _flatten("root", {"a": 1, "b": {"c": 2}}, out, source_default="tool")
    field_ids = {f.field_id for f in out}
    assert field_ids == {"root.a", "root.b.c"}


def test_flatten_list_indexes_each_item() -> None:
    out: list[SnapshotField] = []
    _flatten("root", [10, 20], out, source_default="tool")
    field_ids = {f.field_id for f in out}
    assert field_ids == {"root[0]", "root[1]"}


def test_flatten_skips_none_and_bool() -> None:
    out: list[SnapshotField] = []
    _flatten("root", {"a": None, "b": True, "c": False}, out, source_default="tool")
    assert out == []


def test_flatten_skips_overly_long_strings_as_prose_not_a_fact() -> None:
    out: list[SnapshotField] = []
    _flatten("root", {"note": "x" * 500}, out, source_default="tool")
    assert out == []


def test_flatten_non_numeric_string_has_no_parsed_value() -> None:
    out: list[SnapshotField] = []
    _flatten("root", {"label": "leveraged_expansion"}, out, source_default="tool")
    assert out[0].display == "leveraged_expansion"
    assert out[0].value is None


def _fake_tool_result(tool_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"tool_id": tool_id, "status": "ok", "data": data or {"reading": "42"}, "error": None}


def _patch_all_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    for tool_def in TOOLS:
        if tool_def.tool_id == "check_data_quality":
            continue

        async def fake(
            *_args: Any, _tool_id: str = tool_def.tool_id, **_kwargs: Any
        ) -> dict[str, Any]:
            return _fake_tool_result(_tool_id)

        monkeypatch.setattr(tools_module, tool_def.tool_id, fake)


async def test_build_snapshot_calls_every_declared_tool_exactly_once(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_all_tools(monkeypatch)
    snap = await build_snapshot(
        engine=object(),
        settings=settings,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question="What changed?",
    )
    assert set(snap.tools_called) == {t.tool_id for t in TOOLS}
    assert len(snap.tools_called) == len(TOOLS)
    assert snap.question == "What changed?"
    assert snap.data_quality_state == "ok"
    assert snap.has_conflicts is False
    assert "get_market_data.reading" in snap.field_index


async def test_build_snapshot_is_deterministic_for_identical_inputs(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_all_tools(monkeypatch)
    snap1 = await build_snapshot(
        engine=object(), settings=settings, as_of=AS_OF, knowledge_time=AS_OF, question=None
    )
    snap2 = await build_snapshot(
        engine=object(), settings=settings, as_of=AS_OF, knowledge_time=AS_OF, question=None
    )
    assert snap1.snapshot_id == snap2.snapshot_id


async def test_build_snapshot_raises_if_a_tool_is_not_called(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A ``ComputationError``, never a silently incomplete snapshot (R3) — this guards against a
    future edit to ``build_snapshot`` accidentally dropping a tool call."""
    _patch_all_tools(monkeypatch)

    # Sabotage: have get_institutional_flows report the wrong tool_id, so the declared/called sets
    # can never match.
    async def wrong_id(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return _fake_tool_result("not_a_real_tool_id")

    monkeypatch.setattr(tools_module, "get_institutional_flows", wrong_id)

    with pytest.raises(ComputationError):
        await build_snapshot(
            engine=object(), settings=settings, as_of=AS_OF, knowledge_time=AS_OF, question=None
        )


async def test_build_snapshot_surfaces_degraded_data_quality(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_all_tools(monkeypatch)

    async def unavailable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "tool_id": "get_liquidity",
            "status": "unavailable",
            "data": None,
            "error": {"error_code": "insufficient_data", "detail": "no data"},
        }

    monkeypatch.setattr(tools_module, "get_liquidity", unavailable)
    snap = await build_snapshot(
        engine=object(), settings=settings, as_of=AS_OF, knowledge_time=AS_OF, question=None
    )
    assert snap.data_quality_state == "degraded"


def test_snapshot_payload_never_includes_the_not_tracked_limitations_as_a_field_source() -> None:
    """``payload()`` always discloses ``not_tracked`` (Section 18) verbatim, not folded into a
    citable numeric field."""
    from cfi.analyst.snapshot import Snapshot

    snap = Snapshot(
        snapshot_id="abc",
        snapshot_version="v1",
        created_at=AS_OF,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question=None,
        tools_called=[],
        fields=[],
        field_index={},
        raw={},
        data_quality_state="ok",
        has_conflicts=False,
    )
    payload = snap.payload()
    assert payload["not_tracked"] == list(KNOWN_PLATFORM_LIMITATIONS)
