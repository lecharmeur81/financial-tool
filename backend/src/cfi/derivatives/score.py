"""Derivatives Health Score v1 (0 … 100; 100 = no sign of stress).

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — a deterministic
combination of calculated metrics with fixed, published parameters. Not a signal, not a forecast,
not a recommendation.

Every component is a **direction-neutral stress** reading between 0 (calm) and 1 (at or beyond
its reference scale). Direction is shown next to it as context, never scored: crowded longs and
crowded shorts, rising and falling leverage, contango and backwardation beyond their ranges all
count as stress, because each makes forced position changes more likely — not because they
point to a price direction.

1. stress = clip(metric ÷ reference scale, 0, 1). Reference scales are judgment parameters.
2. Health = 100 × (1 − Σ weight × stress ÷ Σ weights of available components).
3. A component without complete inputs is excluded (never filled). If the available components
   carry less than half of the total weight: "Insufficient data".
4. Derivatives stress = 100 − Health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from cfi.derivatives import metrics as m

SCORE_ID = "derivatives_health_score"
SCORE_VERSION = "v1"
MIN_AVAILABLE_WEIGHT = Decimal("0.5")
BASIS_BAND = (Decimal(0), Decimal("0.10"))  # annualised basis considered ordinary
# DVOL (ratio) mapped to stress 0 … 1 between these values, per asset.
DVOL_SCALES: dict[str, tuple[Decimal, Decimal]] = {
    "BTC": (Decimal("0.30"), Decimal("0.80")),
    "ETH": (Decimal("0.40"), Decimal("1.00")),
}

BANDS: tuple[tuple[Decimal | None, str], ...] = (
    (Decimal(75), "low stress"),
    (Decimal(50), "moderate stress"),
    (Decimal(25), "elevated stress"),
    (None, "high stress"),
)
BAND_NOTE = (
    "Bands (each includes its lower bound): 75 … 100 low stress; 50 … 75 moderate stress; "
    "25 … 50 elevated stress; 0 … 25 high stress. They describe positioning stress only, not "
    "price direction."
)

Status = Literal["ok", "unavailable", "not_applicable"]


@dataclass(frozen=True, slots=True)
class ComponentDef:
    component_id: str
    metric_id: str
    label: str
    weight: Decimal
    scale: str
    definition: str


COMPONENTS: tuple[ComponentDef, ...] = (
    ComponentDef(
        "funding",
        "funding_annualised_7d_abs.v1",
        "Funding pressure (7 days, annualised)",
        Decimal("0.25"),
        "|funding| = 30 % a year → stress 1",
        "Σ funding rates settled over the last 7 days × 365 ÷ 7, per venue, open-interest "
        "weighted across Binance and OKX. Stress = |value| ÷ 30 %. Positive or negative funding "
        "count alike: either side paying heavily means crowded positioning.",
    ),
    ComponentDef(
        "basis",
        "futures_basis_annualised_outside_band.v1",
        "Futures basis outside its ordinary range",
        Decimal("0.15"),
        "15 % a year outside 0 … 10 % → stress 1",
        "Annualised premium of the Deribit future closest to 90 days (≥ 14 days) over the index. "
        "Stress = distance outside 0 … 10 % a year ÷ 15 %. BTC and ETH only.",
    ),
    ComponentDef(
        "leverage",
        "leverage_ratio_change_7d_abs.v1",
        "Leverage change (7 days)",
        Decimal("0.20"),
        "|change| = 20 % → stress 1",
        "Open interest (coins × Coinbase USD price) ÷ market capitalisation, now vs 7 days "
        "earlier, venues with both values. Stress = |relative change| ÷ 20 %. Building and "
        "unwinding leverage count alike.",
    ),
    ComponentDef(
        "liquidations",
        "liquidations_24h_pct_oi.v1",
        "Liquidations, last 24 hours",
        Decimal("0.20"),
        "1 % of open interest → stress 1",
        "Long + short positions liquidated on the OKX perpetual over the last 24 complete hours "
        "÷ OKX open interest (both in coins). Stress = share ÷ 1 %. One venue only.",
    ),
    ComponentDef(
        "volatility",
        "dvol_level.v1",
        "Implied volatility (DVOL)",
        Decimal("0.20"),
        "BTC 30 % → 0, 80 % → 1; ETH 40 % → 0, 100 % → 1",
        "Deribit DVOL (30-day implied volatility) mapped linearly between the asset's calm and "
        "stressed levels. BTC and ETH only.",
    ),
)
DEFS: dict[str, ComponentDef] = {c.component_id: c for c in COMPONENTS}


@dataclass(slots=True)
class ComponentResult:
    definition: ComponentDef
    status: Status
    reason: str | None = None
    value: Decimal | None = None
    value_unit: str = ""
    stress: Decimal | None = None
    effective_weight: Decimal | None = None
    contribution: Decimal | None = None
    calculation: str = ""
    context: str | None = None
    inputs: dict[str, str | None] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreResult:
    asset: str
    as_of: datetime
    status: Literal["ok", "insufficient_data"]
    health: Decimal | None
    stress: Decimal | None
    band: str | None
    available_weight: Decimal
    components: list[ComponentResult]
    reason: str | None = None


def _clip01(x: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), x))


def _q(x: Decimal, places: str = "0.0001") -> Decimal:
    return x.quantize(Decimal(places))


def _pct(x: Decimal) -> str:
    return f"{x * 100:+.2f} %"


def band_for(health: Decimal) -> str:
    for lower, label in BANDS:
        if lower is None or health >= lower:
            return label
    raise AssertionError("unreachable")  # pragma: no cover


def funding_component(f: m.Funding) -> ComponentResult:
    r = ComponentResult(DEFS["funding"], "unavailable", value_unit="% a year")
    r.inputs = {
        f"{v.venue}_annualised_7d": (
            None if v.annualised_7d is None else format(v.annualised_7d, "f")
        )
        for v in f.venues
    }
    if f.annualised_7d is None:
        reasons = "; ".join(f"{v.venue}: {v.reason}" for v in f.venues if v.reason)
        r.reason = reasons or "no funding data"
        return r
    value = f.annualised_7d
    r.status, r.value = "ok", _q(value * 100, "0.01")
    r.stress = _q(_clip01(abs(value) / m.FUNDING_EXTREME))
    r.context = f.direction
    r.calculation = (
        f"{f.weighting}: {_pct(value)} a year; stress = clip(|{value * 100:.2f} %| ÷ 30 %, 0, 1) "
        f"= {r.stress}"
    )
    return r


def basis_component(b: m.Basis | None) -> ComponentResult:
    r = ComponentResult(DEFS["basis"], "unavailable", value_unit="% a year")
    if b is None:
        r.status, r.reason = "not_applicable", "no Deribit futures for this asset"
        return r
    if b.headline is None or b.headline.annualised is None:
        r.reason = b.reason or "no headline future"
        return r
    value = b.headline.annualised
    low, high = BASIS_BAND
    outside = max(Decimal(0), low - value, value - high)
    r.status, r.value = "ok", _q(value * 100, "0.01")
    r.stress = _q(_clip01(outside / Decimal("0.15")))
    r.context = (
        f"{b.shape}: {b.headline.instrument} trades "
        + ("above" if value > 0 else "below" if value < 0 else "at")
        + " the index"
    )
    r.inputs = {
        "instrument": b.headline.instrument,
        "days_to_expiry": format(_q(b.headline.days or Decimal(0), "0.01"), "f"),
        "mark": format(b.headline.mark, "f"),
        "index": format(b.headline.index, "f"),
        "snapshot": None if b.snapshot is None else b.snapshot.isoformat(),
    }
    r.calculation = (
        f"({b.headline.mark} ÷ {b.headline.index} − 1) × 365 ÷ "
        f"{_q(b.headline.days or Decimal(0), '0.01')} days = {_pct(value)} a year; outside 0 … "
        f"10 % by {outside * 100:.2f} points; stress = clip({outside * 100:.2f} ÷ 15, 0, 1) = "
        f"{r.stress}"
    )
    return r


def leverage_component(lev: m.Leverage) -> ComponentResult:
    r = ComponentResult(DEFS["leverage"], "unavailable", value_unit="% (7 d)")
    r.inputs = dict(lev.inputs)
    if lev.change_7d is None:
        r.reason = lev.reason or "leverage change unavailable"
        return r
    value = lev.change_7d
    r.status, r.value = "ok", _q(value * 100, "0.01")
    r.stress = _q(_clip01(abs(value) / Decimal("0.20")))
    r.context = {
        "expansion": "leverage building (open interest growing faster than market value)",
        "reduction": "leverage unwinding (open interest shrinking relative to market value)",
        "stable": "leverage roughly unchanged",
    }.get(lev.condition)
    assert lev.ratio_now is not None  # noqa: S101 — set whenever change is
    assert lev.ratio_week_ago is not None  # noqa: S101
    r.calculation = (
        f"OI ÷ market cap {lev.ratio_now * 100:.4f} % now vs {lev.ratio_week_ago * 100:.4f} % "
        f"7 days earlier ({', '.join(lev.venues)}) → {_pct(value)}; stress = clip(|"
        f"{value * 100:.2f} %| ÷ 20 %, 0, 1) = {r.stress}"
    )
    return r


def liquidation_component(liq: m.Liquidations) -> ComponentResult:
    r = ComponentResult(DEFS["liquidations"], "unavailable", value_unit="% of OI (24 h)")
    r.inputs = {
        "long_24h": None if liq.long_24h is None else format(liq.long_24h, "f"),
        "short_24h": None if liq.short_24h is None else format(liq.short_24h, "f"),
        "open_interest": None if liq.open_interest is None else format(liq.open_interest, "f"),
        "hours_present": str(liq.hours_present),
    }
    if liq.share_of_oi is None or liq.total_24h is None:
        r.reason = liq.reason or "liquidation totals unavailable"
        return r
    value = liq.share_of_oi
    r.status, r.value = "ok", _q(value * 100, "0.0001")
    r.stress = _q(_clip01(value / Decimal("0.01")))
    if liq.long_share is not None:
        r.context = (
            f"{liq.long_share * 100:.0f} % of liquidated size was long positions, "
            f"{(1 - liq.long_share) * 100:.0f} % short positions"
        )
    r.calculation = (
        f"{liq.total_24h} liquidated ÷ {liq.open_interest} open interest = "
        f"{value * 100:.4f} %; stress = clip({value * 100:.4f} ÷ 1, 0, 1) = {r.stress}"
    )
    return r


def volatility_component(asset: str, dvol: m.Point | None, applicable: bool) -> ComponentResult:
    r = ComponentResult(DEFS["volatility"], "unavailable", value_unit="% (annualised)")
    if not applicable or asset not in DVOL_SCALES:
        r.status, r.reason = "not_applicable", "no DVOL index for this asset"
        return r
    if dvol is None or dvol.value is None:
        r.reason = "no recent DVOL value"
        return r
    calm, stressed = DVOL_SCALES[asset]
    r.status, r.value = "ok", _q(dvol.value * 100, "0.01")
    r.stress = _q(_clip01((dvol.value - calm) / (stressed - calm)))
    r.inputs = {"dvol": format(dvol.value, "f"), "hour": dvol.time.isoformat()}
    r.calculation = (
        f"DVOL {dvol.value * 100:.2f} %; stress = clip(({dvol.value * 100:.2f} − "
        f"{calm * 100:.0f}) ÷ ({stressed * 100:.0f} − {calm * 100:.0f}), 0, 1) = {r.stress}"
    )
    return r


def compute(asset: str, as_of: datetime, components: list[ComponentResult]) -> ScoreResult:
    ok = [c for c in components if c.status == "ok" and c.stress is not None]
    applicable = [c for c in components if c.status != "not_applicable"]
    total = sum((c.definition.weight for c in applicable), Decimal(0))
    weight = sum((c.definition.weight for c in ok), Decimal(0))
    if not ok or weight < MIN_AVAILABLE_WEIGHT:
        missing = ", ".join(c.definition.label for c in applicable if c not in ok)
        return ScoreResult(
            asset,
            as_of,
            "insufficient_data",
            None,
            None,
            None,
            weight,
            components,
            f"Insufficient data: available components carry weight {weight} (minimum "
            f"{MIN_AVAILABLE_WEIGHT}); missing: {missing or 'all'}",
        )
    weighted = Decimal(0)
    for c in ok:
        assert c.stress is not None  # noqa: S101
        c.effective_weight = _q(c.definition.weight / weight)
        c.contribution = _q(c.definition.weight * c.stress / weight * 100, "0.01")
        weighted += c.definition.weight * c.stress
    stress = _q(weighted / weight * 100, "0.1")
    health = _q(Decimal(100) - stress, "0.1")
    note = None
    if weight < total:
        note = f"Computed from components carrying weight {weight} of {total}"
    band = band_for(health)
    return ScoreResult(asset, as_of, "ok", health, stress, band, weight, components, note)


def definition() -> dict[str, object]:
    return {
        "score_id": SCORE_ID,
        "version": SCORE_VERSION,
        "evidence_category": "Calculated Metric",
        "range": "0 … 100 (100 = no sign of stress); derivatives stress = 100 − health",
        "method": [
            "Each component is a direction-neutral stress between 0 and 1: its metric divided "
            "by a published reference scale, capped.",
            "Health = 100 × (1 − Σ weight × stress ÷ Σ weights of available components).",
            "Components without complete inputs are excluded, never filled; below half of the "
            "total weight the score is 'Insufficient data'.",
            "Direction (who pays funding, contango or backwardation, long or short "
            "liquidations) is shown as context and never scored.",
        ],
        "components": [
            {
                "component_id": c.component_id,
                "metric_id": c.metric_id,
                "label": c.label,
                "weight": str(c.weight),
                "scale": c.scale,
                "definition": c.definition,
            }
            for c in COMPONENTS
        ],
        "bands": BAND_NOTE,
        "min_available_weight": str(MIN_AVAILABLE_WEIGHT),
        "parameters_note": "Reference scales and weights are judgment parameters chosen by "
        "design, not fitted to data; to be reviewed against history once enough is stored.",
    }
