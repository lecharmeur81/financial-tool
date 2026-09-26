"""Liquidity Score v1 — a transparent composite of published component metrics (Phase 9).

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — a deterministic
calculation over observed data with fixed, published parameters. It is not a statistical signal
(it is not compared with its own history), not a prediction and not a recommendation.

What it measures: the direction and relative size of recent change in the stablecoin supply this
platform tracks (USDT, USDC, and the total DefiLlama tracks) — a proxy for fiat-equivalent
liquidity sitting in the crypto-adjacent, exchange-ready pool. Rising stablecoin supply describes
more of that pool existing; it is not a probability of price increase and does not, by itself,
indicate market direction (R1). "Exchange liquidity changes" is deliberately **not** a scored
component — it is always unavailable (``liquidity/metrics.py:exchange_liquidity_change``) and is
shown separately, never folded into this score as a silent zero.

Method (every number is shown to the user), mirroring the Institutional Flow Score
(``cfi/institutional/score.py``) and the versioned-parameters pattern of the Derivatives Health
Score addendum (``cfi/derivatives/score_parameters.py``):

1. Each component is one already-computed metric result from ``liquidity/metrics.py``.
2. Sub-score = metric value ÷ reference scale, clipped to [-1, +1]. Reference scales are
   **judgment parameters chosen by design** (``score_parameters.py``), not fitted to data.
3. Score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components), range −100 … +100.
4. A component whose metric is "unavailable" is excluded (never filled with a default). If the
   available components carry less than the minimum available weight, the score is
   "Insufficient data".

Bands are descriptive labels of the direction of stablecoin-supply change, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

import cfi.liquidity.score_parameters as sp
from cfi.liquidity.metrics import GrowthAcceleration, SupplyGrowth

SCORE_ID = "liquidity_score"
SCORE_VERSION = sp.CURRENT_VERSION

SEMANTIC_NOTE = (
    "Higher Liquidity Score means stronger measured growth in the stablecoin supply this "
    "platform tracks (USDT, USDC, and DefiLlama's total). It is not a probability of price "
    "increase and does not indicate market direction."
)

ComponentStatus = Literal["ok", "unavailable"]


@dataclass(frozen=True, slots=True)
class ComponentDef:
    component_id: str
    label: str
    weight: Decimal
    scale: Decimal
    unit: str
    definition: str
    evidence: str


def _components(params: sp.ParameterSet) -> tuple[ComponentDef, ...]:
    """Component metadata generated from a parameter set, so text can't drift from numbers."""
    return (
        ComponentDef(
            "usdt_growth_7d",
            "USDT circulating supply growth, 7 days",
            params.weight_usdt_growth_7d,
            params.usdt_growth_scale,
            "ratio (7-day relative change)",
            "USDT circulating supply now ÷ USDT circulating supply 7 days earlier − 1.",
            "Calculated metric from direct evidence (DefiLlama daily circulating-supply snapshot)",
        ),
        ComponentDef(
            "usdc_growth_7d",
            "USDC circulating supply growth, 7 days",
            params.weight_usdc_growth_7d,
            params.usdc_growth_scale,
            "ratio (7-day relative change)",
            "USDC circulating supply now ÷ USDC circulating supply 7 days earlier − 1.",
            "Calculated metric from direct evidence (DefiLlama daily circulating-supply snapshot)",
        ),
        ComponentDef(
            "total_growth_7d",
            "Total stablecoin supply growth, 7 days",
            params.weight_total_growth_7d,
            params.total_growth_scale,
            "ratio (7-day relative change)",
            "Total circulating supply (every stablecoin DefiLlama tracks) now ÷ the same total 7 "
            "days earlier − 1.",
            "Calculated metric from direct evidence (DefiLlama daily circulating-supply snapshot)",
        ),
        ComponentDef(
            "growth_acceleration",
            "Total stablecoin supply growth acceleration",
            params.weight_acceleration,
            params.acceleration_scale,
            "percentage points (change in the 7-day growth rate)",
            "The 7-day growth rate of total stablecoin supply ending now, minus the 7-day growth "
            "rate ending 7 days earlier (a second derivative of supply).",
            "Calculated metric derived from direct evidence (DefiLlama daily circulating-supply "
            "snapshot)",
        ),
    )


COMPONENTS: tuple[ComponentDef, ...] = _components(sp.parameters())
DEFS: dict[str, ComponentDef] = {c.component_id: c for c in COMPONENTS}


def _clip(x: Decimal) -> Decimal:
    return max(Decimal(-1), min(Decimal(1), x))


def band_for(score: Decimal, params: sp.ParameterSet) -> str:
    for lower, label in params.bands:
        if lower is None or score >= lower:
            return label
    raise AssertionError("unreachable")  # pragma: no cover


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


@dataclass(slots=True)
class ScoreResult:
    as_of: datetime
    status: Literal["ok", "insufficient_data"]
    score: Decimal | None
    band: str | None
    available_weight: Decimal
    components: list[ComponentResult]
    reason: str | None = None
    parameter_version: str = SCORE_VERSION
    calculated_at: datetime | None = None


def _growth_component(definition: ComponentDef, growth: SupplyGrowth) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if growth.status != "ok" or growth.change_7d is None:
        result.reason = growth.reason or "no 7-day supply growth could be calculated"
        return result
    value = growth.change_7d
    sub = _clip(value / definition.scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.000001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.calculation = (
        f"7-day change = {result.value:+.6f}; sub-score = clip({result.value:+.6f} ÷ "
        f"{definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def _acceleration_component(
    definition: ComponentDef, acceleration: GrowthAcceleration
) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if acceleration.status != "ok" or acceleration.change is None:
        result.reason = acceleration.reason or "no growth acceleration could be calculated"
        return result
    value = acceleration.change
    sub = _clip(value / definition.scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.000001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.calculation = (
        f"change in 7-day growth rate = {result.value:+.6f}; sub-score = "
        f"clip({result.value:+.6f} ÷ {definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def compute_score(
    *,
    as_of: datetime,
    calculated_at: datetime,
    usdt_growth: SupplyGrowth,
    usdc_growth: SupplyGrowth,
    total_growth: SupplyGrowth,
    total_acceleration: GrowthAcceleration,
    version: str | None = None,
) -> ScoreResult:
    """The Liquidity Score from already-computed component metrics (the caller supplies
    point-in-time metric results; this function does no I/O and no point-in-time filtering)."""
    params = sp.parameters(version)
    defs = {c.component_id: c for c in _components(params)}
    components = [
        _growth_component(defs["usdt_growth_7d"], usdt_growth),
        _growth_component(defs["usdc_growth_7d"], usdc_growth),
        _growth_component(defs["total_growth_7d"], total_growth),
        _acceleration_component(defs["growth_acceleration"], total_acceleration),
    ]
    available = [c for c in components if c.status == "ok"]
    weight = sum((c.definition.weight for c in available), Decimal(0))
    if weight < params.min_available_weight:
        return ScoreResult(
            as_of=as_of,
            status="insufficient_data",
            score=None,
            band=None,
            available_weight=weight,
            components=components,
            reason=(
                f"Insufficient data: available components carry weight {weight} of 1.00 "
                f"(minimum {params.min_available_weight})."
            ),
            parameter_version=params.version,
            calculated_at=calculated_at,
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
        as_of=as_of,
        status="ok",
        score=score,
        band=band_for(score, params),
        available_weight=weight,
        components=components,
        parameter_version=params.version,
        calculated_at=calculated_at,
    )
