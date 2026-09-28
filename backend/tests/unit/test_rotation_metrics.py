"""Unit tests for cfi.rotation.metrics — pure functions, hand-verified expected values (R13: never
a hard-coded value chosen to force a test to pass; every expectation here is computed on paper in
the comments from the same formula the module documents)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.divergence.metrics import Series, SeriesPoint, WindowReading
from cfi.rotation import metrics as rm

DAY = timedelta(days=1)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _daily_series(values: Sequence[int | None], start: datetime = T0) -> Series:
    """One point per day starting at ``start``; ``None`` is a genuinely missing day (never a
    fabricated interpolation, R3)."""
    return [
        SeriesPoint(start + i * DAY, None if v is None else Decimal(v), "ok")
        for i, v in enumerate(values)
    ]


# --------------------------------------------------------------------------- share_series


def test_share_series_computes_percent_of_denominator() -> None:
    numerator = _daily_series([10, 20, 30])
    denominator = _daily_series([100, 100, 100])
    out = rm.share_series(numerator, denominator)
    # 10/100*100=10, 20/100*100=20, 30/100*100=30
    assert [p.value for p in out] == [Decimal(10), Decimal(20), Decimal(30)]


def test_share_series_carries_denominator_forward_asof() -> None:
    numerator = _daily_series([10, 20, 30])
    # denominator only reports on day 0; days 1-2 must carry day 0's value forward (as-of, R3)
    denominator = _daily_series([200, None, None])
    out = rm.share_series(numerator, denominator)
    # 10/200*100=5, 20/200*100=10, 30/200*100=15
    assert [p.value for p in out] == [Decimal(5), Decimal(10), Decimal(15)]


def test_share_series_reports_insufficient_data_when_denominator_unavailable() -> None:
    numerator = _daily_series([10, 20])
    denominator: Series = []  # no denominator readings at all yet
    out = rm.share_series(numerator, denominator)
    assert all(p.value is None for p in out)
    assert all(p.quality_status == "insufficient_data" for p in out)


def test_share_series_reports_insufficient_data_when_denominator_is_exactly_zero() -> None:
    numerator = _daily_series([10])
    denominator = _daily_series([0])
    out = rm.share_series(numerator, denominator)
    assert out[0].value is None
    assert out[0].quality_status == "insufficient_data"


def test_share_series_passes_through_numerator_missing_points_unchanged() -> None:
    numerator = _daily_series([10, None, 30])
    denominator = _daily_series([100, 100, 100])
    out = rm.share_series(numerator, denominator)
    assert out[1].value is None


# --------------------------------------------------------------------------- sum_series


def test_sum_series_adds_components_at_shared_timestamps() -> None:
    a = _daily_series([10, 20, 30])
    b = _daily_series([1, 2, 3])
    out = rm.sum_series([a, b])
    assert [p.value for p in out] == [Decimal(11), Decimal(22), Decimal(33)]


def test_sum_series_carries_a_slower_updating_component_forward_asof() -> None:
    a = _daily_series([10, 20, 30])
    b = _daily_series([1, None, None])  # b only reports on day 0
    out = rm.sum_series([a, b])
    # day0: 10+1=11, day1: 20 + (b as-of day0 = 1) = 21, day2: 30 + 1 = 31
    assert [p.value for p in out] == [Decimal(11), Decimal(21), Decimal(31)]


def test_sum_series_is_none_before_every_component_has_reported() -> None:
    a = _daily_series([10, 20], start=T0)
    b = _daily_series([1, 2], start=T0 + 5 * DAY)  # b starts 5 days later
    out = rm.sum_series([a, b])
    # the first several timestamps (a-only) have no as-of reading for b yet
    assert any(p.value is None for p in out)
    # by the last timestamp (day 6) both have reported: a as-of day6 carries forward its last
    # value (day1=20), b as-of day6 is its own day6 value (2) -> 20+2=22
    assert out[-1].value == Decimal(22)


# --------------------------------------------------------------------------- flow_corroboration


def _ok_reading(direction: str) -> WindowReading:
    return WindowReading(status="ok", direction=direction)  # type: ignore[arg-type]


def test_flow_corroboration_not_applicable_with_no_flow_data() -> None:
    check = rm.flow_corroboration("BTC", "up", institutional_reading=None, whale_reading=None)
    assert check.status == "not_applicable"
    assert check.supporting == []
    assert check.contradicting == []


def test_flow_corroboration_not_applicable_when_share_direction_unavailable() -> None:
    check = rm.flow_corroboration(
        "BTC", "unavailable", institutional_reading=_ok_reading("up"), whale_reading=None
    )
    assert check.status == "not_applicable"


def test_flow_corroboration_supports_when_flow_direction_matches_share_direction() -> None:
    check = rm.flow_corroboration(
        "BTC", "up", institutional_reading=_ok_reading("up"), whale_reading=None
    )
    assert check.status == "checked"
    assert len(check.supporting) == 1
    assert check.contradicting == []


def test_flow_corroboration_contradicts_when_flow_direction_opposes_share_direction() -> None:
    check = rm.flow_corroboration(
        "BTC", "up", institutional_reading=_ok_reading("down"), whale_reading=None
    )
    assert check.status == "checked"
    assert check.supporting == []
    assert len(check.contradicting) == 1


def test_flow_corroboration_checks_both_legs_independently() -> None:
    check = rm.flow_corroboration(
        "BTC", "up", institutional_reading=_ok_reading("up"), whale_reading=_ok_reading("down")
    )
    assert check.status == "checked"
    assert len(check.supporting) == 1
    assert len(check.contradicting) == 1


def test_flow_corroboration_insufficient_flow_data_when_readings_unavailable() -> None:
    check = rm.flow_corroboration(
        "BTC",
        "up",
        institutional_reading=_ok_reading("unavailable"),
        whale_reading=None,
    )
    assert check.status == "insufficient_flow_data"
