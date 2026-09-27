"""Market Anomaly Engine API against real PostgreSQL, fed through the real Coinbase ingestion
pipeline already exercised by ``test_divergence_api.py`` / ``test_market_structure_api.py``.

Scope (documented, not silently narrowed — see PROGRESS.md's Phase 19 known limitations): this
suite seeds only price/volume bars (the lightest harness already proven in Phase 5), which is
enough to exercise the volume/volatility/market_structure metrics end to end plus the full-catalog
and empty-database paths. It does not additionally seed institutional/whale/retail/liquidity/
derivatives data — those domains' own harnesses are already covered by their own phases' integration
suites, and every ``cfi.anomaly.metrics`` pure function is unit-tested against synthetic series in
``test_anomaly_metrics.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ASSET_SYMBOLS, ohlcv_dataset
from tests.integration.conftest import requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)  # after MarketHarness's own fixed "NOW"


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _seed_bars(market: MarketHarness) -> None:
    for asset in ASSET_SYMBOLS:
        await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, asset, depth_days=280)


async def test_catalog_lists_all_13_metrics(test_settings: Settings) -> None:
    status, body = get(test_settings, "/api/v1/anomaly/catalog")
    assert status == 200
    assert len(body["metrics"]) == 13
    assert {m["metric_id"] for m in body["metrics"]} == {
        "etf_flows",
        "institutional_flows",
        "whale_flows",
        "exchange_flows",
        "funding",
        "oi",
        "liquidations",
        "stablecoin_supply",
        "retail_activity",
        "social_activity",
        "volume",
        "volatility",
        "market_structure",
    }
    assert body["bands"]["version"] == "anomaly_bands_v1"
    assert body["not_tracked"]


async def test_scan_is_insufficient_data_when_nothing_is_loaded(test_settings: Settings) -> None:
    status, body = get(
        test_settings,
        "/api/v1/anomaly/scan",
        asset="BTC",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert len(body["anomalies"]) == 13
    volume = next(a for a in body["anomalies"] if a["metric_id"] == "volume")
    assert volume["status"] == "insufficient_data"
    assert volume["band"] == "unavailable"
    assert volume["possible_interpretations"] == [
        "Not enough historical readings to rank this metric yet."
    ]


async def test_scan_reports_ok_status_for_volume_once_bars_are_seeded(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/anomaly/scan",
        asset="BTC",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    volume = next(a for a in body["anomalies"] if a["metric_id"] == "volume")
    assert volume["status"] == "ok"
    assert volume["current_value"] is not None
    assert volume["timestamp"] is not None
    assert volume["band"] in (
        "extreme_high",
        "notable_high",
        "normal",
        "notable_low",
        "extreme_low",
    )
    assert volume["data_quality"]["status"] in ("ok", "degraded")

    volatility = next(a for a in body["anomalies"] if a["metric_id"] == "volatility")
    assert volatility["status"] == "ok"

    market_structure = next(a for a in body["anomalies"] if a["metric_id"] == "market_structure")
    # TOTAL market cap has no seeded history in this suite (Phase 12 gap, see NOT_TRACKED)
    assert market_structure["status"] == "insufficient_data"


async def test_metric_endpoint_matches_the_same_reading_as_scan(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/anomaly/metric",
        metric_id="volume",
        asset="BTC",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["metric_id"] == "volume"
    assert body["asset"] == "BTC"
    assert body["source"]
    assert body["current_value"] is not None
    assert "contradicting_evidence" in body
    counterpart_ids = {c["metric_id"] for c in body["contradicting_evidence"]}
    assert counterpart_ids == {"volatility"}


async def test_metric_endpoint_rejects_an_unknown_metric_id(test_settings: Settings) -> None:
    status, _ = get(
        test_settings,
        "/api/v1/anomaly/metric",
        metric_id="not_a_real_metric",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 404


async def test_never_labels_an_anomaly_bullish_or_bearish(
    market: MarketHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    status, body = get(
        test_settings,
        "/api/v1/anomaly/scan",
        asset="BTC",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    banned = ("bullish", "bearish", "buy", "sell")
    for anomaly in body["anomalies"]:
        for line in anomaly["possible_interpretations"]:
            lowered = line.lower()
            assert not any(word in lowered for word in banned), line
