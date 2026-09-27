"""Market-structure ingestion (Phase 12): the real CoinGecko adapter's ``/global`` extension,
engine and database, against the fake's synthetic, deterministic TOTAL market cap."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from cfi.ingestion.scheduled import recent_window
from cfi.market_structure.sources import ADAPTERS
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD
from tests.integration.conftest import requires_services
from tests.integration.market_structure_support import MarketStructureHarness
from tests.market_structure_fakes import total_market_cap_at

pytestmark = [pytest.mark.integration, requires_services]


async def _values(harness: MarketStructureHarness) -> list[tuple[datetime, object]]:
    async with harness.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT o.event_time, o.value, o.quality_status, s.asset, s.subject_ref "
                "FROM obs.observation o JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = :d ORDER BY o.event_time"
            ),
            {"d": TOTAL_MARKET_CAP_USD.dataset_id},
        )
        return [(r["event_time"], r["value"]) for r in rows.mappings().all()]


async def test_total_market_cap_stores_the_expected_value(
    market_structure: MarketStructureHarness,
) -> None:
    await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
    rows = await _values(market_structure)
    assert len(rows) == 1
    event_time, value = rows[0]
    assert value == total_market_cap_at(event_time)


async def test_total_market_cap_series_uses_the_global_sentinel_subject(
    market_structure: MarketStructureHarness,
) -> None:
    await market_structure.load(TOTAL_MARKET_CAP_USD.dataset_id)
    async with market_structure.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT DISTINCT s.asset, s.subject_ref FROM obs.series s WHERE s.dataset_id = :d"
            ),
            {"d": TOTAL_MARKET_CAP_USD.dataset_id},
        )
        series = [dict(r) for r in rows.mappings().all()]
    assert series == [{"asset": GLOBAL_SUBJECT, "subject_ref": GLOBAL_SUBJECT}]


async def test_repeated_recent_window_does_not_duplicate(
    market_structure: MarketStructureHarness,
) -> None:
    item = market_structure.source(TOTAL_MARKET_CAP_USD.dataset_id)
    await market_structure.run(item)
    before = len(await _values(market_structure))
    window = await recent_window(market_structure.ctx, item)
    result = await market_structure.ctx.engine.ingest(
        item.dataset,
        ADAPTERS[item.provider_id],
        market_structure.ctx.clients[item.provider_id],
        window,
    )
    assert result.status == "succeeded"
    assert result.inserted == 0
    after = len(await _values(market_structure))
    assert after == before
