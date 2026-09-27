"""Market-structure API against real PostgreSQL, fed through the real Coinbase/CoinGecko
ingestion pipelines (the fakes in ``tests/market_fakes.py`` and
``tests/market_structure_fakes.py``).

The catalog/overview shape is checked end to end here (status, evidence labelling, score
components); the underlying formulas are exercised at the unit level
(``test_market_structure_metrics.py``, ``test_market_structure_score.py``)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.db import tables as t
from cfi.market.jobs import backfill_step, ingest_latest
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ASSET_SYMBOLS, MARKET_CAP_USD, ohlcv_dataset
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD
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


async def test_history_omitting_knowledge_time_does_not_leak_a_later_revision(
    market_structure: MarketStructureHarness,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED_TEAM_REPORT.md finding #1 (CRITICAL) / ADR-0060 (Phase 18).

    Before the fix, omitting ``knowledge_time`` made it default to ``utc_now()`` independently of
    ``as_of`` — so ``ingested_at <= knowledge_time`` was a no-op for any as-of-a-past-date query,
    and a later revision (stored after ``as_of`` but with an ``available_at`` that still reads as
    before it) would leak into the historical read. This seeds exactly that scenario directly in
    the database (bypassing the ingestion pipeline, matching the Phase 16 backtest leakage-test
    pattern) and asserts only the revision knowable *as of* the query date is ever returned,
    however far in the future the wall clock actually is when the query runs.
    """
    event_time = market_structure.wall.current
    as_of = event_time

    async with market_structure.db.begin() as conn:
        series_id = (
            await conn.execute(
                insert(t.series)
                .values(
                    dataset_id=TOTAL_MARKET_CAP_USD.dataset_id,
                    metric=TOTAL_MARKET_CAP_USD.metric,
                    asset=GLOBAL_SUBJECT,
                    subject_ref=GLOBAL_SUBJECT,
                    venue=None,
                    period=TOTAL_MARKET_CAP_USD.period,
                    unit=TOTAL_MARKET_CAP_USD.unit,
                    created_at=event_time,
                )
                .returning(t.series.c.series_id)
            )
        ).scalar_one()

        common = {
            "series_id": series_id,
            "event_time": event_time,
            "source_provider": "coingecko",
            "original_source": "coingecko",
            "raw_ref": None,
            "pit_reliability": "native",
            "quality_status": "ok",
            "quality_note": None,
            "confidence": None,
            "transformations": [],
            "available_at": event_time,
            "available_at_estimated": False,
        }
        # Revision 0: the original, first-published figure, known at (and before) as_of.
        await conn.execute(
            insert(t.observation),
            {**common, "ingested_at": event_time, "value": Decimal("1000000000000"), "revision": 0},
        )
        # Revision 1: a correction ingested well AFTER as_of — must never be visible to an
        # as-of-that-date query unless knowledge_time is explicitly moved forward past it.
        await conn.execute(
            insert(t.observation),
            {
                **common,
                "ingested_at": event_time + timedelta(days=5),
                "value": Decimal("2000000000000"),
                "revision": 1,
            },
        )

    # Simulate the wall clock actually being much later than either revision when the query
    # runs (the ordinary case: querying history well after the fact) — this is exactly the
    # condition under which the old "knowledge_time defaults to now()" bug would leak revision 1.
    monkeypatch.setattr("cfi.api.params.utc_now", lambda: event_time + timedelta(days=30))

    status, body = get(
        test_settings,
        "/api/v1/market-structure/history",
        series="total_market_cap",
        days=1,
        as_of=as_of.isoformat(),
        # knowledge_time deliberately omitted
    )
    assert status == 200
    assert len(body["points"]) == 1
    assert body["points"][0]["value"] == format(Decimal("1000000000000"), "f")

    # Sanity check: an explicit, later knowledge_time still legitimately surfaces the revision.
    status, body = get(
        test_settings,
        "/api/v1/market-structure/history",
        series="total_market_cap",
        days=1,
        as_of=as_of.isoformat(),
        knowledge_time=(event_time + timedelta(days=30)).isoformat(),
    )
    assert status == 200
    assert body["points"][0]["value"] == format(Decimal("2000000000000"), "f")
