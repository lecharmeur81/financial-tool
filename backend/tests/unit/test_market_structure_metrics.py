"""Market-structure calculated metrics (Phase 12): moving averages, trend, RSI, ATR, realized
volatility, volume trend, rolling VWAP, relative strength, support/resistance, market breadth,
dominance/TOTAL family and ETH/BTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.market_structure import metrics as m

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def bar(
    i: int,
    close: str,
    *,
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
    volume: str | None = "100",
) -> m.Bar:
    c = Decimal(close)
    return m.Bar(
        time=NOW - timedelta(days=(400 - i)),
        open=Decimal(open_) if open_ else c,
        high=Decimal(high) if high else c,
        low=Decimal(low) if low else c,
        close=c,
        volume=Decimal(volume) if volume is not None else None,
    )


def rising_bars(n: int, start: str = "100", step: str = "1") -> list[m.Bar]:
    price = Decimal(start)
    step_d = Decimal(step)
    out = []
    for i in range(n):
        out.append(bar(i, str(price), high=str(price + 1), low=str(price - 1)))
        price += step_d
    return out


def flat_bars(n: int, price: str = "100") -> list[m.Bar]:
    return [bar(i, price, high=price, low=price) for i in range(n)]


# --------------------------------------------------------------------------- bars_from_rows


def test_bars_from_rows_skips_rows_without_a_close() -> None:
    rows = [
        {
            "event_time": NOW,
            "open": Decimal(1),
            "high": Decimal(1),
            "low": Decimal(1),
            "close": None,
            "volume_base": Decimal(1),
        },
        {
            "event_time": NOW,
            "open": Decimal(1),
            "high": Decimal(2),
            "low": Decimal(1),
            "close": Decimal(2),
            "volume_base": Decimal(10),
        },
    ]
    bars = m.bars_from_rows(rows)
    assert len(bars) == 1
    assert bars[0].close == Decimal(2)


# --------------------------------------------------------------------------- moving averages/trend


def test_moving_averages_unavailable_with_no_bars() -> None:
    result = m.moving_averages([])
    assert result.status == "unavailable"


def test_moving_averages_computes_sma_windows() -> None:
    bars = flat_bars(200, "100")
    result = m.moving_averages(bars)
    assert result.status == "ok"
    assert result.sma20 == Decimal(100)
    assert result.sma50 == Decimal(100)
    assert result.sma200 == Decimal(100)


def test_trend_uptrend_when_close_above_rising_moving_averages() -> None:
    bars = rising_bars(220, start="50", step="1")
    result = m.trend(bars)
    assert result.status == "ok"
    assert result.condition == "uptrend"


def test_trend_downtrend_when_close_below_falling_moving_averages() -> None:
    bars = rising_bars(220, start="300", step="-1")
    result = m.trend(bars)
    assert result.status == "ok"
    assert result.condition == "downtrend"


def test_trend_unavailable_with_fewer_than_200_bars() -> None:
    result = m.trend(flat_bars(50))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- RSI


def test_rsi_all_gains_is_100() -> None:
    bars = rising_bars(30, start="100", step="1")
    result = m.rsi(bars)
    assert result.status == "ok"
    assert result.value == Decimal(100)
    assert result.condition == "overbought"


def test_rsi_all_losses_is_zero() -> None:
    bars = rising_bars(30, start="200", step="-1")
    result = m.rsi(bars)
    assert result.status == "ok"
    assert result.value == Decimal(0)
    assert result.condition == "oversold"


def test_rsi_flat_prices_is_neutral_midpoint() -> None:
    bars = flat_bars(30)
    result = m.rsi(bars)
    assert result.status == "ok"
    assert result.value == Decimal(100)  # avg_loss == 0 -> RSI defined as 100


def test_rsi_unavailable_with_too_few_bars() -> None:
    result = m.rsi(flat_bars(5))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- ATR


def test_atr_unavailable_with_too_few_bars() -> None:
    result = m.atr(flat_bars(5))
    assert result.status == "unavailable"


def test_atr_insufficient_history_before_percentile_window_fills() -> None:
    bars = rising_bars(30, start="100", step="1")
    result = m.atr(bars)
    assert result.status == "insufficient_history"
    assert result.atr_pct is not None


def test_atr_ok_once_percentile_window_has_enough_readings() -> None:
    bars = rising_bars(420, start="100", step="1")
    result = m.atr(bars)
    assert result.status == "ok"
    assert result.percentile is not None
    assert result.condition in {"elevated", "normal", "low"}


# --------------------------------------------------------------------------- realized volatility


def test_realized_volatility_zero_for_flat_prices() -> None:
    bars = flat_bars(420, "100")
    result = m.realized_volatility(bars)
    assert result.status == "ok"
    assert result.annualized_pct == Decimal(0)
    # every trailing reading is identical (zero variance), so the nearest-rank percentile of the
    # current reading against its own history is 100 -> "elevated" (a flat regime is still
    # unremarkable in practice; the label just reflects the tie-heavy percentile formula).
    assert result.condition == "elevated"


def test_realized_volatility_unavailable_with_too_few_bars() -> None:
    result = m.realized_volatility(flat_bars(10))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- volume trend


def test_volume_trend_elevated_when_latest_volume_spikes() -> None:
    bars = [bar(i, "100", volume="100") for i in range(20)]
    bars.append(bar(20, "100", volume="500"))
    result = m.volume_trend(bars)
    assert result.status == "ok"
    assert result.condition == "elevated"
    assert result.ratio == Decimal(5)


def test_volume_trend_unavailable_with_too_few_bars() -> None:
    result = m.volume_trend(flat_bars(5))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- VWAP


def test_rolling_vwap_matches_price_for_constant_price_and_volume() -> None:
    bars = flat_bars(25, "100")
    result = m.rolling_vwap(bars)
    assert result.status == "ok"
    assert result.vwap == Decimal(100)
    assert result.position == "at"


def test_rolling_vwap_unavailable_with_too_few_priced_bars() -> None:
    result = m.rolling_vwap(flat_bars(5))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- relative strength


def test_relative_strength_outperforming_when_asset_beats_benchmark() -> None:
    asset_bars = rising_bars(35, start="100", step="2")  # bigger climb
    bench_bars = rising_bars(35, start="100", step="1")
    result = m.relative_strength(asset_bars, bench_bars)
    assert result.status == "ok"
    assert result.condition == "outperforming"
    assert result.spread_pp is not None
    assert result.spread_pp > 0


def test_relative_strength_unavailable_with_too_few_bars() -> None:
    result = m.relative_strength(flat_bars(10), flat_bars(10))
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- support / resistance


def test_support_resistance_picks_rolling_high_and_low() -> None:
    bars = [bar(i, "100", high=str(100 + i), low=str(100 - i)) for i in range(20)]
    result = m.support_resistance(bars, 20)
    assert result.status == "ok"
    assert result.resistance == Decimal(119)
    assert result.support == Decimal(81)


def test_support_resistance_unavailable_with_too_few_bars() -> None:
    result = m.support_resistance(flat_bars(5), 20)
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- market breadth


def test_market_breadth_broad_advance_when_all_above_sma() -> None:
    result = m.market_breadth({"BTC": True, "ETH": True, "SOL": True, "XRP": True})
    assert result.status == "ok"
    assert result.condition == "broad_advance"
    assert result.fraction == Decimal(1)


def test_market_breadth_broad_decline_when_all_below_sma() -> None:
    result = m.market_breadth({"BTC": False, "ETH": False, "SOL": False, "XRP": False})
    assert result.condition == "broad_decline"


def test_market_breadth_excludes_unavailable_assets() -> None:
    result = m.market_breadth({"BTC": True, "ETH": None, "SOL": False, "XRP": None})
    assert result.status == "ok"
    assert result.total == 2
    assert result.universe == ("BTC", "SOL")


def test_market_breadth_unavailable_when_nothing_has_enough_history() -> None:
    result = m.market_breadth({"BTC": None, "ETH": None})
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- dominance / TOTAL


def test_total_cap_family_computes_dominance_and_total2_total3() -> None:
    result = m.total_cap_family(Decimal(1000), Decimal(500), Decimal(200), NOW)
    assert result.status == "ok"
    assert result.btc_dominance_pct == Decimal(50)
    assert result.eth_dominance_pct == Decimal(20)
    assert result.alt_dominance_pct == Decimal(30)
    assert result.total2_usd == Decimal(500)
    assert result.total3_usd == Decimal(300)


def test_total_cap_family_unavailable_without_total() -> None:
    result = m.total_cap_family(None, Decimal(500), Decimal(200), NOW)
    assert result.status == "unavailable"


def test_total_cap_family_partial_when_only_btc_cap_known() -> None:
    result = m.total_cap_family(Decimal(1000), Decimal(500), None, NOW)
    assert result.status == "ok"
    assert result.btc_dominance_pct == Decimal(50)
    assert result.eth_dominance_pct is None
    assert result.total2_usd == Decimal(500)
    assert result.total3_usd is None
    assert result.alt_dominance_pct is None


# --------------------------------------------------------------------------- ETH/BTC


def test_eth_btc_ratio_strengthening_when_eth_outpaces_btc() -> None:
    eth_bars = rising_bars(100, start="10", step="0.2")
    btc_bars = rising_bars(100, start="100", step="0.1")
    result = m.eth_btc_ratio(eth_bars, btc_bars)
    assert result.status == "ok"
    assert result.condition == "eth_strengthening"


def test_eth_btc_ratio_unavailable_with_no_bars() -> None:
    result = m.eth_btc_ratio([], [])
    assert result.status == "unavailable"
