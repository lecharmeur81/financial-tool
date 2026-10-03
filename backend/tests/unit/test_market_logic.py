"""Pure market-layer logic: bar invariants, gap/freshness reports, roll-ups, schedule, HTTP bans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx2
import pytest

from cfi.core.errors import ProviderTransientError
from cfi.domain.enums import AuthType, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalBar
from cfi.market.service import derived_bar, freshness, gap_report, resolve_range
from cfi.market.universe import all_datasets, ohlcv_dataset
from cfi.providers.base import AuthSpec, ProviderCapabilities, RequestSpec
from cfi.providers.http import CircuitBreaker, ListRecorder, ProviderHttpClient, RetryPolicy
from cfi.worker.schedule import beat_schedule, scheduled_ingestions
from tests.support import FakeClock

T = datetime(2026, 9, 1, 12, tzinfo=UTC)
M = timedelta(minutes=1)
H = timedelta(hours=1)


def bar(**overrides: Any) -> CanonicalBar:
    fields: dict[str, Any] = {
        "dataset_id": "market.ohlcv.usd.1m",
        "metric": "spot_ohlcv",
        "asset": "BTC",
        "subject_ref": "coinbase:spot:BTC-USD",
        "venue": "coinbase",
        "period": "1m",
        "unit": "usd",
        "event_time": T,
        "available_at": T + 2 * M,
        "available_at_estimated": True,
        "ingested_at": T + 2 * M,
        "open": Decimal(100),
        "high": Decimal(110),
        "low": Decimal(95),
        "close": Decimal(105),
        "volume_base": Decimal(3),
        "source_provider": "coinbase",
        "original_source": "coinbase_exchange",
        "quality_status": QualityStatus.OK,
        "pit_reliability": PitReliability.NATIVE,
    }
    return CanonicalBar(**{**fields, **overrides})


# --------------------------------------------------------------------------- bar invariants


def test_bar_consistency_checks_flag_but_do_not_fix() -> None:
    assert bar().consistency_problems() == []
    problems = bar(high=Decimal(90)).consistency_problems()
    assert "high is below open, close or low" in problems
    assert "non-positive price" in bar(low=Decimal(0)).consistency_problems()
    assert "negative volume" in bar(volume_base=Decimal(-1)).consistency_problems()


def test_missing_bar_has_no_prices_or_volume() -> None:
    gap = bar(
        open=None,
        high=None,
        low=None,
        close=None,
        volume_base=None,
        quality_status=QualityStatus.MISSING,
        quality_note="no candle",
    )
    assert gap.is_missing
    assert gap.describe() == "missing"
    with pytest.raises(ValueError, match="all four prices or none"):
        bar(open=None)
    with pytest.raises(ValueError, match="missing bar cannot carry volume"):
        bar(
            open=None,
            high=None,
            low=None,
            close=None,
            quality_status=QualityStatus.MISSING,
            quality_note="x",
        )
    with pytest.raises(ValueError, match="not 'missing'"):
        bar(open=None, high=None, low=None, close=None, volume_base=None)


def test_duplicate_detection_compares_every_bar_field() -> None:
    assert bar().comparable() == bar().comparable()
    assert bar().comparable() != bar(volume_base=Decimal("3.1")).comparable()


# --------------------------------------------------------------------------- read helpers


def test_range_never_includes_the_unfinished_bar() -> None:
    as_of = T + 30 * M + timedelta(seconds=20)
    start, end = resolve_range(M, as_of, None, None, 10)
    assert (start, end) == (T + 20 * M, T + 30 * M)
    start, end = resolve_range(M, as_of, T, T + 3 * H, 10)
    assert end == T + 30 * M  # clamped to the last bar that can have closed


def test_gap_report_separates_missing_from_not_loaded() -> None:
    as_of = T + 9 * M + timedelta(seconds=30)
    present = {T + 3 * M, T + 4 * M, T + 6 * M, T + 7 * M}
    report = gap_report(T, T + 9 * M, M, as_of, present, coverage_start=T + 3 * M)
    assert report.not_loaded == 3  # 12:00-12:02 are before the first stored bar
    assert report.missing_times == [T + 5 * M]  # inside coverage and absent
    # the 12:08 bar closes at 12:09 and counts as final from 12:10 — then it is missing too
    report = gap_report(T, T + 9 * M, M, T + 10 * M, present, coverage_start=T + 3 * M)
    assert report.missing_times == [T + 5 * M, T + 8 * M]
    empty = gap_report(T, T + 9 * M, M, as_of, set(), coverage_start=None)
    assert (empty.expected, empty.not_loaded) == (0, 8)  # 12:08 not final yet


def test_freshness() -> None:
    assert freshness(None, 5 * M, T).status == "no_data"
    fresh = freshness(T - 2 * M, 5 * M, T)
    assert (fresh.status, fresh.age_seconds, fresh.limit_seconds) == ("fresh", 120, 300)
    assert freshness(T - 6 * M, 5 * M, T).status == "stale"


def test_rollup_bar_is_only_shown_when_complete() -> None:
    row = {
        "event_time": T,
        "open": Decimal(1),
        "high": Decimal(3),
        "low": Decimal("0.5"),
        "close": Decimal(2),
        "volume_base": Decimal(10),
        "volume_quote": None,
        "trade_count": None,
        "parts_present": 3,
        "parts_flagged": 0,
        "revision": 0,
    }
    incomplete = derived_bar(row, 4, "1h")
    assert incomplete["quality_status"] == "missing"
    assert incomplete["close"] is None
    assert incomplete["quality_note"] == "incomplete: 3 of 4 1h bars available"
    complete = derived_bar({**row, "parts_present": 4}, 4, "1h")
    assert (complete["open"], complete["close"], complete["quality_status"]) == ("1", "2", "ok")
    flagged = derived_bar({**row, "parts_present": 4, "parts_flagged": 1}, 4, "1h")
    assert flagged["quality_status"] == "suspect"


# --------------------------------------------------------------------------- datasets & schedule


def test_datasets_never_mix_quote_currencies() -> None:
    specs = {s.dataset_id: s for s in all_datasets()}
    assert specs["market.ohlcv.usd.1h"].unit == "usd"
    assert specs["market.ohlcv.usdt.1h"].unit == "usdt"
    assert ohlcv_dataset("usd", "4h").kind == "bar"
    with pytest.raises(ValueError, match="unsupported timeframe"):
        ohlcv_dataset("usd", "2h")


def test_schedule_covers_native_datasets_on_the_right_queues() -> None:
    items = {
        (i.provider_id, i.dataset_id): i for i in scheduled_ingestions(["coinbase", "binance"])
    }
    assert ("coinbase", "market.ohlcv.usd.4h") not in items  # Coinbase has no 4h candles
    assert ("binance", "market.ohlcv.usdt.4h") in items
    assert items[("coinbase", "market.ohlcv.usd.1m")].queue == "ingest_fast"
    assert items[("coinbase", "market.spot_price.usd")].interval_seconds == 30
    assert items[("binance", "market.ohlcv.usdt.1d")].queue == "ingest"
    schedule = beat_schedule(["coingecko"])
    assert "latest:coingecko:market.market_cap.usd" in schedule
    assert schedule["backfill:round"]["options"]["queue"] == "backfill"
    # The Daily Market Brief (Phase 22) is scheduled unconditionally — it reads existing
    # intelligence rather than ingesting from any provider, so it has no provider list to be
    # empty. With every ingestion provider list empty, "brief:daily" is the only entry left.
    assert beat_schedule([]) == {
        "brief:daily": {
            "task": "brief.generate",
            "schedule": beat_schedule([])["brief:daily"]["schedule"],
            "options": {"queue": "ai", "expires": 3600},
        }
    }
    with pytest.raises(ValueError, match="unknown market provider"):
        scheduled_ingestions(["nope"])


# ----------------------------------------------------------------- HTTP bans, optional keys


async def test_long_retry_after_is_honoured_by_not_retrying() -> None:
    """Binance answers 418 (IP ban) or 429 with Retry-After; retrying early extends the ban."""
    clock = FakeClock()
    caps = ProviderCapabilities("p", "P", "https://p.invalid", frozenset())
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(418, headers={"Retry-After": "120"})

    breaker = CircuitBreaker(clock=clock)
    client = ProviderHttpClient(
        caps,
        transport=httpx2.MockTransport(handler),
        retry=RetryPolicy(max_attempts=4, max_delay=30, jitter=0),
        breaker=breaker,
        recorder=ListRecorder(),
        sleep=clock.sleep,
        clock=clock,
    )
    with pytest.raises(ProviderTransientError, match="asked to wait 120 s"):
        await client.send(RequestSpec("/x"))
    assert len(calls) == 1
    assert clock.slept == []
    states = [breaker.state]
    clock.advance(119)
    states.append(breaker.state)
    clock.advance(2)
    states.append(breaker.state)
    assert states == ["open", "open", "half_open"]
    await client.aclose()


async def test_optional_api_key_is_sent_only_when_configured() -> None:
    seen: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("x-cg-demo-api-key"))
        return httpx2.Response(200, json={})

    caps = ProviderCapabilities(
        "cg",
        "CG",
        "https://cg.invalid",
        frozenset(),
        auth=AuthSpec(AuthType.API_KEY_HEADER, "x-cg-demo-api-key", "CG_KEY", optional=True),
    )
    for environ in ({}, {"CG_KEY": "demo-test-key"}):
        client = ProviderHttpClient(caps, transport=httpx2.MockTransport(handler), environ=environ)
        await client.send(RequestSpec("/ping"))
        await client.aclose()
    assert seen == [None, "demo-test-key"]
