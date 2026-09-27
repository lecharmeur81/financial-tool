"""Derivatives Health Score (0 … 100; 100 = no sign of stress).

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

Weights, reference scales, band boundaries and the minimum-available-weight cutoff are not
hard-coded here: they are loaded from a versioned, immutable parameter set (``score_parameters``
— see that module's docstring for why, and how a future v2 would be published). Every function
below defaults to the current version so existing call sites are unaffected; pass ``params``
explicitly to score against a different (e.g. historical) version.

**Higher Health Score means lower measured derivatives stress across the available components.
It is not a probability of price increase and does not indicate market direction.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from cfi.core.time import utc_now
from cfi.derivatives import metrics as m
from cfi.derivatives import score_parameters as sp

SCORE_ID = "derivatives_health_score"
#: Kept in sync with the parameter set the score is currently computed against (R3: a version
#: identifies exactly one set of parameters, forever — see score_parameters.py).
SCORE_VERSION = sp.CURRENT_VERSION

Status = Literal["ok", "unavailable", "not_applicable"]


@dataclass(frozen=True, slots=True)
class ComponentDef:
    component_id: str
    metric_id: str
    label: str
    weight: Decimal
    scale: str
    definition: str


def _components(params: sp.ParameterSet) -> tuple[ComponentDef, ...]:
    """Build the component catalog's descriptive metadata from a parameter set, so the human-
    readable ``scale``/``definition`` text never drifts from the numbers actually used."""
    low, high = params.basis_band
    btc_calm, btc_stressed = params.dvol_scales["BTC"]
    eth_calm, eth_stressed = params.dvol_scales["ETH"]
    return (
        ComponentDef(
            "funding",
            "funding_annualised_7d_abs.v1",
            "Funding pressure (7 days, annualised)",
            params.weight_funding,
            f"|funding| = {params.funding_scale * 100:.0f} % a year → stress 1",
            "Σ funding rates settled over the last 7 days × 365 ÷ 7, per venue, open-interest "
            "weighted across Binance and OKX. Stress = |value| ÷ "
            f"{params.funding_scale * 100:.0f} %. Positive or negative funding count alike: "
            "either side paying heavily means crowded positioning.",
        ),
        ComponentDef(
            "basis",
            "futures_basis_annualised_outside_band.v1",
            "Futures basis outside its ordinary range",
            params.weight_basis,
            f"{params.basis_scale * 100:.0f} % a year outside {low * 100:.0f} … {high * 100:.0f} "
            "% → stress 1",
            "Annualised premium of the Deribit future closest to 90 days (≥ 14 days) over the "
            f"index. Stress = distance outside {low * 100:.0f} … {high * 100:.0f} % a year ÷ "
            f"{params.basis_scale * 100:.0f} %. BTC and ETH only.",
        ),
        ComponentDef(
            "leverage",
            "leverage_ratio_change_7d_abs.v1",
            "Leverage change (7 days)",
            params.weight_leverage,
            f"|change| = {params.leverage_scale * 100:.0f} % → stress 1",
            "Open interest (coins × Coinbase USD price) ÷ market capitalisation, now vs 7 days "
            f"earlier, venues with both values. Stress = |relative change| ÷ "
            f"{params.leverage_scale * 100:.0f} %. Building and unwinding leverage count alike.",
        ),
        ComponentDef(
            "liquidations",
            "liquidations_24h_pct_oi.v1",
            "Liquidations, last 24 hours",
            params.weight_liquidations,
            f"{params.liquidation_scale * 100:.0f} % of open interest → stress 1",
            "Long + short positions liquidated on the OKX perpetual over the last 24 complete "
            "hours ÷ OKX open interest (both in coins). Stress = share ÷ "
            f"{params.liquidation_scale * 100:.0f} %. One venue only.",
        ),
        ComponentDef(
            "volatility",
            "dvol_level.v1",
            "Implied volatility (DVOL)",
            params.weight_volatility,
            f"BTC {btc_calm * 100:.0f} % → 0, {btc_stressed * 100:.0f} % → 1; "
            f"ETH {eth_calm * 100:.0f} % → 0, {eth_stressed * 100:.0f} % → 1",
            "Deribit DVOL (30-day implied volatility) mapped linearly between the asset's calm "
            "and stressed levels. BTC and ETH only.",
        ),
    )


COMPONENTS: tuple[ComponentDef, ...] = _components(sp.parameters())
DEFS: dict[str, ComponentDef] = {c.component_id: c for c in COMPONENTS}

BAND_NOTE = (
    "Bands (each includes its lower bound): 75 … 100 low stress; 50 … 75 moderate stress; "
    "25 … 50 elevated stress; 0 … 25 high stress. They describe positioning stress only, not "
    "price direction."
)
SEMANTIC_NOTE = (
    "Higher Derivatives Health Score means lower measured derivatives stress across the "
    "available components. It is not a probability of price increase and does not indicate "
    "market direction."
)

#: RED_TEAM_REPORT.md finding #9 / ADR-0064: unlike the funding-rate component, which correctly
#: OI-weights across every venue with available data, the liquidation-stress component reads OKX
#: exclusively — a single venue's outage or an idiosyncratic liquidation cascade fully determines
#: this 20%-weighted component with no cross-venue smoothing. Flagged at read time on every "ok"
#: reading (not silently treated as equally reliable as the multi-venue components beside it),
#: rather than down-weighted, since down-weighting would itself need a documented, versioned
#: magnitude — a bigger change than this phase's scope; see DECISIONS.md ADR-0064.
SINGLE_VENUE_CAVEAT = (
    "Liquidation totals are sourced from OKX only (single-venue), unlike funding, which is "
    "OI-weighted across every venue with available data — treat this component's reading with "
    "lower confidence than the others, especially around an OKX-specific outage or cascade."
)

#: RED_TEAM_REPORT.md finding #7 / ADR-0064: cfi.retail's Retail Speculation Score derives 0.40 of
#: its own weight (funding_rate_bias) from this same underlying Binance funding-rate data (25% of
#: this score). A "retail vs. derivatives" divergence is not fully independent for that shared
#: portion.
DERIVATIVES_SHARED_INPUT_NOTE = (
    "25% of this score (the funding component) is sourced from the same underlying Binance "
    "funding-rate data that also drives 40% of the Retail Speculation Score's weight. A divergence "
    "comparison between Retail Speculation and this score is not fully independent for that "
    "shared portion."
)


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
    #: The parameter version this result was actually scored against (R3 — reproducibility:
    #: never inferred from the module's current default, always the one used).
    parameter_version: str = SCORE_VERSION
    #: Wall-clock time this result was computed (distinct from ``as_of``, the point-in-time
    #: market snapshot the inputs describe).
    calculated_at: datetime = field(default_factory=utc_now)
    shared_input_note: str = DERIVATIVES_SHARED_INPUT_NOTE


def _clip01(x: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), x))


def _q(x: Decimal, places: str = "0.0001") -> Decimal:
    return x.quantize(Decimal(places))


def _pct(x: Decimal) -> str:
    return f"{x * 100:+.2f} %"


def band_for(health: Decimal, params: sp.ParameterSet | None = None) -> str:
    bands = (params or sp.parameters()).bands
    for lower, label in bands:
        if lower is None or health >= lower:
            return label
    raise AssertionError("unreachable")  # pragma: no cover


def funding_component(f: m.Funding, params: sp.ParameterSet | None = None) -> ComponentResult:
    params = params or sp.parameters()
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
    r.stress = _q(_clip01(abs(value) / params.funding_scale))
    r.context = f.direction
    r.calculation = (
        f"{f.weighting}: {_pct(value)} a year; stress = clip(|{value * 100:.2f} %| ÷ "
        f"{params.funding_scale * 100:.0f} %, 0, 1) = {r.stress}"
    )
    return r


def basis_component(b: m.Basis | None, params: sp.ParameterSet | None = None) -> ComponentResult:
    params = params or sp.parameters()
    r = ComponentResult(DEFS["basis"], "unavailable", value_unit="% a year")
    if b is None:
        r.status, r.reason = "not_applicable", "no Deribit futures for this asset"
        return r
    if b.headline is None or b.headline.annualised is None:
        r.reason = b.reason or "no headline future"
        return r
    value = b.headline.annualised
    low, high = params.basis_band
    outside = max(Decimal(0), low - value, value - high)
    r.status, r.value = "ok", _q(value * 100, "0.01")
    r.stress = _q(_clip01(outside / params.basis_scale))
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
        f"{_q(b.headline.days or Decimal(0), '0.01')} days = {_pct(value)} a year; outside "
        f"{low * 100:.0f} … {high * 100:.0f} % by {outside * 100:.2f} points; stress = clip("
        f"{outside * 100:.2f} ÷ {params.basis_scale * 100:.0f}, 0, 1) = {r.stress}"
    )
    return r


def leverage_component(lev: m.Leverage, params: sp.ParameterSet | None = None) -> ComponentResult:
    params = params or sp.parameters()
    r = ComponentResult(DEFS["leverage"], "unavailable", value_unit="% (7 d)")
    r.inputs = dict(lev.inputs)
    if lev.change_7d is None:
        r.reason = lev.reason or "leverage change unavailable"
        return r
    value = lev.change_7d
    r.status, r.value = "ok", _q(value * 100, "0.01")
    r.stress = _q(_clip01(abs(value) / params.leverage_scale))
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
        f"{value * 100:.2f} %| ÷ {params.leverage_scale * 100:.0f} %, 0, 1) = {r.stress}"
    )
    return r


def liquidation_component(
    liq: m.Liquidations, params: sp.ParameterSet | None = None
) -> ComponentResult:
    params = params or sp.parameters()
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
    r.stress = _q(_clip01(value / params.liquidation_scale))
    if liq.long_share is not None:
        r.context = (
            f"{liq.long_share * 100:.0f} % of liquidated size was long positions, "
            f"{(1 - liq.long_share) * 100:.0f} % short positions. {SINGLE_VENUE_CAVEAT}"
        )
    else:
        r.context = SINGLE_VENUE_CAVEAT
    r.calculation = (
        f"{liq.total_24h} liquidated ÷ {liq.open_interest} open interest = "
        f"{value * 100:.4f} %; stress = clip({value * 100:.4f} ÷ "
        f"{params.liquidation_scale * 100:.0f}, 0, 1) = {r.stress}"
    )
    return r


def volatility_component(
    asset: str, dvol: m.Point | None, applicable: bool, params: sp.ParameterSet | None = None
) -> ComponentResult:
    params = params or sp.parameters()
    r = ComponentResult(DEFS["volatility"], "unavailable", value_unit="% (annualised)")
    if not applicable or asset not in params.dvol_scales:
        r.status, r.reason = "not_applicable", "no DVOL index for this asset"
        return r
    if dvol is None or dvol.value is None:
        r.reason = "no recent DVOL value"
        return r
    calm, stressed = params.dvol_scales[asset]
    r.status, r.value = "ok", _q(dvol.value * 100, "0.01")
    r.stress = _q(_clip01((dvol.value - calm) / (stressed - calm)))
    r.inputs = {"dvol": format(dvol.value, "f"), "hour": dvol.time.isoformat()}
    r.calculation = (
        f"DVOL {dvol.value * 100:.2f} %; stress = clip(({dvol.value * 100:.2f} − "
        f"{calm * 100:.0f}) ÷ ({stressed * 100:.0f} − {calm * 100:.0f}), 0, 1) = {r.stress}"
    )
    return r


def compute(
    asset: str,
    as_of: datetime,
    components: list[ComponentResult],
    params: sp.ParameterSet | None = None,
) -> ScoreResult:
    params = params or sp.parameters()
    ok = [c for c in components if c.status == "ok" and c.stress is not None]
    applicable = [c for c in components if c.status != "not_applicable"]
    total = sum((c.definition.weight for c in applicable), Decimal(0))
    weight = sum((c.definition.weight for c in ok), Decimal(0))
    if not ok or weight < params.min_available_weight:
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
            f"{params.min_available_weight}); missing: {missing or 'all'}",
            parameter_version=params.version,
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
    band = band_for(health, params)
    return ScoreResult(
        asset,
        as_of,
        "ok",
        health,
        stress,
        band,
        weight,
        components,
        note,
        parameter_version=params.version,
    )


def definition(params: sp.ParameterSet | None = None) -> dict[str, object]:
    params = params or sp.parameters()
    components = _components(params) if params.version != SCORE_VERSION else COMPONENTS
    return {
        "score_id": SCORE_ID,
        "version": params.version,
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
            for c in components
        ],
        "bands": BAND_NOTE,
        "min_available_weight": str(params.min_available_weight),
        "semantic_note": SEMANTIC_NOTE,
        "parameters_note": "Reference scales and weights are v1 methodology / initial "
        "parameters chosen by design, not fitted to data or empirically validated; to be "
        "reviewed against history once enough is stored (Phases 15-16). A future change "
        "publishes a new version id rather than editing this one, so past scores stay "
        "reproducible (see score_parameters.py).",
    }
