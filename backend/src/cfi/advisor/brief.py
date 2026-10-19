"""``advisor_brief.v0``: one asset's evidence, uncertainty, gaps, risks and invalidation conditions.

Phase 53 (ADR-0093). A pure function of two finished contracts built from the same stored snapshot,
so it is database-free, network-free and clock-free; same inputs give the same brief. It follows
CLAUDE.md A2/A3 and R6:

- It never decides. Stance, confidence, posture, risk levels, decision state and every invalidation
  result are copied verbatim from ``decision_view.v0`` / ``investment_decision.v0``; nothing is
  recomputed, strengthened or softened. Removing information can only add a data gap.
- Unavailable is not neutral. A reading that is missing, insufficient, stale, partial or not
  assessed is listed under ``data_gaps`` with its own state and is never counted as a signal.
- Layers are labelled, not merged. Each item carries a ``layer`` from the closed ``LAYERS``
  vocabulary (observed data, calculated signal, regime assessment, historical analogue, hypothesis,
  risk reading, context reading, deterministic assessment). The label is presentation only, taken
  from the source domain; it adds no evidence class that the source does not already have.
- Every item links to snapshot field IDs; ``field_trace`` resolves those IDs to the snapshot's own
  display text and evidence category where the decision view carries them, and says so when not.
- ``NOT_CLAIMED`` states what the brief is not: not personalized advice, not a prediction, not a
  profitability claim, no trade, no account connection.

No Claude call is made here. Language models may later narrate a finished brief; they may not
change it (A3).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

__all__ = [
    "CONTRACT_VERSION",
    "DOMAIN_LAYERS",
    "LAYERS",
    "NOT_CLAIMED",
    "AdvisorInputError",
    "build_advisor_brief",
]

CONTRACT_VERSION: Final = "advisor_brief.v0"
DECISION_CONTRACT: Final = "decision_view.v0"
INVESTMENT_CONTRACT: Final = "investment_decision.v0"


class AdvisorInputError(ValueError):
    """The two source contracts are missing, of another version, or about different snapshots."""


# Closed layer vocabulary (presentation labels; definitions are shown to the reader).
LAYERS: Final[dict[str, str]] = {
    "observed_data": "A stored observation (price, volume), as recorded.",
    "calculated_signal": "A metric or score the platform computed from observed data.",
    "regime_assessment": "The platform's classified market regime; context, not a vote.",
    "historical_analogue": "A description of similar past periods; never a prediction.",
    "hypothesis": "An inferred, hedged explanation; never an observed fact.",
    "risk_reading": "A risk or stress reading; not directional evidence.",
    "context_reading": "Other context the platform reports.",
    "deterministic_assessment": "A rule-based synthesis of the above (not a forecast).",
}

# Source domain -> layer. Anything not listed is a ``context_reading`` (never silently a signal).
DOMAIN_LAYERS: Final[dict[str, str]] = {
    "institutional": "calculated_signal",
    "whale": "calculated_signal",
    "liquidity": "calculated_signal",
    "macro": "calculated_signal",
    "market_structure": "calculated_signal",
    "divergence": "calculated_signal",
    "market_data": "observed_data",
    "regime": "regime_assessment",
    "similarity": "historical_analogue",
    "rotation": "hypothesis",
    "derivatives": "risk_reading",
    "anomaly": "risk_reading",
    "retail": "risk_reading",
}

NOT_CLAIMED: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "ADV-NOT-ADVICE",
        "text": "This is general market context. It does not know your goals, horizon, holdings "
        "or risk tolerance, and it is not personalized financial advice.",
    },
    {
        "id": "ADV-NOT-PREDICTION",
        "text": "Nothing here predicts a price or an outcome. Stance, confidence and decision "
        "state describe how far the stored evidence goes, not what will happen.",
    },
    {
        "id": "ADV-NOT-PROFITABILITY",
        "text": "Historical validation of this platform is descriptive only. It does not show "
        "that any signal or state is profitable or predictive.",
    },
    {
        "id": "ADV-HYPOTHESES-ARE-NOT-FACTS",
        "text": "Items labelled hypothesis or historical analogue are interpretations of the "
        "data, not observed facts, and are not proof of what any investor or wallet did.",
    },
    {
        "id": "ADV-NO-TRADING",
        "text": "This service places no orders and connects to no exchange or trading account.",
    },
    {
        "id": "ADV-UNAVAILABLE-IS-NOT-NEUTRAL",
        "text": "Missing, stale or insufficient evidence is reported as a gap. It is never "
        "counted as neutral, supportive or adverse.",
    },
)

_NOT_AVAILABLE_STATES = frozenset({"available", "available_freshness_not_assessed"})


def _layer(domain: str) -> str:
    return DOMAIN_LAYERS.get(domain, "context_reading")


def _field_ids(*groups: Iterable[Any]) -> list[str]:
    seen: dict[str, None] = {}
    for group in groups:
        for fid in group:
            seen.setdefault(str(fid), None)
    return list(seen)


def _require(decision: dict[str, Any], investment: dict[str, Any], asset: str) -> dict[str, Any]:
    if decision.get("contract_version") != DECISION_CONTRACT:
        raise AdvisorInputError(
            f"expected {DECISION_CONTRACT}, got {decision.get('contract_version')!r}"
        )
    if investment.get("contract_version") != INVESTMENT_CONTRACT:
        raise AdvisorInputError(
            f"expected {INVESTMENT_CONTRACT}, got {investment.get('contract_version')!r}"
        )
    if decision.get("asset") != asset:
        raise AdvisorInputError(f"decision view is for {decision.get('asset')!r}, not {asset!r}")
    d_hash = decision["snapshot"]["producer_payload_hash"]
    i_hash = investment["snapshot"]["producer_payload_hash"]
    d_input = decision["snapshot"]["decision_input_hash"]
    i_input = investment["snapshot"]["decision_input_hash"]
    if d_hash != i_hash or d_input != i_input:
        raise AdvisorInputError("the two contracts were built from different snapshots")
    entry = investment["assets"].get(asset)
    if not isinstance(entry, dict):
        raise AdvisorInputError(f"the investment decision has no entry for {asset!r}")
    return entry


def build_advisor_brief(
    decision_view: dict[str, Any], investment_decision: dict[str, Any], asset: str
) -> dict[str, Any]:
    """Compose the brief for ``asset``. Raises ``AdvisorInputError`` for inconsistent inputs."""
    inv = _require(decision_view, investment_decision, asset)

    stance = dict(decision_view["stance"])
    binding_caps = [
        {"rule_id": c["rule_id"], "kind": "cap_u", "ceiling": c["applied_ceiling"]}
        for c in decision_view["cap_u"]
        if c["binding"]
    ] + [
        {"rule_id": c["rule_id"], "kind": "observed_cap", "ceiling": c["ceiling"]}
        for c in decision_view["observed_caps"]
        if c["binding"]
    ]

    # ---- signals: the decision engine's own evidence items, labelled by layer
    signals: list[dict[str, Any]] = []
    for side in ("supportive", "adverse", "neutral"):
        for item in decision_view["evidence"][side]:
            signals.append(
                {
                    "layer": _layer(item["domain"]),
                    "side": side,
                    "domain": item["domain"],
                    "scope": (item.get("scope_label") or {}).get("code"),
                    "strength": item["strength"],
                    "band": item["band"],
                    "text": item["text"],
                    "quality_flags": list(item["quality_flags"]),
                    "field_ids": list(item["field_ids"]),
                }
            )

    # ---- readings: every domain the decision engine read, with its own evidence state
    readings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for d in decision_view["domains"]:
        state = d["evidence_state"]
        readings.append(
            {
                "layer": _layer(d["domain"]),
                "domain": d["domain"],
                "role": d["role"],
                "evidence_state": state,
                "status": d["status"],
                "freshness": d["freshness"],
                "direction": d["direction"],
                "strength": d["strength"],
                "band": d["band"],
                "quality_flags": list(d["quality_flags"]),
            }
        )
        if state not in _NOT_AVAILABLE_STATES:
            gaps.append(
                {
                    "kind": "reading_not_usable",
                    "domain": d["domain"],
                    "evidence_state": state,
                    "reasons": [r["text"] for r in d["reasons"]],
                }
            )
    cov = decision_view["coverage"]
    gaps.extend({"kind": "missing_directional_domain", "domain": m} for m in cov["missing"])
    gaps.extend({"kind": "missing_context", "domain": m} for m in cov["missing_context"])
    dq = decision_view["data_quality"]
    for key, kind in (
        ("unavailable_components", "unavailable_component"),
        ("stale_components", "stale_component"),
        ("partial_components", "partial_component"),
        ("not_assessed_components", "not_assessed_component"),
        ("unavailable_tools", "unavailable_tool"),
        ("degraded_tools", "degraded_tool"),
        ("look_ahead_violations", "look_ahead_violation"),
    ):
        gaps.extend({"kind": kind, "ref": ref} for ref in dq[key])
    for unresolved in inv["why_not_conclusive"]:
        gaps.append(
            {
                "kind": "investment_state_not_conclusive",
                "reason_id": unresolved["reason_id"],
                "ref": unresolved["ref"],
            }
        )
    for ref in inv["evidence"]["missing_or_unusable"]:
        gaps.append(
            {
                "kind": "investment_evidence_unusable",
                "domain": ref["domain"],
                "evidence_state": ref["state"],
                "reason": ref["exclusion_reason"],
            }
        )

    conflict = dict(decision_view["conflict"])
    uncertainty = {
        "confidence": stance["confidence"],
        "directional_conflict": conflict["directional"],
        "contradictions": list(conflict["contradictions"]),
        "conflicting_tools": list(conflict["conflicting_tools"]),
        "limited_by_caps": stance["differs_from_raw"] or stance["cap_u_applied"],
        "binding_caps": binding_caps,
        "limitations": [x["text"] for x in decision_view["limitations"] if x["text"]],
        "scope_notes": list(decision_view["scope_notes"]),
        "missing_context": [
            x["text"] for x in decision_view["why"]["missing_context"] if x["text"]
        ],
    }

    risk = {
        "decision_risks": [
            {"dimension": r["dimension"], "level": r["level"], "text": r["text"]}
            for r in decision_view["risks"]
        ],
        "max_decision_risk": decision_view["max_risk"],
        "investment_risk_assessment": dict(inv["risk_assessment"]),
        "market_risks_detected": list(inv["market_risks_detected"]),
        "findings": _findings(inv.get("risk_findings")),
    }

    invalidation = inv.get("invalidation")
    invalidation_out: dict[str, Any] | None = None
    field_groups: list[list[str]] = [s["field_ids"] for s in signals]
    if invalidation is not None:
        invalidation_out = {
            "summary": invalidation["summary"],
            "conditions": [
                {
                    "condition_id": c["condition_id"],
                    "name": c["name"],
                    "meaning": c["meaning"],
                    "result": c["result"],
                    "monitor_field_ids": list(c["monitor_field_ids"]),
                }
                for c in invalidation["conditions"]
            ],
        }
        field_groups.extend(c["monitor_field_ids"] for c in invalidation["conditions"])
    reassessment = [
        {
            "kind": r["kind"],
            "ref": r["ref"],
            "when": r["when"],
            "evaluable": r["evaluable"],
            "field_ids": list(r["field_ids"]),
        }
        for r in inv["reassessment"]
    ]
    field_groups.extend(r["field_ids"] for r in reassessment)
    if risk["findings"]:
        field_groups.extend(f["field_ids"] for items in risk["findings"].values() for f in items)

    known = {f["field_id"]: f for f in decision_view["technical"]["fields"]}
    field_trace: dict[str, dict[str, Any]] = {}
    for fid in _field_ids(*field_groups):
        f = known.get(fid)
        field_trace[fid] = (
            {
                "display": f["display"],
                "evidence_category": f["evidence_category"],
                "quality_status": f["quality_status"],
                "unit": f["unit"],
                "source": f["source"],
            }
            if f
            else {"display": None, "note": "no display text in the stored snapshot fields"}
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "asset": asset,
        "answered_from": {
            "decision_view": decision_view["contract_version"],
            "investment_decision": investment_decision["contract_version"],
            "decision_methodology": decision_view["methodology"]["methodology_version"],
            "investment_parameters": investment_decision["parameters"]["version"],
        },
        "snapshot": dict(decision_view["snapshot"]),
        "layers": dict(LAYERS),
        "assessment": {
            "layer": "deterministic_assessment",
            "stance": stance,
            "why": {
                "directional": [
                    x["text"] for x in decision_view["why"]["directional"] if x["text"]
                ],
                "limits": [x["text"] for x in decision_view["why"]["limits"] if x["text"]],
            },
            "investment_state": {
                "status": inv["status"],
                "discovery_type": inv["discovery_type"],
                "decision_state": inv["decision_state"],
                "decision_reasons": list(inv["decision_reasons"]),
                "gated": not investment_decision["assessment"]["performed"],
                "gate_reasons": list(investment_decision["assessment"]["gate_reasons"]),
            },
            "state_notice": investment_decision["notice"]["text"],
        },
        "signals": signals,
        "readings": readings,
        "uncertainty": uncertainty,
        "data_gaps": {"has_gaps": bool(gaps), "items": gaps},
        "risk": risk,
        "invalidation": invalidation_out,
        "reassessment": reassessment,
        "field_trace": field_trace,
        "not_claimed": [dict(n) for n in NOT_CLAIMED],
    }


def _findings(groups: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]] | None:
    if groups is None:
        return None
    return {
        name: [
            {
                "check_id": f["check_id"],
                "category": f["category"],
                "result": f["result"],
                "level": f["level"],
                "field_ids": list(f["field_ids"]),
            }
            for f in items
        ]
        for name, items in groups.items()
    }
