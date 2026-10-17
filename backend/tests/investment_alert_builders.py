"""Hand-built ``investment_decision.v0`` inputs for the Phase 51 investment-alert tests.

Shaped like the real Phase 49 output (``cfi.intelligence.investment.build_investment_decision``);
a separate test runs the evaluator on real builder output so shape drift is caught. Nothing here
touches a database or the network.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cfi.alerts.investment_alerts import StoredSnapshotIdentity
from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence.investment import CONTRACT_VERSION
from cfi.intelligence.investment_universe import PARAMETER_VERSION, STATES_VERSION

SCOPES = tuple(SCOPE_DOMAINS)
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
AS_OF = NOW - timedelta(minutes=3)
KNOWLEDGE_TIME = NOW - timedelta(minutes=2)
ROW_ID = 4242
UUID = "11111111-2222-3333-4444-555555555555"
PAYLOAD_HASH = "ab" * 32

NOT_A_THESIS = "DI-CANDIDATE-IS-NOT-A-THESIS"
CHECKS_NOT_EVALUATED = "DI-DECLARED-CHECKS-NOT-EVALUATED"
_CANDIDATE_TAIL = [NOT_A_THESIS, CHECKS_NOT_EVALUATED]
_STATE_REASONS: dict[str, list[str]] = {
    "candidate_invalidation_triggered": ["DI-INVALIDATION-TRIGGERED", *_CANDIDATE_TAIL],
    "contradicted_evidence": ["DI-CONTRADICTED"],
    "candidate_risk_findings_detected": ["DI-RISK-FINDINGS-DETECTED", *_CANDIDATE_TAIL],
    "candidate_unresolved": ["DI-UNRESOLVED", "DI-UNVERIFIED-CHECKS", *_CANDIDATE_TAIL],
    "candidate_no_findings_detected": ["DI-NO-FINDINGS-DETECTED", *_CANDIDATE_TAIL],
    "insufficient_evidence": ["DI-INSUFFICIENT-EVIDENCE"],
    "no_opportunity": ["DI-NO-OPPORTUNITY"],
    "withheld_integrity_gate": ["DI-GATE-WITHHELD", "DI-UNDERLYING-STATUS"],
}
_CANDIDATE_STATES = {
    "candidate_invalidation_triggered",
    "candidate_risk_findings_detected",
    "candidate_unresolved",
    "candidate_no_findings_detected",
}
SOURCE_CONTRACTS = {
    "unified": "unified_snapshot.v0",
    "confirmation": "cross_domain_confirmation.v0",
    "confirmation_parameters": "confirmation_params.v0",
    "confirmation_families": "confirmation_families.v0",
    "opportunity": "opportunity_discovery.v0",
    "opportunity_parameters": "opportunity_params.v0",
    "ranking": "opportunity_ranking.v0",
    "ranking_parameters": "ranking_params.v0",
    "risk_view": "risk_view.v0",
    "risk": "risk_invalidation.v0",
    "risk_parameters": "risk_params.v0",
    "risk_checks": "risk_checks.v0",
}


def ref(field: str, *, verified: bool = True, state: str = "supportive") -> dict[str, Any]:
    return {
        "domain": "institutional",
        "component": "flows",
        "state": state,
        "freshness": "fresh" if verified else "stale",
        "freshness_verified": verified,
        "field_ids": [field],
        "source_ids": ["src-1"],
    }


def _findings(asset: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        g: [] for g in ("detected", "unverified", "unavailable", "not_applicable", "withheld")
    }
    groups["passed"] = [
        {"check_id": "RI-X-01", "result": "passed", "field_ids": [f"get_risk.data.{asset}.p"]}
    ]
    groups["unverified"] = [
        {"check_id": "RI-DQ-01", "result": "unverified", "field_ids": [f"get_risk.data.{asset}.u"]}
    ]
    return groups


def asset_block(asset: str, state: str) -> dict[str, Any]:
    candidate = state in _CANDIDATE_STATES
    assessed = candidate
    return {
        "status": "candidate" if candidate else "no_candidate",
        "decision_state": state,
        "decision_reasons": list(_STATE_REASONS[state]),
        "evidence": {
            "supporting": [ref(f"get_inst.data.{asset}.s")],
            "contradicting": (
                [ref(f"get_whale.data.{asset}.c", state="adverse")]
                if state == "contradicted_evidence"
                else []
            ),
            "other_eligible": [],
            "missing_or_unusable": [],
        },
        "risk_assessment": {
            "state": "assessed" if assessed else "not_applicable",
            "reasons": ["RI-ASSESSED" if assessed else "RI-NOT-A-CANDIDATE"],
            "counts": {},
        },
        "risk_findings": _findings(asset) if candidate else None,
        "invalidation": (
            {
                "summary": "triggered" if state == "candidate_invalidation_triggered" else "none",
                "conditions": [],
            }
            if candidate
            else None
        ),
    }


def decision(
    states: str | dict[str, str] = "candidate_unresolved",
    *,
    performed: bool = True,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """A decision with every asset in ``states`` (one state, or a state per asset)."""
    per_asset = dict.fromkeys(SCOPES, states) if isinstance(states, str) else dict(states)
    if not performed:
        per_asset = dict.fromkeys(SCOPES, "withheld_integrity_gate")
    out: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "source_contracts": dict(SOURCE_CONTRACTS),
        "snapshot": {
            "row_id": ROW_ID,
            "uuid": UUID,
            "row_created_at": NOW.isoformat(),
            "as_of": AS_OF.isoformat(),
            "knowledge_time": KNOWLEDGE_TIME.isoformat(),
            "producer_payload_hash": PAYLOAD_HASH,
        },
        "parameters": {
            "version": PARAMETER_VERSION,
            "states_version": STATES_VERSION,
            "experimental": True,
        },
        "assessment": {"performed": performed, "gate_reasons": [] if performed else ["DI-GATE-X"]},
        "assets": {s: asset_block(s, per_asset[s]) for s in SCOPES},
    }
    if mutate is not None:
        mutate(out)
    return out


def stored(**overrides: Any) -> StoredSnapshotIdentity:
    kwargs: dict[str, Any] = {
        "row_id": ROW_ID,
        "uuid": UUID,
        "payload_hash": PAYLOAD_HASH,
        "as_of": AS_OF,
        "knowledge_time": KNOWLEDGE_TIME,
    }
    kwargs.update(overrides)
    return StoredSnapshotIdentity(**kwargs)


def frozen_copy(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)
