"""``risk_view.v0`` (Phase 48; ADR-0085): the decision engine's own risk results, copied unchanged.

The Decision Context (``cfi.decision``) already computes the six risk dimensions (RK-01 to RK-06),
the observed caps (RC-01 to RC-04) and the CAP-U ceilings. Unified Snapshot, confirmation,
opportunity and ranking contracts do not carry them. This adapter reads them from the same stored
payload by calling the same public ``build_decision_context`` that Phase 44 calls. It computes
nothing: no level, mapping or threshold is defined here. It adds ``caps_evaluated`` because the
decision rules evaluate caps only for a bullish-family raw stance (decision D-D); without it,
"no cap observed" could be mistaken for "cap condition absent". The stance itself is not exposed."""

from __future__ import annotations

from typing import Any, Final

from cfi.decision.context import DecisionContext, build_decision_context
from cfi.decision.identity import SnapshotRef
from cfi.decision.universe import BULLISH_FAMILY, SCOPE_DOMAINS

__all__ = ["CONTRACT_VERSION", "build_risk_view"]

CONTRACT_VERSION: Final = "risk_view.v0"
_CAP_SOURCE_DOMAINS: Final = ("regime", "derivatives", "anomaly")


def _scope(ctx: DecisionContext) -> dict[str, Any]:
    a = ctx.assessment
    status = {
        d: next((str(r.status) for r in a.readings if r.domain == d), "unavailable")
        for d in _CAP_SOURCE_DOMAINS
    }
    return {
        "caps_evaluated": a.directional_stance_before_limits in BULLISH_FAMILY,
        "risks": [
            {
                "dimension": r.dimension.value,
                "level": r.level.value,
                "reason_ids": list(r.reason_ids),
                "field_ids": list(r.field_ids),
            }
            for r in a.risks
        ],
        "max_risk": a.max_risk.value,
        "observed_caps": [
            {
                "rule_id": c.rule_id,
                "binding": c.binding,
                "source_field_ids": list(c.source_field_ids),
                "reason_id": c.reason_id,
            }
            for c in a.observed_caps
        ],
        "cap_u": [
            {
                "rule_id": c.rule_id,
                "cap_source": c.cap_source,
                "source_field_id": c.source_field_id,
                "binding": c.binding,
                "reason_id": c.reason_id,
            }
            for c in a.cap_u
        ],
        "source_status": status,
    }


def build_risk_view(
    payload: dict[str, Any], *, snapshot_ref: SnapshotRef | None = None
) -> dict[str, Any]:
    """Build ``risk_view.v0`` from a stored payload.

    Raises ``InvalidSnapshotError`` (a ``ValueError``) for a payload the context layer refuses.
    Missing or unavailable *evidence* never raises: it is an explicit level or status."""
    contexts = {
        scope: build_decision_context(payload, scope, snapshot_ref=snapshot_ref)
        for scope in SCOPE_DOMAINS
    }
    first = next(iter(contexts.values()))
    identity = first.identity
    return {
        "contract_version": CONTRACT_VERSION,
        "source": "decision_engine",
        "decision": {
            "methodology_version": first.assessment.methodology_version,
            "parameter_version": first.assessment.parameter_version,
        },
        "identity": {
            "row_id": identity.row_id,
            "uuid": identity.uuid,
            "row_created_at": identity.row_created_at,
            "as_of": identity.as_of,
            "knowledge_time": identity.knowledge_time,
            "snapshot_version": identity.snapshot_version,
            "producer_payload_hash": identity.producer_payload_hash_stored,
            "producer_hash_check": identity.producer_hash_check.value,
            "decision_input_hash": identity.decision_input_hash,
        },
        "scopes": {scope: _scope(ctx) for scope, ctx in contexts.items()},
    }
