"""Macro ingestion (Phase 11): the real FRED adapter, engine and database, against the fake's
synthetic, deterministic series (daily, weekly, monthly and event-based)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from cfi.ingestion.scheduled import recent_window
from cfi.macro.sources import ADAPTERS
from cfi.macro.universe import CPI, FED_BALANCE_SHEET, FED_FUNDS_TARGET_UPPER, VIX
from tests.integration.conftest import requires_services
from tests.integration.macro_support import MacroHarness
from tests.macro_fakes import NOW, value_on

pytestmark = [pytest.mark.integration, requires_services]


async def _values(harness: MacroHarness, dataset_id: str) -> list[tuple[datetime, object]]:
    async with harness.db.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT o.event_time, o.value, o.quality_status FROM obs.observation o "
                "JOIN obs.series s USING (series_id) WHERE s.dataset_id = :d "
                "ORDER BY o.event_time"
            ),
            {"d": dataset_id},
        )
        return [(r["event_time"], r["value"]) for r in rows.mappings().all()]


# --------------------------------------------------------------------------- daily (VIX)


async def test_daily_series_stores_expected_values(macro: MacroHarness) -> None:
    await macro.load(VIX.dataset_id, history_runs=1)
    rows = await _values(macro, VIX.dataset_id)
    assert len(rows) > 0
    latest_time, latest_value = rows[-1]
    assert latest_value == value_on("VIXCLS", latest_time.date())


async def test_daily_series_repeated_recent_window_does_not_duplicate(macro: MacroHarness) -> None:
    """Re-running the *same* recent window (no further history progress) stores no new rows —
    distinct from history still advancing, which legitimately adds more on every call until
    complete (see ``cfi.ingestion.scheduled.history_step``, exercised by the load()-based tests
    above)."""
    item = macro.source(VIX.dataset_id)
    await macro.run(item)  # one recent-window ingest + one history chunk
    before = len(await _values(macro, VIX.dataset_id))
    window = await recent_window(macro.ctx, item)
    result = await macro.ctx.engine.ingest(
        item.dataset, ADAPTERS[item.provider_id], macro.ctx.clients[item.provider_id], window
    )
    assert result.status == "succeeded"
    assert result.inserted == 0
    after = len(await _values(macro, VIX.dataset_id))
    assert after == before


# -------------------------------------------------------------------- weekly (Fed balance sheet)


async def test_weekly_series_stores_values_on_the_weekly_grid(macro: MacroHarness) -> None:
    await macro.load(FED_BALANCE_SHEET.dataset_id, history_runs=1)
    rows = await _values(macro, FED_BALANCE_SHEET.dataset_id)
    assert len(rows) > 0
    for event_time, value in rows:
        assert value == value_on("WALCL", event_time.date())


# --------------------------------------------------------------------------- monthly (CPI)


async def test_monthly_series_stores_values_dated_on_the_first_of_the_month(
    macro: MacroHarness,
) -> None:
    await macro.load(CPI.dataset_id, history_runs=1)
    rows = await _values(macro, CPI.dataset_id)
    assert len(rows) > 0
    for event_time, value in rows:
        assert event_time.day == 1
        assert value == value_on("CPIAUCSL", event_time.date())


# --------------------------------------------------------------------------- event (FOMC target)


async def test_event_series_stores_the_constant_target_rate(macro: MacroHarness) -> None:
    await macro.load(FED_FUNDS_TARGET_UPPER.dataset_id, history_runs=1)
    rows = await _values(macro, FED_FUNDS_TARGET_UPPER.dataset_id)
    assert len(rows) > 0
    # DFEDTARU has zero drift in the fake: every stored value is identical.
    assert {value for _, value in rows} == {value_on("DFEDTARU", NOW.date())}
