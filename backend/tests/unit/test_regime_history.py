"""Unit tests for cfi.regime.history: the backward-walk duration and the sampled historical
examples, both driven by a stub ``classify_at`` callback (no database, no classifier)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.regime import history as h
from cfi.regime.universe import INTERACTIVE_HISTORICAL_CONCURRENCY

DAY = timedelta(days=1)
T0 = datetime(2026, 6, 1, tzinfo=UTC)


def _stub(labels_by_day_offset: dict[int, str]) -> h.ClassifyAt:
    """``labels_by_day_offset[0]`` is ``as_of``'s own label; negative offsets are earlier days."""

    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        offset = (candidate - T0).days
        return labels_by_day_offset.get(offset, "mixed_unclear"), Decimal("0.80")

    return classify_at


async def test_regime_duration_counts_consecutive_matching_days() -> None:
    labels = {0: "expansion", -1: "expansion", -2: "expansion", -3: "recovery"}
    result = await h.regime_duration(
        _stub(labels), as_of=T0, current_regime_id="expansion", max_lookback_days=30
    )
    assert result.days == 3
    assert result.since == T0 - 2 * DAY
    assert not result.capped


async def test_regime_duration_caps_at_max_lookback() -> None:
    labels = {i: "expansion" for i in range(-10, 1)}
    result = await h.regime_duration(
        _stub(labels), as_of=T0, current_regime_id="expansion", max_lookback_days=5
    )
    assert result.capped
    assert result.days == 6  # as_of + 5 walked-back days


async def test_regime_duration_is_one_when_yesterday_already_differs() -> None:
    labels = {0: "expansion", -1: "recovery"}
    result = await h.regime_duration(
        _stub(labels), as_of=T0, current_regime_id="expansion", max_lookback_days=30
    )
    assert result.days == 1
    assert result.since == T0


async def test_historical_examples_finds_a_prior_matching_run() -> None:
    # Current streak: "expansion" from day -2 through day 0 (since = T0 - 2*DAY).
    # Sampling backward at 7-day steps from before the streak (T0 - 3*DAY) should find an
    # "expansion" run further back.
    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        offset_weeks = round((T0 - candidate).days / 7)
        # weeks 1-2 (just before the streak): unrelated; weeks 3-4: a prior "expansion" episode.
        if offset_weeks in (3, 4):
            return "expansion", Decimal("0.75")
        return "recovery", Decimal("0.60")

    episodes = await h.historical_examples(
        classify_at,
        as_of=T0,
        current_regime_id="expansion",
        streak_since=T0 - 2 * DAY,
        lookback_days=60,
        step_days=7,
        min_episode_samples=2,
        max_examples=3,
    )
    assert len(episodes) == 1
    assert episodes[0].sample_days == 2
    assert episodes[0].peak_confidence == Decimal("0.75")


async def test_historical_examples_empty_when_nothing_matches() -> None:
    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        return "recovery", Decimal("0.60")

    episodes = await h.historical_examples(
        classify_at,
        as_of=T0,
        current_regime_id="expansion",
        streak_since=T0,
        lookback_days=30,
        step_days=7,
        min_episode_samples=2,
        max_examples=3,
    )
    assert episodes == []


# --- bounded concurrency (GET /regime/current) ---
def _weeks_stub(log: list[datetime] | None = None) -> h.ClassifyAt:
    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        if log is not None:
            log.append(candidate)
        await asyncio.sleep(0)
        weeks = round((T0 - candidate).days / 7)
        label = "expansion" if weeks % 3 == 0 else "recovery"
        return label, Decimal(weeks % 5) / Decimal(10)

    return classify_at


async def _examples(classify_at: h.ClassifyAt, **extra: int) -> list[h.Episode]:
    return await h.historical_examples(
        classify_at,
        as_of=T0,
        current_regime_id="expansion",
        streak_since=T0 - 2 * DAY,
        lookback_days=365,
        step_days=7,
        min_episode_samples=1,
        max_examples=50,
        **extra,
    )


@pytest.mark.parametrize("concurrency", [2, 3, 4, 8, 100])
async def test_concurrent_examples_equal_the_sequential_result(concurrency: int) -> None:
    sequential = await _examples(_weeks_stub())
    assert sequential, "the stub must yield episodes for the comparison to mean anything"
    assert await _examples(_weeks_stub(), concurrency=concurrency) == sequential


async def test_default_concurrency_is_the_original_sequential_order() -> None:
    log: list[datetime] = []
    await _examples(_weeks_stub(log))
    assert log == sorted(log, reverse=True)  # most recent first, one at a time


async def test_concurrency_is_bounded() -> None:
    running = peak = 0

    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.001)
        running -= 1
        return "recovery", None

    await _examples(classify_at, concurrency=INTERACTIVE_HISTORICAL_CONCURRENCY)
    assert peak == INTERACTIVE_HISTORICAL_CONCURRENCY == 3


async def test_a_failure_is_reraised_unchanged_and_the_rest_are_cancelled() -> None:
    started = 0

    class BoomError(Exception):
        pass

    async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
        nonlocal started
        started += 1
        if started == 2:
            raise BoomError
        await asyncio.sleep(0.05)
        return "recovery", None

    with pytest.raises(BoomError):
        await _examples(classify_at, concurrency=3)
    assert started < 52  # not every remaining sample was run after the failure
