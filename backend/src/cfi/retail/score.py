"""Retail Activity Score and Retail Speculation Score v1 — transparent composites of published
component metrics (Phase 10). Pure functions (no I/O). Evidence category: **Calculated Metric**
(R2) — deterministic calculations over already-computed metrics/signals, with fixed, published
parameters. Neither is a prediction or a recommendation, and **every component that feeds them is
a RETAIL PROXY, never direct retail data** (see ``retail/universe.py`` and ``retail/metrics.py``).

**Retail Activity Score** (0-100, unsigned): "how elevated is retail-proxy participation right
now, relative to its own recent history" — a level/intensity reading, not a direction. Each
component is already a 0-100 historical percentile (``metrics.percentile_rank``); the score is
their weighted average. There is no reference "scale" to apply (a percentile is already 0-100).

**Retail Speculation Score** (-100..+100, signed): "does current data lean toward crowded,
long-biased leveraged/speculative retail-proxy positioning, or short-biased, or balanced".
Method, mirroring the Liquidity Score (``cfi.liquidity.score``):

1. Each directional component's sub-score = value / reference scale, clipped to [-1, +1].
2. The meme-coin-trending component is **not directional** — it is a count (always >= 0) of how
   many curated meme coins are currently trending, so its sub-score is also always >= 0. It can
   only push the score up (toward "more speculative fervour"), never down; zero meme coins
   trending contributes a neutral 0, not a negative reading. This is stated explicitly in its
   ``ComponentDef`` so it is never mistaken for a balanced two-sided signal.
3. Score = 100 x sum(weight x sub-score) / sum(weights of available components).
4. A component whose metric is "unavailable" is excluded (never filled with a default). Below the
   minimum available weight, the score is "Insufficient data".

Bands are descriptive labels only, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

import cfi.retail.score_parameters as sp
from cfi.retail.metrics import DerivativesProxy, MemeCoinActivity, PercentileResult

ACTIVITY_SCORE_ID = "retail_activity_score"
ACTIVITY_SCORE_VERSION = sp.CURRENT_ACTIVITY_VERSION
SPECULATION_SCORE_ID = "retail_speculation_score"
SPECULATION_SCORE_VERSION = sp.CURRENT_SPECULATION_VERSION

ACTIVITY_SEMANTIC_NOTE = (
    "Higher Retail Activity Score means measured retail-proxy activity (small on-chain "
    "transactions, meme-coin search trending, derivatives positioning turnover) is elevated "
    "relative to its own recent history. It is a level/intensity reading, not a direction, and "
    "every input is a proxy, never data identified by its source as retail-only."
)
SPECULATION_SEMANTIC_NOTE = (
    "Higher Retail Speculation Score means the tracked proxies lean toward crowded, long-biased, "
    "leveraged positioning; lower means short-biased. It is not a probability of price increase "
    "and does not indicate what will happen next — every input is a proxy, never data identified "
    "by its source as retail-only (R1, R5)."
)

#: RED_TEAM_REPORT.md finding #7 / ADR-0064: this score's funding_rate_bias component (0.40
#: weight) is the SAME underlying Binance funding-rate series that also drives 0.25 of the
#: Derivatives Health Score (cfi.derivatives.score) — not merely a similar concept, the identical
#: number. (account_ratio_skew, this score's other 0.40 directional component, is a different
#: series — Binance's long/short account ratio — not used by Derivatives Health at all, so it does
#: not add to this particular overlap; it is still disclosed platform-wide as "not retail-exclusive"
#: via measurement_class="proxy".) A "retail is over-leveraged while derivatives health looks fine"
#: divergence narrative could be comparing a metric against a rescaled version of itself rather
#: than two independent signals for that 0.40-weighted portion — disclosed here at the score level
#: (not just in each module's own docstring) so a consumer, including the Divergence Engine, can
#: see it without reading the source.
SPECULATION_SHARED_INPUT_NOTE = (
    "This score's funding_rate_bias component (0.40 weight) is sourced from the same underlying "
    "Binance funding-rate data that also drives 25% of the Derivatives Health Score. A divergence "
    "comparison between this score and Derivatives Health is not fully independent for that "
    "shared portion (account_ratio_skew, this score's other directional component, is a separate "
    "series and does not overlap)."
)

ComponentStatus = Literal["ok", "unavailable"]


@dataclass(frozen=True, slots=True)
class ComponentDef:
    component_id: str
    label: str
    weight: Decimal
    unit: str
    definition: str
    evidence: str
    directional: bool = True  # False: this component can only ever push the score in one way


def _clip(x: Decimal) -> Decimal:
    return max(Decimal(-1), min(Decimal(1), x))


def band_for(score: Decimal, bands: tuple[tuple[Decimal | None, str], ...]) -> str:
    for lower, label in bands:
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
    score_id: str
    as_of: datetime
    status: Literal["ok", "insufficient_data"]
    score: Decimal | None
    band: str | None
    available_weight: Decimal
    components: list[ComponentResult]
    reason: str | None = None
    parameter_version: str = ""
    calculated_at: datetime | None = None
    shared_input_note: str | None = None


def _combine(
    score_id: str,
    as_of: datetime,
    calculated_at: datetime,
    components: list[ComponentResult],
    min_available_weight: Decimal,
    parameter_version: str,
    bands: tuple[tuple[Decimal | None, str], ...],
    *,
    scale: Decimal,
) -> ScoreResult:
    """Shared weighted-combination step for both scores. ``scale`` is 100 for the -100..+100
    speculation score (sub-scores in [-1, 1]) and also 100 for the 0-100 activity score, but
    there the "sub-score" is a percentile already divided by 100 — see each compute function."""
    available = [c for c in components if c.status == "ok"]
    weight = sum((c.definition.weight for c in available), Decimal(0))
    if weight < min_available_weight:
        return ScoreResult(
            score_id=score_id,
            as_of=as_of,
            status="insufficient_data",
            score=None,
            band=None,
            available_weight=weight,
            components=components,
            reason=(
                f"Insufficient data: available components carry weight {weight} of 1.00 "
                f"(minimum {min_available_weight})."
            ),
            parameter_version=parameter_version,
            calculated_at=calculated_at,
        )
    total = Decimal(0)
    for c in available:
        assert c.sub_score is not None  # noqa: S101
        c.effective_weight = (c.definition.weight / weight).quantize(Decimal("0.0001"))
        c.contribution = (scale * c.definition.weight / weight * c.sub_score).quantize(
            Decimal("0.01")
        )
        total += c.definition.weight * c.sub_score
    score = (scale * total / weight).quantize(Decimal("0.1"))
    return ScoreResult(
        score_id=score_id,
        as_of=as_of,
        status="ok",
        score=score,
        band=band_for(score, bands),
        available_weight=weight,
        components=components,
        parameter_version=parameter_version,
        calculated_at=calculated_at,
    )


# ============================================================================ Retail Activity Score


def _activity_components(params: sp.ActivityParameterSet) -> tuple[ComponentDef, ...]:
    return (
        ComponentDef(
            "small_tx_percentile",
            "Small Bitcoin-transaction count, historical percentile",
            params.weight_small_tx_percentile,
            "percentile (0-100)",
            "Today's count of small-value Bitcoin outputs, ranked against its own trailing "
            "history.",
            "Statistical signal (L3) over a calculated metric (L2) over an on-chain proxy "
            "(RETAIL PROXY, not filtered for change outputs or batching)",
        ),
        ComponentDef(
            "meme_trending_percentile",
            "Meme-coin trending count, historical percentile",
            params.weight_meme_trending_percentile,
            "percentile (0-100)",
            "Today's count of curated meme coins appearing in CoinGecko's trending list, ranked "
            "against its own trailing history.",
            "Statistical signal (L3) over a search-attention proxy (RETAIL PROXY)",
        ),
        ComponentDef(
            "derivatives_turnover_percentile",
            "Derivatives positioning-skew magnitude, historical percentile",
            params.weight_derivatives_turnover_percentile,
            "percentile (0-100)",
            "Today's average |long/short account ratio - 1| across tracked perpetuals "
            "(magnitude only, not direction), ranked against its own trailing history.",
            "Statistical signal (L3) over a derivatives-positioning proxy (RETAIL PROXY)",
        ),
    )


def _percentile_component(definition: ComponentDef, result: PercentileResult) -> ComponentResult:
    out = ComponentResult(definition, "unavailable")
    if result.status != "ok" or result.percentile is None:
        out.reason = result.reason or "no percentile could be calculated"
        return out
    out.status = "ok"
    out.value = result.percentile
    out.sub_score = (result.percentile / 100).quantize(Decimal("0.0001"))
    out.calculation = f"percentile = {result.percentile}/100 (n={result.sample_size})"
    return out


def compute_activity_score(
    *,
    as_of: datetime,
    calculated_at: datetime,
    small_tx_percentile: PercentileResult,
    meme_trending_percentile: PercentileResult,
    derivatives_turnover_percentile: PercentileResult,
    version: str | None = None,
) -> ScoreResult:
    params = sp.activity_parameters(version)
    defs = {c.component_id: c for c in _activity_components(params)}
    components = [
        _percentile_component(defs["small_tx_percentile"], small_tx_percentile),
        _percentile_component(defs["meme_trending_percentile"], meme_trending_percentile),
        _percentile_component(
            defs["derivatives_turnover_percentile"], derivatives_turnover_percentile
        ),
    ]
    return _combine(
        ACTIVITY_SCORE_ID,
        as_of,
        calculated_at,
        components,
        params.min_available_weight,
        params.version,
        params.bands,
        scale=Decimal(100),
    )


# ========================================================================= Retail Speculation Score


def _speculation_components(params: sp.SpeculationParameterSet) -> tuple[ComponentDef, ...]:
    return (
        ComponentDef(
            "funding_rate_bias",
            "Perpetual funding-rate bias",
            params.weight_funding_rate_bias,
            "ratio (average funding rate across tracked perps)",
            "Average funding rate across tracked perpetual futures (BTC, ETH, SOL, XRP): "
            "positive means longs are paying shorts (crowded leveraged long demand).",
            "Calculated metric from direct evidence (Binance funding-rate snapshots), a proxy "
            "for retail-associated leveraged speculation, not retail-exclusive data",
        ),
        ComponentDef(
            "account_ratio_skew",
            "Long/short account-ratio skew",
            params.weight_account_ratio_skew,
            "ratio deviation from 1.0",
            "Average (Binance all-account long/short account ratio - 1) across tracked perps: "
            "positive means more accounts long than short.",
            "Calculated metric from direct evidence (Binance account-ratio snapshots); an "
            "account-count ratio skews toward the numerous small accounts, a proxy, not "
            "retail-exclusive data",
        ),
        ComponentDef(
            "meme_trending",
            "Meme-coin trending intensity",
            params.weight_meme_trending,
            "count (curated meme coins currently trending)",
            "Count of curated meme coins currently in CoinGecko's trending list.",
            "Calculated metric from direct evidence (CoinGecko trending snapshot), a search-"
            "attention proxy for speculative fervour",
            directional=False,
        ),
    )


def _funding_component(
    definition: ComponentDef, proxy: DerivativesProxy, scale: Decimal
) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if proxy.status != "ok" or proxy.funding_rate_avg is None:
        result.reason = proxy.reason or "no funding-rate reading available"
        return result
    value = proxy.funding_rate_avg
    sub = _clip(value / scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.000001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.calculation = (
        f"avg funding rate = {result.value:+.6f}; sub-score = clip({result.value:+.6f} / "
        f"{scale}, -1, +1) = {result.sub_score:+.4f}"
    )
    return result


def _ratio_component(
    definition: ComponentDef, proxy: DerivativesProxy, scale: Decimal
) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if proxy.status != "ok" or proxy.account_ratio_avg is None:
        result.reason = proxy.reason or "no account-ratio reading available"
        return result
    value = proxy.account_ratio_avg - 1
    sub = _clip(value / scale)
    result.status = "ok"
    result.value = value.quantize(Decimal("0.000001"))
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.calculation = (
        f"ratio - 1 = {result.value:+.6f}; sub-score = clip({result.value:+.6f} / {scale}, -1, "
        f"+1) = {result.sub_score:+.4f}"
    )
    return result


def _meme_component(
    definition: ComponentDef, activity: MemeCoinActivity, scale: Decimal
) -> ComponentResult:
    result = ComponentResult(definition, "unavailable")
    if activity.status != "ok":
        result.reason = activity.reason or "no trending snapshot available"
        return result
    value = Decimal(activity.meme_coins_trending_count)
    sub = _clip(value / scale)  # always >= 0: count is never negative (see module docstring)
    result.status = "ok"
    result.value = value
    result.sub_score = sub.quantize(Decimal("0.0001"))
    result.calculation = (
        f"meme coins trending = {int(value)}; sub-score = clip({int(value)} / {scale}, -1, +1) "
        f"= {result.sub_score:+.4f} (never negative — see ComponentDef.directional)"
    )
    return result


def compute_speculation_score(
    *,
    as_of: datetime,
    calculated_at: datetime,
    derivatives: DerivativesProxy,
    meme_activity: MemeCoinActivity,
    version: str | None = None,
) -> ScoreResult:
    params = sp.speculation_parameters(version)
    defs = {c.component_id: c for c in _speculation_components(params)}
    components = [
        _funding_component(defs["funding_rate_bias"], derivatives, params.funding_rate_scale),
        _ratio_component(defs["account_ratio_skew"], derivatives, params.account_ratio_skew_scale),
        _meme_component(defs["meme_trending"], meme_activity, params.meme_trending_scale),
    ]
    result = _combine(
        SPECULATION_SCORE_ID,
        as_of,
        calculated_at,
        components,
        params.min_available_weight,
        params.version,
        params.bands,
        scale=Decimal(100),
    )
    result.shared_input_note = SPECULATION_SHARED_INPUT_NOTE
    return result
