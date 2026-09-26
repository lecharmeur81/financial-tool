"""Retail ingestion (Phase 10): the real CoinGecko-trending and Blockchair-small-output-count
adapters, engine and database, against the fakes' synthetic histories."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import text

from cfi.providers import blockchair, coingecko
from tests.integration.conftest import requires_services
from tests.integration.retail_support import RetailHarness
from tests.retail_fakes import (
    LAST_DAY,
    MEME_COUNT_PATTERN,
    all_days,
    meme_count_at,
    small_output_count,
)

pytestmark = [pytest.mark.integration, requires_services]

LAST_DAY_MIDNIGHT = datetime.combine(LAST_DAY, time.min, tzinfo=UTC)


# --------------------------------------------------------------------------- CoinGecko trending


async def test_trending_stores_one_snapshot_per_poll(retail: RetailHarness) -> None:
    await retail.load_trending(polls=5)
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(DISTINCT o.event_time) AS n FROM obs.observation o "
                "JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = 'retail.trending_coin_rank'"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == 5


async def test_trending_stores_ranks_matching_the_fakes_pattern(retail: RetailHarness) -> None:
    """Poll index 0 has zero meme coins trending (only the filler coin, BTC)."""
    await retail.load_trending(polls=1)
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT s.asset, o.value FROM obs.observation o "
                "JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = 'retail.trending_coin_rank'"
            )
        )
        got = {r["asset"]: r["value"] for r in rows.mappings().all()}
    assert meme_count_at(0) == MEME_COUNT_PATTERN[0] == 0
    assert got == {"BTC": 0}


async def test_trending_a_later_poll_includes_meme_coins_at_their_rank(
    retail: RetailHarness,
) -> None:
    """Poll index 2 has two meme coins trending (DOGE rank 0, SHIB rank 1)."""
    await retail.load_trending(polls=3)  # poll indices 0, 1, 2
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT s.asset, o.value, o.event_time FROM obs.observation o "
                "JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = 'retail.trending_coin_rank' "
                "ORDER BY o.event_time DESC"
            )
        )
        by_time: dict[datetime, dict[str, int]] = {}
        for r in rows.mappings().all():
            by_time.setdefault(r["event_time"], {})[r["asset"]] = int(r["value"])
    assert meme_count_at(2) == 2
    latest_time = max(by_time)
    assert by_time[latest_time] == {"DOGE": 0, "SHIB": 1, "BTC": 2}


async def test_trending_repolling_at_the_same_time_does_not_duplicate(
    retail: RetailHarness,
) -> None:
    item = retail.source(coingecko.PROVIDER_ID, "retail.trending_coin_rank", "GLOBAL")
    await retail.run(item)
    await retail.run(item)  # same wall-clock time — same event_time both times
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(DISTINCT o.event_time) AS n FROM obs.observation o "
                "JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = 'retail.trending_coin_rank'"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == 1


# --------------------------------------------------------------------------- Blockchair small-tx


async def test_small_output_count_ingests_the_entire_fake_history(retail: RetailHarness) -> None:
    await retail.load_small_output_count()
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(*) AS n FROM obs.observation o JOIN obs.series s "
                "USING (series_id) WHERE s.dataset_id = 'retail.small_output_count.btc.1d' "
                "AND o.value IS NOT NULL"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == len(all_days())


async def test_small_output_count_stored_value_matches_the_fake_for_the_latest_day(
    retail: RetailHarness,
) -> None:
    await retail.load_small_output_count()
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT o.value, o.source_provider FROM obs.observation o "
                "JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = 'retail.small_output_count.btc.1d' AND o.event_time = :t"
            ),
            {"t": LAST_DAY_MIDNIGHT},
        )
        (row,) = rows.mappings().all()
    assert row["value"] == small_output_count(LAST_DAY)
    assert row["source_provider"] == "blockchair"


async def test_small_output_count_a_second_run_does_not_duplicate(retail: RetailHarness) -> None:
    await retail.load_small_output_count()
    item = retail.source(blockchair.PROVIDER_ID, "retail.small_output_count.btc.1d", "BTC")
    await retail.run(item)
    async with retail.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(*) AS n FROM obs.observation o JOIN obs.series s "
                "USING (series_id) WHERE s.dataset_id = 'retail.small_output_count.btc.1d' "
                "AND o.value IS NOT NULL"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == len(all_days())
