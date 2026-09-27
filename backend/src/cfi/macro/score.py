"""Macro Environment Score v1 — a transparent composite of published component metrics (Phase 11).

Pure functions (no I/O). Evidence category: **Calculated Metric** (R2) — a deterministic
calculation over observed data with fixed, published parameters. It is not a statistical signal
(it is not compared with its own history beyond the trend windows below), not a prediction and
not a recommendation, and it is **not a crypto price forecast**: it describes the conventional
macro backdrop only — monetary-policy stance (yield curve, real policy rate), risk appetite in
traditional markets (VIX, equities), USD strength, US liquidity conditions and inflation
(commodity) pressure — using the components in ``cfi/macro/metrics.py``. Whatever relationship
this backdrop has with crypto markets is left entirely to the person reading it (R1); this score
never converts macro data into a deterministic crypto prediction, matching the phase's explicit
instruction.

Method (every number is shown to the user), mirroring the Liquidity Score
(``cfi/liquidity/score.py``) and the versioned-parameters pattern used by every score in this
project:

1. Each component is one already-computed metric result from ``macro/metrics.py``.
2. Sub-score = metric value ÷ reference scale, clipped to [-1, +1]. Reference scales are
   **judgment parameters chosen by design** (``score_parameters.py``), not fitted to data. A
   positive sub-score means "more accommodative / risk-on"; negative means "more restrictive /
   risk-off" — describing the macro backdrop, never a crypto-price direction.
3. Score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components), range −100 … +100.
4. A component whose metric is "unavailable" is excluded (never filled with a default). If the
   available components carry less than the minimum available weight, the score is
   "Insufficient data".

Bands are descriptive labels of the macro backdrop, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

import cfi.macro.score_parameters as sp
from cfi.macro.metrics import (
    RealPolicyRateReading,
    TrendReading,
    VixReading,
    YieldCurveReading,
)

SCORE_ID = "macro_environment_score"
SCORE_VERSION = sp.CURRENT_VERSION

VINTAGE_RISK_NOTE = (
    "Every component here is sourced from FRED and reflects FRED's CURRENT, most-revised figure "
    "for each historical date — not the value as it was first published. This platform does not "
    "yet track FRED's own real-time ('ALFRED') vintages (ADR-0054, a documented, accepted "
    "limitation; RED_TEAM_REPORT.md finding #2), so a historical reading of this score, and "
    "anything built on it (regime classification, historical similarity, a domain-score-based "
    "backtest), can reflect a later revision that would not actually have been knowable on that "
    "date — most plausibly around initial-vs-final GDP/CPI prints or seasonal re-benchmarking of "
    "the Fed's own balance-sheet series."
)

SEMANTIC_NOTE = (
    "Higher Macro Environment Score means a more accommodative macro backdrop by conventional "
    "measures (a steeper/normal yield curve, a lower real policy rate, calmer equity-market "
    "volatility, rising equities, a weaker US dollar, expanding US liquidity, and easing "
    "commodity-inflation pressure). It describes current macroeconomic conditions using standard "
    "indicators; it is not a crypto price prediction and does not convert macro data into a "
    "deterministic crypto forecast."
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
            "yield_curve_slope",
            "US Treasury yield curve slope (10y − 2y)",
            params.weight_yield_curve,
            params.yield_curve_scale,
            "percentage points",
            "10-year Treasury yield minus 2-year Treasury yield.",
            "Calculated metric from direct evidence (FRED DGS10, DGS2)",
            "Steeper/positive slope -> more accommodative; inverted/negative slope -> more "
            "restrictive.",
        ),
        ComponentDef(
            "real_policy_rate",
            "Approximate real policy rate (effective fed funds − CPI YoY)",
            params.weight_real_policy_rate,
            params.real_policy_rate_scale,
            "percentage points",
            "Effective federal funds rate minus trailing 12-month CPI inflation.",
            "Calculated metric derived from direct evidence (FRED DFF, CPIAUCSL)",
            "Higher real rate -> more restrictive (negative contribution); lower/negative real "
            "rate -> more accommodative.",
        ),
        ComponentDef(
            "vix_level",
            "CBOE Volatility Index (VIX), vs. its long-run reference level",
            params.weight_vix,
            params.vix_scale,
            "index points from reference",
            f"VIX close minus a reference level of {params.vix_reference} (a commonly cited "
            "long-run average).",
            "Calculated metric from direct evidence (FRED VIXCLS)",
            "Higher VIX -> more risk-off (negative contribution); lower VIX -> more risk-on.",
        ),
        ComponentDef(
            "equity_trend",
            "S&P 500, 90-day change",
            params.weight_equity_trend,
            params.equity_trend_scale,
            "ratio (90-day relative change)",
            "S&P 500 close now ÷ S&P 500 close 90 days earlier − 1.",
            "Calculated metric from direct evidence (FRED SP500)",
            "Rising equities -> more risk-on; falling equities -> more risk-off.",
        ),
        ComponentDef(
            "dollar_trend",
            "Broad US Dollar Index proxy, 90-day change",
            params.weight_dollar_trend,
            params.dollar_trend_scale,
            "ratio (90-day relative change)",
            "DTWEXBGS now ÷ DTWEXBGS 90 days earlier − 1 (DXY SUBSTITUTE — see "
            "cfi.macro.universe).",
            "Calculated metric from direct evidence (FRED DTWEXBGS)",
            "A strengthening dollar -> tighter global conditions (negative contribution); a "
            "weakening dollar -> looser conditions.",
        ),
        ComponentDef(
            "net_liquidity_trend",
            "US net-liquidity proxy, 90-day change (Fed balance sheet − TGA − reverse repo)",
            params.weight_net_liquidity_trend,
            params.net_liquidity_trend_scale,
            "ratio (90-day relative change)",
            "(Fed balance sheet − Treasury General Account − overnight reverse repo) now ÷ the "
            "same composite 90 days earlier − 1. US-only proxy, not a true global aggregate — "
            "see cfi.macro.universe.",
            "Calculated metric derived from direct evidence (FRED WALCL, WTREGEN, RRPONTSYD)",
            "Expanding net liquidity -> more accommodative; contracting -> more restrictive.",
        ),
        ComponentDef(
            "oil_trend",
            "WTI crude oil, 90-day change",
            params.weight_oil_trend,
            params.oil_trend_scale,
            "ratio (90-day relative change)",
            "WTI spot price now ÷ WTI spot price 90 days earlier − 1.",
            "Calculated metric from direct evidence (FRED DCOILWTICO)",
            "Rising oil -> inflationary pressure, more restrictive-leaning (negative "
            "contribution); falling oil -> disinflationary, more accommodative-leaning.",
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
    vintage_risk_note: str = VINTAGE_RISK_NOTE


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


def _yield_curve_component(definition: ComponentDef, r: YieldCurveReading) -> ComponentResult:
    return _scaled_component(definition, r.slope_pp, r.status, r.reason, invert=False)


def _real_policy_rate_component(
    definition: ComponentDef, r: RealPolicyRateReading
) -> ComponentResult:
    return _scaled_component(definition, r.real_rate_pp, r.status, r.reason, invert=True)


def _vix_component(
    definition: ComponentDef, r: VixReading, params: sp.ParameterSet
) -> ComponentResult:
    value = None if r.value is None else r.value - params.vix_reference
    return _scaled_component(definition, value, r.status, r.reason, invert=True)


def _trend_component(definition: ComponentDef, r: TrendReading, *, invert: bool) -> ComponentResult:
    return _scaled_component(definition, r.change_pct, r.status, r.reason, invert=invert)


def compute_score(
    *,
    as_of: datetime,
    calculated_at: datetime,
    yield_curve: YieldCurveReading,
    real_policy_rate: RealPolicyRateReading,
    vix: VixReading,
    equity_trend: TrendReading,
    dollar_trend: TrendReading,
    net_liquidity_trend: TrendReading,
    oil_trend: TrendReading,
    version: str | None = None,
) -> ScoreResult:
    """The Macro Environment Score from already-computed component metrics (the caller supplies
    point-in-time metric results; this function does no I/O and no point-in-time filtering)."""
    params = sp.parameters(version)
    defs = {c.component_id: c for c in _components(params)}
    components = [
        _yield_curve_component(defs["yield_curve_slope"], yield_curve),
        _real_policy_rate_component(defs["real_policy_rate"], real_policy_rate),
        _vix_component(defs["vix_level"], vix, params),
        _trend_component(defs["equity_trend"], equity_trend, invert=False),
        _trend_component(defs["dollar_trend"], dollar_trend, invert=True),
        _trend_component(defs["net_liquidity_trend"], net_liquidity_trend, invert=False),
        _trend_component(defs["oil_trend"], oil_trend, invert=True),
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
