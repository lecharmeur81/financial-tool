"""Market API against real PostgreSQL + TimescaleDB, fed through the real ingestion pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step, ingest_latest
from cfi.market.sources import ADAPTERS
from cfi.market.universe import MARKET_CAP_USD, SPOT_PRICE_USD, ohlcv_dataset
from tests.integration.conftest import requires_services
from tests.integration.market_support import NOW, MarketHarness
from tests.market_fakes import synthetic_bar, synthetic_market_cap

pytestmark = [pytest.mark.integration, requires_services]

M = timedelta(minutes=1)
H = timedelta(hours=1)
ANCHOR = NOW.replace(second=0)


def get(settings: Settings, path: str, **params: Any) -> Any:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


def iso(t: datetime) -> str:
    return t.isoformat()


async def test_catalog_describes_venues_units_and_derived_timeframes(
    market: MarketHarness, test_settings: Settings
) -> None:
    status, body = get(test_settings, "/api/v1/market/catalog")
    assert status == 200
    venues = {v["venue_id"]: v for v in body["venues"]}
    assert venues["coinbase"]["quote"] == "usd"
    assert venues["binance"]["quote"] == "usdt"
    tf = {t["timeframe"]: t for t in venues["coinbase"]["timeframes"]}
    assert tf["4h"] == {"timeframe": "4h", "source": "derived", "derived_from": "1h"}
    assert tf["1m"]["source"] == "native"
    assert body["market_cap_source"]["attribution"]["text"] == "Data provided by CoinGecko"
    assert [a["symbol"] for a in body["assets"]] == ["BTC", "ETH", "SOL", "XRP"]


async def test_bars_carry_exact_values_source_freshness_and_gaps(
    market: MarketHarness, test_settings: Settings
) -> None:
    market.fakes["coinbase"].omitted.add(("BTC", 60, ANCHOR - 4 * M))
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], ohlcv_dataset("usd", "1m"))
    status, body = get(
        test_settings,
        "/api/v1/market/bars",
        asset="btc",
        timeframe="1m",
        venue="coinbase",
        limit=20,
        as_of=iso(NOW),
    )
    assert status == 200
    assert body["evidence_category"] == "observed"
    assert body["instrument"]["price_unit"] == "usd"
    assert body["instrument"]["volume_unit"] == "BTC"
    assert body["source"]["provider_name"] == "Coinbase Exchange"
    assert body["source"]["original_source"] == "coinbase_exchange"
    assert body["derivation"] is None
    bars = body["bars"]
    assert len(bars) == 14  # 11:45 … 11:58, including one explicit missing bar
    first = bars[0]
    expected = synthetic_bar("BTC", ANCHOR - 15 * M, M)
    assert Decimal(first["open"]) == expected.open
    assert Decimal(first["close"]) == expected.close
    assert isinstance(first["close"], str)  # exact decimal, not a float
    gap = next(b for b in bars if b["quality_status"] == "missing")
    assert gap["close"] is None
    assert "zero trading activity" in gap["quality_note"]
    quality = body["quality"]
    assert quality["missing"] == 1
    assert quality["not_loaded"] == 5  # 11:40-11:44 are before the first stored bar
    assert quality["coverage_start"].startswith("2026-09-01T11:45:00")
    fresh = body["freshness"]
    assert fresh["status"] == "fresh"
    assert fresh["latest_bar_time"].startswith("2026-09-01T11:58:00")
    assert fresh["limit_seconds"] == 300
    assert body["ingestion"]["last_run"]["status"] == "succeeded"
    assert "1 bar(s) missing in this range." in body["warnings"]


async def test_stale_data_is_reported(market: MarketHarness, test_settings: Settings) -> None:
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], ohlcv_dataset("usd", "1m"))
    _, body = get(
        test_settings,
        "/api/v1/market/bars",
        asset="BTC",
        timeframe="1m",
        as_of=iso(NOW + 2 * H),
    )
    assert body["freshness"]["status"] == "stale"
    assert any(w.startswith("Data is stale") for w in body["warnings"])


async def test_point_in_time_view_never_shows_later_data(
    market: MarketHarness, test_settings: Settings
) -> None:
    """Leakage test (R3/R11): a past as_of must not see bars stored after it."""
    dataset = ohlcv_dataset("usd", "1m")
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], dataset)
    market.wall.advance(H)
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], dataset)  # catches up to 12:58
    _, now_view = get(
        test_settings, "/api/v1/market/bars", asset="ETH", timeframe="1m", as_of=iso(NOW + H)
    )
    assert now_view["freshness"]["latest_bar_time"].startswith("2026-09-01T12:58:00")
    _, past = get(
        test_settings,
        "/api/v1/market/bars",
        asset="ETH",
        timeframe="1m",
        limit=100,
        as_of=iso(NOW + 30 * M),
    )
    times = [b["time"] for b in past["bars"]]
    assert times[-1].startswith("2026-09-01T11:58:00")  # later bars were stored at 13:00:30
    assert past["freshness"]["status"] == "stale"  # as it honestly looked at 12:30:30


async def test_4h_bars_are_rolled_up_from_1h_and_labelled(
    market: MarketHarness, test_settings: Settings
) -> None:
    dataset = ohlcv_dataset("usd", "1h")
    market.fakes["coinbase"].omitted.add(("SOL", 3600, ANCHOR - 7 * H))  # 05:00 → bucket 04:00
    await backfill_step(market.ctx, ADAPTERS["coinbase"], dataset, "SOL", depth_days=2)
    _, body = get(
        test_settings,
        "/api/v1/market/bars",
        asset="SOL",
        timeframe="4h",
        venue="coinbase",
        limit=3,
        as_of=iso(NOW),
    )
    assert body["derivation"]["from_timeframe"] == "1h"
    assert "rolled up from 1h bars" in body["warnings"][-1]
    bars = {b["time"][:16]: b for b in body["bars"]}
    assert set(bars) == {"2026-09-01T00:00", "2026-09-01T04:00"}  # 08:00 bucket not closed
    parts = [ANCHOR - 12 * H + i * H for i in range(4)]  # 00:00 … 03:00
    hourly = [synthetic_bar("SOL", t, H) for t in parts]
    full = bars["2026-09-01T00:00"]
    assert Decimal(full["open"]) == hourly[0].open
    assert Decimal(full["high"]) == max(b.high for b in hourly)
    assert Decimal(full["low"]) == min(b.low for b in hourly)
    assert Decimal(full["close"]) == hourly[-1].close
    assert Decimal(full["volume_base"]) == sum(b.volume for b in hourly)
    assert full["quality_status"] == "ok"
    incomplete = bars["2026-09-01T04:00"]
    assert incomplete["quality_status"] == "missing"
    assert incomplete["close"] is None
    assert incomplete["quality_note"] == "incomplete: 3 of 4 1h bars available"


async def test_overview_shows_last_trade_latest_bars_and_market_cap(
    market: MarketHarness, test_settings: Settings
) -> None:
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], SPOT_PRICE_USD)
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], ohlcv_dataset("usd", "1m"))
    await ingest_latest(market.ctx, ADAPTERS["coingecko"], MARKET_CAP_USD)
    status, body = get(test_settings, "/api/v1/market/overview", as_of=iso(NOW))
    assert status == 200
    btc = body["assets"][0]
    assert btc["symbol"] == "BTC"
    trade = btc["last_trade"]
    assert trade["unit"] == "usd"
    assert trade["freshness"] == "fresh"
    assert trade["source"]["provider_id"] == "coinbase"
    cap = btc["market_cap"]
    assert Decimal(cap["value"]) == synthetic_market_cap("BTC", NOW - timedelta(seconds=30))
    assert cap["source"]["attribution"]["url"] == "https://www.coingecko.com"
    venues = {b["venue_id"]: b for b in btc["latest_bars"]}
    assert venues["coinbase"]["freshness"] == "fresh"
    assert venues["binance"]["freshness"] == "no_data"  # never ingested: shown, not hidden
    assert venues["binance"]["unit"] == "usdt"


async def test_errors_are_explicit(market: MarketHarness, test_settings: Settings) -> None:
    status, body = get(test_settings, "/api/v1/market/bars", asset="DOGE", timeframe="1h")
    assert status == 404
    assert body["error_code"] == "not_found"
    status, _ = get(test_settings, "/api/v1/market/bars", asset="BTC", timeframe="2h")
    assert status == 404
    status, body = get(
        test_settings,
        "/api/v1/market/bars",
        asset="BTC",
        timeframe="1h",
        as_of="2026-09-01T10:00:00",
    )
    assert status == 422
    assert "time zone" in body["detail"]
    status, body = get(test_settings, "/api/v1/market/bars", asset="BTC", timeframe="1h")
    assert status == 200
    assert body["freshness"]["status"] == "no_data"
    assert "No 1h data stored yet for this instrument." in body["warnings"]


async def test_summary_reuses_the_analyst_tool_verbatim(
    market: MarketHarness, test_settings: Settings
) -> None:
    """Phase 26: ``GET /market/summary`` is a thin pass-through to ``cfi.analyst.tools.
    get_market_data`` — same envelope, same fields, no new calculation."""
    await backfill_step(
        market.ctx, ADAPTERS["coinbase"], ohlcv_dataset("usd", "1d"), "BTC", depth_days=280
    )
    status, body = get(test_settings, "/api/v1/market/summary", as_of=iso(NOW))
    assert status == 200
    assert body["tool_id"] == "get_market_data"
    assert body["status"] == "ok"
    btc = body["data"]["assets"]["BTC"]
    assert btc["price_close"]["value"] is not None
    assert btc["change_24h_pct"]["unit"] == "pct"
    assert btc["volume_24h"]["evidence_category"] == "observed_data"
    assert btc["realized_volatility_30d"]["unit"] == "annualized_ratio"


async def test_summary_is_honest_about_untracked_data(test_settings: Settings) -> None:
    """No bars seeded — every asset's fields are `None`, never a fabricated price (R3)."""
    status, body = get(test_settings, "/api/v1/market/summary")
    assert status == 200
    assert body["status"] == "ok"
    for asset in body["data"]["assets"].values():
        assert asset["price_close"]["value"] is None
