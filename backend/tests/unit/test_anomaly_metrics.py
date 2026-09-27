"""Unit tests for cfi.anomaly.metrics — pure functions, hand-verified expected values (R13: never
a hard-coded value chosen to force a test to pass; every expectation here is computed on paper in
the comments from the same formula the module documents)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.anomaly import metrics as m
from cfi.anomaly.universe import ANOMALY_BANDS_V1, classify_band
from cfi.divergence.metrics import Series, SeriesPoint

DAY = timedelta(days=1)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _daily_series(values: Sequence[int | None], start: datetime = T0) -> Series:
    """One point per day starting at ``start``; ``None`` is a genuinely missing day (never a
    fabricated interpolation, R3)."""
    return [
        SeriesPoint(start + i * DAY, None if v is None else Decimal(v), "ok")
        for i, v in enumerate(values)
    ]


# --------------------------------------------------------------------------- current_reading


def test_current_reading_insufficient_data_with_no_points() -> None:
    reading = m.current_reading([], T0)
    assert reading.status == "insufficient_data"
    assert reading.band == "unavailable"


def test_current_reading_insufficient_data_before_any_point() -> None:
    series = _daily_series([1, 2, 3], start=T0 + 10 * DAY)
    reading = m.current_reading(series, T0)  # as_of predates every point
    assert reading.status == "insufficient_data"


def test_current_reading_band_classification_across_the_full_range() -> None:
    """100 daily points valued 1..100, then one more day. The percentile of the last day's value
    against the prior 100 (nearest-rank, tie-tolerant — cfi.retail.metrics.percentile_rank) is
    hand-computed below for each case; ``current_reading`` must classify each into the band that
    percentile falls in per ``ANOMALY_BANDS_V1`` (extreme_high >= 97.5, notable_high >= 90,
    notable_low <= 10, extreme_low <= 2.5). For a current value already present in 1..100, the
    history (itself 1..100) contains exactly one equal point, which contributes half a rank
    (percentile_rank's tie-tolerant convention: below + equal/2)."""
    history_values = list(range(1, 101))  # 1..100, one per day

    def reading_for(current: int) -> m.CurrentReading:
        series = _daily_series([*history_values, current])
        as_of = T0 + 100 * DAY  # the 101st (current) day
        return m.current_reading(series, as_of)

    # current=95: below=94 (1..94 < 95), equal=1 (the 95 in history) -> pct = (94+0.5) = 94.5
    r = reading_for(95)
    assert r.status == "ok"
    assert r.percentile is not None
    assert r.percentile.percentile == Decimal("94.5")
    assert r.band == "notable_high"

    # current=50: below=49, equal=1 -> pct = 49.5 -> normal
    r = reading_for(50)
    assert r.percentile is not None
    assert r.percentile.percentile == Decimal("49.5")
    assert r.band == "normal"

    # current=5: below=4, equal=1 -> pct = 4.5 -> notable_low
    r = reading_for(5)
    assert r.percentile is not None
    assert r.percentile.percentile == Decimal("4.5")
    assert r.band == "notable_low"

    # current=1: below=0, equal=1 (history has one 1) -> pct = 0.5 -> extreme_low
    r = reading_for(1)
    assert r.percentile is not None
    assert r.percentile.percentile == Decimal("0.5")
    assert r.band == "extreme_low"

    # current=1000 (new all-time high, not in history): below=100, equal=0 -> pct = 100.0
    r = reading_for(1000)
    assert r.percentile is not None
    assert r.percentile.percentile == Decimal("100.0")
    assert r.band == "extreme_high"


def test_current_reading_reports_sample_size_and_insufficient_history_band() -> None:
    """Fewer than MIN_PERCENTILE_SAMPLE historical points -> percentile status
    'insufficient_history' and band 'unavailable' (never silently treated as 'normal', R3)."""
    series = _daily_series([1, 2, 3, 4])  # 3 history points once the 4th is "current"
    reading = m.current_reading(series, T0 + 3 * DAY)
    assert reading.status == "ok"  # a current reading exists
    assert reading.percentile is not None
    assert reading.percentile.status == "insufficient_history"
    assert reading.band == "unavailable"


# --------------------------------------------------------------------------- robust_magnitude


def test_robust_magnitude_hand_computed() -> None:
    # history = 1..9, median = 5; |x-5| = 4,3,2,1,0,1,2,3,4 -> sorted 0,1,1,2,2,3,3,4,4 -> MAD = 2
    # current = 13 -> z = (13 - 5) / (1.4826 * 2) = 8 / 2.9652 = 2.697963... -> quantized 2.70
    history = [Decimal(i) for i in range(1, 10)]
    magnitude, method = m.robust_magnitude(Decimal(13), history)
    assert magnitude == Decimal("2.70")
    assert method == m.MAGNITUDE_METHOD


def test_robust_magnitude_none_when_history_has_zero_spread() -> None:
    magnitude, _ = m.robust_magnitude(Decimal(50), [Decimal(5)] * 10)
    assert magnitude is None


def test_robust_magnitude_none_when_history_is_empty() -> None:
    magnitude, _ = m.robust_magnitude(Decimal(50), [])
    assert magnitude is None


def test_robust_magnitude_is_signed() -> None:
    # current below the median -> negative magnitude, not an absolute value
    history = [Decimal(i) for i in range(1, 10)]  # median 5, MAD 2
    magnitude, _ = m.robust_magnitude(Decimal(1), history)
    assert magnitude is not None
    assert magnitude < 0


# --------------------------------------------------------------------------- duration


def test_duration_walks_back_to_the_regime_change() -> None:
    """150 constant days (value 50), then 5 days at 999. Hand-computed per day (see PR
    description-style comments below): the last 5 days are all 'extreme_high', day 150 (the last
    constant day) is 'normal' — the streak must stop there, not continue past the regime change."""
    values = [50] * 150 + [999] * 5
    series = _daily_series(values)
    as_of = T0 + 154 * DAY  # the last (155th) day
    dur = m.duration(series, as_of, lookback_days=200, min_sample=20)
    assert dur.days == 5
    assert dur.since == T0 + 150 * DAY  # first of the 5 extreme_high days
    assert dur.capped is False


def test_duration_zero_when_current_band_is_unavailable() -> None:
    series = _daily_series([1, 2, 3])  # far too little history for MIN_PERCENTILE_SAMPLE
    dur = m.duration(series, T0 + 2 * DAY, lookback_days=30)
    assert dur.days == 0
    assert dur.since is None


def test_duration_caps_at_max_lookback() -> None:
    # every day is a fresh all-time high (strictly increasing) -> band stays extreme_high for
    # every day once enough history exists; the walk must stop at max_lookback, never run forever.
    values = list(range(1, 201))
    series = _daily_series(values)
    as_of = T0 + 199 * DAY
    dur = m.duration(series, as_of, lookback_days=200, min_sample=20, max_lookback=10)
    assert dur.days == 10
    assert dur.capped is True


# --------------------------------------------------------------------------- quality_summary


def test_quality_summary_missing_when_no_valued_points_in_window() -> None:
    series = _daily_series([None, None, None])
    q = m.quality_summary(series, T0 + 2 * DAY, 30)
    assert q.status == "missing"
    assert q.points_considered == 0


def test_quality_summary_ok_when_every_point_is_ok() -> None:
    series = _daily_series([1, 2, 3])
    q = m.quality_summary(series, T0 + 2 * DAY, 30)
    assert q.status == "ok"
    assert q.points_considered == 3
    assert q.flagged_points == 0


def test_quality_summary_degraded_when_some_points_are_flagged() -> None:
    series = [
        SeriesPoint(T0, Decimal(1), "ok"),
        SeriesPoint(T0 + DAY, Decimal(2), "suspect"),
        SeriesPoint(T0 + 2 * DAY, Decimal(3), "ok"),
    ]
    q = m.quality_summary(series, T0 + 2 * DAY, 30)
    assert q.status == "degraded"
    assert q.flagged_points == 1


# --------------------------------------------------------------------------- compare_bands


def test_compare_bands_consistent_when_both_high() -> None:
    assert m.compare_bands("extreme_high", "notable_high") == "consistent"


def test_compare_bands_consistent_when_both_low() -> None:
    assert m.compare_bands("notable_low", "extreme_low") == "consistent"


def test_compare_bands_contradiction_when_opposite_signs() -> None:
    assert m.compare_bands("extreme_high", "notable_low") == "contradiction"
    assert m.compare_bands("extreme_low", "notable_high") == "contradiction"


def test_compare_bands_no_clear_direction_when_either_is_normal() -> None:
    assert m.compare_bands("extreme_high", "normal") == "no_clear_direction"
    assert m.compare_bands("normal", "normal") == "no_clear_direction"


def test_compare_bands_insufficient_data_when_either_is_unavailable() -> None:
    assert m.compare_bands("unavailable", "extreme_high") == "insufficient_data"
    assert m.compare_bands("extreme_high", "unavailable") == "insufficient_data"


# --------------------------------------------------------------------------- classify_band


def test_classify_band_boundaries() -> None:
    assert classify_band(None) == "unavailable"
    assert classify_band(Decimal("97.5")) == "extreme_high"
    assert classify_band(Decimal("97.4")) == "notable_high"
    assert classify_band(Decimal(90)) == "notable_high"
    assert classify_band(Decimal("89.9")) == "normal"
    assert classify_band(Decimal(50)) == "normal"
    assert classify_band(Decimal(10)) == "notable_low"
    assert classify_band(Decimal("10.1")) == "normal"
    assert classify_band(Decimal("2.5")) == "extreme_low"
    assert classify_band(Decimal("2.6")) == "notable_low"


def test_bands_v1_is_symmetric_and_disclosed() -> None:
    assert ANOMALY_BANDS_V1.extreme_high == 100 - ANOMALY_BANDS_V1.extreme_low
    assert ANOMALY_BANDS_V1.notable_high == 100 - ANOMALY_BANDS_V1.notable_low
    assert ANOMALY_BANDS_V1.version
    assert ANOMALY_BANDS_V1.description
