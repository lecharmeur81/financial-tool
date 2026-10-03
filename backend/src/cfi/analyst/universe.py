"""Versioned parameters, fixed vocabulary and scope disclosures for the AI Analyst (Phase 21,
ADR-0068; domain structure correction ADR-0069). Nothing here is fitted to data (R13) — the section
order and grounding rules are the user's own explicit Phase 21 spec, and the banned-language
patterns are a structural, testable enforcement of R1 ("never turn uncertainty into certainty") and
the spec's Section 12 grounding tests, not a stylistic preference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- versioning (ADR-0041)

SNAPSHOT_VERSION = "analyst_snapshot.v1"
PROMPT_VERSION = "analyst_prompt.v1"
RESPONSE_SCHEMA_VERSION = "analyst_response.v1"

# --------------------------------------------------------------------------- required output shape

# The 12 sections, in this exact order (user's Phase 21 spec, Section 5). Order is enforced by
# construction: `cfi.analyst.schema.AnalystResponse`'s field order IS this tuple, so every response
# this system ever serializes or stores presents them in this order regardless of the order Claude's
# own JSON happened to use (JSON object key order carries no semantic meaning; enforcing an incoming
# key order would be enforcing something JSON does not guarantee).
RESPONSE_SECTIONS = (
    "summary",
    "evidence",
    "contradicting_evidence",
    "market_regime",
    "key_changes",
    "capital_participant_behavior",
    "derivatives_liquidity_context",
    "historical_context",
    "risks_uncertainties",
    "scenarios",
    "invalidation_conditions",
    "data_quality",
)

# Flat grounded-list sections: unchanged by the domain-structure correction (ADR-0069) — these were
# never merged-domain buckets, so they keep their original flat `list[EvidenceItem]` shape and
# simple getattr-based validation. "key_changes", "capital_participant_behavior" and
# "derivatives_liquidity_context" are no longer flat lists (see DOMAIN_LOCATIONS below) and are
# validated by `_check_domain_sections` in `validator.py` instead.
GROUNDED_LIST_SECTIONS = (
    "evidence",
    "contradicting_evidence",
    "historical_context",
)

# --------------------------------------------------------------------------- domain structure
# (ADR-0069)

# The 10 intelligence domains that previously had either no dedicated placement at all (macro,
# market_structure, divergences, anomalies, capital_rotation) or were merged indistinguishably into
# one flat list (institutional/whale/retail into capital_participant_behavior; derivatives/liquidity
# into derivatives_liquidity_context). Each domain maps to exactly one analyst tool (`cfi.analyst.
# tools`) — this is the same field_id prefix every snapshot field already carries (`snapshot.py`'s
# `_flatten` prefixes every field with its tool_id), so no new tagging mechanism was invented; the
# domain-to-tool mapping below is simply named so the schema, prompt and validator can all refer to
# it the same way (R13: reuse, do not invent a parallel identification scheme).
DOMAIN_TOOL_IDS: dict[str, str] = {
    "institutional": "get_institutional_flows",
    "whale": "get_whale_activity",
    "retail": "get_retail_activity",
    "derivatives": "get_derivatives",
    "liquidity": "get_liquidity",
    "macro": "get_macro",
    "market_structure": "get_market_structure",
    "divergences": "calculate_divergence",
    "anomalies": "get_anomalies",
    "capital_rotation": "get_capital_rotation",
}

# Where each domain's evidence list lives inside `AnalystResponse` — (top_level_field, sub_field).
# The 12 top-level section names and their order are UNCHANGED (still `RESPONSE_SECTIONS` above);
# only the *type* of these three fields changed, from a flat `list[EvidenceItem]` to a structured
# object with one named list per domain it covers (`cfi.analyst.schema.ParticipantBehavior`,
# `MarketContext`, `KeyChanges`).
DOMAIN_LOCATIONS: dict[str, tuple[str, str]] = {
    "institutional": ("capital_participant_behavior", "institutional"),
    "whale": ("capital_participant_behavior", "whale"),
    "retail": ("capital_participant_behavior", "retail"),
    "derivatives": ("derivatives_liquidity_context", "derivatives"),
    "liquidity": ("derivatives_liquidity_context", "liquidity"),
    "macro": ("key_changes", "macro"),
    "market_structure": ("key_changes", "market_structure"),
    "divergences": ("key_changes", "divergences"),
    "anomalies": ("key_changes", "anomalies"),
    "capital_rotation": ("key_changes", "capital_rotation"),
}

if set(DOMAIN_TOOL_IDS) != set(DOMAIN_LOCATIONS):  # pragma: no cover - module-invariant guard
    raise ValueError("DOMAIN_TOOL_IDS and DOMAIN_LOCATIONS must declare exactly the same domains")

MAX_VALIDATION_ATTEMPTS = 2  # one Claude call, one retry with the validator's own errors appended

# --------------------------------------------------------------------------- banned language (R1)

# Bare "bullish"/"bearish" are unambiguous directional-certainty verdicts with no legitimate
# purely-descriptive use in an evidence-grounded analyst response (same posture as Phase 19's own
# anomaly-interpretation ban). Bare "buy"/"sell" are NOT banned outright — "buy-side flow",
# "sell-side liquidity", "buyers", "aggregate sell volume" are ordinary, non-actionable market
# vocabulary this analyst must be able to use when describing OBSERVED behaviour.
VERDICT_LANGUAGE = re.compile(r"\b(bullish|bearish)\b", re.IGNORECASE)

# Actionable trading directives — the analyst explains evidence, it never instructs a trade
# (CLAUDE.md A1: "not an automatic financial-advice engine").
DIRECTIVE_LANGUAGE = re.compile(
    r"\b(go long|go short|should buy|should sell|buy now|sell now|"
    r"recommend(?:s|ed)? (?:buying|selling)|buy signal|sell signal)\b",
    re.IGNORECASE,
)

# Converting uncertainty into certainty (R1) — guarantees, sure things, "always" causal claims.
CERTAINTY_LANGUAGE = re.compile(
    r"\b(guarantees?|guaranteed|certain(?:ly)? (?:to|will)|definitely will|will definitely|"
    r"100% (?:certain|sure)|risk[- ]free|sure thing|cannot fail|always (?:leads? to|results? in|"
    r"precedes?|repeats?|precede[sd]?))\b",
    re.IGNORECASE,
)

# Historical similarity presented as a guarantee of a future outcome (Section 12's explicit test).
HISTORY_GUARANTEE_LANGUAGE = re.compile(
    r"\b(history (?:always )?repeats itself|guarantees? (?:a|the) (?:repeat|outcome|future)|"
    r"will happen again|is certain to (?:repeat|happen)|is bound to (?:repeat|happen))\b",
    re.IGNORECASE,
)

BANNED_PATTERNS: dict[str, re.Pattern[str]] = {
    "verdict_language (bullish/bearish)": VERDICT_LANGUAGE,
    "directive_language (trading instruction)": DIRECTIVE_LANGUAGE,
    "certainty_language (uncertainty presented as fact)": CERTAINTY_LANGUAGE,
    "history_guarantee_language (similarity presented as prediction)": HISTORY_GUARANTEE_LANGUAGE,
}

# Required literal phrases (R6/Section 4) when the snapshot's own computed state calls for them.
# Exact wording, per the user's own spec — not paraphrased, so the check is a plain substring test.
INSUFFICIENT_DATA_PHRASE = "Insufficient data."
SOURCES_CONFLICT_PHRASE = "Sources conflict."


# --------------------------------------------------------------------------- tool catalog


@dataclass(frozen=True, slots=True)
class ToolDef:
    tool_id: str
    description: str
    domain_service: str  # informational only — which existing service this wraps (R13: reuse)


# The 14 tools named in the user's Phase 21 spec (Section 7). Every one wraps an existing,
# already-tested domain service via `cfi.divergence.adapters.Adapters` or that service's own
# constructor — this phase adds no new data access path, only a controlled, read-only, uniform
# calling convention over what already exists (R13: reuse, do not invent a parallel interface).
TOOLS: tuple[ToolDef, ...] = (
    ToolDef(
        "get_market_data",
        "Latest price, 24h/7d change, volume and realized volatility for "
        "the platform's tracked assets.",
        "cfi.divergence.adapters.Adapters (price/volume/vol)",
    ),
    ToolDef(
        "get_institutional_flows",
        "US spot ETF flows, treasury purchases and the Institutional Flow Score.",
        "cfi.institutional.service.InstitutionalService.overview",
    ),
    ToolDef(
        "get_whale_activity",
        "Exchange flows, large transfers, top holders and the Whale Flow Score.",
        "cfi.whales.service.WhaleService.overview",
    ),
    ToolDef(
        "get_retail_activity",
        "Retail activity/speculation scores and their components.",
        "cfi.retail.service.RetailService.overview",
    ),
    ToolDef(
        "get_derivatives",
        "Funding, open interest, liquidations, options skew and the Derivatives Health Score.",
        "cfi.derivatives.service.DerivativesService.overview",
    ),
    ToolDef(
        "get_liquidity",
        "Stablecoin supply growth and the Liquidity Score.",
        "cfi.liquidity.service.LiquidityService.overview",
    ),
    ToolDef(
        "get_macro",
        "Yield curve, real policy rate, VIX, net liquidity and the Macro Environment Score.",
        "cfi.macro.service.MacroService.overview",
    ),
    ToolDef(
        "get_market_structure",
        "Trend, momentum, breadth, dominance and the Market Structure Score.",
        "cfi.market_structure.service.MarketStructureService.overview",
    ),
    ToolDef(
        "calculate_divergence",
        "The Phase 13 pairwise divergence matrix (institutional vs. "
        "retail, whale vs. price, and 8 more standardized comparisons).",
        "cfi.divergence.service.DivergenceService.matrix",
    ),
    ToolDef(
        "get_market_regime",
        "The current classified market regime, confidence, and contributing/contradicting metrics.",
        "cfi.regime.service.RegimeService.current",
    ),
    ToolDef(
        "find_historical_similar_periods",
        "The most similar historical periods by feature "
        "distance, with their forward-return distributions.",
        "cfi.similarity.service.SimilarityService.current",
    ),
    ToolDef(
        "get_anomalies",
        "Every tracked metric's current percentile-band anomaly reading.",
        "cfi.anomaly.service.AnomalyService.scan",
    ),
    ToolDef(
        "get_capital_rotation",
        "The Phase 20 capital-rotation matrix: OBSERVED share moves "
        "and INFERRED rotation hypotheses with flow corroboration.",
        "cfi.rotation.service.RotationService.matrix",
    ),
    ToolDef(
        "check_data_quality",
        "A cross-tool summary of missing, stale and conflicting data "
        "quality across every other tool call in this snapshot.",
        "computed over this snapshot",
    ),
)

TOOLS_BY_ID: dict[str, ToolDef] = {t.tool_id: t for t in TOOLS}

# Every known-limitation disclosure this analyst must surface rather than silently smooth over
# (Section 18's explicit scope boundary — these are pre-existing platform limitations from Phases
# 13/19/20, restated here so the AI context carries them without changing any underlying metric).
KNOWN_PLATFORM_LIMITATIONS: tuple[str, ...] = (
    "Mid-cap, DeFi and AI-related asset categories have no tracked universe at all (Phase 20) — "
    "'large caps' means only this platform's own 4-asset universe (BTC/ETH/SOL/XRP).",
    "Meme assets are tracked only as a retail-attention proxy (trending-count), never a "
    "capital-flow or market-share measure (Phase 13/20).",
    "An inferred capital rotation is a hedged hypothesis about two nodes' share directions moving "
    "opposite ways — it is never proof that capital moved from one asset to the other (Phase 20).",
    "flow_corroboration has no institutional/whale flow data for stablecoin or untracked nodes "
    "(reports 'not_applicable') — this is a genuine data gap, not evidence against the hypothesis.",
    "Whale flows and exchange flows read the same underlying on-chain series (Phase 19) — this "
    "platform has no aggregate exchange-wallet flow independent of that dataset.",
    "Historical similarity search reports a distribution of forward outcomes across analogue "
    "periods; it is never a prediction that any single outcome will repeat (Phase 15).",
    "Wallet/entity classifications (institution, ETF, exchange, market maker, whale) carry "
    "their own evidence_class (direct/attributed/inferred) and confidence — large does not "
    "mean institutional, and an unlabelled large wallet must never be attributed to a named "
    "entity (R5).",
)
