"""Retail metrics: historical percentile, derivatives proxy, meme-coin trending, small-transaction
activity (Phase 10). Every metric asserted here carries ``measurement_class == "proxy"``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.retail import metrics as m

NOW = datetime(2026, 9, 26, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def pt(ago: timedelta, value: str | None) -> m.Point:
    return m.Point(NOW - ago, None if value is None else Decimal(value))


# --------------------------------------------------------------------------- Point / latest


def test_point_has_value_reflects_none() -> None:
    assert pt(HOUR, "1").has_value is True
    assert pt(HOUR, None).has_value is False


def test_latest_ignores_points_outside_tolerance_or_in_the_future() -> None:
    points = [pt(timedelta(hours=10), "1"), pt(-HOUR, "2"), pt(HOUR, "3")]
    found = m.latest(points, NOW, timedelta(hours=6))
    assert found is not None
    assert found.value == Decimal("3")


def test_latest_returns_none_when_nothing_is_usable() -> None:
    assert m.latest([pt(timedelta(hours=10), "1")], NOW, timedelta(hours=6)) is None


# --------------------------------------------------------------------------- percentile_rank


def test_percentile_rank_insufficient_history_below_min_sample() -> None:
    history = [Decimal(x) for x in range(5)]
    result = m.percentile_rank(history, Decimal(3), min_sample=20)
    assert result.status == "insufficient_history"
    assert result.percentile is None
    assert result.sample_size == 5
    assert result.value == Decimal(3)
    assert "5" in (result.reason or "")


def test_percentile_rank_ok_with_enough_history() -> None:
    history = [Decimal(x) for x in range(1, 21)]  # 1..20
    result = m.percentile_rank(history, Decimal(10), min_sample=20)
    assert result.status == "ok"
    assert result.sample_size == 20
    # 9 values strictly below 10 (1..9), 1 equal (10 itself is not in history so 0 equal here)
    below = sum(1 for h in history if h < 10)
    equal = sum(1 for h in history if h == 10)
    expected = (Decimal(below) + Decimal(equal) / 2) / Decimal(20) * 100
    assert result.percentile == expected.quantize(Decimal("0.1"))


def test_percentile_rank_current_value_at_the_top_is_100() -> None:
    history = [Decimal(x) for x in range(1, 21)]
    result = m.percentile_rank(history, Decimal(1000), min_sample=20)
    assert result.percentile == Decimal("100.0")


def test_percentile_rank_ties_count_as_half() -> None:
    history = [Decimal(5)] * 20
    result = m.percentile_rank(history, Decimal(5), min_sample=20)
    # all 20 equal -> below=0, equal=20 -> (0 + 10)/20*100 = 50.0
    assert result.percentile == Decimal("50.0")


# --------------------------------------------------------------------------- derivatives_proxy


def test_derivatives_proxy_averages_across_available_assets() -> None:
    funding = {
        "BTC": [pt(HOUR, "0.0003")],
        "ETH": [pt(HOUR, "-0.0002")],
    }
    ratio = {
        "BTC": [pt(HOUR, "1.30")],
        "ETH": [pt(HOUR, "0.80")],
    }
    proxy = m.derivatives_proxy(funding, ratio, NOW)
    assert proxy.measurement_class == "proxy"
    assert proxy.status == "ok"
    assert proxy.assets_used == ("BTC", "ETH")
    assert proxy.funding_rate_avg == (Decimal("0.0003") + Decimal("-0.0002")) / 2
    assert proxy.account_ratio_avg == (Decimal("1.30") + Decimal("0.80")) / 2


def test_derivatives_proxy_funding_condition_long_biased() -> None:
    funding = {"BTC": [pt(HOUR, "0.0005")]}
    proxy = m.derivatives_proxy(funding, {}, NOW)
    assert proxy.funding_condition == "long_biased"
    assert proxy.ratio_condition == "unknown"


def test_derivatives_proxy_funding_condition_short_biased() -> None:
    funding = {"BTC": [pt(HOUR, "-0.0005")]}
    proxy = m.derivatives_proxy(funding, {}, NOW)
    assert proxy.funding_condition == "short_biased"


def test_derivatives_proxy_funding_condition_neutral_within_band() -> None:
    funding = {"BTC": [pt(HOUR, "0.00005")]}
    proxy = m.derivatives_proxy(funding, {}, NOW)
    assert proxy.funding_condition == "neutral"


def test_derivatives_proxy_ratio_condition_long_skewed() -> None:
    ratio = {"BTC": [pt(HOUR, "1.30")]}
    proxy = m.derivatives_proxy({}, ratio, NOW)
    assert proxy.ratio_condition == "long_skewed"
    assert proxy.funding_condition == "unknown"


def test_derivatives_proxy_ratio_condition_short_skewed() -> None:
    ratio = {"BTC": [pt(HOUR, "0.80")]}
    proxy = m.derivatives_proxy({}, ratio, NOW)
    assert proxy.ratio_condition == "short_skewed"


def test_derivatives_proxy_ratio_condition_balanced() -> None:
    ratio = {"BTC": [pt(HOUR, "1.02")]}
    proxy = m.derivatives_proxy({}, ratio, NOW)
    assert proxy.ratio_condition == "balanced"


def test_derivatives_proxy_unavailable_when_nothing_is_fresh() -> None:
    stale = {"BTC": [pt(timedelta(hours=48), "0.0005")]}
    proxy = m.derivatives_proxy(stale, {}, NOW)
    assert proxy.status == "unavailable"
    assert proxy.reason is not None
    assert proxy.assets_used == ()


def test_derivatives_proxy_partial_asset_availability() -> None:
    """Only BTC has fresh data; ETH/SOL/XRP are simply absent — no fabricated fill-in."""
    funding = {"BTC": [pt(HOUR, "0.0003")], "ETH": [pt(timedelta(hours=48), "0.0009")]}
    proxy = m.derivatives_proxy(funding, {}, NOW)
    assert proxy.status == "ok"
    assert proxy.assets_used == ("BTC",)


# --------------------------------------------------------------------------- meme_coin_activity


def test_meme_coin_activity_unavailable_without_a_snapshot() -> None:
    activity = m.meme_coin_activity(None, ("DOGE", "SHIB"))
    assert activity.measurement_class == "proxy"
    assert activity.status == "unavailable"
    assert activity.meme_coins_trending_count == 0


def test_meme_coin_activity_counts_only_curated_symbols() -> None:
    snapshot = m.TrendingSnapshot(NOW, {"DOGE": 0, "BTC": 1, "SHIB": 2})
    activity = m.meme_coin_activity(snapshot, ("DOGE", "SHIB", "PEPE"))
    assert activity.status == "ok"
    assert activity.trending_meme_coins == ("DOGE", "SHIB")
    assert activity.best_rank == {"DOGE": 0, "SHIB": 2}
    assert activity.meme_coins_trending_count == 2
    assert activity.as_of_snapshot == NOW


def test_meme_coin_activity_zero_when_no_curated_symbol_is_trending() -> None:
    snapshot = m.TrendingSnapshot(NOW, {"BTC": 0})
    activity = m.meme_coin_activity(snapshot, ("DOGE", "SHIB"))
    assert activity.status == "ok"
    assert activity.meme_coins_trending_count == 0
    assert activity.trending_meme_coins == ()


# --------------------------------------------------------------------------- small_transaction


def test_small_transaction_activity_computes_week_avg_and_change() -> None:
    points = [
        pt(DAY * 6, "100"),
        pt(DAY * 4, "120"),
        pt(DAY * 2, "140"),
        pt(timedelta(hours=1), "200"),
    ]
    activity = m.small_transaction_activity(points, NOW)
    assert activity.measurement_class == "proxy"
    assert activity.status == "ok"
    assert activity.latest_count is not None
    assert activity.latest_count.value == Decimal("200")
    week_avg = (Decimal("100") + Decimal("120") + Decimal("140")) / 3
    assert activity.week_avg == week_avg
    assert activity.change_vs_week_avg == (Decimal("200") - week_avg) / week_avg


def test_small_transaction_activity_unavailable_without_a_recent_point() -> None:
    points = [pt(timedelta(days=10), "100")]
    activity = m.small_transaction_activity(points, NOW)
    assert activity.status == "unavailable"
    assert activity.reason is not None


def test_small_transaction_activity_no_week_avg_without_trailing_history() -> None:
    points = [pt(timedelta(hours=1), "200")]
    activity = m.small_transaction_activity(points, NOW)
    assert activity.status == "ok"
    assert activity.week_avg is None
    assert activity.change_vs_week_avg is None


# --------------------------------------------------------------------------- trailing_values


def test_trailing_values_selects_only_the_open_ended_window() -> None:
    points = [pt(DAY * 10, "1"), pt(DAY * 3, "2"), pt(timedelta(0), "3")]
    values = m.trailing_values(points, NOW, DAY * 7)
    assert values == [Decimal("2")]  # the DAY*10 point is outside the window; "now" is excluded
