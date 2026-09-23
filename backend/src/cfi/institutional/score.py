"""Institutional Flow Score v1 — a transparent composite of published component metrics.

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — a deterministic
calculation over observed data with fixed, published parameters. It is not a statistical signal
(it is not compared with its own history), not a prediction and not a recommendation.

What it measures: the direction and relative size of recent flows through *institutional
channels* — US spot ETFs (creations/redemptions) and, for bitcoin, listed-company treasuries.
ETF share buyers include retail investors; the score describes the channel, not the investors.

Method (every number is shown to the user):

1. Each component metric is computed from point-in-time data (``available_at <= as_of``).
2. Sub-score = metric ÷ reference scale, capped to [-1, +1] (the breadth component is already in
   [-1, +1]). Reference scales are **judgment parameters chosen by design**, not fitted to data:
   e.g. a 5-day net flow of 1 % of ETF net assets counts as the full +1.
3. Score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components), range −100 … +100.
4. A component whose inputs cover less than 90 % of its window is excluded (never filled). If the
   available components carry less than half the total weight, the score is
   "Insufficient data".

Bands are descriptive labels of the flow direction, not advice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.time import ensure_utc
from cfi.institutional.aggregation import DailyPoint, trading_window

SCORE_ID = "institutional_flow_score"
SCORE_VERSION = "v1"
MIN_COVERAGE = Decimal("0.9")
MIN_AVAILABLE_WEIGHT = Decimal("0.5")
TREASURY_WINDOW_DAYS = 30
FLAGGED = ("suspect", "conflicting")

# (lower bound inclusive, label); the last band catches everything below.
BANDS: tuple[tuple[Decimal | None, str], ...] = (
    (Decimal(50), "strong net inflow"),
    (Decimal(15), "net inflow"),
    (Decimal(-15), "balanced"),
    (Decimal(-50), "net outflow"),
    (None, "strong net outflow"),
)
BAND_NOTE = (
    "Bands (each includes its lower bound): +50 … +100 strong net inflow; +15 … +50 net inflow; "
    "−15 … +15 balanced; −50 … −15 net outflow; −100 … below −50 strong net outflow. "
    "They describe flow direction only."
)

ComponentStatus = Literal["ok", "unavailable"]


@dataclass(frozen=True, slots=True)
class ComponentDef:
    component_id: str
    metric_id: str
    label: str
    weight: Decimal
    scale: Decimal | None  # metric value at which the sub-score reaches ±1; None = already ±1
    unit: str
    definition: str
    evidence: str


COMPONENTS: tuple[ComponentDef, ...] = (
    ComponentDef(
        "etf_flow_5d",
        "etf_net_flow_5d_pct_aum.v1",
        "US spot ETF net flow, last 5 trading days",
        Decimal("0.35"),
        Decimal("1.0"),
        "% of ETF net assets",
        "Σ daily net flow (USD) over the last 5 US trading days ÷ total ETF net assets (USD) on "
        "the last day with data in the window × 100.",
        "Calculated metric from direct evidence (ETF creations/redemptions)",
    ),
    ComponentDef(
        "etf_flow_20d",
        "etf_net_flow_20d_pct_aum.v1",
        "US spot ETF net flow, last 20 trading days",
        Decimal("0.30"),
        Decimal("3.0"),
        "% of ETF net assets",
        "Σ daily net flow (USD) over the last 20 US trading days ÷ total ETF net assets (USD) on "
        "the last day with data in the window × 100.",
        "Calculated metric from direct evidence (ETF creations/redemptions)",
    ),
    ComponentDef(
        "etf_flow_breadth_10d",
        "etf_flow_day_balance_10d.v1",
        "Inflow days minus outflow days, last 10 trading days",
        Decimal("0.15"),
        None,
        "net share of days (−1 … +1)",
        "(days with net inflow − days with net outflow) ÷ days with data, over the last 10 US "
        "trading days. Days with exactly zero net flow count as neither.",
        "Calculated metric from direct evidence (ETF creations/redemptions)",
    ),
    ComponentDef(
        "treasury_net_acq_30d",
        "treasury_net_acquisitions_30d_pct.v1",
        "Listed-company net BTC acquisitions, last 30 days",
        Decimal("0.20"),
        Decimal("2.0"),
        "% of reported company holdings",
        "Σ BTC acquired (net of sales) in purchases dated within the last 30 days and public by "
        "as_of ÷ Σ each tracked company's latest reported BTC holdings × 100.",
        "Calculated metric from attributed evidence (company disclosures compiled by the provider)",
    ),
)


@dataclass(frozen=True, slots=True)
class Purchase:
    day: date
    company: str
    flow_native: Decimal | None
    quality_status: str
    pit_reliability: str
    available_at_estimated: bool


@dataclass(slots=True)
class ComponentResult:
    definition: ComponentDef
    status: ComponentStatus
    reason: str | None = None
    value: Decimal | None = None
    sub_score: Decimal | None = None
    effective_weight: Decimal | None = None
    contribution: Decimal | None = None
    calculation: str = ""
    window_start: date | None = None
    window_end: date | None = None
    days_expected: int = 0
    days_present: int = 0
    missing_days: list[date] = field(default_factory=list)
    flagged: int = 0
    revised: int = 0
    backfilled: int = 0
    estimated_availability: int = 0
    latest_input: date | None = None
    inputs: dict[str, str | int | None] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreResult:
    asset: str
    as_of: datetime
    status: Literal["ok", "insufficient_data"]
    score: Decimal | None
    band: str | None
    available_weight: Decimal
    components: list[ComponentResult]
    reason: str | None = None


def usd(value: Decimal) -> str:
    """Human-readable USD amount in millions, e.g. ``$1,234.5M`` / ``−$12.0M``."""
    millions = value / Decimal(1_000_000)
    sign = "−" if millions < 0 else ""
    return f"{sign}${abs(millions):,.1f}M"


def _clip(x: Decimal) -> Decimal:
    return max(Decimal(-1), min(Decimal(1), x))


def band_for(score: Decimal) -> str:
    for lower, label in BANDS:
        if lower is None or score >= lower:
            return label
    raise AssertionError("unreachable")  # pragma: no cover


def window_end_day(points: Sequence[DailyPoint], due_until: date, as_of: datetime) -> date:
    """ETF windows end at the later of the last day due by ``as_of`` and the last day already
    received (native data often arrives before the conservative due time)."""
    as_of_day = ensure_utc(as_of).date()
    received = [p.day for p in points if p.has_value and p.day <= as_of_day]
    return max([due_until, *received])


def _etf_window(
    definition: ComponentDef, points: Sequence[DailyPoint], end_day: date, days: int
) -> tuple[ComponentResult, list[DailyPoint]]:
    window = trading_window(end_day, days)
    by_day = {p.day: p for p in points}
    present = [by_day[d] for d in window if d in by_day and by_day[d].has_value]
    result = ComponentResult(
        definition,
        "unavailable",
        window_start=window[0],
        window_end=window[-1],
        days_expected=days,
        days_present=len(present),
        missing_days=[d for d in window if d not in {p.day for p in present}],
        flagged=sum(p.quality_status in FLAGGED for p in present),
        revised=sum(p.revision > 0 for p in present),
        backfilled=sum(p.pit_reliability == "backfilled_latest" for p in present),
        estimated_availability=sum(p.available_at_estimated for p in present),
        latest_input=present[-1].day if present else None,
    )
    if not present:
        result.reason = f"no ETF data for the {days} trading days {window[0]} … {window[-1]}"
    elif Decimal(len(present)) / Decimal(days) < MIN_COVERAGE:
        result.reason = (
            f"only {len(present)} of {days} trading days have data "
            f"(minimum {MIN_COVERAGE:.0%}); missing: "
            + ", ".join(d.isoformat() for d in result.missing_days)
        )
    return result, present


def etf_flow_component(
    definition: ComponentDef, points: Sequence[DailyPoint], end_day: date, days: int
) -> ComponentResult:
    result, present = _etf_window(definition, points, end_day, days)
    if result.reason is not None:
        return result
    total = sum((p.flow_usd for p in present if p.flow_usd is not None), Decimal(0))
    aum_point = next((p for p in reversed(present) if p.holdings_usd is not None), None)
    if aum_point is None or aum_point.holdings_usd is None or aum_point.holdings_usd <= 0:
        result.reason = "no positive ETF net assets reported in the window"
        return result
    aum = aum_point.holdings_usd
    assert definition.scale is not None  # noqa: S101 — flow components have a scale
    value = total / aum * 100
    sub = _clip(value / definition.scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.0001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.inputs = {
        "net_flow_usd": format(total, "f"),
        "net_assets_usd": format(aum, "f"),
        "net_assets_date": aum_point.day.isoformat(),
    }
    result.calculation = (
        f"{usd(total)} net flow over {len(present)} trading days "
        f"({result.window_start} … {result.window_end}) ÷ {usd(aum)} net assets on "
        f"{aum_point.day} × 100 = {result.value:.4f} %; sub-score = clip({result.value:.4f} ÷ "
        f"{definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def etf_breadth_component(
    definition: ComponentDef, points: Sequence[DailyPoint], end_day: date, days: int
) -> ComponentResult:
    result, present = _etf_window(definition, points, end_day, days)
    if result.reason is not None:
        return result
    inflow = sum(1 for p in present if p.flow_usd is not None and p.flow_usd > 0)
    outflow = sum(1 for p in present if p.flow_usd is not None and p.flow_usd < 0)
    value = Decimal(inflow - outflow) / Decimal(len(present))
    result.status = "ok"
    result.value = value.quantize(Decimal("0.0001"))
    result.sub_score = result.value
    result.inputs = {"inflow_days": inflow, "outflow_days": outflow, "days": len(present)}
    result.calculation = (
        f"({inflow} inflow days − {outflow} outflow days) ÷ {len(present)} days with data "
        f"({result.window_start} … {result.window_end}) = {result.value:+.4f}; "
        "sub-score = value (already within −1 … +1)"
    )
    return result


def treasury_component(
    definition: ComponentDef,
    asset: str,
    purchases: Sequence[Purchase],
    holdings: dict[str, Decimal],
    as_of: datetime,
) -> ComponentResult:
    as_of_day = ensure_utc(as_of).date()
    start = as_of_day - timedelta(days=TREASURY_WINDOW_DAYS - 1)
    result = ComponentResult(definition, "unavailable", window_start=start, window_end=as_of_day)
    if asset != "BTC":
        result.reason = (
            f"no dated listed-company purchase history for {asset} from a verified free source"
        )
        return result
    total_holdings = sum(holdings.values(), Decimal(0))
    if total_holdings <= 0:
        result.reason = "no listed-company BTC holdings known as of this time"
        return result
    in_window = [p for p in purchases if start <= p.day <= as_of_day and p.flow_native is not None]
    acquired = sum((p.flow_native for p in in_window if p.flow_native is not None), Decimal(0))
    value = acquired / total_holdings * 100
    assert definition.scale is not None  # noqa: S101
    result.status = "ok"
    result.value = value.quantize(Decimal("0.0001"))
    result.sub_score = _clip(value / definition.scale).quantize(Decimal("0.0001"))
    result.days_present = len(in_window)
    result.flagged = sum(p.quality_status in FLAGGED for p in in_window)
    result.backfilled = sum(p.pit_reliability == "backfilled_latest" for p in in_window)
    result.estimated_availability = sum(p.available_at_estimated for p in in_window)
    result.latest_input = max((p.day for p in in_window), default=None)
    result.inputs = {
        "btc_acquired_net": format(acquired, "f"),
        "purchase_events": len(in_window),
        "companies_with_purchases": len({p.company for p in in_window}),
        "companies_tracked": len(holdings),
        "reported_holdings_btc": format(total_holdings, "f"),
    }
    result.calculation = (
        f"{acquired:,} BTC acquired net in {len(in_window)} disclosed purchase(s) dated "
        f"{start} … {as_of_day} ÷ {total_holdings:,} BTC latest reported holdings of "
        f"{len(holdings)} companies × 100 = {result.value:.4f} %; sub-score = "
        f"clip({result.value:.4f} ÷ {definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def compute_score(
    *,
    asset: str,
    as_of: datetime,
    etf_points: Sequence[DailyPoint],
    due_until: date,
    purchases: Sequence[Purchase],
    holdings: dict[str, Decimal],
) -> ScoreResult:
    """The score for one asset from point-in-time inputs (already filtered by the caller)."""
    defs = {c.component_id: c for c in COMPONENTS}
    end_day = window_end_day(etf_points, due_until, as_of)
    components = [
        etf_flow_component(defs["etf_flow_5d"], etf_points, end_day, 5),
        etf_flow_component(defs["etf_flow_20d"], etf_points, end_day, 20),
        etf_breadth_component(defs["etf_flow_breadth_10d"], etf_points, end_day, 10),
        treasury_component(defs["treasury_net_acq_30d"], asset, purchases, holdings, as_of),
    ]
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
