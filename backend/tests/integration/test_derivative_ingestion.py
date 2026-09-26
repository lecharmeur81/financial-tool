"""Derivatives ingestion against real PostgreSQL + TimescaleDB: the real adapters, engine and
jobs, fed by fake Binance futures, OKX and Deribit servers
(expected values: tests/fixtures/derivatives/README.md)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from cfi.derivatives.sources import source
from cfi.derivatives.universe import dataset
from tests.derivative_fakes import LATEST, NOW, SPIKE
from tests.integration.conftest import requires_services
from tests.integration.derivative_support import DerivativesHarness

pytestmark = [pytest.mark.integration, requires_services]


async def test_everything_is_stored_with_provenance(deriv: DerivativesHarness) -> None:
    await deriv.load_everything()
    rows = await deriv.rows(
        """
        SELECT s.venue, o.value, o.available_at, o.pit_reliability, o.source_provider
          FROM obs.observation o JOIN obs.series s USING (series_id)
         WHERE s.dataset_id = 'deriv.open_interest.btc.1h' AND o.event_time = :t
         ORDER BY s.venue
        """,
        t=LATEST,
    )
    assert [(r["venue"], r["value"]) for r in rows] == [
        ("binance", Decimal(110_000)),
        ("okx", Decimal(30_000)),
    ]
    assert {r["source_provider"] for r in rows} == {"binance_futures", "okx_derivatives"}
    assert rows[0]["available_at"] == LATEST + timedelta(minutes=5)
    assert rows[0]["pit_reliability"] == "native"
    liq = await deriv.rows(
        """
        SELECT s.subject_ref, o.value, o.transformations
          FROM obs.observation o JOIN obs.series s USING (series_id)
         WHERE s.dataset_id = 'deriv.liquidations.btc.1h' AND o.event_time = :t
         ORDER BY s.subject_ref
        """,
        t=SPIKE,
    )
    # 1,800 long and 200 short contracts × 0.01 BTC
    assert [(r["subject_ref"], r["value"]) for r in liq] == [
        ("PERP:BTC-USDT:long", Decimal(18)),
        ("PERP:BTC-USDT:short", Decimal(2)),
    ]
    hours = await deriv.rows(
        """
        SELECT count(DISTINCT o.event_time) AS n, min(o.event_time) AS first
          FROM obs.observation o JOIN obs.series s USING (series_id)
         WHERE s.dataset_id = 'deriv.liquidations.btc.1h' AND o.quality_status = 'ok'
        """
    )
    # collected from 09:00 on 2026-09-02 (first run) to 11:00 on 2026-09-10, without a gap
    assert hours[0]["n"] == 8 * 24 + 3
    quotes = await deriv.rows(
        """
        SELECT s.dataset_id, q.instrument, q.instrument_kind, q.mark_iv, q.expiry, q.event_time
          FROM obs.derivative_quote q JOIN obs.series s USING (series_id)
         ORDER BY q.instrument
        """
    )
    assert len([q for q in quotes if q["dataset_id"] == "deriv.futures_curve.btc"]) == 7
    put = next(q for q in quotes if q["instrument"] == "BTC-9OCT26-54000-P")
    assert put["mark_iv"] == Decimal("0.55")  # 55 % stored as a ratio
    assert put["event_time"] == NOW  # Deribit's response time
    dvol = await deriv.rows(
        """
        SELECT o.value FROM obs.observation o JOIN obs.series s USING (series_id)
         WHERE s.dataset_id = 'deriv.volatility_index.1h' AND o.event_time = :t
        """,
        t=LATEST,
    )
    assert dvol == [{"value": Decimal("0.45")}]


async def test_failures_and_empty_answers_are_recorded(deriv: DerivativesHarness) -> None:
    item = source("okx_derivatives", "deriv.liquidations.sol.1h", "SOL")
    [result] = await deriv.run(item)
    assert result.status == "failed"  # the fake lists no SOL instrument: never guessed
    assert result.error_code == "schema_mismatch"
    [empty, *_] = await deriv.run(source("okx_derivatives", "deriv.open_interest.sol.1h", "SOL"))
    assert empty.status == "succeeded"
    assert empty.stale is True  # no data for the window is reported, not hidden


async def test_reingestion_is_idempotent_and_gaps_become_missing(
    deriv: DerivativesHarness,
) -> None:
    item = source("binance_futures", "deriv.open_interest.btc.1h", "BTC")
    [first, _history] = await deriv.run(item)
    assert first.inserted == 6
    [again, *_] = await deriv.run(item)
    assert (again.inserted, again.duplicates) == (0, 6)
    new_hour = LATEST + timedelta(hours=1)
    deriv.binance.drop = {new_hour}
    deriv.wall.advance(timedelta(hours=1))
    [late, *_] = await deriv.run(item)
    # the new hour (12:00) is not published: an explicit missing point, never interpolated
    missing = await deriv.rows(
        """
        SELECT o.event_time, o.quality_note FROM obs.observation o
          JOIN obs.series s USING (series_id)
         WHERE s.dataset_id = :d AND o.quality_status = 'missing'
        """,
        d=dataset("open_interest", "BTC").dataset_id,
    )
    assert late.missing >= 1
    assert [m["event_time"] for m in missing] == [new_hour]
    assert "Binance published no value" in missing[0]["quality_note"]
