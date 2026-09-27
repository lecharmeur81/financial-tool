"""Forward returns and maximum drawdown for historical analogues (Phase 15).

Pure functions over an already-fetched ``Bar`` list (``cfi.market_structure.metrics``) — this
module queries nothing itself. The caller fetches bars once via
``cfi.market.queries.MarketQueries.bars(..., as_of=query_as_of)``, which is already point-in-time
filtered (``available_at <= as_of``, R3); every function here additionally checks that the target
date of a forward-looking calculation has genuinely elapsed by that same ``as_of`` before reporting
a value — the explicit, structural enforcement of this phase's instruction: "Historical future
returns may only be displayed when they would genuinely have been known after that historical
date." A horizon that has not yet elapsed is reported as its own first-class ``"not_yet_known"``
status (R3: missing is a first-class state), never a zero, never omitted silently, never estimated.

No predicted future return is ever computed here — only realized, already-elapsed outcomes.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from cfi.market_structure.metrics import Bar

Status = str  # "ok" | "not_yet_known" | "unavailable"


@dataclass(frozen=True, slots=True)
class ForwardReturn:
    status: Status
    horizon_days: int
    value_pct: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DrawdownResult:
    status: Status
    window_days: int
    value_pct: Decimal | None = None  # <= 0; magnitude of the largest peak-to-trough decline
    partial: bool = False
    reason: str | None = None


def _bar_at_or_before(bars: Sequence[Bar], target: datetime) -> Bar | None:
    candidates = [b for b in bars if b.time <= target]
    return max(candidates, key=lambda b: b.time) if candidates else None


def forward_return(
    bars: Sequence[Bar], *, anchor: datetime, horizon_days: int, as_of: datetime
) -> ForwardReturn:
    """The % change in close price from ``anchor`` to ``anchor + horizon_days``, using the latest
    bar at or before each point — reported only once that target date is at or before ``as_of``
    (never fabricated ahead of that, never using a bar dated after ``as_of``, since ``bars`` itself
    must already have been fetched with that same ``as_of`` cutoff)."""
    target = anchor + timedelta(days=horizon_days)
    if target > as_of:
        return ForwardReturn(
            status="not_yet_known",
            horizon_days=horizon_days,
            reason=f"{horizon_days}-day forward return is not yet knowable as of "
            f"{as_of.isoformat()} (target date {target.date().isoformat()} has not occurred)",
        )
    start_bar = _bar_at_or_before(bars, anchor)
    end_bar = _bar_at_or_before(bars, target)
    if start_bar is None or end_bar is None or start_bar.close == 0:
        return ForwardReturn(
            status="unavailable", horizon_days=horizon_days, reason="missing price data"
        )
    pct = (end_bar.close - start_bar.close) / start_bar.close * 100
    return ForwardReturn(
        status="ok", horizon_days=horizon_days, value_pct=pct.quantize(Decimal("0.01"))
    )


def max_drawdown(
    bars: Sequence[Bar], *, anchor: datetime, window_days: int, as_of: datetime
) -> DrawdownResult:
    """The largest peak-to-trough decline in close price within
    ``[anchor, anchor + window_days]``, truncated to whatever of that window has already elapsed by
    ``as_of`` (marked ``partial`` when the full window has not yet elapsed — still real, observed
    data, never a projection of what the rest of the window might bring)."""
    target = anchor + timedelta(days=window_days)
    known_through = min(target, as_of)
    if known_through <= anchor:
        return DrawdownResult(
            status="not_yet_known",
            window_days=window_days,
            reason=f"window has not yet begun to elapse as of {as_of.isoformat()}",
        )
    window_bars = sorted(
        (b for b in bars if anchor <= b.time <= known_through), key=lambda b: b.time
    )
    if len(window_bars) < 2:
        return DrawdownResult(
            status="unavailable", window_days=window_days, reason="missing price data"
        )
    peak = window_bars[0].close
    worst = Decimal(0)
    for b in window_bars:
        if b.close > peak:
            peak = b.close
        if peak > 0:
            decline = (b.close - peak) / peak * 100
            if decline < worst:
                worst = decline
    partial = known_through < target
    return DrawdownResult(
        status="ok",
        window_days=window_days,
        value_pct=worst.quantize(Decimal("0.01")),
        partial=partial,
        reason="window not yet complete — reflects only the elapsed portion" if partial else None,
    )


@dataclass(frozen=True, slots=True)
class Distribution:
    """A range across historical analogues' actual outcomes — never a single predicted value (this
    phase's explicit instruction: "Show distributions and historical ranges instead")."""

    status: str  # "ok" | "insufficient_data"
    horizon_days: int
    count: int
    min_pct: Decimal | None = None
    p25_pct: Decimal | None = None
    median_pct: Decimal | None = None
    p75_pct: Decimal | None = None
    max_pct: Decimal | None = None
    reason: str | None = None


def build_distribution(
    values: Sequence[Decimal], *, horizon_days: int, min_sample: int
) -> Distribution:
    n = len(values)
    if n < min_sample:
        return Distribution(
            status="insufficient_data",
            horizon_days=horizon_days,
            count=n,
            reason=f"only {n} historical analogues had a known {horizon_days}-day outcome "
            f"(need >= {min_sample})",
        )
    ordered = sorted(values)
    median = statistics.median(ordered)
    if n >= 4:
        p25, _, p75 = statistics.quantiles(ordered, n=4, method="inclusive")
    else:
        p25, p75 = ordered[0], ordered[-1]
    return Distribution(
        status="ok",
        horizon_days=horizon_days,
        count=n,
        min_pct=ordered[0],
        p25_pct=p25,
        median_pct=median,
        p75_pct=p75,
        max_pct=ordered[-1],
    )
