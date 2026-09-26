"""Liquidity ingestion (Phase 9): the real DefiLlama adapter, engine and database, against the
fake server's synthetic stablecoin-supply history."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.integration.conftest import requires_services
from tests.integration.liquidity_support import LiquidityHarness
from tests.liquidity_fakes import LATEST_DAY, NOW, all_days, epoch_seconds, total_supply

pytestmark = [pytest.mark.integration, requires_services]


async def test_ingests_the_entire_fake_history_in_one_run(liquidity: LiquidityHarness) -> None:
    await liquidity.load_everything()
    async with liquidity.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(*) AS n FROM obs.observation o JOIN obs.series s "
                "USING (series_id) WHERE s.asset = 'TOTAL' AND o.value IS NOT NULL"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == len(all_days())


async def test_stored_value_matches_the_fake_for_the_latest_day(
    liquidity: LiquidityHarness,
) -> None:
    await liquidity.load_everything()
    async with liquidity.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT o.value, o.available_at, o.available_at_estimated, o.source_provider "
                "FROM obs.observation o JOIN obs.series s USING (series_id) "
                "WHERE s.asset = 'TOTAL' AND o.event_time = :t"
            ),
            {"t": NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)},
        )
        (row,) = rows.mappings().all()
    assert row["value"] == total_supply(LATEST_DAY)
    assert row["source_provider"] == "defillama"
    # 36 h after the UTC-midnight event time; the fake's clock is well past that
    assert row["available_at_estimated"] is True


async def test_a_second_run_re_reads_the_recent_window_without_duplicating_data(
    liquidity: LiquidityHarness,
) -> None:
    await liquidity.load_everything()
    await liquidity.run(liquidity.source("TOTAL"))
    async with liquidity.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT count(*) AS n FROM obs.observation o JOIN obs.series s "
                "USING (series_id) WHERE s.asset = 'TOTAL' AND o.value IS NOT NULL"
            )
        )
        n = rows.mappings().one()["n"]
    assert n == len(all_days())


def test_fake_epoch_seconds_roundtrip_sanity() -> None:
    # a quick sanity check on the fixture's own date <-> epoch-seconds math (not the adapter)
    assert epoch_seconds(LATEST_DAY) % 86400 == 0
