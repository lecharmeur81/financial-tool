"""Macro calculated metrics (Phase 11): yield-curve slope, approximate real policy rate, CPI
year-over-year change, VIX condition, generic trend, and the US net-liquidity composite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.macro import metrics as m

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def pts(*pairs: tuple[int, str]) -> list[m.Point]:
    """``(days_before_now, value)`` pairs -> Points, oldest first."""
    return [m.Point(NOW - timedelta(days=d), Decimal(v)) for d, v in pairs]


# --------------------------------------------------------------------------- latest / at


def test_latest_picks_newest_point_within_tolerance() -> None:
    points = pts((10, "1"), (2, "2"), (0, "3"))
    result = m.latest(points, NOW, m.DAILY_TOLERANCE)
    assert result is not None
    assert result.value == Decimal(3)


def test_latest_returns_none_when_nothing_within_tolerance() -> None:
    points = pts((30, "1"))
    assert m.latest(points, NOW, m.DAILY_TOLERANCE) is None


# --------------------------------------------------------------------------- yield curve


def test_yield_curve_inverted_condition() -> None:
    ten = pts((0, "3.80"))
    two = pts((0, "4.20"))
    result = m.yield_curve_slope(ten, two, NOW)
    assert result.status == "ok"
    assert result.slope_pp == Decimal("-0.40")
    assert result.condition == "inverted"


def test_yield_curve_normal_condition() -> None:
    ten = pts((0, "4.50"))
    two = pts((0, "3.00"))
    result = m.yield_curve_slope(ten, two, NOW)
    assert result.slope_pp == Decimal("1.50")
    assert result.condition == "normal"


def test_yield_curve_flat_condition_between_thresholds() -> None:
    ten = pts((0, "4.00"))
    two = pts((0, "3.80"))
    result = m.yield_curve_slope(ten, two, NOW)
    assert result.slope_pp == Decimal("0.20")
    assert result.condition == "flat"


def test_yield_curve_unavailable_when_2y_missing() -> None:
    result = m.yield_curve_slope(pts((0, "4.00")), [], NOW)
    assert result.status == "unavailable"
    assert "2-year" in (result.reason or "")


# --------------------------------------------------------------------------- CPI YoY / real rate


def test_cpi_year_over_year_change() -> None:
    cpi = pts((365, "300.0"), (0, "312.0"))
    result = m.cpi_year_over_year(cpi, NOW)
    assert result.status == "ok"
    assert result.change_pct == Decimal(12) / Decimal(300)


def test_real_policy_rate_subtracts_cpi_yoy_from_fed_funds() -> None:
    funds = pts((0, "4.33"))
    cpi = pts((365, "300.0"), (0, "312.0"))  # 4% YoY
    result = m.real_policy_rate(funds, cpi, NOW)
    assert result.status == "ok"
    assert result.fed_funds_pct == Decimal("4.33")
    assert result.cpi_yoy_pct == Decimal("4.00")
    assert result.real_rate_pp == Decimal("0.33")


def test_real_policy_rate_unavailable_when_fed_funds_missing() -> None:
    cpi = pts((365, "300.0"), (0, "312.0"))
    result = m.real_policy_rate([], cpi, NOW)
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- VIX condition


def test_vix_elevated_condition() -> None:
    result = m.vix_condition(pts((0, "30.0")), NOW)
    assert result.condition == "elevated"


def test_vix_calm_condition() -> None:
    result = m.vix_condition(pts((0, "12.0")), NOW)
    assert result.condition == "calm"


def test_vix_normal_condition_between_thresholds() -> None:
    result = m.vix_condition(pts((0, "20.0")), NOW)
    assert result.condition == "normal"


# --------------------------------------------------------------------------- generic trend


def test_trend_up_condition() -> None:
    points = pts((90, "100"), (0, "110"))
    result = m.trend("x", points, NOW, m.QUARTER, m.DAILY_TOLERANCE)
    assert result.status == "ok"
    assert result.change_pct == Decimal("0.10")
    assert result.condition == "up"


def test_trend_down_condition() -> None:
    points = pts((90, "100"), (0, "90"))
    result = m.trend("x", points, NOW, m.QUARTER, m.DAILY_TOLERANCE)
    assert result.change_pct == Decimal("-0.10")
    assert result.condition == "down"


def test_trend_flat_condition_below_move_threshold() -> None:
    points = pts((90, "100"), (0, "101"))
    result = m.trend("x", points, NOW, m.QUARTER, m.DAILY_TOLERANCE)
    assert result.condition == "flat"


def test_trend_unavailable_when_base_value_not_positive() -> None:
    points = pts((90, "0"), (0, "10"))
    result = m.trend("x", points, NOW, m.QUARTER, m.DAILY_TOLERANCE)
    assert result.status == "unavailable"


def test_trend_unavailable_when_no_earlier_point_in_window() -> None:
    points = pts((0, "10"))
    result = m.trend("x", points, NOW, m.QUARTER, m.DAILY_TOLERANCE)
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- net liquidity


def test_us_net_liquidity_composite() -> None:
    walcl = pts((0, "7100000"))  # $ millions
    tga = pts((0, "750000"))  # $ millions
    rrp = pts((0, "0.500"))  # $ billions
    result = m.us_net_liquidity(walcl, tga, rrp, NOW)
    assert result.status == "ok"
    assert result.fed_balance_sheet_usd_b == Decimal("7100.0")
    assert result.tga_usd_b == Decimal("750.0")
    assert result.reverse_repo_usd_b == Decimal("0.500")
    assert result.net_liquidity_usd_b == Decimal("6349.5")


def test_us_net_liquidity_unavailable_when_reverse_repo_missing() -> None:
    result = m.us_net_liquidity(pts((0, "7100000")), pts((0, "750000")), [], NOW)
    assert result.status == "unavailable"
    assert "reverse repo" in (result.reason or "")


def test_net_liquidity_trend_computes_change_between_two_composite_readings() -> None:
    walcl = pts((90, "7000000"), (0, "7100000"))
    tga = pts((90, "700000"), (0, "750000"))
    rrp = pts((90, "1.000"), (0, "0.500"))
    result = m.net_liquidity_trend(walcl, tga, rrp, NOW)
    assert result.status == "ok"
    # then: (7000000-700000)/1000 - 1.000 = 6299.0 ; now: (7100000-750000)/1000 - 0.500 = 6349.5
    assert result.then is not None
    assert result.then.value == Decimal("6299.0")
    assert result.now is not None
    assert result.now.value == Decimal("6349.5")
    assert result.change_pct == (Decimal("6349.5") / Decimal("6299.0") - 1)
