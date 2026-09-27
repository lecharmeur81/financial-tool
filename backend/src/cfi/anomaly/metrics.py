"""Market Anomaly Engine calculated metrics (L2/L3) — pure functions, no I/O (Phase 19).

Every input is a normalized, already point-in-time-filtered ``cfi.divergence.metrics.Series``
(built by ``cfi.divergence.adapters.Adapters`` from each domain's own read service — Phase 19 adds
no parallel read layer). Nothing here fabricates a value: a day with no known reading contributes
nothing, and every result reports its own sample size so a short or gappy history is stated, never
hidden (R3).

**Methodology (make it transparent, mirroring ``cfi.divergence.metrics``'s own precedent):**

- *Current reading*: the latest known value at or before ``as_of``.
- *Historical percentile*: where the current reading ranks among every other valued reading in the
  loaded lookback, strictly before the current reading's own time (current excluded, per
  ``cfi.retail.metrics.percentile_rank``'s convention) — ``cfi.retail.metrics.percentile_rank``,
  reused unchanged.
- *Band*: the percentile classified against ``cfi.anomaly.universe.ANOMALY_BANDS_V1``'s versioned,
  disclosed cut-points (``cfi.anomaly.universe.classify_band``).
- *Magnitude*: a modified z-score — ``(current - median) / (1.4826 * MAD)`` where MAD is the median
  absolute deviation of the same history used for the percentile (1.4826 is the standard constant
  that makes MAD a consistent estimator of the standard deviation under normality) — a robust
  alternative to a mean/stdev z-score that a small number of extreme historical readings cannot
  distort. Reported as ``None`` (never a fabricated 0) when the history has zero spread (MAD = 0)
  or is empty.
- *Duration*: how many consecutive days (walking backward from ``as_of``, daily grid) the metric's
  *own* band (recomputed at each day, against ITS OWN history strictly before that day — never a
  single lookahead-tainted classification) has matched today's band. A day where the band is
  ``"unavailable"`` breaks the streak, matching ``cfi.divergence.metrics.duration``'s precedent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from cfi.anomaly.universe import (
    ANOMALY_BANDS_V1,
    MAX_DURATION_LOOKBACK_DAYS,
    MIN_PERCENTILE_SAMPLE,
    AnomalyBandParameters,
    Band,
    classify_band,
)
from cfi.divergence.metrics import Series
from cfi.retail.metrics import PercentileResult, percentile_rank

MAD_CONSISTENCY_CONSTANT = Decimal("1.4826")

MAGNITUDE_METHOD = (
    "modified_zscore_mad_v1: (current - median) / (1.4826 * median absolute deviation) of the "
    "same historical readings used for the percentile rank (current excluded)."
)


@dataclass(frozen=True, slots=True)
class _ValuedPoint:
    time: datetime
    value: Decimal


def _asof(points: Series, at: datetime) -> _ValuedPoint | None:
    """The latest valued point at or before ``at``, or ``None`` if none exists — never a future
    point, never an interpolation (R3)."""
    candidates = [p for p in points if p.has_value and p.time <= at]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.time)
    if latest.value is None:  # pragma: no cover - guarded by has_value above
        return None
    return _ValuedPoint(latest.time, latest.value)


def _history_before(points: Series, before: datetime) -> list[Decimal]:
    return [p.value for p in points if p.has_value and p.time < before and p.value is not None]


def robust_magnitude(current: Decimal, history: list[Decimal]) -> tuple[Decimal | None, str]:
    """A modified (MAD-based) z-score of ``current`` against ``history`` — ``None`` (never a
    fabricated 0) when ``history`` is empty or has zero spread."""
    if not history:
        return None, MAGNITUDE_METHOD
    med = Decimal(str(median(history)))
    deviations = [abs(v - med) for v in history]
    mad = Decimal(str(median(deviations)))
    if mad == 0:
        return None, MAGNITUDE_METHOD
    z = (current - med) / (MAD_CONSISTENCY_CONSTANT * mad)
    return z.quantize(Decimal("0.01")), MAGNITUDE_METHOD


@dataclass(frozen=True, slots=True)
class CurrentReading:
    status: str  # ok / insufficient_data
    reason: str | None = None
    time: datetime | None = None
    value: Decimal | None = None
    percentile: PercentileResult | None = None
    band: Band = "unavailable"
    magnitude: Decimal | None = None
    magnitude_method: str = MAGNITUDE_METHOD
    sample_size: int = 0


def current_reading(
    points: Series,
    as_of: datetime,
    *,
    min_sample: int = MIN_PERCENTILE_SAMPLE,
    bands: AnomalyBandParameters = ANOMALY_BANDS_V1,
) -> CurrentReading:
    now_pt = _asof(points, as_of)
    sample_size = sum(1 for p in points if p.has_value)
    if now_pt is None:
        return CurrentReading("insufficient_data", "no valued point at or before as_of")
    history = _history_before(points, now_pt.time)
    pr = percentile_rank(history, now_pt.value, min_sample=min_sample)
    band = classify_band(pr.percentile, bands)
    mag, method = robust_magnitude(now_pt.value, history)
    return CurrentReading("ok", None, now_pt.time, now_pt.value, pr, band, mag, method, sample_size)


def _daily_grid(start: datetime, end: datetime) -> list[datetime]:
    out = []
    day = start
    while day <= end:
        out.append(day)
        day += timedelta(days=1)
    return out


@dataclass(frozen=True, slots=True)
class DurationResult:
    days: int
    capped: bool
    since: datetime | None


def duration(
    points: Series,
    as_of: datetime,
    *,
    lookback_days: int,
    min_sample: int = MIN_PERCENTILE_SAMPLE,
    bands: AnomalyBandParameters = ANOMALY_BANDS_V1,
    max_lookback: int = MAX_DURATION_LOOKBACK_DAYS,
) -> DurationResult:
    """How many consecutive trailing days the metric's own band has matched today's band, walking
    backward day-by-day. Each day's band is recomputed against only the history strictly before
    that day's own reading — never against the full lookback window shared by every day, which
    would let later data leak into an earlier day's classification (R3/R4 no look-ahead bias)."""
    start = as_of - timedelta(days=lookback_days)
    dates = _daily_grid(start, as_of)
    if not dates:
        return DurationResult(0, False, None)
    bands_by_day: list[Band] = []
    for d in dates:
        pt = _asof(points, d)
        if pt is None:
            bands_by_day.append("unavailable")
            continue
        hist = _history_before(points, pt.time)
        pr = percentile_rank(hist, pt.value, min_sample=min_sample)
        bands_by_day.append(classify_band(pr.percentile, bands))
    current = bands_by_day[-1]
    if current == "unavailable":
        return DurationResult(0, False, None)
    count = 0
    capped = False
    for i in range(len(dates) - 1, -1, -1):
        if bands_by_day[i] != current:
            break
        count += 1
        if count >= max_lookback:
            capped = True
            break
    since = dates[len(dates) - count] if count > 0 else None
    return DurationResult(count, capped, since)


@dataclass(frozen=True, slots=True)
class QualitySummary:
    status: str  # ok / degraded / missing
    points_considered: int
    flagged_points: int


def quality_summary(points: Series, as_of: datetime, lookback_days: int) -> QualitySummary:
    cutoff = as_of - timedelta(days=lookback_days)
    in_window = [p for p in points if cutoff <= p.time <= as_of]
    valued = [p for p in in_window if p.has_value]
    flagged = sum(1 for p in in_window if p.quality_status not in ("ok", "estimated"))
    if not valued:
        return QualitySummary("missing", 0, flagged)
    return QualitySummary("ok" if flagged == 0 else "degraded", len(valued), flagged)


# --------------------------------------------------------------------------- contradicting evidence

_HIGH_BANDS = frozenset({"extreme_high", "notable_high"})
_LOW_BANDS = frozenset({"extreme_low", "notable_low"})


def _band_sign(band: Band) -> int:
    if band in _HIGH_BANDS:
        return 1
    if band in _LOW_BANDS:
        return -1
    return 0


def compare_bands(band: Band, counterpart_band: Band) -> str:
    """A purely mechanical comparison of two percentile bands — never an economic or
    bullish/bearish judgment (R1/R2): 'consistent' when both are non-normal and share the same
    percentile-band sign, 'contradiction' when both are non-normal with opposite signs,
    'no_clear_direction' when either is 'normal', 'insufficient_data' when either is
    'unavailable'. Reuses the same four-way vocabulary already established by
    ``cfi.whales.score``'s contradiction indicators."""
    if band == "unavailable" or counterpart_band == "unavailable":
        return "insufficient_data"
    a, b = _band_sign(band), _band_sign(counterpart_band)
    if a == 0 or b == 0:
        return "no_clear_direction"
    return "consistent" if a == b else "contradiction"
