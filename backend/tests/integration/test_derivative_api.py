"""Derivatives API against real PostgreSQL + TimescaleDB, fed through the real ingestion
pipeline from the synthetic history (expected values: tests/fixtures/derivatives/README.md)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from tests.derivative_fakes import NOW
from tests.integration.conftest import requires_services
from tests.integration.derivative_support import DerivativesHarness

pytestmark = [pytest.mark.integration, requires_services]

PIT = {"as_of": NOW.isoformat(), "knowledge_time": NOW.isoformat()}


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


def by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {i[key]: i for i in items}


async def test_btc_health_score_matches_the_hand_computation(
    deriv: DerivativesHarness, test_settings: Settings
) -> None:
    await deriv.load_everything()
    status, body = get(test_settings, "/api/v1/derivatives/asset", asset="btc", **PIT)
    assert status == 200
    score = body["score"]
    assert (score["status"], score["health"], score["stress"], score["band"]) == (
        "ok",
        "59.4",
        "40.6",
        "moderate stress",
    )
    assert score["evidence_category"] == "Calculated Metric"
    c = by_id(score["components"], "component_id")
    assert {k: v["stress"] for k, v in c.items()} == {
        "funding": "0.5214",
        "basis": "0.1381",
        "leverage": "0.8333",
        "liquidations": "0.1433",
        "volatility": "0.3000",
    }
    assert c["funding"]["value"] == "15.64"  # % a year, OI-weighted
    assert c["basis"]["value"] == "12.07"
    assert c["leverage"]["value"] == "16.67"
    assert c["volatility"]["value"] == "45.00"
    for comp in c.values():  # every component exposes how it was computed
        assert comp["calculation"]
        assert comp["definition"]
        assert comp["weight"]
        assert comp["contribution"] is not None
    assert c["funding"]["context"] == "positive: long positions pay short positions"
    assert c["basis"]["context"].startswith("contango")
    assert c["leverage"]["inputs"]["market_cap_now"] == "1200000000000"


async def test_btc_metrics_and_conditions(
    deriv: DerivativesHarness, test_settings: Settings
) -> None:
    await deriv.load_everything()
    _, body = get(test_settings, "/api/v1/derivatives/asset", asset="BTC", **PIT)
    oi = body["open_interest"]
    assert (oi["total"], oi["change_24h_pct"], oi["change_7d_pct"]) == ("140000", "12.00", "16.67")
    assert oi["condition"] == "expansion"
    assert oi["total_usd"] == "8400000000"  # 140,000 × 60,000 (Coinbase close)
    assert body["leverage"]["condition"] == "expansion"
    funding = body["funding"]
    assert funding["annualised_7d_pct"] == "15.64"
    assert {v["venue"]: v["settlements_7d"] for v in funding["venues"]} == {
        "binance": 21,
        "okx": 21,
    }
    basis = body["basis"]
    assert basis["headline"]["instrument"] == "BTC-25DEC26"
    assert basis["headline"]["annualised_pct"] == "12.07"
    assert basis["perpetual_premium_pct"] == "0.0500"
    assert basis["shape"] == "contango"
    liq = body["liquidations"]
    assert (liq["long_24h"], liq["short_24h"], liq["total_24h"]) == (
        "31.80",
        "11.20",
        "43.00",
    )  # exact: 60 contracts × 0.01
    assert liq["share_of_oi_pct"] == "0.1433"
    assert [e["hour"] for e in liq["events"]] == ["2026-09-10T05:00:00+00:00"]
    options = body["options"]
    assert (options["put_call_oi_ratio"], options["put_call_volume_ratio"]) == (
        "0.6452",
        "0.7317",
    )
    assert options["atm_iv_pct"] == "45.00"
    assert options["skew_pct_points"] == "8.00"
    assert options["skew_put"] == {"strike": "54000", "iv_pct": "55.00"}
    assert options["expiry"] == "2026-10-09T08:00:00+00:00"
    assert body["volatility"]["dvol_pct"] == "45.00"
    ratios = by_id(body["positioning"]["long_short_account_ratio"], "venue")
    assert (ratios["binance"]["ratio"], ratios["okx"]["ratio"]) == ("1.5", "1.2")
    assert body["price_context"]["description"] == (
        "Open interest rising while price is flat: new positions are being opened without a "
        "price move."
    )
    states = {c["condition_id"]: c["state"] for c in body["conditions"]}
    assert states == {
        "oi_expansion": "active",
        "oi_contraction": "inactive",
        "leverage_expansion": "active",
        "leverage_reduction": "inactive",
        "funding_extreme": "inactive",
        "basis_extreme": "inactive",
        "liquidation_event": "active",
        "derivatives_stress": "inactive",
    }
    # no reading is labelled with a direction (the evidence note says so; everything else is data)
    text = str({k: v for k, v in body.items() if k != "evidence_note"}).lower()
    assert "bullish" not in text
    assert "bearish" not in text
    sources = body["data_quality"]["sources"]
    assert {s["provider_id"] for s in sources} == {"binance_futures", "okx_derivatives", "deribit"}
    assert all(s["last_run"] is not None for s in sources)


async def test_missing_data_says_insufficient_data(
    deriv: DerivativesHarness, test_settings: Settings
) -> None:
    await deriv.load_everything()
    _, sol = get(test_settings, "/api/v1/derivatives/asset", asset="SOL", **PIT)
    assert sol["score"]["status"] == "insufficient_data"
    assert sol["score"]["health"] is None
    assert sol["score"]["reason"].startswith("Insufficient data")
    c = by_id(sol["score"]["components"], "component_id")
    assert c["funding"]["status"] == "ok"  # Binance only: 0.0001 × 21 × 365 ÷ 7
    assert c["funding"]["value"] == "10.95"
    assert (c["basis"]["status"], c["volatility"]["status"]) == ("not_applicable",) * 2
    assert sol["options"]["status"] == "not_applicable"
    sol_states = {c["condition_id"]: c["state"] for c in sol["conditions"]}
    assert sol_states["liquidation_event"] == "unknown"  # no OKX data: never "not active"
    assert sol_states["leverage_expansion"] == "unknown"
    assert sol_states["basis_extreme"] == "not_applicable"
    status, overview = get(test_settings, "/api/v1/derivatives/overview", **PIT)
    assert status == 200
    assets = by_id(overview["assets"], "asset")
    assert list(assets) == ["BTC", "ETH", "SOL", "XRP"]
    assert assets["BTC"]["health"] == "59.4"
    assert assets["ETH"]["score_status"] == "insufficient_data"
    assert "Open interest expansion" in assets["BTC"]["active_conditions"]
    status, _ = get(test_settings, "/api/v1/derivatives/asset", asset="DOGE", **PIT)
    assert status == 404


async def test_point_in_time_views_never_see_later_data(
    deriv: DerivativesHarness, test_settings: Settings
) -> None:
    await deriv.load_everything()
    day_before = NOW - timedelta(days=1)
    _, body = get(
        test_settings,
        "/api/v1/derivatives/asset",
        asset="BTC",
        as_of=day_before.isoformat(),
        knowledge_time=NOW.isoformat(),
    )
    oi = body["open_interest"]
    assert oi["total"] == "125000"  # 95,000 + 30,000 at 11:00 the day before
    assert body["basis"]["status"] == "unavailable"  # the Deribit snapshot was taken later
    assert body["options"]["status"] == "unavailable"
    assert body["liquidations"]["events"] == []  # the cascade happened later
    # knowledge time: what this system had stored — nothing of the snapshots taken at NOW
    _, before = get(
        test_settings,
        "/api/v1/derivatives/asset",
        asset="BTC",
        as_of=NOW.isoformat(),
        knowledge_time=(NOW - timedelta(minutes=1)).isoformat(),
    )
    assert before["open_interest"]["total"] is None
    assert before["score"]["components"][0]["status"] == "unavailable"


async def test_history_and_catalog(deriv: DerivativesHarness, test_settings: Settings) -> None:
    await deriv.load_everything()
    status, body = get(test_settings, "/api/v1/derivatives/history", asset="BTC", days=2, **PIT)
    assert status == 200
    agg = body["open_interest"]["aggregate"]
    assert agg[-1] == {"time": "2026-09-10T11:00:00+00:00", "value": "140000"}
    assert body["open_interest"]["aggregate_venues"] == ["binance", "okx"]
    assert body["price"]["points"][-1]["value"] == "60000"
    assert set(body["liquidations"]["sides"]) == {"long", "short"}
    status, catalog = get(test_settings, "/api/v1/derivatives/catalog")
    assert status == 200
    assert {p["provider_id"] for p in catalog["providers"]} == {
        "binance_futures",
        "okx_derivatives",
        "deribit",
    }
    weights = [c["weight"] for c in catalog["score"]["components"]]
    assert sum(float(w) for w in weights) == pytest.approx(1.0)
    assert catalog["not_tracked"]
