"""`cfi.journal.context` — pure extraction over an already-built snapshot (Phase 25 spec
"Decision-time context" / "Market regime"), covering the "Decision-time snapshot capture" and
"Missing data" testing categories without touching a database: every case here is a shape of
``Snapshot.raw`` that the real ``get_market_regime``/``get_market_data`` tools can actually
produce (``cfi.analyst.tools._run``'s own envelope: ``{"tool_id", "status", "data", "error"}``)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.analyst.snapshot import Snapshot
from cfi.journal.context import observed_price, regime_label


def _snapshot(raw: dict[str, object]) -> Snapshot:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Snapshot(
        snapshot_id="deadbeef",
        snapshot_version="v1",
        created_at=now,
        as_of=now,
        knowledge_time=now,
        question=None,
        tools_called=[],
        fields=[],
        field_index={},
        raw=raw,
        data_quality_state="ok",
        has_conflicts=False,
    )


# ------------------------------------------------------------------ regime_label


def test_regime_label_extracts_the_current_label() -> None:
    snapshot = _snapshot(
        {"get_market_regime": {"status": "ok", "data": {"label": "leveraged_expansion"}}}
    )
    assert regime_label(snapshot) == "leveraged_expansion"


def test_regime_label_is_none_when_tool_is_unavailable() -> None:
    snapshot = _snapshot(
        {"get_market_regime": {"status": "unavailable", "data": None, "error": {"msg": "down"}}}
    )
    assert regime_label(snapshot) is None


def test_regime_label_is_none_when_tool_result_is_missing_entirely() -> None:
    assert regime_label(_snapshot({})) is None


def test_regime_label_is_none_when_label_field_is_absent() -> None:
    snapshot = _snapshot({"get_market_regime": {"status": "ok", "data": {}}})
    assert regime_label(snapshot) is None


def test_regime_label_is_none_when_label_is_not_a_string() -> None:
    snapshot = _snapshot({"get_market_regime": {"status": "ok", "data": {"label": 12}}})
    assert regime_label(snapshot) is None


# ------------------------------------------------------------------ observed_price


def test_observed_price_extracts_the_closing_price_for_a_tracked_asset() -> None:
    snapshot = _snapshot(
        {
            "get_market_data": {
                "status": "ok",
                "data": {"assets": {"BTC": {"price_close": {"value": "65000.5"}}}},
            }
        }
    )
    assert observed_price(snapshot, "BTC") == Decimal("65000.5")


def test_observed_price_is_none_for_an_untracked_asset() -> None:
    snapshot = _snapshot(
        {
            "get_market_data": {
                "status": "ok",
                "data": {"assets": {"BTC": {"price_close": {"value": "65000.5"}}}},
            }
        }
    )
    assert observed_price(snapshot, "DOGE") is None


def test_observed_price_is_none_when_tool_is_unavailable() -> None:
    snapshot = _snapshot({"get_market_data": {"status": "unavailable", "data": None}})
    assert observed_price(snapshot, "BTC") is None


def test_observed_price_is_none_when_value_itself_is_missing() -> None:
    snapshot = _snapshot(
        {
            "get_market_data": {
                "status": "ok",
                "data": {"assets": {"BTC": {"price_close": {"value": None}}}},
            }
        }
    )
    assert observed_price(snapshot, "BTC") is None


def test_observed_price_is_none_when_value_is_not_numeric() -> None:
    snapshot = _snapshot(
        {
            "get_market_data": {
                "status": "ok",
                "data": {"assets": {"BTC": {"price_close": {"value": "not-a-number"}}}},
            }
        }
    )
    assert observed_price(snapshot, "BTC") is None


def test_observed_price_is_none_when_tool_result_is_missing_entirely() -> None:
    assert observed_price(_snapshot({}), "BTC") is None
