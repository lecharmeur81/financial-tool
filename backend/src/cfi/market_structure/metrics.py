"""Market-structure calculated metrics (Phase 12): trend, moving averages, RSI, ATR, realized
volatility, volume trend, a rolling VWAP, relative strength vs BTC, naive rolling
support/resistance, market breadth across the tracked universe, BTC/ETH dominance, TOTAL/TOTAL2/
TOTAL3, and the ETH/BTC ratio.

Every function here is a pure **Calculated Metric** (R2) over already-ingested, point-in-time OHLCV
bars (Phase 5) and market-capitalisation observations (Phase 5/6, Phase 12's own TOTAL). Nothing
here is a Statistical Signal, a Regime Classification, a forecast or a recommendation, and none of
it is turned into an automatic trading recommendation (this phase's explicit instruction) — every
reading describes the current technical condition of the data, nothing more.

Formulas (every one is also shown in the API's ``calculation`` field, per component):

- **Moving averages / trend**: simple moving average (SMA) over 20/50/200 daily bars. Trend
  condition follows the conventional "golden/death cross" ordering: ``uptrend`` when
  ``close > SMA50 > SMA200``, ``downtrend`` when ``close < SMA50 < SMA200``, ``mixed`` otherwise.
- **RSI**: Wilder's 14-day relative strength index (average gain vs. average loss, Wilder-smoothed).
- **ATR**: Wilder's 14-day average true range, also reported as a percentage of price.
- **Volatility**: annualised standard deviation of 30-day rolling daily log returns
  (``std × √365``), ranked as a nearest-rank percentile against its own trailing ~1-year history —
  the same "how does this compare with its own recent history" idea as every other phase's
  percentile-based signals (e.g. ``cfi.retail.metrics.percentile_rank``), reimplemented locally so
  this module stays self-contained.
- **Volume trend**: latest daily volume vs. the trailing 20-day average (excluding the latest bar).
- **VWAP**: a rolling 20-day volume-weighted average price (``Σ(typical price × volume) ÷
  Σvolume``) — **not** a session-anchored intraday VWAP (daily bars have no intraday session to
  anchor to); labelled as a rolling-window approximation everywhere it appears.
- **Relative strength**: one asset's trailing 30-day return minus BTC's trailing 30-day return
  (a "how has this done vs. BTC" spread), always benchmarked against BTC
  (``cfi.market_structure.universe.BENCHMARK_ASSET``).
- **Support/resistance**: naive rolling N-day high (resistance) and low (support) — a Donchian-
  channel-style method, never a fitted, clustered or ML-derived level.
- **Market breadth**: the fraction of the tracked universe (BTC, ETH, SOL, XRP — this platform's
  full asset list, not the whole crypto market; see ``NOT_TRACKED``) trading above its own 50-day
  SMA.
- **Dominance / TOTAL family**: BTC/ETH dominance = each asset's market cap ÷ TOTAL × 100; TOTAL2 =
  TOTAL − BTC's market cap; TOTAL3 = TOTAL2 − ETH's market cap (the common charting convention).
- **ETH/BTC**: ETH's close ÷ BTC's close (same quote currency, same venue), plus its own 90-day
  trend.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, getcontext
from functools import lru_cache
from typing import Any, Literal

Status = Literal["ok", "unavailable", "insufficient_history"]

SMA_PERIODS: tuple[int, ...] = (20, 50, 200)
TREND_MA_SHORT = 50
TREND_MA_LONG = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = Decimal(70)
RSI_OVERSOLD = Decimal(30)
ATR_PERIOD = 14
VOLATILITY_WINDOW = 30  # days of log returns in one rolling volatility reading
VOLATILITY_PERCENTILE_WINDOW = 365  # trailing rolling-volatility readings ranked against
VOLATILITY_MIN_HISTORY = 20  # fewer than this many rolling readings -> insufficient_history
PERCENTILE_ELEVATED = Decimal(80)
PERCENTILE_LOW = Decimal(20)
VOLUME_TREND_WINDOW = 20
VOLUME_ELEVATED = Decimal("1.5")
VOLUME_LOW = Decimal("0.5")
VWAP_WINDOW = 20
RELATIVE_STRENGTH_WINDOW = 30
RELATIVE_STRENGTH_THRESHOLD = Decimal("0.05")  # ±5pp spread vs BTC before "out/under-performing"
SUPPORT_RESISTANCE_LOOKBACKS: tuple[int, ...] = (20, 50)
BREADTH_MA_PERIOD = 50
ETH_BTC_TREND_WINDOW = 90
ETH_BTC_TREND_MOVE = Decimal("0.03")

ANNUALISATION_DAYS = Decimal(365)


# --------------------------------------------------------------------------- bars


@dataclass(frozen=True, slots=True)
class Bar:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


def bars_from_rows(rows: Sequence[dict[str, object]]) -> list[Bar]:
    """Stored bars with a close price, oldest first (a missing/incomplete bar contributes
    nothing — never a fabricated interpolation, R3)."""
    out: list[Bar] = []
    for r in rows:
        close = r.get("close")
        if close is None:
            continue
        out.append(
            Bar(
                time=r["event_time"],  # type: ignore[arg-type]
                open=r["open"],  # type: ignore[arg-type]
                high=r["high"],  # type: ignore[arg-type]
                low=r["low"],  # type: ignore[arg-type]
                close=close,  # type: ignore[arg-type]
                volume=r.get("volume_base"),  # type: ignore[arg-type]
            )
        )
    return out


def _percentile_rank(value: Decimal, series: Sequence[Decimal]) -> Decimal:
    """Nearest-rank percentile (0-100) of ``value`` within ``series`` (``value`` included)."""
    n = len(series)
    at_or_below = sum(1 for v in series if v <= value)
    return (Decimal(at_or_below) / Decimal(n) * 100).quantize(Decimal("0.1"))


# --------------------------------------------------------------------------- moving averages/trend


@dataclass(slots=True)
class MovingAverageReading:
    status: Status
    reason: str | None = None
    close: Decimal | None = None
    sma20: Decimal | None = None
    sma50: Decimal | None = None
    sma200: Decimal | None = None
    time: datetime | None = None


def _sma(closes: Sequence[Decimal], period: int) -> Decimal | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:], Decimal(0)) / period


def moving_averages(bars: Sequence[Bar]) -> MovingAverageReading:
    if not bars:
        return MovingAverageReading("unavailable", "no daily bars available")
    closes = [b.close for b in bars]
    return MovingAverageReading(
        status="ok",
        close=closes[-1],
        sma20=_sma(closes, 20),
        sma50=_sma(closes, 50),
        sma200=_sma(closes, 200),
        time=bars[-1].time,
    )


@dataclass(slots=True)
class TrendReading:
    status: Status
    reason: str | None = None
    close: Decimal | None = None
    sma50: Decimal | None = None
    sma200: Decimal | None = None
    condition: str = "unknown"  # uptrend / downtrend / mixed / unknown
    time: datetime | None = None


def trend(bars: Sequence[Bar]) -> TrendReading:
    """Price-trend structure from moving-average ordering: ``uptrend`` when
    ``close > SMA50 > SMA200``, ``downtrend`` when ``close < SMA50 < SMA200``, ``mixed``
    otherwise."""
    ma = moving_averages(bars)
    if ma.status != "ok" or ma.sma50 is None or ma.sma200 is None or ma.close is None:
        return TrendReading(
            "unavailable", f"fewer than {TREND_MA_LONG} daily bars available for a 200-day SMA"
        )
    if ma.close > ma.sma50 > ma.sma200:
        condition = "uptrend"
    elif ma.close < ma.sma50 < ma.sma200:
        condition = "downtrend"
    else:
        condition = "mixed"
    return TrendReading(
        "ok", close=ma.close, sma50=ma.sma50, sma200=ma.sma200, condition=condition, time=ma.time
    )


# --------------------------------------------------------------------------- RSI


@dataclass(slots=True)
class RsiReading:
    status: Status
    reason: str | None = None
    value: Decimal | None = None
    condition: str = "unknown"  # overbought / oversold / neutral / unknown
    time: datetime | None = None


def rsi(bars: Sequence[Bar], period: int = RSI_PERIOD) -> RsiReading:
    closes = [b.close for b in bars]
    if len(closes) < period + 1:
        return RsiReading("unavailable", f"fewer than {period + 1} daily bars available")
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else Decimal(0) for d in deltas]
    losses = [-d if d < 0 else Decimal(0) for d in deltas]
    avg_gain = sum(gains[:period], Decimal(0)) / period
    avg_loss = sum(losses[:period], Decimal(0)) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        value = Decimal(100)
    else:
        rs = avg_gain / avg_loss
        value = Decimal(100) - (Decimal(100) / (1 + rs))
    condition = (
        "overbought"
        if value >= RSI_OVERBOUGHT
        else "oversold"
        if value <= RSI_OVERSOLD
        else "neutral"
    )
    return RsiReading("ok", value=value, condition=condition, time=bars[-1].time)


# --------------------------------------------------------------------------- ATR


def _true_ranges(bars: Sequence[Bar]) -> list[Decimal]:
    out = []
    for i in range(1, len(bars)):
        h, low, prev_close = bars[i].high, bars[i].low, bars[i - 1].close
        out.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    return out


def _wilder_series(values: Sequence[Decimal], period: int) -> list[Decimal]:
    """Wilder smoothing: first value is the simple average of the first ``period`` values, each
    later value is ``prior × (period-1)/period + current/period``. ``out[i]`` corresponds to
    ``values[period - 1 + i]``."""
    if len(values) < period:
        return []
    out = [sum(values[:period], Decimal(0)) / period]
    for v in values[period:]:
        out.append((out[-1] * (period - 1) + v) / period)
    return out


def atr_pct_series(bars: Sequence[Bar], period: int = ATR_PERIOD) -> list[tuple[datetime, Decimal]]:
    """(time, ATR ÷ close) at every bar once enough history exists. ``true_ranges[j]`` pairs with
    ``bars[j + 1]``; the Wilder series then aligns with ``bars[period + i]``."""
    trs = _true_ranges(bars)
    smoothed = _wilder_series(trs, period)
    out = []
    for i, atr_value in enumerate(smoothed):
        bar = bars[period + i]
        if bar.close > 0:
            out.append((bar.time, atr_value / bar.close))
    return out


@dataclass(slots=True)
class AtrReading:
    status: Status
    reason: str | None = None
    atr_pct: Decimal | None = None
    percentile: Decimal | None = None
    window_readings: int = 0
    condition: str = "unknown"  # elevated / normal / low / unknown
    time: datetime | None = None


def atr(bars: Sequence[Bar], period: int = ATR_PERIOD) -> AtrReading:
    series = atr_pct_series(bars, period)
    if not series:
        return AtrReading("unavailable", f"fewer than {period + 1} daily bars available")
    trailing = [v for _, v in series[-VOLATILITY_PERCENTILE_WINDOW:]]
    if len(trailing) < VOLATILITY_MIN_HISTORY:
        return AtrReading(
            "insufficient_history",
            f"fewer than {VOLATILITY_MIN_HISTORY} ATR%% readings available (have {len(trailing)})",
            atr_pct=trailing[-1],
            window_readings=len(trailing),
            time=series[-1][0],
        )
    current = trailing[-1]
    percentile = _percentile_rank(current, trailing)
    condition = (
        "elevated"
        if percentile >= PERCENTILE_ELEVATED
        else "low"
        if percentile <= PERCENTILE_LOW
        else "normal"
    )
    return AtrReading(
        "ok",
        atr_pct=current,
        percentile=percentile,
        window_readings=len(trailing),
        condition=condition,
        time=series[-1][0],
    )


# --------------------------------------------------------------------------- realized volatility


@dataclass(slots=True)
class VolatilityReading:
    status: Status
    reason: str | None = None
    annualized_pct: Decimal | None = None
    percentile: Decimal | None = None
    window_readings: int = 0
    condition: str = "unknown"  # elevated / normal / low / unknown
    time: datetime | None = None


# Memoisation of the two pure, expensive steps of the rolling volatility (``Decimal.ln`` and the
# per-window standard deviation). Historical snapshots re-read overlapping daily-bar histories, so
# the same ratios and the same 30-return windows recur across snapshots. Exactness: a cache key is
# the *text* of the input (``str(Decimal)`` keeps sign, digits AND exponent, unlike ``==`` which
# treats 1.0 and 1.00 as equal) plus every Decimal-context setting that can change a result, and a
# hit returns the value an identical computation produced. Bounded (LRU); exceptions are never
# cached. Values are immutable ``Decimal``s, so sharing them is safe.
_LN_MEMO_SIZE = 4096
_WINDOW_MEMO_SIZE = 8192


def _decimal_context_key() -> tuple[Any, ...]:
    ctx = getcontext()
    return (
        ctx.prec,
        ctx.rounding,
        ctx.Emin,
        ctx.Emax,
        ctx.capitals,
        ctx.clamp,
        tuple(signal for signal, enabled in ctx.traps.items() if enabled),
    )


@lru_cache(maxsize=_LN_MEMO_SIZE)
def _ln_of(ratio_text: str, context_key: tuple[Any, ...]) -> Decimal:
    return Decimal(ratio_text).ln()


@lru_cache(maxsize=_WINDOW_MEMO_SIZE)
def _window_annualized(
    return_texts: tuple[str, ...], window: int, context_key: tuple[Any, ...]
) -> Decimal:
    chunk = [Decimal(t) for t in return_texts]
    mean = sum(chunk, Decimal(0)) / window
    variance = sum(((x - mean) ** 2 for x in chunk), Decimal(0)) / (window - 1)
    return variance.sqrt() * ANNUALISATION_DAYS.sqrt()


def realized_volatility_series(
    bars: Sequence[Bar], window: int = VOLATILITY_WINDOW
) -> list[tuple[datetime, Decimal]]:
    """(time, annualized stdev of daily log returns) for a rolling ``window``-day lookback, at
    every bar once enough history exists. ``log_returns[j]`` pairs with ``bars[j + 1]``; a window
    ending at ``log_returns[i - 1]`` (i.e. ``log_returns[i - window:i]``) pairs with ``bars[i]``."""
    context_key = _decimal_context_key()
    closes = [b.close for b in bars]
    log_returns = [
        _ln_of(str(closes[i] / closes[i - 1]), context_key)
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    texts = [sys.intern(str(x)) for x in log_returns]
    out = []
    for i in range(window, len(log_returns) + 1):
        annualized = _window_annualized(tuple(texts[i - window : i]), window, context_key)
        out.append((bars[i].time, annualized))
    return out


def realized_volatility(bars: Sequence[Bar], window: int = VOLATILITY_WINDOW) -> VolatilityReading:
    series = realized_volatility_series(bars, window)
    if not series:
        return VolatilityReading(
            "unavailable", f"fewer than {window + 1} daily bars available for a rolling volatility"
        )
    trailing = [v for _, v in series[-VOLATILITY_PERCENTILE_WINDOW:]]
    if len(trailing) < VOLATILITY_MIN_HISTORY:
        return VolatilityReading(
            "insufficient_history",
            f"fewer than {VOLATILITY_MIN_HISTORY} volatility readings available "
            f"(have {len(trailing)})",
            annualized_pct=trailing[-1],
            window_readings=len(trailing),
            time=series[-1][0],
        )
    current = trailing[-1]
    percentile = _percentile_rank(current, trailing)
    condition = (
        "elevated"
        if percentile >= PERCENTILE_ELEVATED
        else "low"
        if percentile <= PERCENTILE_LOW
        else "normal"
    )
    return VolatilityReading(
        "ok",
        annualized_pct=current,
        percentile=percentile,
        window_readings=len(trailing),
        condition=condition,
        time=series[-1][0],
    )


# --------------------------------------------------------------------------- volume trend


@dataclass(slots=True)
class VolumeTrendReading:
    status: Status
    reason: str | None = None
    current_volume: Decimal | None = None
    average_volume: Decimal | None = None
    ratio: Decimal | None = None
    condition: str = "unknown"  # elevated / normal / low / unknown
    time: datetime | None = None


def volume_trend(bars: Sequence[Bar], window: int = VOLUME_TREND_WINDOW) -> VolumeTrendReading:
    volumes = [b.volume for b in bars if b.volume is not None]
    if len(volumes) < window + 1:
        return VolumeTrendReading(
            "unavailable", f"fewer than {window + 1} daily bars with volume available"
        )
    current = volumes[-1]
    baseline = sum(volumes[-window - 1 : -1], Decimal(0)) / window
    if baseline == 0:
        return VolumeTrendReading("unavailable", "trailing average volume is zero")
    ratio = current / baseline
    condition = (
        "elevated" if ratio >= VOLUME_ELEVATED else "low" if ratio <= VOLUME_LOW else "normal"
    )
    return VolumeTrendReading(
        "ok",
        current_volume=current,
        average_volume=baseline,
        ratio=ratio,
        condition=condition,
        time=bars[-1].time,
    )


# --------------------------------------------------------------------------- VWAP (rolling window)


@dataclass(slots=True)
class VwapReading:
    status: Status
    reason: str | None = None
    vwap: Decimal | None = None
    close: Decimal | None = None
    position: str = "unknown"  # above / below / at / unknown
    window_days: int = 0
    time: datetime | None = None


def rolling_vwap(bars: Sequence[Bar], window: int = VWAP_WINDOW) -> VwapReading:
    """A rolling ``window``-day volume-weighted average price. Not a session-anchored intraday
    VWAP — daily bars have no intraday session to anchor to; this is a rolling-window
    approximation, always labelled as such."""
    priced: list[tuple[Bar, Decimal]] = [(b, b.volume) for b in bars if b.volume is not None]
    if len(priced) < window:
        return VwapReading("unavailable", f"fewer than {window} daily bars with volume available")
    recent = priced[-window:]
    total_v = sum((v for _, v in recent), Decimal(0))
    if total_v == 0:
        return VwapReading("unavailable", "zero total volume in the window")
    total_pv = sum((((b.high + b.low + b.close) / 3) * v for b, v in recent), Decimal(0))
    value = total_pv / total_v
    close = bars[-1].close
    position = "above" if close > value else "below" if close < value else "at"
    return VwapReading(
        "ok", vwap=value, close=close, position=position, window_days=window, time=bars[-1].time
    )


# --------------------------------------------------------------------------- relative strength


@dataclass(slots=True)
class RelativeStrengthReading:
    status: Status
    reason: str | None = None
    asset_return_pct: Decimal | None = None
    benchmark_return_pct: Decimal | None = None
    spread_pp: Decimal | None = None
    condition: str = "unknown"  # outperforming / underperforming / in_line / unknown
    window_days: int = 0
    time: datetime | None = None


def relative_strength(
    asset_bars: Sequence[Bar], benchmark_bars: Sequence[Bar], window: int = RELATIVE_STRENGTH_WINDOW
) -> RelativeStrengthReading:
    """``asset``'s trailing ``window``-day return minus the benchmark's over the same window —
    always benchmarked against BTC (``cfi.market_structure.universe.BENCHMARK_ASSET``), matched by
    bar index (both series are expected to be fetched over the same date range)."""
    if len(asset_bars) <= window or len(benchmark_bars) <= window:
        return RelativeStrengthReading(
            "unavailable", f"fewer than {window + 1} daily bars available for both series"
        )
    if asset_bars[-1 - window].close <= 0 or benchmark_bars[-1 - window].close <= 0:
        return RelativeStrengthReading("unavailable", "a base price is not positive")
    asset_ret = asset_bars[-1].close / asset_bars[-1 - window].close - 1
    bench_ret = benchmark_bars[-1].close / benchmark_bars[-1 - window].close - 1
    spread = asset_ret - bench_ret
    condition = (
        "outperforming"
        if spread >= RELATIVE_STRENGTH_THRESHOLD
        else "underperforming"
        if spread <= -RELATIVE_STRENGTH_THRESHOLD
        else "in_line"
    )
    return RelativeStrengthReading(
        "ok",
        asset_return_pct=asset_ret,
        benchmark_return_pct=bench_ret,
        spread_pp=spread,
        condition=condition,
        window_days=window,
        time=asset_bars[-1].time,
    )


# --------------------------------------------------------------------------- support / resistance


@dataclass(slots=True)
class SupportResistanceReading:
    status: Status
    reason: str | None = None
    lookback_days: int = 0
    support: Decimal | None = None
    resistance: Decimal | None = None
    close: Decimal | None = None
    time: datetime | None = None


def support_resistance(bars: Sequence[Bar], lookback: int) -> SupportResistanceReading:
    """Naive rolling ``lookback``-day high (resistance) and low (support) — a Donchian-channel-
    style method, never a fitted, clustered or ML-derived level."""
    if len(bars) < lookback:
        return SupportResistanceReading(
            "unavailable", f"fewer than {lookback} daily bars available", lookback_days=lookback
        )
    window = bars[-lookback:]
    return SupportResistanceReading(
        "ok",
        lookback_days=lookback,
        support=min(b.low for b in window),
        resistance=max(b.high for b in window),
        close=bars[-1].close,
        time=bars[-1].time,
    )


# --------------------------------------------------------------------------- market breadth


@dataclass(slots=True)
class BreadthReading:
    status: Status
    reason: str | None = None
    advancing: int = 0
    total: int = 0
    fraction: Decimal | None = None
    condition: str = "unknown"  # broad_advance / broad_decline / mixed / unknown
    universe: tuple[str, ...] = ()


def market_breadth(above_sma50: dict[str, bool | None]) -> BreadthReading:
    """The fraction of the tracked universe trading above its own 50-day SMA — a proxy limited to
    the four assets this platform tracks, never full-market breadth (see ``NOT_TRACKED``)."""
    available = {a: v for a, v in above_sma50.items() if v is not None}
    if not available:
        return BreadthReading("unavailable", "no tracked asset has enough history for a 50-day SMA")
    up = sum(1 for v in available.values() if v)
    total = len(available)
    fraction = Decimal(up) / Decimal(total)
    condition = (
        "broad_advance"
        if fraction >= Decimal("0.75")
        else "broad_decline"
        if fraction <= Decimal("0.25")
        else "mixed"
    )
    return BreadthReading(
        "ok",
        advancing=up,
        total=total,
        fraction=fraction,
        condition=condition,
        universe=tuple(sorted(available)),
    )


# --------------------------------------------------------------------------- dominance / TOTAL


@dataclass(slots=True)
class TotalCapFamilyReading:
    status: Status
    reason: str | None = None
    total_usd: Decimal | None = None
    total2_usd: Decimal | None = None
    total3_usd: Decimal | None = None
    btc_dominance_pct: Decimal | None = None
    eth_dominance_pct: Decimal | None = None
    alt_dominance_pct: Decimal | None = None
    time: datetime | None = None


def total_cap_family(
    total_usd: Decimal | None,
    btc_market_cap_usd: Decimal | None,
    eth_market_cap_usd: Decimal | None,
    time: datetime | None,
) -> TotalCapFamilyReading:
    """BTC/ETH dominance, TOTAL2 and TOTAL3 — all Calculated Metrics derived from TOTAL and the
    per-asset market caps this platform already tracks (never separately ingested)."""
    if total_usd is None or total_usd <= 0:
        return TotalCapFamilyReading("unavailable", "no TOTAL market-cap value available")
    btc_dominance = None if btc_market_cap_usd is None else (btc_market_cap_usd / total_usd * 100)
    eth_dominance = None if eth_market_cap_usd is None else (eth_market_cap_usd / total_usd * 100)
    total2 = None if btc_market_cap_usd is None else total_usd - btc_market_cap_usd
    total3 = None if (total2 is None or eth_market_cap_usd is None) else total2 - eth_market_cap_usd
    alt_dominance = (
        None
        if (btc_dominance is None or eth_dominance is None)
        else (Decimal(100) - btc_dominance - eth_dominance)
    )
    return TotalCapFamilyReading(
        "ok",
        total_usd=total_usd,
        total2_usd=total2,
        total3_usd=total3,
        btc_dominance_pct=btc_dominance,
        eth_dominance_pct=eth_dominance,
        alt_dominance_pct=alt_dominance,
        time=time,
    )


# --------------------------------------------------------------------------- ETH/BTC


@dataclass(slots=True)
class EthBtcReading:
    status: Status
    reason: str | None = None
    ratio: Decimal | None = None
    change_pct: Decimal | None = None
    condition: str = "unknown"  # eth_strengthening / eth_weakening / flat / unknown
    window_days: int = 0
    time: datetime | None = None


def eth_btc_ratio(
    eth_bars: Sequence[Bar], btc_bars: Sequence[Bar], window: int = ETH_BTC_TREND_WINDOW
) -> EthBtcReading:
    if not eth_bars or not btc_bars:
        return EthBtcReading("unavailable", "no daily bars available for ETH and/or BTC")
    if btc_bars[-1].close <= 0:
        return EthBtcReading("unavailable", "BTC close is not positive")
    now_ratio = eth_bars[-1].close / btc_bars[-1].close
    if len(eth_bars) <= window or len(btc_bars) <= window:
        return EthBtcReading(
            "ok",
            ratio=now_ratio,
            time=eth_bars[-1].time,
            reason=f"fewer than {window + 1} daily bars available for a {window}-day trend",
        )
    then_btc = btc_bars[-1 - window].close
    then_eth = eth_bars[-1 - window].close
    if then_btc <= 0 or then_eth <= 0:
        return EthBtcReading(
            "ok",
            ratio=now_ratio,
            time=eth_bars[-1].time,
            reason="a base price is not positive for the trend window",
        )
    then_ratio = then_eth / then_btc
    change = now_ratio / then_ratio - 1
    condition = (
        "eth_strengthening"
        if change >= ETH_BTC_TREND_MOVE
        else "eth_weakening"
        if change <= -ETH_BTC_TREND_MOVE
        else "flat"
    )
    return EthBtcReading(
        "ok",
        ratio=now_ratio,
        change_pct=change,
        condition=condition,
        window_days=window,
        time=eth_bars[-1].time,
    )


#: Fixed parameter documentation, exposed via the API's ``/catalog`` (mirrors every prior phase's
#: ``PARAMETERS`` dict — every threshold shown to the user, never hidden).
PARAMETERS: dict[str, str] = {
    "moving_averages": f"Simple moving average over {SMA_PERIODS} daily bars.",
    "trend": (
        f"uptrend: close > SMA{TREND_MA_SHORT} > SMA{TREND_MA_LONG}; downtrend: "
        f"close < SMA{TREND_MA_SHORT} < SMA{TREND_MA_LONG}; mixed otherwise."
    ),
    "rsi": (
        f"Wilder's {RSI_PERIOD}-day RSI. overbought >= {RSI_OVERBOUGHT}, "
        f"oversold <= {RSI_OVERSOLD}, neutral otherwise."
    ),
    "atr": (
        f"Wilder's {ATR_PERIOD}-day average true range, as a percentage of price, ranked as a "
        f"percentile of its own trailing {VOLATILITY_PERCENTILE_WINDOW}-day history "
        f"(minimum {VOLATILITY_MIN_HISTORY} readings). elevated >= {PERCENTILE_ELEVATED}th "
        f"percentile, low <= {PERCENTILE_LOW}th, normal otherwise."
    ),
    "volatility": (
        f"Annualized standard deviation of {VOLATILITY_WINDOW}-day rolling daily log returns "
        f"(std x sqrt(365)), ranked the same way as ATR."
    ),
    "volume_trend": (
        f"Latest daily volume vs. the trailing {VOLUME_TREND_WINDOW}-day average (excluding the "
        f"latest bar). elevated >= {VOLUME_ELEVATED}x, low <= {VOLUME_LOW}x, normal otherwise."
    ),
    "vwap": (
        f"Rolling {VWAP_WINDOW}-day volume-weighted average price (a rolling-window "
        "approximation, not a session-anchored intraday VWAP)."
    ),
    "relative_strength": (
        f"Trailing {RELATIVE_STRENGTH_WINDOW}-day return minus BTC's trailing "
        f"{RELATIVE_STRENGTH_WINDOW}-day return. outperforming >= "
        f"+{RELATIVE_STRENGTH_THRESHOLD * 100}pp, underperforming <= "
        f"-{RELATIVE_STRENGTH_THRESHOLD * 100}pp, in_line otherwise."
    ),
    "support_resistance": (
        f"Naive rolling {SUPPORT_RESISTANCE_LOOKBACKS}-day high (resistance) and low (support) — "
        "a Donchian-channel-style method, never fitted or clustered."
    ),
    "market_breadth": (
        f"Fraction of the tracked universe (BTC, ETH, SOL, XRP) trading above its own "
        f"{BREADTH_MA_PERIOD}-day SMA. broad_advance >= 75%, broad_decline <= 25%, mixed otherwise."
    ),
    "dominance_and_total_family": (
        "BTC/ETH dominance = asset market cap / TOTAL x 100. TOTAL2 = TOTAL - BTC market cap. "
        "TOTAL3 = TOTAL2 - ETH market cap."
    ),
    "eth_btc": f"ETH close / BTC close, plus its own {ETH_BTC_TREND_WINDOW}-day trend.",
}
