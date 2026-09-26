"""Derivatives calculated metrics (L2): open interest change, leverage, funding, basis,
liquidations, options, and the conditions flagged from them.

Pure functions (no I/O). Every input is point-in-time data (``available_at <= as_of``) supplied
by the service. Every threshold is a **judgment parameter chosen by design** (not fitted to data)
and is published with each result. Nothing here labels a reading bullish or bearish: rising
leverage, positive funding or put-heavy positioning describe how positions are built, not where
price goes (R1).

Ratios are fractions (0.05 = 5 %); the service formats percentages.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)

# Snapshots older than this (relative to as_of) are not used as "now".
LATEST_TOLERANCE = timedelta(hours=3)
# A point used for "24 h / 7 d earlier" may be up to this far before the target time.
LOOKBACK_TOLERANCE = timedelta(hours=1)

OI_EXPANSION_24H = Decimal("0.05")
OI_EXPANSION_7D = Decimal("0.15")
LEVERAGE_CHANGE_7D = Decimal("0.10")
FUNDING_EXTREME = Decimal("0.30")  # annualised, either sign
# Longest gap allowed between funding settlements (or window edges) for a complete 7-day sum.
MAX_FUNDING_GAP = timedelta(hours=9)
BASIS_HIGH = Decimal("0.20")  # annualised
BASIS_LOW = Decimal("-0.05")
BASIS_TARGET_DAYS = Decimal(90)
BASIS_MIN_DAYS = Decimal(14)
LIQUIDATION_EVENT_MULTIPLE = Decimal(5)
LIQUIDATION_EVENT_MIN_OI = Decimal("0.0005")
LIQUIDATION_MIN_HISTORY_HOURS = 24
OPTION_TARGET_DAYS = Decimal(30)
OPTION_MIN_DAYS = Decimal(7)
SKEW_PUT_MONEYNESS = Decimal("0.9")
SKEW_CALL_MONEYNESS = Decimal("1.1")
SKEW_STRIKE_TOLERANCE = Decimal("0.03")
PRICE_FLAT = Decimal("0.01")
OI_FLAT = Decimal("0.01")
DAYS_PER_YEAR = Decimal(365)

PARAMETERS: dict[str, str] = {
    "oi_expansion_24h": "≥ +5 % in 24 h (contraction ≤ −5 %)",
    "oi_expansion_7d": "≥ +15 % in 7 d (contraction ≤ −15 %)",
    "leverage_change_7d": "± 10 % relative change of open interest ÷ market cap over 7 d",
    "funding_extreme": "|annualised 7-day funding| ≥ 30 %",
    "basis_extreme": "annualised basis of the headline future ≥ +20 % or ≤ −5 %",
    "basis_headline": "dated future closest to 90 days to expiry, at least 14 days",
    "liquidation_event": "an hour with liquidations ≥ 5 × the median of the hours before it in "
    "the 7-day window (at least 24 of them) and ≥ 0.05 % of open interest",
    "skew": "implied volatility of the put nearest 0.9 × forward minus the call nearest 1.1 × "
    "forward (strikes within ± 3 % of those targets), expiry closest to 30 days (≥ 7 days)",
    "latest_tolerance": "a 'latest' value must be at most 3 h old",
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


# --------------------------------------------------------------------------- open interest


@dataclass(slots=True)
class VenueOI:
    venue: str
    now: Point | None
    day_ago: Point | None
    week_ago: Point | None

    @property
    def change_24h(self) -> Decimal | None:
        if self.now is None or self.day_ago is None:
            return None
        return _ratio_change(self.now.value or Decimal(0), self.day_ago.value or Decimal(0))

    @property
    def change_7d(self) -> Decimal | None:
        if self.now is None or self.week_ago is None:
            return None
        return _ratio_change(self.now.value or Decimal(0), self.week_ago.value or Decimal(0))


@dataclass(slots=True)
class OpenInterest:
    venues: list[VenueOI]
    total_now: Decimal | None
    change_24h: Decimal | None
    change_7d: Decimal | None
    venues_24h: list[str]
    venues_7d: list[str]
    condition: str  # expansion / contraction / mixed / stable / unknown
    reason: str


def _aggregate(venues: Sequence[VenueOI], attr: str) -> tuple[Decimal | None, list[str]]:
    """Change of the summed open interest over the venues with both values (never mixing sets)."""
    both = [v for v in venues if v.now is not None and getattr(v, attr) is not None]
    if not both:
        return None, []
    now = sum((v.now.value or Decimal(0) for v in both if v.now), Decimal(0))
    then = sum((getattr(v, attr).value or Decimal(0) for v in both), Decimal(0))
    return _ratio_change(now, then), [v.venue for v in both]


def open_interest(series: Mapping[str, Sequence[Point]], as_of: datetime) -> OpenInterest:
    venues = []
    for venue, points in sorted(series.items()):
        now = latest(points, as_of, LATEST_TOLERANCE)
        venues.append(
            VenueOI(
                venue,
                now,
                None if now is None else at(points, now.time - DAY),
                None if now is None else at(points, now.time - WEEK),
            )
        )
    present = [v for v in venues if v.now is not None]
    total = sum((v.now.value or Decimal(0) for v in present if v.now), Decimal(0))
    change_24h, venues_24h = _aggregate(venues, "day_ago")
    change_7d, venues_7d = _aggregate(venues, "week_ago")
    condition, reason = oi_condition(change_24h, change_7d)
    return OpenInterest(
        venues,
        total if present else None,
        change_24h,
        change_7d,
        venues_24h,
        venues_7d,
        condition,
        reason,
    )


def oi_condition(change_24h: Decimal | None, change_7d: Decimal | None) -> tuple[str, str]:
    """OI expansion / contraction: ≥ +5 % in 24 h or ≥ +15 % in 7 d (and the negatives)."""
    if change_24h is None and change_7d is None:
        return "unknown", "no open interest change could be calculated"
    up = (change_24h is not None and change_24h >= OI_EXPANSION_24H) or (
        change_7d is not None and change_7d >= OI_EXPANSION_7D
    )
    down = (change_24h is not None and change_24h <= -OI_EXPANSION_24H) or (
        change_7d is not None and change_7d <= -OI_EXPANSION_7D
    )
    if up and down:
        return "mixed", "24-hour and 7-day changes cross opposite thresholds"
    if up:
        return "expansion", "open interest rose past a threshold: more positions are open"
    if down:
        return "contraction", "open interest fell past a threshold: positions were closed"
    return "stable", "open interest changed less than the thresholds"


# --------------------------------------------------------------------------- leverage


@dataclass(slots=True)
class Leverage:
    status: str  # ok / unavailable
    reason: str | None = None
    ratio_now: Decimal | None = None
    ratio_week_ago: Decimal | None = None
    change_7d: Decimal | None = None
    condition: str = "unknown"  # expansion / reduction / stable / unknown
    venues: list[str] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)


def leverage(
    oi: OpenInterest,
    price: Sequence[Point],
    market_cap: Sequence[Point],
) -> Leverage:
    """Open interest (coins × USD price) ÷ market capitalisation, now and 7 days earlier.

    Uses only venues with both values. Price is the Coinbase close of the hour ending at the
    snapshot (bar starting one hour earlier); market cap the latest daily value at or before the
    snapshot (within 2 days)."""
    both = [v for v in oi.venues if v.now is not None and v.week_ago is not None]
    if not both:
        return Leverage("unavailable", "no venue has open interest now and 7 days earlier")
    t_now = max(v.now.time for v in both if v.now)
    t_then = t_now - WEEK
    coins_now = sum((v.now.value or Decimal(0) for v in both if v.now), Decimal(0))
    coins_then = sum((v.week_ago.value or Decimal(0) for v in both if v.week_ago), Decimal(0))
    p_now, p_then = at(price, t_now - HOUR), at(price, t_then - HOUR)
    m_now = latest(market_cap, t_now, 2 * DAY)
    m_then = latest(market_cap, t_then, 2 * DAY)
    missing = [
        name
        for name, point in (
            ("USD price now", p_now),
            ("USD price 7 days earlier", p_then),
            ("market cap now", m_now),
            ("market cap 7 days earlier", m_then),
        )
        if point is None
    ]
    if missing or not (p_now and p_then and m_now and m_then):
        return Leverage("unavailable", "missing " + ", ".join(missing))
    price_now, price_then = p_now.value or Decimal(0), p_then.value or Decimal(0)
    cap_now, cap_then = m_now.value or Decimal(0), m_then.value or Decimal(0)
    if cap_now <= 0 or cap_then <= 0:
        return Leverage("unavailable", "market cap is not positive")
    ratio_now = coins_now * price_now / cap_now
    ratio_then = coins_then * price_then / cap_then
    change = _ratio_change(ratio_now, ratio_then)
    condition = "unknown"
    if change is not None:
        condition = (
            "expansion"
            if change >= LEVERAGE_CHANGE_7D
            else "reduction"
            if change <= -LEVERAGE_CHANGE_7D
            else "stable"
        )
    return Leverage(
        "ok",
        None,
        ratio_now,
        ratio_then,
        change,
        condition,
        [v.venue for v in both],
        {
            "oi_coins_now": format(coins_now, "f"),
            "oi_coins_week_ago": format(coins_then, "f"),
            "usd_price_now": format(price_now, "f"),
            "usd_price_week_ago": format(price_then, "f"),
            "market_cap_now": format(cap_now, "f"),
            "market_cap_week_ago": format(cap_then, "f"),
            "snapshot_now": t_now.isoformat(),
        },
    )


# --------------------------------------------------------------------------- funding


@dataclass(slots=True)
class VenueFunding:
    venue: str
    status: str  # ok / incomplete / unavailable
    reason: str | None
    settlements: int
    sum_7d: Decimal | None
    annualised_7d: Decimal | None
    latest_rate: Decimal | None
    latest_time: datetime | None
    interval_hours: Decimal | None
    latest_annualised: Decimal | None
    largest_gap_hours: Decimal | None


@dataclass(slots=True)
class Funding:
    venues: list[VenueFunding]
    annualised_7d: Decimal | None
    weighting: str
    condition: str  # extreme_positive / extreme_negative / normal / unknown
    direction: str | None


def venue_funding(venue: str, events: Sequence[Point], as_of: datetime) -> VenueFunding:
    """Σ funding rates settled in (as_of − 7 d, as_of] × 365 / 7: an annualised rate that does
    not depend on the settlement interval, valid only when no settlement is missing."""
    start = as_of - WEEK
    window = sorted((p for p in events if start < p.time <= as_of), key=lambda p: p.time)
    valued = [p for p in window if p.has_value]
    all_valued = sorted(
        (p for p in events if p.has_value and p.time <= as_of), key=lambda p: p.time
    )
    last = all_valued[-1] if all_valued else None
    interval = None
    if len(all_valued) >= 2:
        interval = Decimal((all_valued[-1].time - all_valued[-2].time) // timedelta(minutes=1)) / 60
    latest_annualised = (
        None
        if last is None or not interval
        else (last.value or Decimal(0)) * DAYS_PER_YEAR * 24 / interval
    )
    base = VenueFunding(
        venue,
        "unavailable",
        None,
        len(valued),
        None,
        None,
        None if last is None else last.value,
        None if last is None else last.time,
        interval,
        latest_annualised,
        None,
    )
    if not valued:
        base.reason = "no funding settlements in the last 7 days"
        return base
    edges = [start, *(p.time for p in valued), as_of]
    gap = max(b - a for a, b in pairwise(edges))
    base.largest_gap_hours = Decimal(gap // timedelta(minutes=1)) / 60
    total = sum((p.value or Decimal(0) for p in valued), Decimal(0))
    base.sum_7d = total
    if gap > MAX_FUNDING_GAP or len(valued) < len(window):
        base.status = "incomplete"
        base.reason = (
            f"settlements missing: largest gap {base.largest_gap_hours:.1f} h (maximum "
            f"{MAX_FUNDING_GAP // HOUR} h)"
            if gap > MAX_FUNDING_GAP
            else "some settlements are stored as missing"
        )
        return base
    base.status = "ok"
    base.annualised_7d = total * DAYS_PER_YEAR / 7
    return base


def funding(by_venue: Mapping[str, Sequence[Point]], oi: OpenInterest, as_of: datetime) -> Funding:
    """Venue funding and their open-interest-weighted average (simple average when a venue's
    open interest is unknown)."""
    venues = [venue_funding(v, events, as_of) for v, events in sorted(by_venue.items())]
    ok = [v for v in venues if v.annualised_7d is not None]
    if not ok:
        return Funding(venues, None, "none", "unknown", None)
    weights = {v.venue: (v.now.value if v.now else None) for v in oi.venues}
    if all(weights.get(v.venue) for v in ok):
        total_w = sum((weights[v.venue] or Decimal(0) for v in ok), Decimal(0))
        value = (
            sum(((v.annualised_7d or Decimal(0)) * (weights[v.venue] or 0) for v in ok), Decimal(0))
            / total_w
        )
        weighting = "open-interest weighted (" + ", ".join(v.venue for v in ok) + ")"
    else:
        value = sum((v.annualised_7d or Decimal(0) for v in ok), Decimal(0)) / len(ok)
        weighting = "simple average (open interest missing for a venue)"
    condition = (
        "extreme_positive"
        if value >= FUNDING_EXTREME
        else "extreme_negative"
        if value <= -FUNDING_EXTREME
        else "normal"
    )
    direction = (
        "positive: long positions pay short positions"
        if value > 0
        else "negative: short positions pay long positions"
        if value < 0
        else "zero"
    )
    return Funding(venues, value, weighting, condition, direction)


# --------------------------------------------------------------------------- futures basis


@dataclass(frozen=True, slots=True)
class Quote:
    """One instrument of a venue snapshot (the fields the metrics use)."""

    time: datetime
    instrument: str
    kind: str
    expiry: datetime | None
    mark: Decimal | None
    index: Decimal | None
    open_interest_usd: Decimal | None = None
    strike: Decimal | None = None
    option_type: str | None = None
    mark_iv: Decimal | None = None
    underlying: Decimal | None = None
    open_interest: Decimal | None = None
    volume: Decimal | None = None


@dataclass(slots=True)
class CurvePoint:
    instrument: str
    expiry: datetime | None
    days: Decimal | None
    mark: Decimal
    index: Decimal
    premium: Decimal
    annualised: Decimal | None
    open_interest_usd: Decimal | None


@dataclass(slots=True)
class Basis:
    status: str
    reason: str | None
    snapshot: datetime | None
    curve: list[CurvePoint]
    headline: CurvePoint | None
    perpetual_premium: Decimal | None
    condition: str  # extreme_high / extreme_low / normal / unknown
    shape: str | None  # contango / backwardation / flat


def _days(expiry: datetime, now: datetime) -> Decimal:
    return Decimal((expiry - now) // timedelta(seconds=1)) / 86_400


def basis(quotes: Sequence[Quote], as_of: datetime, tolerance: timedelta) -> Basis:
    """Premium of each future over the index, annualised by days to expiry. Headline: the dated
    future closest to 90 days (at least 14 days) — short-dated premiums annualise into noise."""
    usable = [q for q in quotes if q.mark and q.index and q.time <= as_of]
    snapshot = max((q.time for q in usable), default=None)
    if snapshot is None or snapshot < as_of - tolerance:
        return Basis(
            "unavailable", "no recent futures snapshot", snapshot, [], None, None, "unknown", None
        )
    # an instrument past its expiry is not part of the curve (flagged suspect at ingestion)
    rows = [q for q in usable if q.time == snapshot and (q.expiry is None or q.expiry > snapshot)]
    curve: list[CurvePoint] = []
    perp = None
    for q in rows:
        mark, index = q.mark or Decimal(0), q.index or Decimal(1)
        premium = mark / index - 1
        if q.kind == "perpetual" or q.expiry is None:
            perp = premium
            continue
        days = _days(q.expiry, snapshot)
        curve.append(
            CurvePoint(
                q.instrument,
                q.expiry,
                days,
                mark,
                index,
                premium,
                premium * DAYS_PER_YEAR / days if days >= 1 else None,
                q.open_interest_usd,
            )
        )
    curve.sort(key=lambda c: c.days or Decimal(0))
    eligible = [c for c in curve if c.days is not None and c.days >= BASIS_MIN_DAYS]
    headline = min(
        eligible, key=lambda c: abs((c.days or Decimal(0)) - BASIS_TARGET_DAYS), default=None
    )
    if headline is None or headline.annualised is None:
        return Basis(
            "unavailable",
            "no dated future with at least 14 days to expiry",
            snapshot,
            curve,
            None,
            perp,
            "unknown",
            None,
        )
    value = headline.annualised
    condition = (
        "extreme_high" if value >= BASIS_HIGH else "extreme_low" if value <= BASIS_LOW else "normal"
    )
    shape = "contango" if value > 0 else "backwardation" if value < 0 else "flat"
    return Basis("ok", None, snapshot, curve, headline, perp, condition, shape)


# --------------------------------------------------------------------------- liquidations


@dataclass(frozen=True, slots=True)
class LiquidationEvent:
    hour: datetime
    total: Decimal
    long: Decimal
    short: Decimal
    median_before: Decimal
    share_of_oi: Decimal


@dataclass(slots=True)
class Liquidations:
    status: str  # ok / incomplete / unavailable
    reason: str | None
    window_start: datetime | None
    window_end: datetime | None
    hours_expected: int
    hours_present: int
    long_24h: Decimal | None
    short_24h: Decimal | None
    total_24h: Decimal | None
    long_share: Decimal | None
    share_of_oi: Decimal | None
    open_interest: Decimal | None
    events: list[LiquidationEvent]
    events_note: str | None
    hourly: list[tuple[datetime, Decimal | None, Decimal | None]]


def liquidations(
    long: Sequence[Point],
    short: Sequence[Point],
    oi: Sequence[Point],
    as_of: datetime,
) -> Liquidations:
    """Last 24 complete hours (both sides present for every hour), hourly events over 7 days."""
    long_by = {p.time: p for p in long}
    short_by = {p.time: p for p in short}
    # an hour's total is final 2 minutes after it closes (dataset availability rule)
    end = floor_hour(as_of - timedelta(minutes=2))
    start = end - DAY

    def total(h: datetime) -> tuple[Decimal | None, Decimal | None]:
        lp, sp = long_by.get(h), short_by.get(h)
        return (lp.value if lp else None), (sp.value if sp else None)

    hourly = [(h, *total(h)) for h in [end - WEEK + i * HOUR for i in range(168)]]
    present = [(h, lo, sh) for h, lo, sh in hourly[-24:] if lo is not None and sh is not None]
    oi_now = latest(oi, as_of, LATEST_TOLERANCE)
    result = Liquidations(
        "unavailable",
        None,
        start,
        end,
        24,
        len(present),
        None,
        None,
        None,
        None,
        None,
        None if oi_now is None else oi_now.value,
        [],
        None,
        hourly,
    )
    result.events, result.events_note = liquidation_events(hourly, oi)
    if not present:
        result.reason = "no liquidation totals stored for the last 24 hours"
        return result
    lo = sum((x[1] for x in present), Decimal(0))
    sh = sum((x[2] for x in present), Decimal(0))
    result.long_24h, result.short_24h, result.total_24h = lo, sh, lo + sh
    result.long_share = None if lo + sh == 0 else lo / (lo + sh)
    if len(present) < 24:
        result.status = "incomplete"
        result.reason = f"only {len(present)} of 24 hours have totals"
    elif oi_now is None or not oi_now.value:
        result.status = "incomplete"
        result.reason = "no recent open interest to compare with"
    else:
        result.status = "ok"
        result.share_of_oi = (lo + sh) / oi_now.value
    return result


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def liquidation_events(
    hourly: Sequence[tuple[datetime, Decimal | None, Decimal | None]], oi: Sequence[Point]
) -> tuple[list[LiquidationEvent], str | None]:
    """Hours of the window whose total is ≥ 5 × the median of the (up to 168) hours before and
    ≥ 0.05 % of open interest; the first 24 stored hours only serve as history."""
    known = [(h, lo + sh, lo, sh) for h, lo, sh in hourly if lo is not None and sh is not None]
    if len(known) <= LIQUIDATION_MIN_HISTORY_HOURS:
        return [], (
            f"events need more than {LIQUIDATION_MIN_HISTORY_HOURS} stored hours "
            f"({len(known)} so far)"
        )
    events = []
    for i in range(LIQUIDATION_MIN_HISTORY_HOURS, len(known)):
        hour, tot, lo, sh = known[i]
        before = [k[1] for k in known[max(0, i - 168) : i]]
        median = Decimal(statistics.median(before))
        oi_point = latest(oi, hour, LATEST_TOLERANCE)
        if oi_point is None or not oi_point.value:
            continue
        share = tot / oi_point.value
        big = tot > 0 and tot >= LIQUIDATION_EVENT_MULTIPLE * median
        if big and share >= LIQUIDATION_EVENT_MIN_OI:
            events.append(LiquidationEvent(hour, tot, lo, sh, median, share))
    return events, None


# --------------------------------------------------------------------------- options


@dataclass(slots=True)
class Options:
    status: str
    reason: str | None
    snapshot: datetime | None
    instruments: int = 0
    call_oi: Decimal | None = None
    put_oi: Decimal | None = None
    put_call_oi: Decimal | None = None
    call_volume: Decimal | None = None
    put_volume: Decimal | None = None
    put_call_volume: Decimal | None = None
    notional_oi_usd: Decimal | None = None
    index: Decimal | None = None
    expiry: datetime | None = None
    expiry_days: Decimal | None = None
    forward: Decimal | None = None
    atm_strike: Decimal | None = None
    atm_iv: Decimal | None = None
    skew: Decimal | None = None
    skew_put: tuple[Decimal, Decimal] | None = None  # (strike, iv)
    skew_call: tuple[Decimal, Decimal] | None = None
    skew_reason: str | None = None


def _nearest(rows: Sequence[Quote], target: Decimal) -> Quote | None:
    usable = [q for q in rows if q.strike is not None and q.mark_iv is not None]
    if not usable:
        return None
    best = min(usable, key=lambda q: (abs((q.strike or 0) - target), q.strike))
    if abs((best.strike or Decimal(0)) - target) > SKEW_STRIKE_TOLERANCE * target:
        return None
    return best


def options(quotes: Sequence[Quote], as_of: datetime, tolerance: timedelta) -> Options:
    usable = [q for q in quotes if q.time <= as_of and q.kind == "option"]
    snapshot = max((q.time for q in usable), default=None)
    if snapshot is None or snapshot < as_of - tolerance:
        return Options("unavailable", "no recent option chain snapshot", snapshot)
    rows = [
        q
        for q in usable
        if q.time == snapshot and q.mark is not None and (q.expiry is None or q.expiry > snapshot)
    ]
    calls = [q for q in rows if q.option_type == "call"]
    puts = [q for q in rows if q.option_type == "put"]

    def total(items: Sequence[Quote], attr: str) -> Decimal:
        return sum((getattr(q, attr) or Decimal(0) for q in items), Decimal(0))

    out = Options("ok", None, snapshot, len(rows))
    out.call_oi, out.put_oi = total(calls, "open_interest"), total(puts, "open_interest")
    out.call_volume, out.put_volume = total(calls, "volume"), total(puts, "volume")
    out.put_call_oi = None if not out.call_oi else out.put_oi / out.call_oi
    out.put_call_volume = None if not out.call_volume else out.put_volume / out.call_volume
    indexes = [q.index for q in rows if q.index]
    out.index = Decimal(statistics.median(indexes)) if indexes else None
    if out.index is not None:
        out.notional_oi_usd = (out.call_oi + out.put_oi) * out.index
    expiries = sorted({q.expiry for q in rows if q.expiry is not None})
    eligible = [e for e in expiries if _days(e, snapshot) >= OPTION_MIN_DAYS]
    if not eligible:
        out.skew_reason = "no expiry at least 7 days away"
        return out
    expiry = min(eligible, key=lambda e: (abs(_days(e, snapshot) - OPTION_TARGET_DAYS), e))
    out.expiry, out.expiry_days = expiry, _days(expiry, snapshot)
    chain = [q for q in rows if q.expiry == expiry]
    forwards = [q.underlying for q in chain if q.underlying]
    if not forwards:
        out.skew_reason = "no forward price reported for the expiry"
        return out
    forward = Decimal(statistics.median(forwards))
    out.forward = forward
    atm = _nearest(chain, forward)
    if atm is not None:
        at_strike = [q.mark_iv for q in chain if q.strike == atm.strike and q.mark_iv is not None]
        out.atm_strike = atm.strike
        out.atm_iv = sum(at_strike, Decimal(0)) / len(at_strike)
    put = _nearest([q for q in chain if q.option_type == "put"], SKEW_PUT_MONEYNESS * forward)
    call = _nearest([q for q in chain if q.option_type == "call"], SKEW_CALL_MONEYNESS * forward)
    if (
        put is None
        or call is None
        or put.strike is None
        or put.mark_iv is None
        or call.strike is None
        or call.mark_iv is None
    ):
        out.skew_reason = "no put near 0.9 × forward or no call near 1.1 × forward (± 3 %)"
        return out
    out.skew_put, out.skew_call = (put.strike, put.mark_iv), (call.strike, call.mark_iv)
    out.skew = put.mark_iv - call.mark_iv
    return out


# --------------------------------------------------------------------------- context


def change(
    points: Sequence[Point], as_of: datetime, lookback: timedelta
) -> tuple[Point | None, Decimal | None]:
    now = latest(points, as_of, LATEST_TOLERANCE)
    if now is None:
        return None, None
    then = at(points, now.time - lookback)
    if then is None or not then.value:
        return now, None
    return now, _ratio_change(now.value or Decimal(0), then.value)


def price_oi_context(price_change: Decimal | None, oi_change: Decimal | None) -> str | None:
    """Plain description of price and open interest moving together — no direction call."""
    if price_change is None or oi_change is None:
        return None

    def word(x: Decimal, flat: Decimal) -> str:
        return "rising" if x >= flat else "falling" if x <= -flat else "flat"

    p, o = word(price_change, PRICE_FLAT), word(oi_change, OI_FLAT)
    if o == "flat":
        return f"Price {p} with little change in open interest: positioning roughly unchanged."
    action = "new positions are being opened" if o == "rising" else "positions are being closed"
    if p == "flat":
        return f"Open interest {o} while price is flat: {action} without a price move."
    return f"Price {p} with open interest {o}: {action} as price moves."
