"""Versioned parameters and fixed vocabulary for the Daily Market Brief (Phase 22 spec). Nothing
here is fitted to data (R13): the section order is the user's own explicit Phase 22 spec (Section
4), and the extra banned-language patterns are a structural, testable enforcement of Section 7
("no automatic trading advice"), the same discipline ``cfi.analyst.universe`` already applies to
the Phase 21 analyst.

This module does NOT redesign ``cfi.analyst.universe`` or ``cfi.analyst.schema.AnalystResponse``
(Section 2) — it reuses that module's own banned-language set, domain-to-tool map, and the
"Insufficient data."/"Sources conflict." phrases by import, and adds only what Phase 21 never
needed: long/short-as-a-position-directive and position-sizing language (Phase 21 produces no
"position" concept at all), and this phase's own 15-section response shape.
"""

from __future__ import annotations

import re

from cfi.analyst.universe import (
    BANNED_PATTERNS as _ANALYST_BANNED_PATTERNS,
)
from cfi.analyst.universe import (
    DOMAIN_TOOL_IDS,
    INSUFFICIENT_DATA_PHRASE,
    KNOWN_PLATFORM_LIMITATIONS,
    SOURCES_CONFLICT_PHRASE,
)

__all__ = [
    "BANNED_PATTERNS",
    "BRIEF_ANALYST_VERSION",
    "BRIEF_PROMPT_VERSION",
    "BRIEF_RESPONSE_SCHEMA_VERSION",
    "INSUFFICIENT_DATA_PHRASE",
    "KNOWN_PLATFORM_LIMITATIONS",
    "LIST_SECTIONS",
    "MARKET_REGIME_TOOL_ID",
    "MAX_VALIDATION_ATTEMPTS",
    "RESPONSE_SECTIONS",
    "SECTION_TOOL_IDS",
    "SOURCES_CONFLICT_PHRASE",
]

# --------------------------------------------------------------------------- versioning
# (Section 8: the brief must be reproducible from, among other things, "prompt version" and
# "analyst version" — both independent of Phase 21's own `cfi.analyst.universe.PROMPT_VERSION`/
# `RESPONSE_SCHEMA_VERSION`, since this is a different artifact over the same evidence, never a
# redesign of the analyst's own response shape.)

BRIEF_PROMPT_VERSION = "brief_prompt.v1"
BRIEF_RESPONSE_SCHEMA_VERSION = "brief_response.v1"
BRIEF_ANALYST_VERSION = "brief_analyst.v1"

MAX_VALIDATION_ATTEMPTS = 2  # one Claude call, one retry with the validator's own errors appended

# --------------------------------------------------------------------------- required output shape
# (Phase 22 spec, Section 4 — the user's own literal 15-section list, in this exact order.)

RESPONSE_SECTIONS = (
    "executive_summary",
    "market_regime",
    "institutional_activity",
    "whale_activity",
    "retail_activity",
    "derivatives_liquidity",
    "macro",
    "market_structure",
    "divergences_anomalies",
    "capital_rotation",
    "historical_context",
    "contradicting_evidence",
    "risks_uncertainties",
    "what_to_monitor",
    "data_quality",
)
if len(RESPONSE_SECTIONS) != 15:  # pragma: no cover - module-invariant guard
    raise ValueError("RESPONSE_SECTIONS must have exactly the 15 sections the Phase 22 spec lists")

# The sections whose value is a flat `list[BriefEvidenceItem]` (every section except the two prose
# strings `executive_summary`/`data_quality`, the two plain-string lists `risks_uncertainties`/
# `what_to_monitor`, and `market_regime`, which is its own nested object — see
# `cfi.brief.schema.MarketRegimeSection`).
LIST_SECTIONS = (
    "institutional_activity",
    "whale_activity",
    "retail_activity",
    "derivatives_liquidity",
    "macro",
    "market_structure",
    "divergences_anomalies",
    "capital_rotation",
    "historical_context",
    "contradicting_evidence",
)

# Which existing Phase-21-analyst tool(s) ground each list section's own `field_ids` — reused
# directly from `cfi.analyst.universe.DOMAIN_TOOL_IDS` (R13: no parallel identification scheme). A
# section naming more than one tool (e.g. "derivatives_liquidity") may cite either; a domain's own
# field may still only be cited from within a section that is allowed to cite that domain.
SECTION_TOOL_IDS: dict[str, tuple[str, ...]] = {
    "institutional_activity": (DOMAIN_TOOL_IDS["institutional"],),
    "whale_activity": (DOMAIN_TOOL_IDS["whale"],),
    "retail_activity": (DOMAIN_TOOL_IDS["retail"],),
    "derivatives_liquidity": (DOMAIN_TOOL_IDS["derivatives"], DOMAIN_TOOL_IDS["liquidity"]),
    "macro": (DOMAIN_TOOL_IDS["macro"],),
    "market_structure": (DOMAIN_TOOL_IDS["market_structure"],),
    "divergences_anomalies": (DOMAIN_TOOL_IDS["divergences"], DOMAIN_TOOL_IDS["anomalies"]),
    "capital_rotation": (DOMAIN_TOOL_IDS["capital_rotation"],),
    "historical_context": ("find_historical_similar_periods",),
    # Contradicting Evidence (Section 4, item 12) exists precisely to cross-reference evidence
    # against the dominant interpretation, so it may legitimately cite any domain's own tool.
    "contradicting_evidence": tuple(DOMAIN_TOOL_IDS.values()),
}

MARKET_REGIME_TOOL_ID = "get_market_regime"

# --------------------------------------------------------------------------- banned language
# (Section 7 — reuses every pattern the analyst already enforces (R1), plus what Phase 21 never
# needed to ban because it has no "position" concept at all.)

BANNED_PATTERNS: dict[str, re.Pattern[str]] = dict(_ANALYST_BANNED_PATTERNS)

# Explicit long/short *position* directives (bare "long"/"short" remain ordinary descriptive words
# — "long positioning", "short interest" — same posture `cfi.analyst.universe.DIRECTIVE_LANGUAGE`
# already takes for bare "buy"/"sell").
_BRIEF_DIRECTIVE_LANGUAGE = re.compile(
    r"\b(enter (?:a )?long|enter (?:a )?short|take a long position|take a short position|"
    r"open a long|open a short|go long (?:btc|eth|sol|xrp)|go short (?:btc|eth|sol|xrp))\b",
    re.IGNORECASE,
)

# Position-sizing instructions (Section 7) — Phase 21 never produces a "position" concept at all.
_BRIEF_POSITION_SIZING_LANGUAGE = re.compile(
    r"\b(position siz(?:e|ing)|allocate \d+\s*%|risk \d+\s*%\s*(?:of|per)|"
    r"stop[- ]loss at|take[- ]profit at)\b",
    re.IGNORECASE,
)

# A price target presented as a certainty (Section 7) — a price *level* described as evidence or a
# scenario condition is fine; what is banned is asserting it will certainly occur.
_BRIEF_PRICE_TARGET_CERTAINTY_LANGUAGE = re.compile(
    r"\bwill (?:definitely |certainly )?(?:hit|reach|rally to|crash to|go to)\s*\$?\d",
    re.IGNORECASE,
)

BANNED_PATTERNS["brief_directive_language (long/short position instruction)"] = (
    _BRIEF_DIRECTIVE_LANGUAGE
)
BANNED_PATTERNS["brief_position_sizing_language (position sizing instruction)"] = (
    _BRIEF_POSITION_SIZING_LANGUAGE
)
BANNED_PATTERNS["brief_price_target_certainty_language (price target as certainty)"] = (
    _BRIEF_PRICE_TARGET_CERTAINTY_LANGUAGE
)
