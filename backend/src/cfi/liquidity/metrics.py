"""Liquidity / stablecoin calculated metrics (L2): supply growth, contraction, market share, and
growth acceleration / deceleration.

Pure functions (no I/O). Every input is point-in-time data (``available_at <= as_of``) supplied by
the service. Every threshold is a **judgment parameter chosen by design** (not fitted to data) and
is published alongside each result (``PARAMETERS``). Nothing here labels a reading bullish or
bearish: rising stablecoin supply describes fiat entering the tracked exchange-adjacent pool
(potential dry powder), not where price goes (R1).

Day-over-day change in stored circulating supply is used as the observable proxy for net
minting/burning (see ``liquidity/universe.py`` docstring) — never presented as an exact
minting/burning transaction count.

"Exchange liquidity changes" (stablecoin balances/flows on exchanges) were explicitly asked for
in Phase 9 but are **not calculable** from any free source found; ``exchange_liquidity_change()``
always returns ``status="unavailable"`` with the reason, rather than silently omitting the field
(R3 — missing is a first-class state, never a silent gap).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

DAY = timedelta(days=1)
WEEK = timedelta(days=7)
TWO_WEEKS = timedelta(days=14)
MONTH = timedelta(days=30)

# DefiLlama publishes one snapshot per calendar day; a "latest" or "N days earlier" point may be
# up to this far from the target time (matches liquidity.universe.SUPPLY.freshness_limit).
LATEST_TOLERANCE = timedelta(hours=36)
LOOKBACK_TOLERANCE = timedelta(hours=36)

GROWTH_24H = Decimal("0.01")  # ±1 % day-over-day counts as growth / contraction
GROWTH_7D = Decimal("0.03")  # ±3 % over 7 days
GROWTH_30D = Decimal("0.08")  # ±8 % over 30 days
ACCELERATION_CHANGE = Decimal("0.02")  # ±2 pp change in the 7-day growth rate

PARAMETERS: dict[str, str] = {
    "growth_24h": "day-over-day change ≥ +1 % counts as growth (contraction ≤ −1 %)",
    "growth_7d": "7-day change ≥ +3 % counts as growth (contraction ≤ −3 %)",
    "growth_30d": "30-day change ≥ +8 % counts as growth (contraction ≤ −8 %)",
    "acceleration": "the 7-day growth rate ending now vs. the 7-day growth rate ending 7 days "
    "earlier differs by ≥ 2 percentage points, either direction",
    "latest_tolerance": "a 'latest' value must be at most 36 h old (one missed daily snapshot)",
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


def at(points: Sequence[Point], target: datetime) -> Point | None:
    """The point at ``target`` (or up to ``LOOKBACK_TOLERANCE`` before it)."""
    return latest(points, target, LOOKBACK_TOLERANCE)


def _ratio_change(now: Decimal, then: Decimal) -> Decimal | None:
    return None if then <= 0 else now / then - 1


# --------------------------------------------------------------------------- supply growth


@dataclass(slots=True)
class SupplyGrowth:
    subject: str
    status: str  # ok / unavailable
    reason: str | None
    now: Point | None = None
    day_ago: Point | None = None
    week_ago: Point | None = None
    month_ago: Point | None = None
    change_24h: Decimal | None = None
    change_7d: Decimal | None = None
    change_30d: Decimal | None = None
    condition: str = "unknown"  # growth / contraction / mixed / stable / unknown
    condition_reason: str = ""


def growth_condition(
    change_24h: Decimal | None, change_7d: Decimal | None, change_30d: Decimal | None
) -> tuple[str, str]:
    """Growth / contraction: ≥ +1 % in 24 h, ≥ +3 % in 7 d, or ≥ +8 % in 30 d (and the
    negatives)."""
    changes = [
        (change_24h, GROWTH_24H, "24 h"),
        (change_7d, GROWTH_7D, "7 d"),
        (change_30d, GROWTH_30D, "30 d"),
    ]
    if all(c is None for c, _, _ in changes):
        return "unknown", "no supply change could be calculated"
    up = any(c is not None and c >= t for c, t, _ in changes)
    down = any(c is not None and c <= -t for c, t, _ in changes)
    if up and down:
        return "mixed", "different windows cross opposite thresholds"
    if up:
        return "growth", "supply rose past a threshold: net minting exceeded burning"
    if down:
        return "contraction", "supply fell past a threshold: net burning exceeded minting"
    return "stable", "supply changed less than the thresholds in every window"


def supply_growth(subject: str, points: Sequence[Point], as_of: datetime) -> SupplyGrowth:
    """Day/week/month change of one subject's stored circulating supply."""
    now = latest(points, as_of, LATEST_TOLERANCE)
    if now is None:
        return SupplyGrowth(
            subject,
            "unavailable",
            f"no circulating-supply snapshot for {subject} at or before "
            f"{as_of.isoformat()} within {LATEST_TOLERANCE}",
        )
    day_ago = at(points, now.time - DAY)
    week_ago = at(points, now.time - WEEK)
    month_ago = at(points, now.time - MONTH)
    change_24h = (
        None
        if day_ago is None or day_ago.value is None or now.value is None
        else _ratio_change(now.value, day_ago.value)
    )
    change_7d = (
        None
        if week_ago is None or week_ago.value is None or now.value is None
        else _ratio_change(now.value, week_ago.value)
    )
    change_30d = (
        None
        if month_ago is None or month_ago.value is None or now.value is None
        else _ratio_change(now.value, month_ago.value)
    )
    condition, reason = growth_condition(change_24h, change_7d, change_30d)
    return SupplyGrowth(
        subject,
        "ok",
        None,
        now,
        day_ago,
        week_ago,
        month_ago,
        change_24h,
        change_7d,
        change_30d,
        condition,
        reason,
    )


# --------------------------------------------------------------------------- market share


@dataclass(slots=True)
class MarketShare:
    subject: str
    status: str  # ok / unavailable
    reason: str | None
    subject_value: Decimal | None = None
    total_value: Decimal | None = None
    share: Decimal | None = None  # fraction of total, e.g. 0.62
    as_of_used: datetime | None = None


def market_share(
    subject: str, subject_points: Sequence[Point], total_points: Sequence[Point], as_of: datetime
) -> MarketShare:
    """A subject's circulating supply ÷ total stablecoin supply, both from the same stored
    snapshot time (never mixing a subject snapshot with a total from a different day)."""
    subject_now = latest(subject_points, as_of, LATEST_TOLERANCE)
    if subject_now is None or subject_now.value is None:
        return MarketShare(subject, "unavailable", f"no circulating-supply snapshot for {subject}")
    total_now = at(total_points, subject_now.time)
    if total_now is None or total_now.value is None:
        return MarketShare(
            subject, "unavailable", "no total stablecoin supply snapshot near the same time"
        )
    if total_now.value <= 0:
        return MarketShare(subject, "unavailable", "total stablecoin supply is not positive")
    share = subject_now.value / total_now.value
    return MarketShare(
        subject, "ok", None, subject_now.value, total_now.value, share, subject_now.time
    )


# --------------------------------------------------------------------------- growth acceleration


@dataclass(slots=True)
class GrowthAcceleration:
    status: str  # ok / unavailable
    reason: str | None
    rate_now_7d: Decimal | None = None
    rate_prior_7d: Decimal | None = None
    change: Decimal | None = None  # rate_now_7d − rate_prior_7d, in the same ratio units
    condition: str = "unknown"  # acceleration / deceleration / stable / unknown


def growth_acceleration(points: Sequence[Point], as_of: datetime) -> GrowthAcceleration:
    """Second derivative of supply: the 7-day growth rate ending now, compared with the 7-day
    growth rate ending 7 days earlier. A rising rate is acceleration; a falling one, deceleration.
    """
    now = latest(points, as_of, LATEST_TOLERANCE)
    if now is None or now.value is None:
        return GrowthAcceleration("unavailable", "no current circulating-supply snapshot")
    week_ago = at(points, now.time - WEEK)
    two_weeks_ago = at(points, now.time - TWO_WEEKS)
    if week_ago is None or week_ago.value is None:
        return GrowthAcceleration("unavailable", "no snapshot 7 days earlier")
    if two_weeks_ago is None or two_weeks_ago.value is None:
        return GrowthAcceleration("unavailable", "no snapshot 14 days earlier")
    rate_now = _ratio_change(now.value, week_ago.value)
    rate_prior = _ratio_change(week_ago.value, two_weeks_ago.value)
    if rate_now is None or rate_prior is None:
        return GrowthAcceleration("unavailable", "a base value for one window is not positive")
    change = rate_now - rate_prior
    condition = (
        "acceleration"
        if change >= ACCELERATION_CHANGE
        else "deceleration"
        if change <= -ACCELERATION_CHANGE
        else "stable"
    )
    return GrowthAcceleration("ok", None, rate_now, rate_prior, change, condition)


# --------------------------------------------------------------------------- exchange liquidity


@dataclass(frozen=True, slots=True)
class ExchangeLiquidityChange:
    status: str  # always "unavailable" (Phase 9 scope; see liquidity/universe.py NOT_TRACKED)
    reason: str


EXCHANGE_LIQUIDITY_UNAVAILABLE = ExchangeLiquidityChange(
    status="unavailable",
    reason=(
        "No free source found publishes per-exchange stablecoin balances or flows; this would "
        "need labelled on-chain address attribution for exchange wallets, which only paid "
        "providers (Nansen, Arkham, CryptoQuant) offer. This is a named, visible gap, not a "
        "silently omitted field."
    ),
)


def exchange_liquidity_change() -> ExchangeLiquidityChange:
    """Always 'unavailable' in Phase 9 (see module docstring and ``liquidity/universe.py``)."""
    return EXCHANGE_LIQUIDITY_UNAVAILABLE
