"""Market-data ingestion end to end: real adapters + engine + jobs + PostgreSQL/TimescaleDB,
with fake provider servers answering in each provider's documented format (synthetic values)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import httpx2
import pytest

from cfi.market.jobs import backfill_step, ingest_latest, latest_window
from cfi.market.sources import ADAPTERS
from cfi.market.universe import (
    MARKET_CAP_USD,
    MARKET_CAP_USD_1D,
    SPOT_PRICE_USD,
    ohlcv_dataset,
)
from cfi.providers import coinbase
from tests.integration.conftest import requires_services
from tests.integration.market_support import BARS_SQL, NOW, MarketHarness
from tests.market_fakes import SynthBar, synthetic_bar, synthetic_market_cap

pytestmark = [pytest.mark.integration, requires_services]

M = timedelta(minutes=1)
H = timedelta(hours=1)
CB_1M = ohlcv_dataset("usd", "1m")
CB_1H = ohlcv_dataset("usd", "1h")
BN_1H = ohlcv_dataset("usdt", "1h")
ANCHOR = NOW.replace(second=0)  # 12:00, open time of the unfinished 1m bar


async def test_latest_bars_are_stored_with_full_provenance(market: MarketHarness) -> None:
    results = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert [r.subject for r in results] == ["BTC", "ETH", "SOL", "XRP"]
    btc = results[0]
    assert btc.status == "succeeded"
    assert btc.inserted == 14  # 11:45 … 11:58
    assert btc.skipped == 1  # 11:59 closed at 12:00 and is final only from 12:01
    assert btc.missing == 0
    assert btc.stale is False

    rows = await market.rows(BARS_SQL, d=CB_1M.dataset_id, a="BTC")
    assert len(rows) == 14
    first = rows[0]
    expected = synthetic_bar("BTC", first["event_time"], M)
    assert first["event_time"] == ANCHOR - 15 * M
    assert (first["open"], first["high"], first["low"], first["close"]) == (
        expected.open,
        expected.high,
        expected.low,
        expected.close,
    )
    assert first["volume_base"] == expected.volume
    assert first["volume_quote"] is None  # not reported by Coinbase, not estimated
    # what / asset / unit / venue / provider / origin / timing / reliability / transformation
    assert (first["unit"], first["venue"], first["subject_ref"]) == (
        "usd",
        "coinbase",
        "coinbase:spot:BTC-USD",
    )
    assert (first["source_provider"], first["original_source"]) == ("coinbase", "coinbase_exchange")
    assert first["available_at"] == first["event_time"] + M + timedelta(seconds=60)
    assert first["ingested_at"] == NOW
    assert first["pit_reliability"] == "backfilled_latest"  # recorded 13 min after it was final
    assert rows[-1]["pit_reliability"] == "native"  # 11:58 recorded 30 s after it was final
    assert first["transformations"] == [
        "event_time: epoch seconds -> UTC",
        "fields reordered from [time, low, high, open, close, volume]",
    ]
    assert first["raw_ref"] is not None

    jobs = await market.rows(
        "SELECT subject, status, skipped, job_type FROM ops.job_run ORDER BY job_run_id"
    )
    assert jobs[0] == {"subject": "BTC", "status": "succeeded", "skipped": 1, "job_type": "ingest"}

    # one minute later (window 11:46-12:00): 11:59 is now final, 12:00 is not, the rest is
    # already stored
    market.wall.advance(M)
    again = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert (again[0].inserted, again[0].duplicates, again[0].skipped) == (1, 13, 1)


async def test_a_minute_without_a_candle_becomes_an_explicit_missing_row(
    market: MarketHarness,
) -> None:
    market.fakes["coinbase"].omitted.add(("BTC", 60, ANCHOR - 10 * M))
    (btc, *_) = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert btc.missing == 1
    rows = {r["event_time"]: r for r in await market.rows(BARS_SQL, d=CB_1M.dataset_id, a="BTC")}
    gap = rows[ANCHOR - 10 * M]
    assert gap["close"] is None
    assert gap["volume_base"] is None
    assert gap["quality_status"] == "missing"
    assert gap["quality_note"] == coinbase.CAPABILITIES.gap_note  # "may mean zero trading"
    findings = await market.rows(
        "SELECT check_name, details FROM ops.quality_check_result WHERE check_name = :c",
        c="completeness_gap",
    )
    assert len(findings) == 1


async def test_inconsistent_bar_is_kept_and_flagged_suspect(market: MarketHarness) -> None:
    t = ANCHOR - 5 * M
    bad = SynthBar(
        Decimal(100), Decimal(90), Decimal(95), Decimal(98), Decimal(1), Decimal(98), 1
    )  # high below open
    market.fakes["coinbase"].overrides[("ETH", 60, t)] = bad
    _, eth, *_ = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert eth.suspect == 1
    rows = {r["event_time"]: r for r in await market.rows(BARS_SQL, d=CB_1M.dataset_id, a="ETH")}
    assert rows[t]["quality_status"] == "suspect"
    assert rows[t]["high"] == Decimal(90)  # kept exactly as reported, never "fixed"
    assert "high is below open, close or low" in rows[t]["quality_note"]
    job = await market.rows("SELECT suspect FROM ops.job_run WHERE subject = 'ETH'")
    assert job == [{"suspect": 1}]


async def test_changed_bar_is_a_new_revision_not_an_overwrite(market: MarketHarness) -> None:
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    t = ANCHOR - 3 * M
    original = synthetic_bar("XRP", t, M)
    market.fakes["coinbase"].overrides[("XRP", 60, t)] = SynthBar(
        original.open,
        original.high,
        original.low,
        original.close,
        original.volume + 1,
        original.quote_volume,
        original.trades,
    )
    market.wall.advance(M)
    *_, xrp = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert xrp.revisions == 1
    rows = [
        r for r in await market.rows(BARS_SQL, d=CB_1M.dataset_id, a="XRP") if r["event_time"] == t
    ]
    assert [(r["revision"], r["volume_base"]) for r in rows] == [
        (0, original.volume),
        (1, original.volume + 1),
    ]
    finding = await market.rows(
        "SELECT status FROM ops.quality_check_result WHERE check_name = 'revision'"
    )
    assert finding == [{"status": "unexpected"}]  # exchange candles are not revisable


async def test_worker_downtime_is_caught_up_on_the_next_run(market: MarketHarness) -> None:
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    market.wall.advance(3 * H)
    window = await latest_window(market.ctx, CB_1M, "coinbase", "SOL")
    assert window.start == ANCHOR - M  # resumes right after the newest stored bar (11:59)
    *_, sol, _xrp = await ingest_latest(market.ctx, ADAPTERS["coinbase"], CB_1M)
    assert sol.missing == 0
    assert sol.inserted == 180  # 11:59 … 14:58, nothing left unrecorded


async def test_backfill_walks_history_back_and_stops_at_the_listing(
    market: MarketHarness,
) -> None:
    listing = ANCHOR - 500 * H
    market.fakes["coinbase"].listed_from["SOL"] = listing
    steps = []
    while (
        result := await backfill_step(market.ctx, ADAPTERS["coinbase"], CB_1H, "SOL", depth_days=90)
    ) is not None:
        steps.append(result)
    assert [r.job_type for r in steps] == ["backfill"] * 5
    assert [r.inserted for r in steps] == [299, 200, 0, 0, 0]  # 11:00 not final at 12:00:30
    rows = await market.rows(BARS_SQL, d=CB_1H.dataset_id, a="SOL")
    assert rows[0]["event_time"] == listing
    assert all(r["quality_status"] == "ok" for r in rows)  # pre-listing is not "missing"
    (state,) = await market.rows("SELECT * FROM ops.backfill_state")
    assert state["complete"] is True
    assert "start of the provider's available history" in state["note"]
    assert state["covered_from"] == ANCHOR - 1500 * H


async def test_failed_backfill_chunk_is_retried_not_skipped(market: MarketHarness) -> None:
    market.fakes["coinbase"].then(*(httpx2.Response(503) for _ in range(3)))
    failed = await backfill_step(market.ctx, ADAPTERS["coinbase"], CB_1H, "BTC", depth_days=30)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "provider_transient_error"
    assert await market.rows("SELECT * FROM ops.backfill_state") == []  # no progress recorded
    ok = await backfill_step(market.ctx, ADAPTERS["coinbase"], CB_1H, "BTC", depth_days=30)
    assert ok is not None
    assert ok.status == "succeeded"
    (state,) = await market.rows("SELECT covered_from FROM ops.backfill_state")
    assert state["covered_from"] == ANCHOR - 300 * H


async def test_binance_bars_are_a_separate_usdt_series(market: MarketHarness) -> None:
    results = await ingest_latest(market.ctx, ADAPTERS["binance"], BN_1H)
    assert all(r.status == "succeeded" for r in results)
    rows = await market.rows(BARS_SQL, d=BN_1H.dataset_id, a="ETH")
    assert {r["unit"] for r in rows} == {"usdt"}
    assert rows[0]["subject_ref"] == "binance:spot:ETH-USDT"
    expected = synthetic_bar("ETH", rows[0]["event_time"], H)
    assert rows[0]["volume_quote"] == expected.quote_volume
    assert rows[0]["trade_count"] == expected.trades


async def test_last_trade_and_market_caps(market: MarketHarness) -> None:
    await ingest_latest(market.ctx, ADAPTERS["coinbase"], SPOT_PRICE_USD)
    await ingest_latest(market.ctx, ADAPTERS["coingecko"], MARKET_CAP_USD)
    daily = await backfill_step(
        market.ctx, ADAPTERS["coingecko"], MARKET_CAP_USD_1D, "BTC", depth_days=5
    )
    assert daily is not None
    assert daily.skipped == 1  # CoinGecko's running value is not a daily snapshot
    obs = await market.rows(
        """SELECT s.dataset_id, s.subject_ref, o.value, o.event_time, o.pit_reliability
             FROM obs.observation o JOIN obs.series s USING (series_id)
            ORDER BY s.dataset_id, s.subject_ref, o.event_time"""
    )
    trades = [o for o in obs if o["dataset_id"] == SPOT_PRICE_USD.dataset_id]
    assert [o["subject_ref"] for o in trades] == [
        "coinbase:spot:BTC-USD",
        "coinbase:spot:ETH-USD",
        "coinbase:spot:SOL-USD",
        "coinbase:spot:XRP-USD",
    ]
    caps = {o["subject_ref"]: o for o in obs if o["dataset_id"] == MARKET_CAP_USD.dataset_id}
    assert caps["BTC"]["value"] == synthetic_market_cap("BTC", NOW - timedelta(seconds=30))
    history = [o for o in obs if o["dataset_id"] == MARKET_CAP_USD_1D.dataset_id]
    midnight = NOW.replace(hour=0, minute=0, second=0)
    assert [o["event_time"] for o in history][-1] == midnight
    assert history[-1]["value"] == synthetic_market_cap("BTC", midnight)


# --------------------------------------------------------------------------- backup venues


@pytest.mark.parametrize(
    ("provider", "quote", "instrument"),
    [
        ("okx", "usdt", "okx:spot:SOL-USDT"),
        ("bybit", "usdt", "bybit:spot:SOL-USDT"),
        ("kraken", "usd", "kraken:spot:SOL-USD"),
    ],
)
@pytest.mark.parametrize("timeframe", ["1m", "4h", "1d"])
async def test_backup_venues_store_their_own_series(
    market: MarketHarness, provider: str, quote: str, instrument: str, timeframe: str
) -> None:
    dataset = ohlcv_dataset(quote, timeframe)
    results = await ingest_latest(market.ctx, ADAPTERS[provider], dataset)
    assert all(r.status == "succeeded" for r in results), [r.error_detail for r in results]
    sol = results[2]
    assert sol.inserted > 0
    assert sol.missing == 0
    assert sol.skipped <= 2  # the venue's current bar, and one that closed under a minute ago
    rows = [
        r
        for r in await market.rows(BARS_SQL, d=dataset.dataset_id, a="SOL")
        if r["source_provider"] == provider
    ]
    assert {r["subject_ref"] for r in rows} == {instrument}
    assert {r["unit"] for r in rows} == {quote}
    period = {"1m": M, "4h": 4 * H, "1d": 24 * H}[timeframe]
    for row in rows:
        expected = synthetic_bar("SOL", row["event_time"], period)
        assert row["close"] == expected.close
        assert row["event_time"] + period + timedelta(seconds=60) <= NOW  # only final bars


async def test_okx_paginates_backwards_through_history(market: MarketHarness) -> None:
    dataset = ohlcv_dataset("usdt", "1h")
    step = await backfill_step(market.ctx, ADAPTERS["okx"], dataset, "BTC", depth_days=60)
    assert step is not None
    assert step.status == "succeeded"
    assert step.pages >= 10  # 1000 bars in pages of 100
    assert step.inserted == 999  # the newest hour is not final yet
    rows = await market.rows(BARS_SQL, d=dataset.dataset_id, a="BTC")
    assert len({r["event_time"] for r in rows}) == 999


async def test_kraken_history_stops_where_kraken_stops(market: MarketHarness) -> None:
    """Kraken serves only its 720 most recent bars: older requests return nothing new, so the
    backfill ends with a note instead of pretending older data is missing."""
    dataset = ohlcv_dataset("usd", "1h")
    while (
        await backfill_step(market.ctx, ADAPTERS["kraken"], dataset, "ETH", depth_days=365)
    ) is not None:
        pass
    rows = await market.rows(BARS_SQL, d=dataset.dataset_id, a="ETH")
    # 720 entries: the newest is uncommitted and the one before closed <1 minute ago (not final)
    assert len(rows) == 718
    assert all(r["quality_status"] == "ok" for r in rows)
    (state,) = await market.rows(
        "SELECT complete, note FROM ops.backfill_state WHERE provider_id = 'kraken'"
    )
    assert state["complete"] is True
    assert "available history" in state["note"]
