"""Investment Decision (Phase 49; ADR-0086): an explainable decision state per opportunity.

Pure and deterministic: no database, network, clock or model. Inputs are the four contracts of one
stored snapshot: ``opportunity_discovery.v0`` (Phase 46), ``opportunity_ranking.v0`` (Phase 47),
``risk_invalidation.v0`` (Phase 48) and ``risk_view.v0`` (the decision engine's own risk results,
needed to verify Phase 48). The supplied ranking and risk are the ones reported: Phase 48's public
builder validates them (it recomputes the ranking and checks equality) and the supplied risk must
equal what that builder returns. A mismatch is refused, never replaced.

Nothing is scored or ranked here and no numeric value is produced. The Phase 47 rank is context
only.
Each asset gets one closed decision state chosen by a documented precedence; every upstream
finding, invalidation result, missing item and limitation is still reported whatever the state.
A candidate is never called safe and never a confirmed thesis. The Decision Intelligence stance and
posture (``cfi.decision``) are neither read nor shown. Unsupported, malformed or inconsistent input
raises ``InvestmentInputError``; no partial result is produced."""

from __future__ import annotations

import copy
from typing import Any, Final

from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence.investment_universe import (
    DETECTED_LIMITATION_CHECKS,
    INVESTMENT_PARAMS_V0,
    LIMITATIONS,
    NOTICE,
    PRECEDENCE,
    STATES,
    InvestmentParameters,
)
from cfi.intelligence.risk import (
    CONTRACT_VERSION as RISK_CONTRACT_VERSION,
)
from cfi.intelligence.risk import RiskInputError, _verified, build_risk_invalidation

__all__ = ["CONTRACT_VERSION", "InvestmentInputError", "build_investment_decision"]

CONTRACT_VERSION: Final = "investment_decision.v0"
_SCOPES: Final = tuple(SCOPE_DOMAINS)
_STATE_IDS: Final = tuple(s for s, _ in STATES)
_NON_CANDIDATE_STATE: Final = {
    "no_candidate": ("no_opportunity", "DI-NO-OPPORTUNITY"),
    "insufficient_evidence": ("insufficient_evidence", "DI-INSUFFICIENT-EVIDENCE"),
    "conflicting_evidence": ("contradicted_evidence", "DI-CONTRADICTED"),
    "blocked": ("withheld_integrity_gate", "DI-GATE-WITHHELD"),
}
_RESULT_GROUPS: Final = (
    "detected",
    "unverified",
    "unavailable",
    "not_applicable",
    "withheld",
    "passed",
)


class InvestmentInputError(ValueError):
    """An input is unsupported, malformed or inconsistent with another input."""


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise InvestmentInputError(message)


def _mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvestmentInputError(f"{what} must be a mapping")
    return value


def _list(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise InvestmentInputError(f"{what} must be a list")
    return value


def _validate(
    opp: object, ranking: object, risk: object, view: object
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    o = _mapping(opp, "the opportunities input")
    r = _mapping(ranking, "the ranking input")
    k = _mapping(risk, "the risk input")
    v = _mapping(view, "the risk view input")
    _need(
        k.get("contract_version") == RISK_CONTRACT_VERSION,
        f"the risk input must be {RISK_CONTRACT_VERSION!r}",
    )
    try:
        expected = build_risk_invalidation(o, r, v)
    except (
        RiskInputError
    ) as exc:  # also covers a ranking that is not derived from the opportunities
        raise InvestmentInputError(f"the inputs were refused by risk validation: {exc}") from exc
    _need(expected == k, "the risk output was not derived from these inputs")
    for scope in _SCOPES:
        _need(
            set(k["assets"][scope]) >= {"assessment", "findings", "invalidation"},
            f"{scope}: risk block",
        )
    return o, r, k


# ----------------------------------------------------------------------------- references
def _evidence_ref(m: object, scope: str) -> dict[str, Any]:
    e = _mapping(m, f"{scope}: every evidence member")
    _need(isinstance(e.get("domain"), str), f"{scope}: evidence member 'domain' must be a string")
    _need(isinstance(e.get("state"), str), f"{scope}: evidence member 'state' must be a string")
    for key in ("field_ids", "source_ids"):
        value = e.get(key, [])
        _need(
            isinstance(value, list) and all(isinstance(x, str) for x in value),
            f"{scope}: evidence member {key!r} must be a list of strings",
        )
    return {
        "domain": e["domain"],
        "component": e.get("component"),
        "family": e.get("family"),
        "state": e["state"],
        "scope_basis": e.get("scope_basis"),
        "shared_across_assets": e.get("shared_across_assets"),
        "direction": e.get("direction"),
        "strength": e.get("strength"),
        "freshness": e.get("freshness"),
        "freshness_verified": _verified(e),
        "quality_flags": list(e.get("quality_flags") or []),
        "source_ids": list(e.get("source_ids") or []),
        "field_ids": list(e.get("field_ids") or []),
        "exclusion_reason": e.get("exclusion_reason"),
    }


def _unique(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for r in refs:
        key = (r["domain"], r["component"], r["state"], tuple(r["field_ids"]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _evidence(scope: str, a: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    eligible = _unique([_evidence_ref(m, scope) for m in _list(a.get("evidence_refs"), "refs")])
    missing = _unique([_evidence_ref(m, scope) for m in _list(a.get("excluded_members"), "excl")])
    return {
        "supporting": [r for r in eligible if r["state"] == "supportive"],
        "contradicting": [r for r in eligible if r["state"] == "adverse"],
        "other_eligible": [r for r in eligible if r["state"] not in ("supportive", "adverse")],
        "missing_or_unusable": missing,
    }


def _finding_ref(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": f["check_id"],
        "category": f["category"],
        "scope": f["scope"],
        "result": f["result"],
        "level": f["level"],
        "reason_ids": list(f["reason_ids"]),
        "engine_reason_ids": list(f["engine_reason_ids"]),
        "freshness_verified": f["freshness_verified"],
        "field_ids": list(f["field_ids"]),
        "source_ids": list(f["source_ids"]),
    }


def _group(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    refs = [_finding_ref(f) for f in findings]
    return {g: [r for r in refs if r["result"] == g] for g in _RESULT_GROUPS}


# -------------------------------------------------------------------------- classification
def _classify_candidate(
    findings: list[dict[str, Any]], invalidation: dict[str, Any]
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Choose a candidate's state from Phase 48 findings and invalidation. Pure decision logic.

    ``findings`` are every Phase 48 finding that applies to the candidate (integrity, market-wide
    and asset). Returns the state, its reason codes and the unresolved items."""
    limits = DETECTED_LIMITATION_CHECKS
    detected_risk = [
        f for f in findings if f["result"] == "detected" and f["check_id"] not in limits
    ]
    limitations = [f for f in findings if f["result"] == "detected" and f["check_id"] in limits]
    unverified = [f for f in findings if f["result"] == "unverified"]
    unavailable = [f for f in findings if f["result"] == "unavailable"]
    not_applicable = [f for f in findings if f["result"] == "not_applicable"]
    withheld = [f for f in findings if f["result"] == "withheld"]
    cannot = [c for c in invalidation["conditions"] if c["result"] == "cannot_evaluate"]

    unresolved: list[dict[str, Any]] = []
    reasons: list[str] = []

    def note(reason: str, items: list[dict[str, Any]], key: str) -> None:
        if items:
            reasons.append(reason)
            unresolved.extend({"reason_id": reason, "ref": i[key]} for i in items)

    note("DI-UNVERIFIED-CHECKS", unverified, "check_id")
    note("DI-UNAVAILABLE-CHECKS", unavailable, "check_id")
    note("DI-NOT-APPLICABLE-CHECKS", not_applicable, "check_id")
    note("DI-INVALIDATION-NOT-FULLY-EVALUABLE", cannot, "condition_id")
    for f in limitations:
        reason = limits[f["check_id"]]
        reasons.append(reason)
        unresolved.append({"reason_id": reason, "ref": f["check_id"]})
    reasons = list(dict.fromkeys(reasons))

    if invalidation["summary"] == "triggered":
        return (
            "candidate_invalidation_triggered",
            ["DI-INVALIDATION-TRIGGERED", *reasons],
            unresolved,
        )
    if withheld:  # a gate withholds findings; the whole-request gate path is handled by the caller
        return "withheld_integrity_gate", ["DI-GATE-WITHHELD"], unresolved
    if detected_risk:
        conflict = (
            ["DI-SOURCE-CONFLICT"]
            if any(f["check_id"] == "RI-INT-03" for f in detected_risk)
            else []
        )
        return (
            "candidate_risk_findings_detected",
            ["DI-RISK-FINDINGS-DETECTED", *conflict, *reasons],
            unresolved,
        )
    if unresolved:
        return "candidate_unresolved", ["DI-UNRESOLVED", *reasons], unresolved
    return "candidate_no_findings_detected", ["DI-NO-FINDINGS-DETECTED"], unresolved


def _reassessment(
    findings: list[dict[str, Any]],
    invalidation: dict[str, Any] | None,
    declared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reassessment items, only from Phase 48 monitor fields and unresolved checks."""
    out: list[dict[str, Any]] = []
    if invalidation is not None:
        results = {c["condition_id"]: c["result"] for c in invalidation["conditions"]}
        for m in invalidation["monitor"]:
            out.append(
                {
                    "kind": "monitor_condition",
                    "ref": m["condition_id"],
                    "condition_result": results[m["condition_id"]],
                    "when": m["when"],
                    "field_ids": list(m["field_ids"]),
                    "evaluable": results[m["condition_id"]] != "cannot_evaluate",
                }
            )
    for f in findings:
        if f["result"] == "unverified":
            out.append(
                {
                    "kind": "verify_freshness",
                    "ref": f["check_id"],
                    "condition_result": f["result"],
                    "when": "freshness of these sources becomes verifiable",
                    "field_ids": list(f["field_ids"]),
                    "evaluable": bool(f["field_ids"]),
                }
            )
        elif f["result"] in ("unavailable", "not_applicable"):
            out.append(
                {
                    "kind": "cannot_evaluate",
                    "ref": f["check_id"],
                    "condition_result": f["result"],
                    "when": "the check's required data or evaluation becomes available",
                    "field_ids": [],
                    "evaluable": False,
                }
            )
    for d in declared:
        out.append(
            {
                "kind": "cannot_evaluate",
                "ref": d["check_id"],
                "condition_result": d["result"],
                "when": "a verified source for this check exists",
                "field_ids": [],
                "evaluable": False,
            }
        )
    return out


def _applicable(risk: dict[str, Any], a: dict[str, Any]) -> list[dict[str, Any]]:
    return [*risk["integrity"]["findings"], *risk["market_risks"]["findings"], *a["findings"]]


# ------------------------------------------------------------------------------- engine
def build_investment_decision(
    opportunities: dict[str, Any],
    ranking: dict[str, Any],
    risk_invalidation: dict[str, Any],
    risk_view: dict[str, Any],
    *,
    params: InvestmentParameters = INVESTMENT_PARAMS_V0,
) -> dict[str, Any]:
    """Build ``investment_decision.v0`` from the four contracts of one snapshot.

    Raises ``InvestmentInputError`` (a ``ValueError``) for unsupported, malformed or mutually
    inconsistent input. Missing or unverified *evidence* never raises: it is an explicit state."""
    o, r, risk = _validate(opportunities, ranking, risk_invalidation, risk_view)
    gates = o["gates"]
    gated = not risk["assessment"]["performed"]
    gate_reasons = (["DI-GATE-LOOK-AHEAD"] if gates["look_ahead"]["triggered"] else []) + (
        ["DI-GATE-INTEGRITY"] if gates["producer_hash"]["triggered"] else []
    )
    declared = risk["unavailable_checks"]

    assets: dict[str, Any] = {}
    for scope in _SCOPES:
        a = o["assets"][scope]
        ra = risk["assets"][scope]
        status = a["status"]
        base: dict[str, Any] = {
            "status": status,
            "discovery_type": a["discovery_type"],
            "reasons": list(a["reasons"]),
            "ranking_context": {**copy.deepcopy(ra["ranking_context"]), "used_for_decision": False},
        }
        evidence = _evidence(scope, a)
        candidate = status == "candidate"
        findings = _applicable(risk, ra) if candidate else []
        invalidation = ra["invalidation"] if candidate else None
        unresolved: list[dict[str, Any]] = []

        if gated:
            state, reasons = (
                "withheld_integrity_gate",
                ["DI-GATE-WITHHELD", *gate_reasons, "DI-UNDERLYING-STATUS"],
            )
        elif candidate:
            _need(invalidation is not None, f"{scope}: a candidate needs an invalidation block")
            state, reasons, unresolved = _classify_candidate(findings, invalidation or {})
            reasons = [*reasons, "DI-CANDIDATE-IS-NOT-A-THESIS", "DI-DECLARED-CHECKS-NOT-EVALUATED"]
        else:
            state, reason = _NON_CANDIDATE_STATE[status]
            reasons = [reason]
            _need(state != "withheld_integrity_gate", f"{scope}: blocked without a triggered gate")
        _need(state in _STATE_IDS, f"{scope}: unknown decision state")

        why: list[dict[str, Any]] = list(unresolved)
        if candidate and not gated:
            why.append({"reason_id": "DI-CANDIDATE-IS-NOT-A-THESIS", "ref": scope})
            why.append({"reason_id": "DI-DECLARED-CHECKS-NOT-EVALUATED", "ref": scope})
        else:
            # No Phase 48 assessment exists for this asset: say so, so an empty list never reads as
            # "nothing prevents a conclusion" and empty findings never read as a clean result.
            if gated:
                why.extend({"reason_id": "DI-GATE-WITHHELD", "ref": g} for g in gate_reasons)
            else:
                why.append({"reason_id": reasons[0], "ref": status})
            why.append({"reason_id": "DI-NO-RISK-ASSESSMENT", "ref": scope})
        assets[scope] = {
            **base,
            "decision_state": state,
            "decision_reasons": list(dict.fromkeys(reasons)),
            "evidence": evidence,
            "risk_assessment": {
                "state": ra["assessment"],
                "reasons": list(ra["assessment_reasons"]),
                "counts": copy.deepcopy(ra["counts"]),
            },
            "risk_findings": _group(findings) if candidate and not gated else None,
            "invalidation": copy.deepcopy(invalidation) if candidate and not gated else None,
            "market_risks_detected": list(ra["market_risks_detected"]),
            "why_not_conclusive": why,
            "reassessment": _reassessment(
                findings if candidate and not gated else [],
                invalidation if candidate and not gated else None,
                declared if candidate and not gated else [],
            ),
        }

    return {
        "contract_version": CONTRACT_VERSION,
        "source_contracts": {
            "risk": risk["contract_version"],
            "ranking": r["contract_version"],
            "opportunity": o["contract_version"],
            "risk_view": risk["source_contracts"]["risk_view"],
            "unified": o["source_contracts"]["unified"],
            "confirmation": o["source_contracts"]["confirmation"],
            "confirmation_parameters": o["source_contracts"]["confirmation_parameters"],
            "confirmation_families": o["source_contracts"]["confirmation_families"],
            "opportunity_parameters": o["parameters"]["version"],
            "ranking_parameters": r["parameters"]["version"],
            "risk_parameters": risk["parameters"]["version"],
            "risk_checks": risk["checks"]["version"],
        },
        "risk_decision_engine": copy.deepcopy(risk["decision"]),
        "snapshot": copy.deepcopy(o["snapshot"]),
        "parameters": {
            "version": params.version,
            "states_version": params.states_version,
            "precedence": list(PRECEDENCE),
            "experimental": True,
        },
        "states": [{"id": i, "meaning": m} for i, m in STATES],
        "evidence_dependence": copy.deepcopy(risk["evidence_dependence"]),
        "gates": copy.deepcopy(gates),
        "assessment": {"performed": not gated, "gate_reasons": gate_reasons},
        "integrity": [_finding_ref(f) for f in risk["integrity"]["findings"]],
        "market_risks": [_finding_ref(f) for f in risk["market_risks"]["findings"]],
        "declared_unavailable": copy.deepcopy(declared),
        "assets": assets,
        "counts": {
            s: sum(1 for x in assets.values() if x["decision_state"] == s) for s in _STATE_IDS
        },
        "data_quality": copy.deepcopy(o["data_quality"]),
        "upstream_limitations": copy.deepcopy(risk["limitations"]),
        "notice": {"id": NOTICE[0], "text": NOTICE[1]},
        "limitations": [{"id": i, "text": t} for i, t in LIMITATIONS],
    }
