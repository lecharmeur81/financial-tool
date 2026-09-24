"""Whale Flow Score v1, accumulation / distribution metrics and contradiction indicators.

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — deterministic
calculations over observed data with fixed, published parameters. Not a signal (not compared with
its own history), not a prediction, not a recommendation.

Sign convention everywhere: **positive = accumulation** (coins leaving exchanges, large holders
growing, old coins staying still), **negative = distribution** (coins moving to exchanges, large
holders shrinking, old coins moving). These are readings of on-chain behaviour; they say nothing
certain about buying or selling.

Method (mirrors the Institutional Flow Score, ADR-0048):

1. Each component is computed from point-in-time data (``available_at <= as_of``).
2. Sub-score = signed metric ÷ reference scale, capped to [−1, +1]. Reference scales are
   **judgment parameters chosen by design**, not fitted to data.
3. Score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components), −100 … +100.
4. A component whose inputs cover less than its minimum coverage is excluded (never filled). If
   the available components carry less than half the total weight: "Insufficient data".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.time import ensure_utc
from cfi.institutional.score import ComponentDef, ComponentResult, ScoreResult

SCORE_ID = "whale_flow_score"
SCORE_VERSION = "v1"
MIN_COVERAGE = Decimal("0.9")
MIN_AVAILABLE_WEIGHT = Decimal("0.5")
# Rich-list comparison: share of the earlier snapshot's unknown large holders that must still be
# listed now (addresses that leave the top 100 have no current balance in the list).
MIN_HOLDER_MATCH = Decimal("0.8")
SNAPSHOT_GAP = timedelta(days=7)
SNAPSHOT_TOLERANCE = timedelta(days=1)
# Contradiction indicators: a sub-score counts as a direction from this magnitude on.
DIRECTION_THRESHOLD = Decimal("0.25")
# Exchange balance changes (two sources): a direction from this change (percent) on.
SUPPLY_DIRECTION_PCT = Decimal("0.5")
SCORE_DIRECTION = Decimal(15)
FLAGGED = ("suspect", "conflicting")

BANDS: tuple[tuple[Decimal | None, str], ...] = (
    (Decimal(50), "strong accumulation"),
    (Decimal(15), "accumulation"),
    (Decimal(-15), "neutral"),
    (Decimal(-50), "distribution"),
    (None, "strong distribution"),
)
BAND_NOTE = (
    "Bands (each includes its lower bound): +50 … +100 strong accumulation; +15 … +50 "
    "accumulation; −15 … +15 neutral; −50 … −15 distribution; −100 … below −50 strong "
    "distribution. They describe on-chain behaviour only, not price direction."
)

COMPONENTS: tuple[ComponentDef, ...] = (
    ComponentDef(
        "exchange_netflow_7d",
        "exchange_netflow_7d_pct_exchange_supply.v1",
        "Net flow to exchanges, last 7 days",
        Decimal("0.35"),
        Decimal("1.0"),
        "% of exchange supply",
        "Σ (exchange inflow − exchange outflow) over the last 7 complete UTC days ÷ exchange "
        "supply on the last day × 100. Sub-score = −value ÷ scale (coins moving onto exchanges "
        "count as distribution).",
        "Calculated metric from attributed evidence (Coin Metrics exchange address attribution)",
    ),
    ComponentDef(
        "exchange_supply_30d",
        "exchange_supply_change_30d_pct.v1",
        "Change of exchange supply, last 30 days",
        Decimal("0.15"),
        Decimal("3.0"),
        "%",
        "(exchange supply on the last day − exchange supply 30 days earlier) ÷ the earlier value "
        "× 100. Sub-score = −value ÷ scale.",
        "Calculated metric from attributed evidence (Coin Metrics exchange address attribution)",
    ),
    ComponentDef(
        "large_holders_7d",
        "unknown_large_holder_balance_change_7d_pct.v1",
        "Balance change of unknown large holders (top 100), 7 days",
        Decimal("0.25"),
        Decimal("1.0"),
        "%",
        "Addresses classified 'unknown large holder' in the top-100 list 7 days earlier (± 1 "
        "day) and still listed now: Σ (balance now − balance then) ÷ Σ balance then × 100. "
        "Sub-score = +value ÷ scale. Requires ≥ 80 % of those addresses still listed.",
        "Calculated metric from inferred evidence (size only — owners unknown)",
    ),
    ComponentDef(
        "revived_1y_7d",
        "revived_supply_1y_7d_vs_90d.v1",
        "Coins ≥ 1 year old moving: last 7 days vs the 90 days before",
        Decimal("0.25"),
        Decimal("1.0"),
        "ratio",
        "(Σ BTC spent from outputs ≥ 365 days old over the last 7 days ÷ 7) ÷ (Σ over the 90 "
        "days before ÷ days with data). Sub-score = −(ratio − 1) ÷ scale (old coins moving more "
        "than usual count as distribution). Bitcoin only.",
        "Calculated metric from observed on-chain data (coin age, not owners)",
    ),
)
DEFS: dict[str, ComponentDef] = {c.component_id: c for c in COMPONENTS}


@dataclass(frozen=True, slots=True)
class DayValue:
    day: date
    value: Decimal | None
    quality_status: str = "ok"
    revision: int = 0
    pit_reliability: str = "native"
    available_at_estimated: bool = False

    @property
    def has_value(self) -> bool:
        return self.value is not None


Series = Mapping[date, DayValue]


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One top-100 list: balance per address and the class assigned to it at that time."""

    time: datetime
    balances: Mapping[str, Decimal]
    classes: Mapping[str, str]


def _clip(x: Decimal) -> Decimal:
    return max(Decimal(-1), min(Decimal(1), x))


def band_for(score: Decimal) -> str:
    for lower, label in BANDS:
        if lower is None or score >= lower:
            return label
    raise AssertionError("unreachable")  # pragma: no cover


def days(end: date, count: int) -> list[date]:
    return [end - timedelta(days=count - 1 - i) for i in range(count)]


def due_day(as_of: datetime, lag: timedelta) -> date:
    """Latest UTC day that should be public by ``as_of`` (day end + publication lag)."""
    moment = ensure_utc(as_of) - lag
    return moment.date() - timedelta(days=1)


def window_end(series: Sequence[Series], due: date, as_of: datetime) -> date:
    """The later of the last day due and the last complete day already received."""
    last_complete = ensure_utc(as_of).date() - timedelta(days=1)
    received = [d for s in series for d, v in s.items() if v.has_value and d <= last_complete]
    return max([due, *received]) if received else due


def _describe_window(result: ComponentResult, wanted: list[date], present: list[DayValue]) -> None:
    got = {p.day for p in present}
    result.window_start, result.window_end = wanted[0], wanted[-1]
    result.days_expected = len(wanted)
    result.days_present = len(present)
    result.missing_days = [d for d in wanted if d not in got]
    result.flagged = sum(p.quality_status in FLAGGED for p in present)
    result.revised = sum(p.revision > 0 for p in present)
    result.backfilled = sum(p.pit_reliability == "backfilled_latest" for p in present)
    result.estimated_availability = sum(p.available_at_estimated for p in present)
    result.latest_input = present[-1].day if present else None


def _coverage_reason(label: str, wanted: list[date], present: int, minimum: Decimal) -> str | None:
    if Decimal(present) / Decimal(len(wanted)) >= minimum:
        return None
    return (
        f"{label}: only {present} of {len(wanted)} days have data ({wanted[0]} … {wanted[-1]}; "
        f"minimum {minimum:.0%})"
    )


def _num(value: Decimal, places: str = "0.0001") -> Decimal:
    return value.quantize(Decimal(places))


def exchange_netflow_component(
    inflow: Series, outflow: Series, supply: Series, end: date, unit: str
) -> ComponentResult:
    definition = DEFS["exchange_netflow_7d"]
    result = ComponentResult(definition, "unavailable")
    wanted = days(end, 7)
    both = [d for d in wanted if inflow.get(d, _NONE).has_value and outflow.get(d, _NONE).has_value]
    present = [inflow[d] for d in both] + [outflow[d] for d in both]
    _describe_window(result, wanted, [inflow[d] for d in both])
    result.flagged = sum(p.quality_status in FLAGGED for p in present)
    result.revised = sum(p.revision > 0 for p in present)
    result.backfilled = sum(p.pit_reliability == "backfilled_latest" for p in present)
    result.estimated_availability = sum(p.available_at_estimated for p in present)
    if (reason := _coverage_reason("inflow and outflow", wanted, len(both), MIN_COVERAGE)) or (
        not both
    ):
        result.reason = reason or "no exchange flow data in the window"
        return result
    supply_day = next((d for d in reversed(wanted) if supply.get(d, _NONE).has_value), None)
    if supply_day is None or (supply[supply_day].value or 0) <= 0:
        result.reason = "no positive exchange supply reported in the window"
        return result
    total_in = sum((inflow[d].value or Decimal(0) for d in both), Decimal(0))
    total_out = sum((outflow[d].value or Decimal(0) for d in both), Decimal(0))
    net = total_in - total_out
    base = supply[supply_day].value
    assert base is not None  # noqa: S101
    assert definition.scale is not None  # noqa: S101
    value = net / base * 100
    result.status = "ok"
    result.value = _num(value)
    result.sub_score = _num(_clip(-value / definition.scale))
    result.inputs = {
        f"inflow_{unit}": format(total_in, "f"),
        f"outflow_{unit}": format(total_out, "f"),
        f"net_flow_to_exchanges_{unit}": format(net, "f"),
        f"exchange_supply_{unit}": format(base, "f"),
        "exchange_supply_date": supply_day.isoformat(),
    }
    result.calculation = (
        f"({total_in:,.2f} in − {total_out:,.2f} out) {unit.upper()} over {len(both)} days "
        f"({wanted[0]} … {wanted[-1]}) ÷ {base:,.2f} {unit.upper()} exchange supply on "
        f"{supply_day} × 100 = {result.value:+.4f} %; sub-score = clip(−{result.value:.4f} ÷ "
        f"{definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def exchange_supply_component(supply: Series, end: date, unit: str) -> ComponentResult:
    definition = DEFS["exchange_supply_30d"]
    result = ComponentResult(definition, "unavailable")
    start = end - timedelta(days=30)
    points = [supply[d] for d in (start, end) if supply.get(d, _NONE).has_value]
    _describe_window(result, [start, end], points)
    result.days_expected, result.missing_days = (
        2,
        [d for d in (start, end) if not supply.get(d, _NONE).has_value],
    )
    if len(points) < 2:
        result.reason = "exchange supply missing on " + ", ".join(
            d.isoformat() for d in result.missing_days
        )
        return result
    first, last = points[0].value, points[1].value
    assert first is not None  # noqa: S101
    assert last is not None  # noqa: S101
    assert definition.scale is not None  # noqa: S101
    if first <= 0:
        result.reason = "non-positive exchange supply at the start of the window"
        return result
    value = (last - first) / first * 100
    result.status = "ok"
    result.value = _num(value)
    result.sub_score = _num(_clip(-value / definition.scale))
    result.inputs = {
        f"exchange_supply_start_{unit}": format(first, "f"),
        f"exchange_supply_end_{unit}": format(last, "f"),
    }
    result.calculation = (
        f"({last:,.2f} − {first:,.2f}) {unit.upper()} ÷ {first:,.2f} (exchange supply {start} → "
        f"{end}) × 100 = {result.value:+.4f} %; sub-score = clip(−{result.value:.4f} ÷ "
        f"{definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


@dataclass(frozen=True, slots=True)
class HolderChange:
    """Balance change of the addresses of one class present in two top-100 snapshots."""

    now: Snapshot
    then: Snapshot
    actor_class: str
    considered: int
    matched: int
    entered: int
    left: int
    balance_then: Decimal
    balance_now: Decimal

    @property
    def change(self) -> Decimal:
        return self.balance_now - self.balance_then

    @property
    def change_pct(self) -> Decimal | None:
        return None if self.balance_then <= 0 else self.change / self.balance_then * 100


def pick_snapshots(
    snapshots: Sequence[Snapshot], as_of: datetime
) -> tuple[Snapshot | None, Snapshot | None]:
    """Latest snapshot by ``as_of`` and the latest one 7 days (± 1 day) before it."""
    visible = sorted((s for s in snapshots if s.time <= as_of), key=lambda s: s.time)
    if not visible:
        return None, None
    now = visible[-1]
    target = now.time - SNAPSHOT_GAP
    earlier = [
        s for s in visible if target - SNAPSHOT_TOLERANCE <= s.time <= target + SNAPSHOT_TOLERANCE
    ]
    then = min(earlier, key=lambda s: abs(s.time - target)) if earlier else None
    return now, then


def holder_change(now: Snapshot, then: Snapshot, actor_class: str) -> HolderChange:
    """Class membership is taken from the *earlier* snapshot (then), so addresses that grew into
    the list are not counted and addresses that left it are reported, never estimated."""
    before = {a for a, c in then.classes.items() if c == actor_class}
    after = {a for a, c in now.classes.items() if c == actor_class}
    matched = before & set(now.balances)
    return HolderChange(
        now=now,
        then=then,
        actor_class=actor_class,
        considered=len(before),
        matched=len(matched),
        entered=len(after - before),
        left=len(before - set(now.balances)),
        balance_then=sum((then.balances[a] for a in matched), Decimal(0)),
        balance_now=sum((now.balances[a] for a in matched), Decimal(0)),
    )


def large_holder_component(
    snapshots: Sequence[Snapshot], as_of: datetime, unit: str
) -> tuple[ComponentResult, HolderChange | None]:
    definition = DEFS["large_holders_7d"]
    result = ComponentResult(definition, "unavailable")
    now, then = pick_snapshots(snapshots, as_of)
    if now is None:
        result.reason = "no top-100 balance snapshot stored yet"
        return result, None
    result.window_end = now.time.date()
    if then is None:
        result.reason = (
            f"no snapshot 7 days (± 1 day) before the latest one ({now.time:%Y-%m-%d %H:%M} UTC):"
            " snapshots are recorded daily from the first run, there is no history"
        )
        return result, None
    change = holder_change(now, then, "unknown_large_holder")
    result.window_start = then.time.date()
    result.days_expected, result.days_present = change.considered, change.matched
    result.inputs = {
        "snapshot_then": then.time.isoformat(),
        "snapshot_now": now.time.isoformat(),
        "addresses_then": change.considered,
        "still_listed": change.matched,
        "left_top_100": change.left,
        "entered_top_100": change.entered,
        f"balance_then_{unit}": format(change.balance_then, "f"),
        f"balance_now_{unit}": format(change.balance_now, "f"),
    }
    if change.considered == 0:
        result.reason = "no unknown large holders in the earlier snapshot"
        return result, change
    share = Decimal(change.matched) / Decimal(change.considered)
    if share < MIN_HOLDER_MATCH or change.balance_then <= 0:
        result.reason = (
            f"only {change.matched} of {change.considered} addresses are still in the top 100 "
            f"(minimum {MIN_HOLDER_MATCH:.0%})"
        )
        return result, change
    pct = change.change_pct
    assert pct is not None  # noqa: S101
    assert definition.scale is not None  # noqa: S101
    result.status = "ok"
    result.value = _num(pct)
    result.sub_score = _num(_clip(pct / definition.scale))
    result.calculation = (
        f"{change.matched} unknown large holders listed on {then.time:%Y-%m-%d} and now: "
        f"({change.balance_now:,.2f} − {change.balance_then:,.2f}) {unit.upper()} ÷ "
        f"{change.balance_then:,.2f} × 100 = {result.value:+.4f} %; sub-score = "
        f"clip({result.value:.4f} ÷ {definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result, change


def revived_component(revived: Series, end: date, asset: str) -> ComponentResult:
    definition = DEFS["revived_1y_7d"]
    result = ComponentResult(definition, "unavailable")
    if asset != "BTC":
        result.reason = f"coin-age data is tracked for Bitcoin only, not {asset}"
        return result
    recent = days(end, 7)
    baseline = days(end - timedelta(days=7), 90)
    got_recent = [revived[d] for d in recent if revived.get(d, _NONE).has_value]
    got_base = [revived[d] for d in baseline if revived.get(d, _NONE).has_value]
    _describe_window(result, recent, got_recent)
    result.window_start = baseline[0]
    result.days_expected = len(recent) + len(baseline)
    result.days_present = len(got_recent) + len(got_base)
    result.missing_days = [d for d in (*baseline, *recent) if not revived.get(d, _NONE).has_value]
    reason = _coverage_reason("last 7 days", recent, len(got_recent), MIN_COVERAGE) or (
        _coverage_reason("90-day baseline", baseline, len(got_base), MIN_COVERAGE)
    )
    if reason:
        result.reason = reason
        return result
    avg7 = sum((p.value or Decimal(0) for p in got_recent), Decimal(0)) / len(got_recent)
    avg90 = sum((p.value or Decimal(0) for p in got_base), Decimal(0)) / len(got_base)
    if avg90 <= 0:
        result.reason = "no coins ≥ 1 year old moved in the baseline period"
        return result
    assert definition.scale is not None  # noqa: S101
    ratio = avg7 / avg90
    result.status = "ok"
    result.value = _num(ratio)
    result.sub_score = _num(_clip(-(ratio - 1) / definition.scale))
    result.inputs = {
        "daily_average_7d_btc": format(_num(avg7, "0.00000001"), "f"),
        "daily_average_90d_btc": format(_num(avg90, "0.00000001"), "f"),
        "baseline_days_with_data": len(got_base),
    }
    result.calculation = (
        f"{avg7:,.2f} BTC/day ({recent[0]} … {recent[-1]}) ÷ {avg90:,.2f} BTC/day "
        f"({baseline[0]} … {baseline[-1]}, {len(got_base)} days) = {result.value:.4f}; "
        f"sub-score = clip(−({result.value:.4f} − 1) ÷ {definition.scale}, −1, +1) = "
        f"{result.sub_score:+.4f}"
    )
    return result


def combine(asset: str, as_of: datetime, components: list[ComponentResult]) -> ScoreResult:
    available = [c for c in components if c.status == "ok"]
    weight = sum((c.definition.weight for c in available), Decimal(0))
    if weight < MIN_AVAILABLE_WEIGHT:
        return ScoreResult(
            asset=asset,
            as_of=as_of,
            status="insufficient_data",
            score=None,
            band=None,
            available_weight=weight,
            components=components,
            reason=(
                f"Insufficient data: available components carry weight {weight} of 1.00 "
                f"(minimum {MIN_AVAILABLE_WEIGHT})."
            ),
        )
    total = Decimal(0)
    for c in available:
        assert c.sub_score is not None  # noqa: S101
        c.effective_weight = (c.definition.weight / weight).quantize(Decimal("0.0001"))
        c.contribution = (100 * c.definition.weight / weight * c.sub_score).quantize(
            Decimal("0.01")
        )
        total += c.definition.weight * c.sub_score
    score = (100 * total / weight).quantize(Decimal("0.1"))
    return ScoreResult(
        asset=asset,
        as_of=as_of,
        status="ok",
        score=score,
        band=band_for(score),
        available_weight=weight,
        components=components,
    )


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    asset: str
    unit: str
    as_of: datetime
    end: date
    inflow: Series
    outflow: Series
    exchange_supply: Series
    revived: Series
    snapshots: Sequence[Snapshot] = field(default=())


def compute_score(inputs: ScoreInputs) -> tuple[ScoreResult, HolderChange | None]:
    holders, change = large_holder_component(inputs.snapshots, inputs.as_of, inputs.unit)
    components = [
        exchange_netflow_component(
            inputs.inflow, inputs.outflow, inputs.exchange_supply, inputs.end, inputs.unit
        ),
        exchange_supply_component(inputs.exchange_supply, inputs.end, inputs.unit),
        holders,
        revived_component(inputs.revived, inputs.end, inputs.asset),
    ]
    return combine(inputs.asset, inputs.as_of, components), change


# ---------------------------------------------------------------------------- other metrics


@dataclass(frozen=True, slots=True)
class RatioResult:
    status: Literal["ok", "unavailable"]
    value: Decimal | None
    numerator: Decimal | None
    denominator: Decimal | None
    window_start: date
    window_end: date
    days_present: int
    reason: str | None = None


def miner_spending_ratio(spent: Series, issuance: Series, end: date) -> RatioResult:
    """Σ coinbase-origin coins spent ÷ Σ new issuance over the last 7 days (both required on
    ≥ 90 % of the days). ≈ 1: newly mined coins move on as fast as they are created; above 1:
    older mined coins are moving too; below 1: mined coins are kept."""
    wanted = days(end, 7)
    both = [d for d in wanted if spent.get(d, _NONE).has_value and issuance.get(d, _NONE).has_value]
    if reason := _coverage_reason("spent and issuance", wanted, len(both), MIN_COVERAGE):
        return RatioResult(
            "unavailable", None, None, None, wanted[0], wanted[-1], len(both), reason
        )
    num = sum((spent[d].value or Decimal(0) for d in both), Decimal(0))
    den = sum((issuance[d].value or Decimal(0) for d in both), Decimal(0))
    if den <= 0:
        return RatioResult(
            "unavailable", None, num, den, wanted[0], wanted[-1], len(both), "no issuance"
        )
    return RatioResult("ok", _num(num / den), num, den, wanted[0], wanted[-1], len(both))


# ---------------------------------------------------------------------------- contradictions

Direction = Literal["accumulation", "distribution", "neutral", "unknown"]
ContradictionStatus = Literal[
    "contradiction", "consistent", "no_clear_direction", "insufficient_data"
]


@dataclass(frozen=True, slots=True)
class Reading:
    label: str
    value: Decimal | None
    unit: str
    direction: Direction
    source: str


@dataclass(frozen=True, slots=True)
class Contradiction:
    indicator_id: str
    label: str
    status: ContradictionStatus
    explanation: str
    readings: tuple[Reading, Reading]


def direction_of(value: Decimal | None, threshold: Decimal) -> Direction:
    if value is None:
        return "unknown"
    if value >= threshold:
        return "accumulation"
    if value <= -threshold:
        return "distribution"
    return "neutral"


def compare(indicator_id: str, label: str, a: Reading, b: Reading, meaning: str) -> Contradiction:
    if "unknown" in (a.direction, b.direction):
        missing = " and ".join(r.label for r in (a, b) if r.direction == "unknown")
        return Contradiction(
            indicator_id, label, "insufficient_data", f"Insufficient data: {missing}.", (a, b)
        )
    if "neutral" in (a.direction, b.direction):
        return Contradiction(
            indicator_id,
            label,
            "no_clear_direction",
            "At least one side shows no clear direction; nothing to compare.",
            (a, b),
        )
    if a.direction == b.direction:
        return Contradiction(
            indicator_id, label, "consistent", f"Both point to {a.direction}.", (a, b)
        )
    return Contradiction(
        indicator_id,
        label,
        "contradiction",
        f"{a.label} points to {a.direction}, {b.label} to {b.direction}. {meaning}",
        (a, b),
    )


def component_reading(c: ComponentResult, source: str) -> Reading:
    return Reading(
        c.definition.label,
        c.sub_score if c.status == "ok" else None,
        "sub-score",
        direction_of(c.sub_score if c.status == "ok" else None, DIRECTION_THRESHOLD),
        source,
    )


def contradictions(
    score: ScoreResult,
    *,
    institutional_score: Decimal | None,
    institutional_status: str,
    richlist_exchange_change_pct: Decimal | None,
    coinmetrics_exchange_change_pct: Decimal | None,
) -> list[Contradiction]:
    by_id = {c.definition.component_id: c for c in score.components}
    netflow = component_reading(by_id["exchange_netflow_7d"], "Coin Metrics")
    out = [
        compare(
            "exchange_flows_vs_old_coins",
            "Exchange flows vs old coins moving",
            netflow,
            component_reading(by_id["revived_1y_7d"], "Blockchair"),
            "Coins leave exchanges while long-dormant coins move (or the reverse): the two "
            "on-chain readings disagree.",
        ),
        compare(
            "exchange_flows_vs_large_holders",
            "Exchange flows vs unknown large holders",
            netflow,
            component_reading(by_id["large_holders_7d"], "Blockchair + labels"),
            "Exchange flows and the balances of large unlabelled addresses move in opposite "
            "directions (large holders may include unlabelled exchange or custody wallets).",
        ),
        compare(
            "whales_vs_etf",
            "Whale flow score vs Institutional Flow Score (ETF channel)",
            Reading(
                "Whale Flow Score",
                score.score,
                "score",
                direction_of(score.score, SCORE_DIRECTION),
                "this page",
            ),
            Reading(
                "Institutional Flow Score",
                institutional_score,
                "score",
                direction_of(
                    institutional_score if institutional_status == "ok" else None, SCORE_DIRECTION
                ),
                "Phase 6 (SoSoValue ETF flows, treasury purchases)",
            ),
            "On-chain behaviour and flows through institutional channels point different ways.",
        ),
        compare(
            "exchange_balances_two_sources",
            "Exchange balances: labelled top-100 addresses vs Coin Metrics",
            Reading(
                "Labelled exchange addresses in the top 100 (7 days)",
                richlist_exchange_change_pct,
                "%",
                direction_of(
                    None if richlist_exchange_change_pct is None else -richlist_exchange_change_pct,
                    SUPPLY_DIRECTION_PCT,
                ),
                "Blockchair + BitInfoCharts labels",
            ),
            Reading(
                "Coin Metrics exchange supply (same 7 days)",
                coinmetrics_exchange_change_pct,
                "%",
                direction_of(
                    None
                    if coinmetrics_exchange_change_pct is None
                    else -coinmetrics_exchange_change_pct,
                    SUPPLY_DIRECTION_PCT,
                ),
                "Coin Metrics",
            ),
            "The two sources cover different address sets; a disagreement means the labelled "
            "wallets moved against the wider exchange total.",
        ),
    ]
    return out


_NONE = DayValue(date.min, None)
