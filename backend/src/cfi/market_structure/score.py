"""Market Structure Score v1 — a transparent composite of published component metrics (Phase 12).

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — a deterministic
calculation over already-computed technical readings (``cfi/market_structure/metrics.py``) with
fixed, published parameters. It is not a statistical signal, not a regime classification, not a
forecast, and **it is not a trading recommendation**: it summarises the current technical condition
of already-tracked price, breadth and volatility data into one published number, using the
components below. What action (if any) to take is left entirely to the person reading it (R1); this
score never converts these metrics into an automatic trading recommendation, matching the phase's
explicit instruction.

Method (every number is shown to the user), mirroring the Macro Environment Score
(``cfi/macro/score.py``) and the versioned-parameters pattern used by every score in this project:

1. Each component is one already-computed metric result from ``market_structure/metrics.py``.
2. Sub-score = metric value ÷ reference scale, clipped to [-1, +1]. Reference scales are
   **judgment parameters chosen by design** (``score_parameters.py``), not fitted to data. A
   positive sub-score means "stronger / more constructive technical structure"; negative means
   "weaker / more deteriorated technical structure" — describing the current technical condition of
   the data, never a buy/sell signal.
3. Score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components), range −100 … +100.
4. A component whose metric is "unavailable" is excluded (never filled with a default). If the
   available components carry less than the minimum available weight, the score is
   "Insufficient data".

Bands are descriptive labels of the technical structure, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

import cfi.market_structure.score_parameters as sp
from cfi.market_structure.metrics import (
    BreadthReading,
    MovingAverageReading,
    RelativeStrengthReading,
    RsiReading,
    VolatilityReading,
)

SCORE_ID = "market_structure_score"
SCORE_VERSION = sp.CURRENT_VERSION

SEMANTIC_NOTE = (
    "Higher Market Structure Score means a stronger, more constructive technical structure by "
    "conventional measures (BTC trading further above its 200-day moving average, BTC momentum "
    "(RSI) further above neutral, a larger share of the tracked universe above its own 50-day "
    "moving average, altcoins outperforming BTC, and calmer realized volatility). It describes the "
    "current technical condition of already-tracked price, breadth and volatility data using "
    "standard indicators; it is not a trading recommendation and does not convert these metrics "
    "into an automatic buy/sell signal."
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
    direction_note: str


def _components(params: sp.ParameterSet) -> tuple[ComponentDef, ...]:
    """Component metadata generated from a parameter set, so text can't drift from numbers."""
    return (
        ComponentDef(
            "price_trend",
            "BTC price vs. 200-day moving average",
            params.weight_price_trend,
            params.price_trend_scale,
            "ratio (close ÷ SMA200 − 1)",
            "BTC close ÷ BTC 200-day simple moving average − 1.",
            "Calculated metric from direct evidence (Coinbase daily OHLCV bars, Phase 5)",
            "Close further above SMA200 -> more constructive; further below -> more deteriorated.",
        ),
        ComponentDef(
            "momentum",
            "BTC RSI(14), vs. neutral (50)",
            params.weight_momentum,
            params.momentum_scale,
            "RSI points from neutral",
            "BTC's Wilder 14-day RSI minus 50.",
            "Calculated metric from direct evidence (Coinbase daily OHLCV bars, Phase 5)",
            "RSI further above 50 -> more constructive momentum; further below -> weaker momentum.",
        ),
        ComponentDef(
            "market_breadth",
            "Market breadth (tracked universe above its own 50-day SMA)",
            params.weight_breadth,
            params.breadth_scale,
            "fraction from 0.5",
            "Fraction of the tracked universe (BTC, ETH, SOL, XRP) trading above its own "
            "50-day SMA, minus 0.5.",
            "Calculated metric from direct evidence (Coinbase daily OHLCV bars, Phase 5)",
            "A larger share above their 50-day SMA -> broader participation (more "
            "constructive); a smaller share -> narrower, weaker participation.",
        ),
        ComponentDef(
            "altcoin_relative_strength",
            "Altcoin relative strength vs. BTC (ETH, SOL, XRP average)",
            params.weight_altcoin_relative_strength,
            params.altcoin_relative_strength_scale,
            "percentage points (average 30-day spread vs. BTC)",
            "Average of ETH, SOL and XRP's trailing 30-day return minus BTC's trailing 30-day "
            "return, across whichever of the three have enough history.",
            "Calculated metric from direct evidence (Coinbase daily OHLCV bars, Phase 5)",
            "Altcoins outperforming BTC -> risk-on rotation (more constructive); "
            "underperforming -> risk-off toward BTC (more deteriorated).",
        ),
        ComponentDef(
            "volatility_regime",
            "BTC realized volatility percentile (vs. its own trailing history)",
            params.weight_volatility_regime,
            params.volatility_regime_scale,
            "percentile points from 50",
            "BTC's annualized 30-day realized-volatility percentile (vs. its own trailing "
            "~1-year history) minus 50.",
            "Calculated metric from direct evidence (Coinbase daily OHLCV bars, Phase 5)",
            "Volatility percentile below 50 (calmer than usual) -> more constructive; above 50 "
            "(more turbulent than usual) -> more deteriorated.",
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


def _scaled_component(
    definition: ComponentDef,
    value: Decimal | None,
    status: str,
    reason: str | None,
    *,
    invert: bool,
) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if status != "ok" or value is None:
        result.reason = reason or f"no {definition.component_id} value could be calculated"
        return result
    signed = -value if invert else value
    sub = _clip(signed / definition.scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.000001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    sign = "-" if invert else ""
    result.calculation = (
        f"value = {result.value:+.6f}; sub-score = clip({sign}{result.value:+.6f} ÷ "
        f"{definition.scale}, −1, +1) = {result.sub_score:+.4f}"
    )
    return result


def _price_trend_component(definition: ComponentDef, r: MovingAverageReading) -> ComponentResult:
    if r.status != "ok" or r.close is None or r.sma200 is None or r.sma200 <= 0:
        return _scaled_component(
            definition,
            None,
            "unavailable",
            r.reason or "no BTC 200-day SMA available",
            invert=False,
        )
    value = r.close / r.sma200 - 1
    return _scaled_component(definition, value, "ok", None, invert=False)


def _momentum_component(definition: ComponentDef, r: RsiReading) -> ComponentResult:
    value = None if r.value is None else r.value - 50
    return _scaled_component(definition, value, r.status, r.reason, invert=False)


def _breadth_component(definition: ComponentDef, r: BreadthReading) -> ComponentResult:
    value = None if r.fraction is None else r.fraction - Decimal("0.5")
    return _scaled_component(definition, value, r.status, r.reason, invert=False)


#: RED_TEAM_REPORT.md finding #6: below this many available altcoin readings, the component is
#: reported "unavailable" rather than silently averaging (and weighting at the full 0.20) whichever
#: single asset happens to remain — matching the MIN_COVERAGE convention already used by
#: cfi.whales.score / cfi.institutional.score for the identical "too little breadth to trust the
#: average" concern.
MIN_ALTCOIN_COUNT = 2


def _altcoin_relative_strength_component(
    definition: ComponentDef, readings: list[RelativeStrengthReading]
) -> ComponentResult:
    """Average ``spread_pp`` across whichever of the supplied altcoin readings are available
    (never a fabricated fill-in for a missing asset, R3) — unavailable when fewer than
    ``MIN_ALTCOIN_COUNT`` are (ADR-0063, finding #6), not just when all are."""
    available = [r.spread_pp for r in readings if r.status == "ok" and r.spread_pp is not None]
    if len(available) < MIN_ALTCOIN_COUNT:
        return _scaled_component(
            definition,
            None,
            "unavailable",
            f"only {len(available)} of {len(readings)} altcoin relative-strength readings "
            f"available (ETH/SOL/XRP), fewer than the minimum {MIN_ALTCOIN_COUNT} needed to "
            "trust the average",
            invert=False,
        )
    value = sum(available, Decimal(0)) / len(available)
    return _scaled_component(definition, value, "ok", None, invert=False)


def _volatility_regime_component(definition: ComponentDef, r: VolatilityReading) -> ComponentResult:
    value = None if r.percentile is None else r.percentile - 50
    status = "ok" if r.percentile is not None else r.status
    return _scaled_component(definition, value, status, r.reason, invert=True)


def compute_score(
    *,
    as_of: datetime,
    calculated_at: datetime,
    price_trend: MovingAverageReading,
    momentum: RsiReading,
    breadth: BreadthReading,
    altcoin_relative_strength: list[RelativeStrengthReading],
    volatility_regime: VolatilityReading,
    version: str | None = None,
) -> ScoreResult:
    """The Market Structure Score from already-computed component metrics (the caller supplies
    point-in-time metric results; this function does no I/O and no point-in-time filtering)."""
    params = sp.parameters(version)
    defs = {c.component_id: c for c in _components(params)}
    components = [
        _price_trend_component(defs["price_trend"], price_trend),
        _momentum_component(defs["momentum"], momentum),
        _breadth_component(defs["market_breadth"], breadth),
        _altcoin_relative_strength_component(
            defs["altcoin_relative_strength"], altcoin_relative_strength
        ),
        _volatility_regime_component(defs["volatility_regime"], volatility_regime),
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
