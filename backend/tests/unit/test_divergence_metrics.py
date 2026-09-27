"""Unit tests for cfi.divergence.metrics: window reading, direction, rolling series, duration,
historical examples, quality summary and the deterministic evidence rules. All synthetic — no I/O,
no database (see cfi.divergence.adapters for the (DB-gated) integration coverage)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.divergence import metrics as m

DAY = timedelta(days=1)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def series(values: dict[int, str | None]) -> m.Series:
    """``values`` maps day-offset -> a decimal string (or None to omit that day entirely)."""
    return [
        m.SeriesPoint(T0 + day * DAY, None if v is None else Decimal(v))
        for day, v in sorted(values.items())
        if v is not None
    ]


# --------------------------------------------------------------------------- direction_of


def test_direction_of_up_down_flat_unavailable() -> None:
    assert m.direction_of(Decimal(5)) == "up"
    assert m.direction_of(Decimal(-5)) == "down"
    assert m.direction_of(Decimal(0)) == "flat"
    assert m.direction_of(None) == "unavailable"


# --------------------------------------------------------------------------- window_reading


def test_window_reading_ok_computes_delta_direction_and_pct() -> None:
    pts = series({0: "100", 30: "130"})
    r = m.window_reading(pts, T0 + 30 * DAY, 30)
    assert r.status == "ok"
    assert r.delta == Decimal(30)
    assert r.direction == "up"
    assert r.change_pct == Decimal(30)  # (130/100 - 1) * 100


def test_window_reading_insufficient_when_no_point_before_as_of() -> None:
    pts = series({10: "100"})
    r = m.window_reading(pts, T0, 30)
    assert r.status == "insufficient_data"
    assert r.direction == "unavailable"


def test_window_reading_insufficient_when_no_point_before_window_start() -> None:
    pts = series({29: "100", 30: "110"})
    r = m.window_reading(pts, T0 + 30 * DAY, 30)
    assert r.status == "insufficient_data"
    assert "30 day" in (r.reason or "")


def test_window_reading_carries_forward_last_known_value() -> None:
    """A gappy (e.g. weekly) series still produces a reading: the latest known value at or
    before each endpoint is used, never an invented interpolation."""
    pts = series({0: "100", 7: "105", 40: "120"})  # nothing between day 7 and day 40
    r = m.window_reading(pts, T0 + 45 * DAY, 30)  # window start = day 15 -> carries day 7's 105
    assert r.status == "ok"
    assert r.first_value == Decimal(105)
    assert r.last_value == Decimal(120)


# --------------------------------------------------------------------------- rolling_series


def test_rolling_series_daily_grid_and_deltas() -> None:
    pts = [m.SeriesPoint(T0 + i * DAY, Decimal(100 + i)) for i in range(0, 61)]
    roll = m.rolling_series(pts, window_days=30, as_of=T0 + 60 * DAY, lookback_days=30)
    assert len(roll.dates) == 31  # inclusive daily grid over 30 days
    assert roll.deltas[-1] == Decimal(30)  # day 60 value (160) - day 30 value (130)
    assert roll.directions[-1] == "up"


def test_rolling_series_none_when_history_too_short() -> None:
    pts = series({0: "100"})
    roll = m.rolling_series(pts, window_days=30, as_of=T0 + 5 * DAY, lookback_days=10)
    assert all(d is None for d in roll.deltas)
    assert all(dr == "unavailable" for dr in roll.directions)


# --------------------------------------------------------------------------- magnitude & percentile


def test_magnitude_and_percentile_ranks_current_against_history() -> None:
    # 25 flat deltas of 1, then a final delta of 100 -> current should rank at the very top.
    deltas: list[Decimal | None] = []
    deltas.extend([Decimal(1)] * 25)
    deltas.append(Decimal(100))
    roll = m.RollingSeries(
        dates=[T0 + i * DAY for i in range(len(deltas))],
        deltas=deltas,
        directions=[m.direction_of(d) for d in deltas],
    )
    magnitude, pct = m.magnitude_and_percentile(roll)
    assert magnitude == Decimal(100)
    assert pct.status == "ok"
    assert pct.percentile == Decimal("100.0")


def test_magnitude_and_percentile_insufficient_history() -> None:
    deltas: list[Decimal | None] = []
    deltas.extend([Decimal(1)] * 5)
    deltas.append(Decimal(2))
    roll = m.RollingSeries(
        dates=[T0 + i * DAY for i in range(len(deltas))],
        deltas=deltas,
        directions=[m.direction_of(d) for d in deltas],
    )
    _, pct = m.magnitude_and_percentile(roll)
    assert pct.status == "insufficient_history"


def test_magnitude_and_percentile_none_when_current_missing() -> None:
    directions: list[m.Direction] = ["unavailable"]
    roll = m.RollingSeries(dates=[T0], deltas=[None], directions=directions)
    magnitude, pct = m.magnitude_and_percentile(roll)
    assert magnitude is None
    assert pct.status == "insufficient_history"


# --------------------------------------------------------------------------- duration


def test_duration_counts_consecutive_matching_days() -> None:
    dir_a: list[m.Direction] = ["down", "down", "up", "up", "up"]
    dir_b: list[m.Direction] = ["up", "down", "down", "down", "down"]
    dates = [T0 + i * DAY for i in range(5)]
    d = m.duration(dir_a, dir_b, dates)
    assert d.days == 3  # the last 3 days share (up, down)
    assert d.since == dates[2]
    assert not d.capped


def test_duration_zero_when_current_leg_unavailable() -> None:
    dir_a: list[m.Direction] = ["up", "unavailable"]
    dir_b: list[m.Direction] = ["down", "down"]
    d = m.duration(dir_a, dir_b, [T0, T0 + DAY])
    assert d.days == 0
    assert d.since is None


def test_duration_empty_inputs() -> None:
    assert m.duration([], [], []) == m.DurationResult(0, False, None)


# --------------------------------------------------------------------------- historical_examples


def test_historical_examples_finds_a_prior_matching_run_above_threshold() -> None:
    n = 40
    dates = [T0 + i * DAY for i in range(n)]
    # idx 0-9: unrelated combo; idx 10-12: target combo (large magnitude, the historical episode);
    # idx 13-29: unrelated combo (breaks the streak); idx 30-39: target combo (the current streak).
    dir_a: list[m.Direction] = []
    dir_a.extend(["up"] * 10)
    dir_a.extend(["down"] * 3)
    dir_a.extend(["up"] * 17)
    dir_a.extend(["down"] * 10)
    dir_b: list[m.Direction] = ["up"] * n
    deltas_a: list[Decimal | None] = [Decimal(-1)] * n
    for i in (10, 11, 12):
        deltas_a[i] = Decimal(-500)
    roll_a = m.RollingSeries(dates, deltas_a, dir_a)
    roll_b = m.RollingSeries(dates, [Decimal(1)] * n, dir_b)
    current_duration = m.duration(dir_a, dir_b, dates).days
    assert current_duration == 10
    episodes = m.historical_examples(roll_a, roll_b, current_duration)
    assert len(episodes) >= 1
    assert episodes[0].days == 3
    assert episodes[0].peak_percentile_a is not None
    assert episodes[0].peak_percentile_a >= Decimal(70)


def test_historical_examples_empty_when_current_direction_unavailable() -> None:
    dates = [T0, T0 + DAY]
    roll_a = m.RollingSeries(dates, [Decimal(1), None], ["up", "unavailable"])
    roll_b = m.RollingSeries(dates, [Decimal(1), Decimal(1)], ["up", "up"])
    assert m.historical_examples(roll_a, roll_b, 0) == []


# --------------------------------------------------------------------------- quality_summary


def test_quality_summary_ok_degraded_missing() -> None:
    ok_pts = [m.SeriesPoint(T0, Decimal(1), "ok")]
    assert m.quality_summary(ok_pts, T0, 30).status == "ok"

    flagged_pts = [m.SeriesPoint(T0, Decimal(1), "suspect")]
    assert m.quality_summary(flagged_pts, T0, 30).status == "degraded"

    assert m.quality_summary([], T0, 30).status == "missing"


# --------------------------------------------------------------------------- evidence


def test_evidence_flags_short_duration_and_thin_history() -> None:
    reading_a = m.WindowReading("ok", window_days=30, direction="up")
    reading_b = m.WindowReading("ok", window_days=30, direction="down")
    thin = m.PercentileResult("insufficient_history", "only 3 historical points", sample_size=3)
    dur = m.DurationResult(1, False, T0)
    quality = m.QualitySummary("ok", 10, 0)
    _supporting, contradicting = m.evidence(
        reading_a=reading_a,
        reading_b=reading_b,
        percentile_a=thin,
        percentile_b=thin,
        dur=dur,
        quality_a=quality,
        quality_b=quality,
    )
    assert any("fewer than the minimum" in c for c in contradicting)
    assert any("only 1 day" in c for c in contradicting)


def test_evidence_supports_high_percentile_and_full_quality() -> None:
    reading_a = m.WindowReading("ok", window_days=30, direction="up")
    reading_b = m.WindowReading("ok", window_days=30, direction="down")
    strong = m.PercentileResult("ok", percentile=Decimal("95.0"), sample_size=50)
    dur = m.DurationResult(40, False, T0)
    quality = m.QualitySummary("ok", 10, 0)
    supporting, contradicting = m.evidence(
        reading_a=reading_a,
        reading_b=reading_b,
        percentile_a=strong,
        percentile_b=strong,
        dur=dur,
        quality_a=quality,
        quality_b=quality,
    )
    assert any("top quintile" in s for s in supporting)
    assert any("full ('ok') data quality" in s for s in supporting)
    assert not contradicting
