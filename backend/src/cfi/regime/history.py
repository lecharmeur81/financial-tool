"""Regime start date / duration, and historical examples of the same regime (Phase 14).

No domain score has a persisted, ranged history of its own (``cfi.regime.universe.NOT_TRACKED``),
so both of these are computed by *re-running the classifier* at past ``as_of`` values through a
caller-supplied ``classify_at`` callback, rather than reading a stored regime-history table (there
is none). Two deliberately different, documented performance trade-offs (ADR-0057):

* :func:`regime_duration` walks backward **one day at a time** from ``as_of``, stopping as soon as
  the label changes (or a cap is reached) — usually a short walk, since most regimes do not
  persist anywhere near the cap.
* :func:`historical_examples` instead **samples** weekly over a much longer lookback, further back
  than the current streak — a coarser but far cheaper method for spotting prior episodes of the
  same regime, intentionally distinct from the daily duration walk above.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

ClassifyAt = Callable[[datetime], Awaitable[tuple[str, Decimal | None]]]


async def _classify_all(
    classify_at: ClassifyAt, times: list[datetime], concurrency: int
) -> list[tuple[str, Decimal | None]]:
    """``classify_at`` for every time, results in the order of ``times``.

    ``concurrency <= 1`` is the original strictly sequential loop. Above 1 the (mutually
    independent) classifications run with at most ``concurrency`` in flight; the first failure is
    re-raised unchanged and the remaining ones are cancelled."""
    if concurrency <= 1 or len(times) <= 1:
        return [await classify_at(t) for t in times]
    gate = asyncio.Semaphore(concurrency)

    async def one(t: datetime) -> tuple[str, Decimal | None]:
        async with gate:
            return await classify_at(t)

    tasks = [asyncio.ensure_future(one(t)) for t in times]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        raise


@dataclass(frozen=True, slots=True)
class DurationResult:
    days: int
    capped: bool
    since: datetime | None


async def regime_duration(
    classify_at: ClassifyAt,
    *,
    as_of: datetime,
    current_regime_id: str,
    max_lookback_days: int,
) -> DurationResult:
    if max_lookback_days <= 0:
        return DurationResult(1, False, as_of)
    days = 1
    since = as_of
    for i in range(1, max_lookback_days + 1):
        candidate = as_of - timedelta(days=i)
        regime_id, _ = await classify_at(candidate)
        if regime_id != current_regime_id:
            return DurationResult(days, False, since)
        days += 1
        since = candidate
    return DurationResult(days, True, since)


@dataclass(frozen=True, slots=True)
class Episode:
    start: datetime
    end: datetime
    sample_days: int
    peak_confidence: Decimal | None


async def historical_examples(
    classify_at: ClassifyAt,
    *,
    as_of: datetime,
    current_regime_id: str,
    streak_since: datetime,
    lookback_days: int,
    step_days: int,
    min_episode_samples: int,
    max_examples: int,
    concurrency: int = 1,
) -> list[Episode]:
    """Sample backward from just before the current streak began, at ``step_days`` resolution,
    over ``lookback_days``; group consecutive same-label samples into runs; report runs matching
    ``current_regime_id`` that span at least ``min_episode_samples``, most recent first."""
    if step_days <= 0 or lookback_days <= 0:
        return []
    start_before_streak = streak_since - timedelta(days=step_days)
    n_samples = lookback_days // step_days
    sample_times: list[datetime] = []
    for i in range(n_samples):
        sample_time = start_before_streak - timedelta(days=step_days * i)
        if sample_time < as_of - timedelta(days=lookback_days):
            break
        sample_times.append(sample_time)
    # The samples do not depend on one another (each is classified against the same fixed anchor
    # regime), so they may run concurrently; the order of ``samples`` is unchanged.
    classified = await _classify_all(classify_at, sample_times, concurrency)
    samples = [
        (t, regime_id, confidence)
        for t, (regime_id, confidence) in zip(sample_times, classified, strict=True)
    ]
    # ``samples`` runs most-recent-first; walk it building runs of matching consecutive labels.
    episodes: list[Episode] = []
    i = 0
    while i < len(samples):
        _, label, _ = samples[i]
        j = i
        while j + 1 < len(samples) and samples[j + 1][1] == label:
            j += 1
        run = samples[i : j + 1]
        if label == current_regime_id and len(run) >= min_episode_samples:
            times = [t for t, _, _ in run]
            confidences = [c for _, _, c in run if c is not None]
            episodes.append(
                Episode(
                    start=min(times),
                    end=max(times),
                    sample_days=len(run),
                    peak_confidence=max(confidences) if confidences else None,
                )
            )
        i = j + 1
    return episodes[:max_examples]
