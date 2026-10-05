"""The fixed beginner template library (``decision_templates.v0``) and its safety lint.

Every explanatory text in an assessment is a template id from this library: the engine never
generates free-form prose (methodology section 13). The assessment's stance, confidence and posture
are closed-enum identifiers; the exact stance/posture labels are UI identifiers and are not
templates. No sentence here contains a digit, a forecast, a probability, certainty language or a
trading instruction.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Final

__all__ = [
    "EXACT_MATCH_EXEMPT_IDS",
    "LINT_RULES",
    "TEMPLATES",
    "lint_library",
    "lint_text",
    "render",
]


def _dir(domain: str, s2: str, s1: str, n: str, a1: str, a2: str, u: str) -> dict[str, str]:
    return {
        f"DIR.{domain}.S2": s2,
        f"DIR.{domain}.S1": s1,
        f"DIR.{domain}.N": n,
        f"DIR.{domain}.A1": a1,
        f"DIR.{domain}.A2": a2,
        f"DIR.{domain}.U": u,
    }


def _risk(dim: str, low: str, mod: str, elev: str, high: str, na: str | None) -> dict[str, str]:
    out = {
        f"RISK.{dim}.Low": low,
        f"RISK.{dim}.Moderate": mod,
        f"RISK.{dim}.Elevated": elev,
        f"RISK.{dim}.High": high,
    }
    if na is not None:
        out[f"RISK.{dim}.Not assessed"] = na
    return out


_LIBRARY: dict[str, str] = {}
_LIBRARY.update(
    _dir(
        "institutional",
        "Money is flowing into US spot Bitcoin funds at an unusually strong pace.",
        "More money is flowing into US spot Bitcoin funds than out of them.",
        "Flows into and out of US spot Bitcoin funds are roughly balanced.",
        "More money is leaving US spot Bitcoin funds than entering them.",
        "Money is leaving US spot Bitcoin funds at an unusually strong pace.",
        "We cannot currently confirm whether large institutional investors are adding or "
        "reducing exposure because institutional-flow data is unavailable.",
    )
)
_LIBRARY.update(
    _dir(
        "whale",
        "Large wallets are adding to their holdings at a strong pace.",
        "Large wallets are currently adding to their holdings.",
        "Large-wallet activity is balanced; neither accumulation nor distribution stands out.",
        "Large wallets are currently reducing their holdings.",
        "Large wallets are reducing their holdings at a strong pace.",
        "We cannot currently confirm what large wallets are doing because large-wallet data "
        "is unavailable.",
    )
)
_LIBRARY.update(
    _dir(
        "liquidity",
        "New money is entering through stablecoins at a strong pace.",
        "More new money is entering through stablecoins.",
        "The supply of stablecoins is roughly steady.",
        "Less new money is entering through stablecoins.",
        "The supply of stablecoins is shrinking at a strong pace.",
        "We cannot currently measure stablecoin money flows because stablecoin supply data "
        "is unavailable.",
    )
)
_LIBRARY.update(
    _dir(
        "macro",
        "The broader economic backdrop is broadly accommodative.",
        "The broader economic backdrop is improving.",
        "The broader economic backdrop is mixed.",
        "The broader economic backdrop is tightening.",
        "The broader economic backdrop is broadly restrictive.",
        "We cannot currently describe the broader economic backdrop because macroeconomic "
        "data is unavailable.",
    )
)
_LIBRARY.update(
    _dir(
        "market_structure",
        "Price trend, momentum and breadth are broadly constructive.",
        "Price trend and breadth are improving.",
        "Price trend and breadth are mixed.",
        "Price trend and breadth are deteriorating.",
        "Price trend and breadth are broadly weak.",
        "We cannot currently describe price structure because market-structure data is "
        "unavailable.",
    )
)
_LIBRARY.update(
    {
        "SUFFIX.stale": "This reading is older than expected, so it is treated as weaker evidence.",
        "SUFFIX.partial": "Some inputs behind this reading are missing, so it is treated as "
        "weaker evidence.",
    }
)
_LIBRARY.update(
    _risk(
        "market",
        "The broader market backdrop shows no strong warning signs.",
        "The broader market backdrop is mixed or unclear.",
        "The broader market backdrop shows some warning signs.",
        "The broader market backdrop shows strong warning signs.",
        "We cannot currently assess broader market risk because the underlying data is "
        "unavailable.",
    )
)
_LIBRARY.update(
    _risk(
        "liquidity",
        "Stablecoin money flows show no strain.",
        "Stablecoin money flow data is partly stale or incomplete.",
        "Stablecoin money flows are weakening.",
        "Stablecoin money flows are weakening sharply.",
        "We cannot currently assess liquidity risk because stablecoin supply data is unavailable.",
    )
)
_LIBRARY.update(
    _risk(
        "leverage",
        "Leverage in the market looks normal; there is no strong sign of stress.",
        "Leverage is somewhat above normal.",
        "Leverage shows signs of stress.",
        "Traders are using unusually heavy leverage, which can make sharp moves more likely "
        "in either direction.",
        "We cannot currently assess leverage because derivatives data is unavailable.",
    )
)
_LIBRARY.update(
    _risk(
        "volatility",
        "Recent price swings are within their usual range.",
        "Recent price swings are unusually quiet.",
        "Recent price swings are larger than usual.",
        "Recent price swings are at an unusually extreme level.",
        "We cannot currently assess volatility because the comparison data is unavailable.",
    )
)
_LIBRARY.update(
    _risk(
        "narrative",
        "Speculative activity looks ordinary.",
        "Speculative activity is somewhat above ordinary.",
        "Speculative activity is running hot.",
        "Speculative activity is running very hot and positioning is crowded toward rising prices.",
        "We cannot currently assess speculative activity because retail-proxy data is unavailable.",
    )
)
_LIBRARY.update(
    _risk(
        "data_quality",
        "All expected evidence is present and current.",
        "Some expected evidence is missing, stale or incomplete.",
        "Several expected pieces of evidence are missing, stale or incomplete.",
        "Most expected evidence is missing, stale or incomplete.",
        None,
    )
)
_LIBRARY.update(
    {
        "CTX.regime.accumulation": "The regime model reads the market as being in an "
        "accumulation phase.",
        "CTX.regime.recovery": "The regime model reads the market as being in a recovery phase.",
        "CTX.regime.expansion": "The regime model reads the market as being in an expansion phase.",
        "CTX.regime.euphoria": "The regime model reads the market as being in a euphoric phase.",
        "CTX.regime.distribution": "The regime model reads the market as being in a "
        "distribution phase.",
        "CTX.regime.capitulation": "The regime model reads the market as being in a "
        "capitulation phase.",
        "CTX.regime.mixed_unclear": "The regime model finds the market state mixed or unclear.",
        "CTX.regime.U": "We cannot currently describe the market regime because the regime "
        "model has insufficient data.",
        "CTX.similarity.ok": "Past periods with comparable conditions exist in the platform's "
        "history; this is historical context only.",
        "CTX.similarity.U": "We cannot currently find comparable past periods because there is "
        "insufficient data.",
        "CTX.divergence.true": "At least one pair of market participants is behaving "
        "differently from the other.",
        "CTX.divergence.false": "No participant pair currently shows a notable difference in "
        "behavior.",
        "CTX.divergence.U": "We cannot currently compare participant behavior because the data "
        "is unavailable.",
        "CTX.rotation.possible": "Some measures suggest money may be moving between crypto "
        "sectors; this is an inference, not a confirmed movement.",
        "CTX.rotation.none": "No reliable evidence currently shows money moving broadly into "
        "other crypto sectors.",
        "CTX.rotation.U": "We cannot currently assess movement between crypto sectors because "
        "the data is unavailable.",
        "CTX.anomaly.extreme": "At least one measure is at an unusually extreme level compared "
        "with its own history.",
        "CTX.anomaly.notable": "At least one measure is at an unusual level compared with its "
        "own history.",
        "CTX.anomaly.none": "No measure is currently at an unusual level compared with its own "
        "history.",
        "CTX.anomaly.U": "We cannot currently compare measures with their own history because "
        "the data is unavailable.",
        "CTX.regime.missing": "Regime context is unavailable; the directional classification is "
        "based on the available underlying evidence.",
    }
)
_LIBRARY.update(
    {
        "STANCE.Strongly Bullish": "Nearly all available evidence is on the constructive side, "
        "with at least one strong reading.",
        "STANCE.Bullish": "Most available evidence is on the constructive side.",
        "STANCE.Cautiously Bullish": "The available evidence leans constructive, but not by a "
        "wide margin.",
        "STANCE.Neutral / Wait": "The available evidence does not clearly favor either side.",
        "STANCE.Cautiously Bearish": "The available evidence leans adverse, but not by a wide "
        "margin.",
        "STANCE.Bearish": "Most available evidence is on the adverse side.",
        "STANCE.Strongly Bearish": "Nearly all available evidence is on the adverse side, with "
        "at least one strong reading.",
        "STANCE.Insufficient Evidence": "Insufficient data.",
        "STANCE.note": "This is a classification of today's evidence, not a prediction of price.",
        "CONF.High": "The available evidence is complete and consistent for this classification.",
        "CONF.Moderate": "The available evidence supports this classification, with some gaps "
        "or caveats.",
        "CONF.Low": "The available evidence only weakly supports this classification.",
        "CONF.Insufficient Evidence": "There is not enough evidence to support a classification.",
        "CONF.note": "Confidence describes how well the available evidence supports this "
        "classification, not the chance that price rises or falls.",
        "POSTURE.INVESTIGATE FURTHER": "There is not enough evidence for guidance, so the first "
        "step is to find out why data is missing.",
        "POSTURE.WAIT FOR CONFIRMATION": "The evidence is mixed, conflicting or contradicted by "
        "the market regime, so further confirmation is needed before conclusions are drawn.",
        "POSTURE.MONITOR WITH ELEVATED CAUTION": "The evidence leans constructive, but caveats "
        "or elevated risk remain, so careful observation is the general posture.",
        "POSTURE.MONITOR CONSTRUCTIVE CONDITIONS": "The evidence is broadly constructive, "
        "complete and not accompanied by elevated risk, so continued observation of these "
        "conditions is the general posture.",
        "POSTURE.REASSESS / REDUCE RISK": "The evidence is broadly adverse, so reassessing risk "
        "is the general posture.",
        "POSTURE.AVOID ADDING HIGH-RISK EXPOSURE": "The evidence carries high risk, lacks key "
        "confirmation or leans adverse, so not adding high-risk exposure is the general "
        "posture.",
        "POSTURE.note": "The platform does not know the user's goals, horizon, holdings, risk "
        "tolerance or financial circumstances. Guidance is general and is not personalized "
        "financial advice.",
        "CAPU.regime": "Regime context is unavailable, so the safety limit that depends on it "
        "could not be checked; the classification is held at neutral until it can be.",
        "CAPU.derivatives": "Derivatives data is unavailable, so the stress limit that depends "
        "on it could not be checked; the classification is held at its most cautious "
        "constructive level.",
        "CAPU.anomaly": "Unusual-level data is unavailable, so the extreme-reading limit that "
        "depends on it could not be checked; the classification is held at its most cautious "
        "constructive level.",
        "CAPU.frame.directional": "Directional evidence: the available readings, taken on their "
        "own, support the classification shown as the directional evidence.",
        "CAPU.frame.limit": "Safety limit: the final classification is held below that level "
        "because a safety source could not be checked.",
        "CAPU.frame.missing": "Missing context: the source that could not be checked is listed "
        "separately and is not evidence in either direction.",
        "LIMIT.derivatives_freshness": "Freshness of derivatives data is not assessed, so it is "
        "neither confirmed as current nor treated as stale.",
        "CONFLICT.phrase": "Sources conflict.",
        "CONFLICT.pair": "Some available evidence points in opposite directions and has not "
        "been averaged away.",
        "CAP.RC-01": "Derivatives stress is high, so the classification is limited to its most "
        "cautious constructive level.",
        "CAP.RC-02": "A measure is at an extreme level compared with its own history, so the "
        "classification is limited to its most cautious constructive level.",
        "CAP.RC-03": "The regime model reads a euphoric phase, so the classification is limited "
        "to its most cautious constructive level.",
        "CAP.RC-04": "The regime model reads a distribution or capitulation phase, which "
        "disagrees with the constructive evidence, so the classification is set to neutral.",
        "MISSING.not_tracked": "Mid-cap, DeFi, AI-related and meme assets: not tracked.",
        "MISSING.meme": "Meme-coin activity appears only as a retail-attention proxy, not as a "
        "tracked asset universe.",
    }
)

TEMPLATES: Final = MappingProxyType(_LIBRARY)

# Fixed disclaimers that must name the thing they disclaim (exact-string exemption from TL-07/08).
EXACT_MATCH_EXEMPT_IDS: Final = frozenset({"STANCE.note", "CONF.note", "POSTURE.note"})

_VERBS = [
    "buy",
    "sell",
    "hold",
    "enter",
    "exit",
    "add",
    "reduce",
    "avoid",
    "wait",
    "consider",
    "increase",
    "decrease",
    "open",
    "close",
    "trade",
    "invest",
    "take",
    "set",
    "use",
    "go",
    "stay",
    "keep",
    "start",
    "stop",
    "accumulate",
    "load",
    "watch",
    "act",
    "switch",
    "move",
    "place",
]

LINT_RULES: Final = MappingProxyType(
    {
        "TL-01": re.compile(r"\bbuy(s|ing)?\b", re.IGNORECASE),
        "TL-02": re.compile(r"\bsell(s|ing)?\b", re.IGNORECASE),
        "TL-03": re.compile(r"\blong(s)?\b", re.IGNORECASE),
        "TL-04": re.compile(r"\bshort(s|ing)?\b", re.IGNORECASE),
        "TL-05": re.compile(
            r"\b(guarantee[sd]?|certain(ly)?|definite(ly)?|sure|surely|inevitabl[ey]|always|never)\b",
            re.IGNORECASE,
        ),
        "TL-06": re.compile(r"\bwill\b|won't|going to", re.IGNORECASE),
        "TL-07": re.compile(
            r"price target|target price|forecast|\bpredict(s|ed|ion)?\b|expected return|"
            r"\bupside\b|\bdownside\b",
            re.IGNORECASE,
        ),
        "TL-08": re.compile(r"\b(probabilit(y|ies)|odds|chances?)\b", re.IGNORECASE),
        "TL-09": re.compile(r"[0-9%]"),
        "TL-10": re.compile(r"\b(bullish|bearish)\b", re.IGNORECASE),
        # TL-11: a sentence beginning with an imperative trading verb.
        "TL-11": re.compile(rf"(?:^|[.!?]\s+)(?:{'|'.join(_VERBS)})\b", re.IGNORECASE),
    }
)
_EXEMPT_FROM_NOTE: Final = frozenset({"TL-07", "TL-08"})


def lint_text(text: str, *, exact_exempt: bool = False) -> list[str]:
    """Rule ids (TL-xx) the text violates. ``exact_exempt`` applies the documented exemption of the
    three fixed disclaimers from TL-07/TL-08."""
    return [
        rule_id
        for rule_id, pattern in LINT_RULES.items()
        if pattern.search(text) and not (exact_exempt and rule_id in _EXEMPT_FROM_NOTE)
    ]


def lint_library() -> dict[str, list[str]]:
    """Violations per template id (empty dict means the whole library is clean)."""
    out: dict[str, list[str]] = {}
    for template_id, sentence in TEMPLATES.items():
        found = lint_text(sentence, exact_exempt=template_id in EXACT_MATCH_EXEMPT_IDS)
        if found:
            out[template_id] = found
    return out


def render(template_ids: tuple[str, ...] | list[str]) -> str:
    """Join template sentences. Raises ``KeyError`` for an id that is not in the library."""
    return " ".join(TEMPLATES[t] for t in template_ids)
