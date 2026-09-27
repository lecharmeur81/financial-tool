"""Macro calculated metrics (L2): yield-curve slope, an approximate real policy rate, CPI/PCE
year-over-year inflation, a US net-liquidity composite, and simple trend (percentage change)
readings for the risk-appetite series (equities, the dollar-index proxy, oil).

Pure functions (no I/O). Every input is point-in-time data (``available_at <= as_of``) supplied by
the service. Every threshold is a **judgment parameter chosen by design** (not fitted to data),
published alongside each result (``PARAMETERS``). Nothing here labels a reading bullish or
bearish for crypto, and nothing here converts macro data into a crypto price forecast (R1 and the
phase's explicit instruction) — conditions describe the macro backdrop only (restrictive/
accommodative monetary policy, risk-on/risk-off in traditional markets), never what crypto markets
will do next.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

DAY = timedelta(days=1)
QUARTER = timedelta(days=90)
YEAR = timedelta(days=365)

# How far a "latest"/"N days earlier" point may be from its target time, per source cadence.
# Wide enough to always find *some* available point under normal operation, not just the freshest
# one: a point becomes available only period_length + delay after its event_time (see
# cfi.macro.universe's availability rules), and remains the latest available one until the *next*
# point's own availability delay has passed — so the worst-case staleness of "the latest available
# point" is roughly one full period plus the release delay, not just the delay alone.
# Daily (period_end_plus, ~1-2 day delay): trading-day gaps (weekends) add up to 2-3 more days.
DAILY_TOLERANCE = timedelta(days=7)
# Weekly (period_end_plus, ~3-day delay): worst case is one week (7d) plus the delay (3d) before
# the next point supersedes the current one — comfortably covered with margin.
WEEKLY_TOLERANCE = timedelta(days=18)
# Monthly (event_time_plus, up to ~60-day delay for PCE): worst case is one month (~30d) plus the
# longest release delay (PCE, ~60d) before the next point becomes available.
MONTHLY_TOLERANCE = timedelta(days=95)

YIELD_CURVE_INVERSION = Decimal("-0.10")  # 10y - 2y <= this (pp) counts as inverted
YIELD_CURVE_STEEP = Decimal("1.00")  # 10y - 2y >= this (pp) counts as steep/normal
VIX_ELEVATED = Decimal(25)  # VIX level at/above this counts as elevated (risk-off)
VIX_CALM = Decimal(15)  # VIX level at/below this counts as calm (risk-on)
TREND_MOVE = Decimal("0.03")  # ±3% over the trend window counts as a directional move

PARAMETERS: dict[str, str] = {
    "yield_curve": "10y - 2y Treasury yield <= -0.10 pp counts as inverted; >= +1.00 pp counts "
    "as steep/normal",
    "vix_condition": "VIX >= 25 counts as elevated (risk-off); VIX <= 15 counts as calm (risk-on)",
    "trend_move": "±3% change over the trend window (90 days for market series, 365 days for "
    "CPI/PCE year-over-year) counts as a directional move",
    "tolerance": "a 'latest'/'N days earlier' point must be within 7 days (daily series), 18 "
    "days (weekly) or 95 days (monthly) of its target time — wide enough to always find the "
    "latest available point given each series' own release-schedule delay, not just its cadence",
}


@dataclass(frozen=True, slots=True)
class Point:
    time: datetime
    value: Decimal | None
    quality_status: str = "ok"

    @property
    def has_value(self) -> bool:
        return self.value is not None


def latest(points: Sequence[Point], as_of: datetime, tolerance: timedelta) -> Point | None:
    """Newest point with a value at or before ``as_of`` and not older than ``tolerance``."""
    usable = [p for p in points if p.has_value and as_of - tolerance <= p.time <= as_of]
    return max(usable, key=lambda p: p.time) if usable else None


def at(points: Sequence[Point], target: datetime, tolerance: timedelta) -> Point | None:
    """The point nearest ``target`` (at or before it), within ``tolerance``."""
    return latest(points, target, tolerance)


def _ratio_change(now: Decimal, then: Decimal) -> Decimal | None:
    return None if then <= 0 else now / then - 1


# --------------------------------------------------------------------------- single-series level


@dataclass(slots=True)
class LevelReading:
    metric: str
    status: str  # ok / unavailable
    reason: str | None
    value: Decimal | None = None
    time: datetime | None = None


def level(
    metric: str, points: Sequence[Point], as_of: datetime, tolerance: timedelta
) -> LevelReading:
    now = latest(points, as_of, tolerance)
    if now is None or now.value is None:
        return LevelReading(
            metric,
            "unavailable",
            f"no {metric} value at or before {as_of.isoformat()} within {tolerance}",
        )
    return LevelReading(metric, "ok", None, now.value, now.time)


# --------------------------------------------------------------------------- trend (pct change)


@dataclass(slots=True)
class TrendReading:
    metric: str
    status: str  # ok / unavailable
    reason: str | None
    now: Point | None = None
    then: Point | None = None
    change_pct: Decimal | None = None
    condition: str = "unknown"  # up / down / flat / unknown
    condition_reason: str = ""


def trend(
    metric: str,
    points: Sequence[Point],
    as_of: datetime,
    window: timedelta,
    tolerance: timedelta,
) -> TrendReading:
    """Percentage change over ``window`` ending at (or just before) ``as_of``."""
    now = latest(points, as_of, tolerance)
    if now is None or now.value is None:
        return TrendReading(
            metric, "unavailable", f"no current {metric} value within {tolerance} of as_of"
        )
    then = at(points, now.time - window, tolerance)
    if then is None or then.value is None:
        return TrendReading(
            metric, "unavailable", f"no {metric} value near {window} before the current one"
        )
    change = _ratio_change(now.value, then.value)
    if change is None:
        return TrendReading(metric, "unavailable", f"base {metric} value is not positive")
    condition = "up" if change >= TREND_MOVE else "down" if change <= -TREND_MOVE else "flat"
    verb = "rose" if condition == "up" else "fell" if condition == "down" else "changed less than"
    reason = f"{verb} the ±{TREND_MOVE * 100}% threshold over the window"
    return TrendReading(metric, "ok", None, now, then, change, condition, reason)


# --------------------------------------------------------------------------- yield curve slope


@dataclass(slots=True)
class YieldCurveReading:
    status: str
    reason: str | None
    ust10y: Decimal | None = None
    ust2y: Decimal | None = None
    slope_pp: Decimal | None = None  # 10y - 2y, percentage points
    time: datetime | None = None
    condition: str = "unknown"  # inverted / normal / flat / unknown
    condition_reason: str = ""


def yield_curve_slope(
    ust10y_points: Sequence[Point], ust2y_points: Sequence[Point], as_of: datetime
) -> YieldCurveReading:
    ten = latest(ust10y_points, as_of, DAILY_TOLERANCE)
    two = latest(ust2y_points, as_of, DAILY_TOLERANCE)
    if ten is None or ten.value is None:
        return YieldCurveReading("unavailable", "no 10-year Treasury yield near as_of")
    if two is None or two.value is None:
        return YieldCurveReading("unavailable", "no 2-year Treasury yield near as_of")
    slope = ten.value - two.value
    if slope <= YIELD_CURVE_INVERSION:
        condition, reason = "inverted", "10y - 2y at or below the inversion threshold"
    elif slope >= YIELD_CURVE_STEEP:
        condition, reason = "normal", "10y - 2y at or above the steep/normal threshold"
    else:
        condition, reason = "flat", "10y - 2y between the inversion and steep thresholds"
    return YieldCurveReading(
        "ok", None, ten.value, two.value, slope, max(ten.time, two.time), condition, reason
    )


# --------------------------------------------------------------------------- real policy rate


@dataclass(slots=True)
class RealPolicyRateReading:
    status: str
    reason: str | None
    fed_funds_pct: Decimal | None = None
    cpi_yoy_pct: Decimal | None = None
    real_rate_pp: Decimal | None = None  # fed_funds - cpi_yoy, percentage points
    time: datetime | None = None


def cpi_year_over_year(cpi_points: Sequence[Point], as_of: datetime) -> TrendReading:
    """CPI level, 12 months earlier vs. now (a simple, non-seasonally-re-derived YoY change over
    the platform's own already seasonally-adjusted CPI series)."""
    return trend("cpi_yoy", cpi_points, as_of, YEAR, MONTHLY_TOLERANCE)


def real_policy_rate(
    fed_funds_points: Sequence[Point], cpi_points: Sequence[Point], as_of: datetime
) -> RealPolicyRateReading:
    """An approximate real policy rate: effective fed funds rate minus trailing CPI year-over-year
    inflation. A commonly used approximation, not the Fed's own preferred real-rate measure (which
    typically uses forward-looking inflation expectations, not trailing CPI)."""
    funds = latest(fed_funds_points, as_of, DAILY_TOLERANCE)
    if funds is None or funds.value is None:
        return RealPolicyRateReading("unavailable", "no effective fed funds rate near as_of")
    cpi_yoy = cpi_year_over_year(cpi_points, as_of)
    if cpi_yoy.status != "ok" or cpi_yoy.change_pct is None:
        return RealPolicyRateReading(
            "unavailable", cpi_yoy.reason or "no CPI year-over-year change could be calculated"
        )
    cpi_pct = (cpi_yoy.change_pct * 100).quantize(Decimal("0.01"))
    real_rate = (funds.value - cpi_pct).quantize(Decimal("0.01"))
    return RealPolicyRateReading("ok", None, funds.value, cpi_pct, real_rate, funds.time)


# --------------------------------------------------------------------------- US net liquidity


@dataclass(slots=True)
class NetLiquidityReading:
    status: str
    reason: str | None
    fed_balance_sheet_usd_b: Decimal | None = None
    tga_usd_b: Decimal | None = None
    reverse_repo_usd_b: Decimal | None = None
    net_liquidity_usd_b: Decimal | None = None
    time: datetime | None = None


def us_net_liquidity(
    fed_balance_sheet_points: Sequence[Point],
    tga_points: Sequence[Point],
    reverse_repo_points: Sequence[Point],
    as_of: datetime,
) -> NetLiquidityReading:
    """A commonly cited 'net liquidity' proxy: Fed balance sheet − Treasury General Account −
    overnight reverse repo, in USD billions. Fed balance sheet and TGA are stored in USD millions
    (FRED's own units); reverse repo in USD billions — converted to a common unit here."""
    walcl = latest(fed_balance_sheet_points, as_of, WEEKLY_TOLERANCE)
    tga = latest(tga_points, as_of, WEEKLY_TOLERANCE)
    rrp = latest(reverse_repo_points, as_of, DAILY_TOLERANCE)
    if walcl is None or walcl.value is None:
        return NetLiquidityReading("unavailable", "no Fed balance sheet value near as_of")
    if tga is None or tga.value is None:
        return NetLiquidityReading("unavailable", "no Treasury General Account value near as_of")
    if rrp is None or rrp.value is None:
        return NetLiquidityReading("unavailable", "no reverse repo value near as_of")
    walcl_b = walcl.value / 1000
    tga_b = tga.value / 1000
    net = (walcl_b - tga_b - rrp.value).quantize(Decimal("0.1"))
    latest_time = max(walcl.time, tga.time, rrp.time)
    return NetLiquidityReading(
        "ok",
        None,
        walcl_b.quantize(Decimal("0.1")),
        tga_b.quantize(Decimal("0.1")),
        rrp.value,
        net,
        latest_time,
    )


def net_liquidity_trend(
    fed_balance_sheet_points: Sequence[Point],
    tga_points: Sequence[Point],
    reverse_repo_points: Sequence[Point],
    as_of: datetime,
    window: timedelta = QUARTER,
) -> TrendReading:
    """Percentage change in the US net-liquidity composite over ``window`` (default 90 days).
    Computed from two independent composite readings (now and ``window`` earlier), not a
    per-series trend — each reading may draw its three inputs from slightly different, independently
    tolerant timestamps (see ``us_net_liquidity``)."""
    now_reading = us_net_liquidity(fed_balance_sheet_points, tga_points, reverse_repo_points, as_of)
    if (
        now_reading.status != "ok"
        or now_reading.net_liquidity_usd_b is None
        or now_reading.time is None
    ):
        return TrendReading("net_liquidity", "unavailable", now_reading.reason)
    then_reading = us_net_liquidity(
        fed_balance_sheet_points, tga_points, reverse_repo_points, now_reading.time - window
    )
    if then_reading.status != "ok" or then_reading.net_liquidity_usd_b is None:
        return TrendReading(
            "net_liquidity", "unavailable", f"no net-liquidity reading near {window} earlier"
        )
    change = _ratio_change(now_reading.net_liquidity_usd_b, then_reading.net_liquidity_usd_b)
    if change is None:
        return TrendReading(
            "net_liquidity", "unavailable", "base net-liquidity level is not positive"
        )
    condition = "up" if change >= TREND_MOVE else "down" if change <= -TREND_MOVE else "flat"
    now_point = Point(now_reading.time, now_reading.net_liquidity_usd_b)
    then_point = Point(now_reading.time - window, then_reading.net_liquidity_usd_b)
    return TrendReading("net_liquidity", "ok", None, now_point, then_point, change, condition)


# --------------------------------------------------------------------------- VIX condition


@dataclass(slots=True)
class VixReading:
    status: str
    reason: str | None
    value: Decimal | None = None
    time: datetime | None = None
    condition: str = "unknown"  # elevated / calm / normal / unknown
    condition_reason: str = ""


def vix_condition(vix_points: Sequence[Point], as_of: datetime) -> VixReading:
    now = latest(vix_points, as_of, DAILY_TOLERANCE)
    if now is None or now.value is None:
        return VixReading("unavailable", "no VIX value near as_of")
    if now.value >= VIX_ELEVATED:
        condition, reason = "elevated", "VIX at or above the elevated (risk-off) threshold"
    elif now.value <= VIX_CALM:
        condition, reason = "calm", "VIX at or below the calm (risk-on) threshold"
    else:
        condition, reason = "normal", "VIX between the calm and elevated thresholds"
    return VixReading("ok", None, now.value, now.time, condition, reason)
