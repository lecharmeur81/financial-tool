"""Liquidity metrics: supply growth/contraction, market share, growth acceleration, and the
always-unavailable exchange liquidity change (Phase 9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.liquidity import metrics as m

NOW = datetime(2026, 9, 26, tzinfo=UTC)
DAY = timedelta(days=1)


def pt(days_ago: float, value: str | None) -> m.Point:
    return m.Point(NOW - timedelta(days=days_ago), None if value is None else Decimal(value))


# --------------------------------------------------------------------------- supply_growth


def test_supply_growth_computes_all_three_windows() -> None:
    points = [pt(30, "100"), pt(7, "103"), pt(1, "104"), pt(0, "110")]
    g = m.supply_growth("USDT", points, NOW)
    assert g.status == "ok"
    assert g.now is not None
    assert g.now.value == Decimal("110")
    assert g.change_24h == Decimal("110") / Decimal("104") - 1
    assert g.change_7d == Decimal("110") / Decimal("103") - 1
    assert g.change_30d == Decimal("110") / Decimal("100") - 1


def test_supply_growth_unavailable_with_no_recent_point() -> None:
    points = [pt(40, "100")]  # older than LATEST_TOLERANCE
    g = m.supply_growth("USDT", points, NOW)
    assert g.status == "unavailable"
    assert g.reason is not None


def test_supply_growth_partial_windows_when_only_some_history_exists() -> None:
    points = [pt(0, "110")]  # only "now"; no day/week/month-ago points
    g = m.supply_growth("USDT", points, NOW)
    assert g.status == "ok"
    assert g.change_24h is None
    assert g.change_7d is None
    assert g.change_30d is None
    assert g.condition == "unknown"


def test_growth_condition_growth_when_any_window_crosses_its_threshold() -> None:
    condition, reason = m.growth_condition(Decimal("0.02"), None, None)
    assert condition == "growth"
    assert "minting" in reason


def test_growth_condition_contraction_when_any_window_crosses_its_threshold() -> None:
    condition, _ = m.growth_condition(None, Decimal("-0.05"), None)
    assert condition == "contraction"


def test_growth_condition_mixed_when_windows_disagree() -> None:
    condition, reason = m.growth_condition(Decimal("0.02"), Decimal("-0.05"), None)
    assert condition == "mixed"
    assert "cross opposite" in reason


def test_growth_condition_stable_when_under_every_threshold() -> None:
    condition, _ = m.growth_condition(Decimal("0.001"), Decimal("0.001"), Decimal("0.001"))
    assert condition == "stable"


def test_growth_condition_unknown_when_nothing_could_be_calculated() -> None:
    condition, _ = m.growth_condition(None, None, None)
    assert condition == "unknown"


def test_supply_growth_never_divides_by_a_non_positive_base() -> None:
    points = [pt(7, "0"), pt(0, "110")]
    g = m.supply_growth("USDT", points, NOW)
    assert g.change_7d is None  # a zero base is not a usable ratio, not a fabricated infinity


# --------------------------------------------------------------------------- market_share


def test_market_share_is_subject_over_total_at_the_same_snapshot() -> None:
    subject_points = [pt(0, "60")]
    total_points = [pt(0, "100")]
    s = m.market_share("USDT", subject_points, total_points, NOW)
    assert s.status == "ok"
    assert s.share == Decimal("60") / Decimal("100")
    assert s.subject_value == Decimal("60")
    assert s.total_value == Decimal("100")


def test_market_share_unavailable_without_a_subject_snapshot() -> None:
    s = m.market_share("USDT", [], [pt(0, "100")], NOW)
    assert s.status == "unavailable"
    assert s.reason is not None


def test_market_share_unavailable_without_a_matching_total_snapshot() -> None:
    s = m.market_share("USDT", [pt(0, "60")], [], NOW)
    assert s.status == "unavailable"


def test_market_share_unavailable_when_total_is_not_positive() -> None:
    s = m.market_share("USDT", [pt(0, "60")], [pt(0, "0")], NOW)
    assert s.status == "unavailable"
    assert s.reason is not None
    assert "positive" in s.reason


# --------------------------------------------------------------------------- growth_acceleration


def test_growth_acceleration_detects_a_speeding_up_rate() -> None:
    # prior 7-day growth: 100 -> 102 (+2%); current 7-day growth: 102 -> 110 (~+7.8%)
    points = [pt(14, "100"), pt(7, "102"), pt(0, "110")]
    a = m.growth_acceleration(points, NOW)
    assert a.status == "ok"
    assert a.rate_prior_7d == Decimal("102") / Decimal("100") - 1
    assert a.rate_now_7d == Decimal("110") / Decimal("102") - 1
    assert a.change == a.rate_now_7d - a.rate_prior_7d
    assert a.condition == "acceleration"


def test_growth_acceleration_detects_a_slowing_rate() -> None:
    # prior 7-day growth: 100 -> 110 (+10%); current 7-day growth: 110 -> 111 (~+0.9%)
    points = [pt(14, "100"), pt(7, "110"), pt(0, "111")]
    a = m.growth_acceleration(points, NOW)
    assert a.condition == "deceleration"


def test_growth_acceleration_stable_when_the_rate_barely_changes() -> None:
    points = [pt(14, "100"), pt(7, "103"), pt(0, "106")]
    a = m.growth_acceleration(points, NOW)
    assert a.condition == "stable"


def test_growth_acceleration_unavailable_without_two_weeks_of_history() -> None:
    points = [pt(7, "100"), pt(0, "110")]
    a = m.growth_acceleration(points, NOW)
    assert a.status == "unavailable"
    assert a.reason is not None
    assert "14 days" in a.reason


def test_growth_acceleration_unavailable_without_a_current_point() -> None:
    a = m.growth_acceleration([], NOW)
    assert a.status == "unavailable"


# --------------------------------------------------------------------------- exchange liquidity


def test_exchange_liquidity_change_is_always_unavailable() -> None:
    e = m.exchange_liquidity_change()
    assert e.status == "unavailable"
    assert "No free source" in e.reason


# --------------------------------------------------------------------------- latest / at helpers


def test_latest_ignores_points_older_than_tolerance() -> None:
    points = [pt(2, "100")]
    assert m.latest(points, NOW, timedelta(hours=1)) is None
    assert m.latest(points, NOW, timedelta(days=3)) is not None


def test_at_finds_a_point_within_lookback_tolerance() -> None:
    points = [pt(7.5, "100")]
    found = m.at(points, NOW - timedelta(days=7))
    assert found is not None
    assert found.value == Decimal("100")
