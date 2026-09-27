"""Market-structure API against real PostgreSQL, fed through the real Coinbase/CoinGecko
ingestion pipelines (the fakes in ``tests/market_fakes.py`` and
``tests/market_structure_fakes.py``).

The catalog/overview shape is checked end to end here (status, evidence labelling, score
components); the underlying formulas are exercised at the unit level
(``test_market_structure_metrics.py``, ``test_market_structure_score.py``)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step, ingest_latest
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ASSET_SYMBOLS, MARKET_CAP_USD, ohlcv_dataset
from cfi.market_structure.universe import TOTAL_MARKET_CAP_USD
from tests.integration.conftest import requires_services
from tests.integration.market_structure_support import MarketStructureHarness
from tests.integration.market_support import MarketHarness
from tests.market_structure_fakes import total_market_cap_at

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _seed_bars(market: MarketHarness) -> None:
    """Enough daily history (one 300-bar Coinbase chunk, well above the 200 bars every metric
    needs to reach 'ok') for all four tracked assets."""
    for asset in ASSET_SYMBOLS:
        await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, asset, depth_days=280)
    await ingest_latest(market.ctx, MARKET_ADAPTERS["coingecko"], MARKET_CAP_USD)


async def test_catalog_lists_tracked_assets_and_the_score_definition(
    market_structure: MarketStructureHarness, test_settings: Settings
) -> None:
    status, body = get(test_settings, "/api/v1/market-structure/catalog")
    assert status == 200
    assert set(body["tracked_assets"]) == {"BTC", "ETH", "SOL", "XRP"}
    assert body["benchmark_asset"] == "BTC"
    assert body["score"]["score_id"] == "market_structure_score"
    component_ids = {c["component_id"] for c in body["score"]["components"]}
    assert component_ids == {
        "price_trend",
        "momentum",
        "market_breadth",
        "altcoin_relative_strength",
        "volatility_regime",
    }
    assert any(d["dataset_id"] == TOTAL_MARKET_CAP_USD.dataset_id for d in body["datasets"])


async def test_overview_is_insufficient_when_nothing_is_loaded(
    market_structure: MarketStructureHarness, test_settings: Settings
) -> None:
    as_of = market_structure.wall.current
    status, body = get(
        test_settings,
        "/api/v1/market-structure/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    assert body["score"]["status"] == "insufficient_data"
    assert body["score"]["score"] is None
    assert body["total_cap_family"]["status"] == "unavailable"
    for asset in ("BTC", "ETH", "SOL", "XRP"):
        assert body["assets"][asset]["moving_averages"]["status"] == "unavailable"


async def test_overview_computes_readings_once_bars_and_total_cap_are_loaded(
    market: MarketHarness, market_structure: MarketStructureHarness, test_settings: Settings
) -> None:
    await _seed_bars(market)
    await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
    as_of = market_structure.wall.current
    status, body = get(
        test_settings,
        "/api/v1/market-structure/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    assert body["score"]["status"] == "ok"
    assert body["score"]["score"] is not None
    assert "not a trading recommendation" in body["score"]["semantic_note"]

    for asset in ("BTC", "ETH", "SOL", "XRP"):
        section = body["assets"][asset]
        assert section["moving_averages"]["status"] == "ok"
        assert section["trend"]["status"] == "ok"
        assert section["rsi"]["status"] == "ok"

    total = body["total_cap_family"]
    assert total["status"] == "ok"
    expected_total = total_market_cap_at(as_of)
    assert total["total_usd"] == format(expected_total, "f")
    # dominance = btc/eth market cap (from CoinGecko's synthetic simple/price) / TOTAL x 100
    assert 0 < float(total["btc_dominance_pct"]) < 100

    assert body["market_breadth"]["status"] == "ok"
    assert body["eth_btc"]["status"] == "ok"


async def test_history_returns_total_market_cap_points(
    market_structure: MarketStructureHarness, test_settings: Settings
) -> None:
    await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
    as_of = market_structure.wall.current
    status, body = get(
        test_settings,
        "/api/v1/market-structure/history",
        series="total_market_cap",
        days=30,
        as_of=as_of.isoformat(),
    )
    assert status == 200
    assert body["series"] == "total_market_cap"
    assert len(body["points"]) == 1


async def test_history_rejects_unknown_series(
    market_structure: MarketStructureHarness, test_settings: Settings
) -> None:
    as_of = market_structure.wall.current
    status, _body = get(
        test_settings,
        "/api/v1/market-structure/history",
        series="not_real",
        days=30,
        as_of=as_of.isoformat(),
    )
    assert status == 404
