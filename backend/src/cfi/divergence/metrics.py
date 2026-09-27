"""Divergence Engine calculated metrics (L2/L3) — pure functions, no I/O.

Every input is a normalized, already point-in-time-filtered ``SeriesPoint`` list (built by
``cfi.divergence.adapters`` from each domain's own read service). Nothing here fabricates a value:
a day with no known reading contributes nothing (never an interpolation), and every result reports
its own sample size so a short or gappy history is stated, never hidden (R3).

**Methodology (make it transparent, per the Phase 13 instruction):**

- *Window reading*: "as-of" style — the latest known value at or before ``as_of``, minus the
  latest known value at or before ``window_days`` earlier. This carries the last known reading
  forward for series that update less than daily (e.g. weekly macro data), the same point-in-time
  philosophy used everywhere else in this platform — it is not an invented interpolation, only the
  most recently observed value repeated until a new one arrives.
- *Direction*: the sign of that delta. Positive = "up", negative = "down", exactly zero = "flat".
  No smoothing, no arbitrary dead zone — the simplest, most transparent rule available.
- *Historical percentile*: where the current window's absolute delta ranks among every other
  window-delta computed the same way over the loaded lookback
  (``cfi.retail.metrics.percentile_rank``, reused unchanged — nearest-rank percentile, tie-tolerant,
  0-100).
- *Duration*: how many consecutive days (walking backward from ``as_of``) the same
  (direction_a, direction_b) combination has held.
- *Historical examples*: earlier (non-current) runs of days with the same
  (direction_a, direction_b) combination, ranked by the peak percentile of |delta_a| reached
  during that run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from cfi.divergence.universe import (
    EPISODE_PERCENTILE_THRESHOLD,
    MAX_DURATION_LOOKBACK_DAYS,
    MAX_HISTORICAL_EXAMPLES,
    MIN_PERCENTILE_SAMPLE,
)
from cfi.retail.metrics import PercentileResult as PercentileResult
from cfi.retail.metrics import percentile_rank

Direction = Literal["up", "down", "flat", "unavailable"]


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    time: datetime
    value: Decimal | None
    quality_status: str = "ok"

    @property
    def has_value(self) -> bool:
        return self.value is not None


Series = list[SeriesPoint]


@dataclass(frozen=True, slots=True)
class _ValuedPoint:
    time: datetime
    value: Decimal


def _asof(points: Series, at: datetime) -> _ValuedPoint | None:
    """The most recent valued point at or before ``at`` (points need not be pre-sorted)."""
    candidates = [p for p in points if p.value is not None and p.time <= at]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.time)
    assert latest.value is not None  # noqa: S101 — narrowed by the filter above
    return _ValuedPoint(latest.time, latest.value)


def direction_of(delta: Decimal | None) -> Direction:
    if delta is None:
        return "unavailable"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


@dataclass(frozen=True, slots=True)
class WindowReading:
    status: str  # ok / insufficient_data
    reason: str | None = None
    window_days: int = 0
    first_time: datetime | None = None
    first_value: Decimal | None = None
    last_time: datetime | None = None
    last_value: Decimal | None = None
    delta: Decimal | None = None
    change_pct: Decimal | None = None
    direction: Direction = "unavailable"
    sample_size: int = 0


def window_reading(points: Series, as_of: datetime, window_days: int) -> WindowReading:
    now_pt = _asof(points, as_of)
    prev_pt = _asof(points, as_of - timedelta(days=window_days))
    sample_size = sum(1 for p in points if p.has_value)
    if now_pt is None:
        return WindowReading(
            "insufficient_data",
            "no valued point at or before as_of",
            window_days,
            sample_size=sample_size,
        )
    if prev_pt is None:
        return WindowReading(
            "insufficient_data",
            f"no valued point at or before {window_days} day(s) before as_of",
            window_days,
            sample_size=sample_size,
        )
    delta = now_pt.value - prev_pt.value
    pct = None if prev_pt.value == 0 else (delta / abs(prev_pt.value) * 100)
    return WindowReading(
        "ok",
        None,
        window_days,
        prev_pt.time,
        prev_pt.value,
        now_pt.time,
        now_pt.value,
        delta,
        pct,
        direction_of(delta),
        sample_size,
    )


@dataclass(frozen=True, slots=True)
class QualitySummary:
    status: str  # ok / degraded / missing
    points_in_window: int
    flagged_points: int


def quality_summary(points: Series, as_of: datetime, window_days: int) -> QualitySummary:
    cutoff = as_of - timedelta(days=window_days)
    in_window = [p for p in points if cutoff <= p.time <= as_of]
    valued = [p for p in in_window if p.has_value]
    flagged = sum(1 for p in in_window if p.quality_status not in ("ok", "estimated"))
    if not valued:
        return QualitySummary("missing", 0, flagged)
    return QualitySummary("ok" if flagged == 0 else "degraded", len(valued), flagged)


def _daily_grid(start: datetime, end: datetime) -> list[datetime]:
    out = []
    day = start
    while day <= end:
        out.append(day)
        day += timedelta(days=1)
    return out


@dataclass(frozen=True, slots=True)
class RollingSeries:
    """A daily-resolution rolling-delta series over ``dates``: ``deltas[i]`` is the window-delta
    ending on ``dates[i]`` (``None`` when either endpoint of that window has no known value yet)."""

    dates: list[datetime]
    deltas: list[Decimal | None]
    directions: list[Direction]


def rolling_series(
    points: Series, *, window_days: int, as_of: datetime, lookback_days: int
) -> RollingSeries:
    start = as_of - timedelta(days=lookback_days)
    dates = _daily_grid(start, as_of)
    deltas: list[Decimal | None] = []
    directions: list[Direction] = []
    for d in dates:
        now_pt = _asof(points, d)
        prev_pt = _asof(points, d - timedelta(days=window_days))
        delta = now_pt.value - prev_pt.value if (now_pt and prev_pt) else None
        deltas.append(delta)
        directions.append(direction_of(delta))
    return RollingSeries(dates, deltas, directions)


def magnitude_and_percentile(rolling: RollingSeries) -> tuple[Decimal | None, PercentileResult]:
    """The current (last) reading's absolute magnitude and its percentile rank against every
    other historical absolute delta in ``rolling`` (current excluded, per ``percentile_rank``'s own
    convention)."""
    current = rolling.deltas[-1] if rolling.deltas else None
    if current is None:
        return None, PercentileResult("insufficient_history", "no current reading available")
    history = [abs(d) for d in rolling.deltas[:-1] if d is not None]
    result = percentile_rank(history, abs(current), min_sample=MIN_PERCENTILE_SAMPLE)
    return abs(current), result


@dataclass(frozen=True, slots=True)
class DurationResult:
    days: int
    capped: bool
    since: datetime | None


def duration(
    dir_a: list[Direction], dir_b: list[Direction], dates: list[datetime]
) -> DurationResult:
    """How many consecutive trailing days (dir_a, dir_b) has matched its current value, walking
    backward from the end. A day where either leg is 'unavailable' breaks the streak (an unknown
    state is never silently counted as a continuation, R3)."""
    if not dir_a or not dir_b or not dates:
        return DurationResult(0, False, None)
    current = (dir_a[-1], dir_b[-1])
    if "unavailable" in current:
        return DurationResult(0, False, None)
    count = 0
    capped = False
    for i in range(len(dates) - 1, -1, -1):
        if (dir_a[i], dir_b[i]) != current:
            break
        count += 1
        if count >= MAX_DURATION_LOOKBACK_DAYS:
            capped = True
            break
    since = dates[len(dates) - count] if count > 0 else None
    return DurationResult(count, capped, since)


@dataclass(frozen=True, slots=True)
class Episode:
    start: datetime
    end: datetime
    days: int
    peak_abs_delta_a: Decimal | None
    peak_percentile_a: Decimal | None


def historical_examples(
    rolling_a: RollingSeries, rolling_b: RollingSeries, current_duration_days: int
) -> list[Episode]:
    """Earlier (non-current) runs of days sharing today's (direction_a, direction_b) combination,
    ranked by the peak historical percentile of |delta_a| reached during the run, most recent
    first. Only runs whose peak percentile meets ``EPISODE_PERCENTILE_THRESHOLD`` are reported —
    a quiet, unremarkable repeat of the same directions is not a "historical example" worth
    surfacing."""
    dates = rolling_a.dates
    dir_a, dir_b = rolling_a.directions, rolling_b.directions
    n = len(dates)
    if n == 0 or "unavailable" in (dir_a[-1], dir_b[-1]):
        return []
    current = (dir_a[-1], dir_b[-1])
    # exclude the trailing current streak from the scan
    scan_end = n - 1 - current_duration_days
    if scan_end < 0:
        return []
    history_a = [abs(d) for d in rolling_a.deltas if d is not None]
    runs: list[Episode] = []
    i = scan_end
    while i >= 0:
        if (dir_a[i], dir_b[i]) != current:
            i -= 1
            continue
        j = i
        while j >= 0 and (dir_a[j], dir_b[j]) == current:
            j -= 1
        run_start_idx, run_end_idx = j + 1, i
        peak_abs: Decimal | None = None
        for k in range(run_start_idx, run_end_idx + 1):
            d = rolling_a.deltas[k]
            if d is not None and (peak_abs is None or abs(d) > peak_abs):
                peak_abs = abs(d)
        peak_pct = None
        if peak_abs is not None:
            baseline = [v for v in history_a if v != peak_abs] or history_a
            pr = percentile_rank(baseline, peak_abs, min_sample=MIN_PERCENTILE_SAMPLE)
            peak_pct = pr.percentile
        if peak_pct is not None and peak_pct >= EPISODE_PERCENTILE_THRESHOLD:
            runs.append(
                Episode(
                    dates[run_start_idx],
                    dates[run_end_idx],
                    run_end_idx - run_start_idx + 1,
                    peak_abs,
                    peak_pct,
                )
            )
        i = run_start_idx - 1
    return runs[:MAX_HISTORICAL_EXAMPLES]


def evidence(
    *,
    reading_a: WindowReading,
    reading_b: WindowReading,
    percentile_a: PercentileResult,
    percentile_b: PercentileResult,
    dur: DurationResult,
    quality_a: QualitySummary,
    quality_b: QualitySummary,
) -> tuple[list[str], list[str]]:
    """Deterministic, rule-based supporting/contradicting evidence (L3 Statistical Signal — not an
    AI interpretation, R2/R6): every bullet cites a number already computed above, nothing here is
    a free-text judgment call."""
    supporting: list[str] = []
    contradicting: list[str] = []

    if percentile_a.status == "ok" and percentile_a.percentile is not None:
        if percentile_a.percentile >= Decimal(80):
            supporting.append(
                f"Metric A's window change is in the top quintile of its own history "
                f"({percentile_a.percentile}th percentile)."
            )
        elif Decimal(40) <= percentile_a.percentile <= Decimal(60):
            contradicting.append(
                f"Metric A's magnitude is unremarkable relative to its own history "
                f"({percentile_a.percentile}th percentile, near the median)."
            )
    else:
        contradicting.append(
            "Metric A has fewer than the minimum historical comparable windows "
            f"({percentile_a.sample_size} available, need >= {MIN_PERCENTILE_SAMPLE}) — its "
            "percentile rank is not yet reliable."
        )

    if percentile_b.status == "ok" and percentile_b.percentile is not None:
        if percentile_b.percentile >= Decimal(80):
            supporting.append(
                f"Metric B's window change is in the top quintile of its own history "
                f"({percentile_b.percentile}th percentile)."
            )
        elif Decimal(40) <= percentile_b.percentile <= Decimal(60):
            contradicting.append(
                f"Metric B's magnitude is unremarkable relative to its own history "
                f"({percentile_b.percentile}th percentile, near the median)."
            )
    else:
        contradicting.append(
            "Metric B has fewer than the minimum historical comparable windows "
            f"({percentile_b.sample_size} available, need >= {MIN_PERCENTILE_SAMPLE}) — its "
            "percentile rank is not yet reliable."
        )

    if dur.days >= reading_a.window_days:
        supporting.append(
            f"This combination has held for {dur.days} consecutive day(s), at least as long as "
            f"the {reading_a.window_days}-day comparison window itself."
        )
    elif dur.days <= 1:
        contradicting.append(
            f"This combination has held for only {dur.days} day(s) — not yet a persistent pattern."
        )

    if quality_a.status == "ok" and quality_b.status == "ok":
        supporting.append("Both legs have full ('ok') data quality for the comparison window.")
    else:
        if quality_a.status != "ok":
            contradicting.append(
                f"Metric A's data quality for this window is '{quality_a.status}'."
            )
        if quality_b.status != "ok":
            contradicting.append(
                f"Metric B's data quality for this window is '{quality_b.status}'."
            )

    return supporting, contradicting
