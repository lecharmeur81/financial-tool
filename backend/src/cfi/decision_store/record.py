"""Pure mapping from a stored snapshot to decision-assessment rows (Phase 40).

No database, network, clock or randomness. Nothing here assesses anything itself: every value comes
from ``cfi.decision.context.build_decision_context`` - the same function, with the same default
parameters, that the Phase 39 read service calls - applied to the payload exactly as it is stored.
The full assessment stored is ``DecisionContext.deterministic_dict()`` (``generated_at`` excluded),
so a persisted row can be compared with a fresh computation for the same snapshot.

Identity (ADR-0076, D-M) is ``(snapshot_id, scope, methodology_version, parameter_version)``.
``template_version`` is provenance only. A snapshot whose producer hash does not match is still
assessed and recorded with ``producer_hash_check = "mismatch"``: the mismatch is audit information,
never a completeness signal and never repaired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cfi.decision.context import DecisionContext, build_decision_context
from cfi.decision.identity import SnapshotRef
from cfi.decision.universe import SCOPE_DOMAINS

__all__ = [
    "AssessmentRecord",
    "StoredSnapshot",
    "record_from_context",
    "records_for_snapshot",
]


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """One stored ``ai.snapshot`` row, as persistence needs it."""

    row_id: int
    uuid: str
    payload_hash: str
    created_at: datetime
    as_of: datetime
    knowledge_time: datetime
    payload: dict[str, Any]

    def ref(self) -> SnapshotRef:
        return SnapshotRef(
            row_id=self.row_id,
            uuid=self.uuid,
            payload_hash=self.payload_hash,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class AssessmentRecord:
    snapshot_id: int
    scope: str
    methodology_version: str
    parameter_version: str
    template_version: str  # provenance, not identity
    snapshot_version: str
    snapshot_as_of: datetime
    knowledge_time: datetime
    producer_payload_hash: str | None
    producer_hash_check: str
    decision_input_hash: str
    stance: str
    confidence: str
    posture: str
    coverage_available: int
    expected_domains: int
    conflict: bool
    assessment: dict[str, Any]

    @property
    def identity(self) -> tuple[int, str, str, str]:
        """The D-M identity. ``template_version`` is deliberately absent."""
        return (self.snapshot_id, self.scope, self.methodology_version, self.parameter_version)


def record_from_context(ctx: DecisionContext, snapshot: StoredSnapshot) -> AssessmentRecord:
    ident = ctx.identity
    result = ctx.assessment
    return AssessmentRecord(
        snapshot_id=snapshot.row_id,
        scope=ctx.scope,
        methodology_version=ctx.methodology_version,
        parameter_version=ctx.parameter_version,
        template_version=ctx.template_version,
        snapshot_version=ident.snapshot_version,
        snapshot_as_of=snapshot.as_of,
        knowledge_time=snapshot.knowledge_time,
        producer_payload_hash=ident.producer_payload_hash_stored,
        producer_hash_check=ident.producer_hash_check.value,
        decision_input_hash=ident.decision_input_hash,
        stance=str(ctx.final_stance.value),
        confidence=str(ctx.confidence.value),
        posture=str(ctx.posture.value),
        coverage_available=result.coverage_available,
        expected_domains=result.expected_domains,
        conflict=bool(ctx.conflict),
        assessment=ctx.deterministic_dict(),
    )


def records_for_snapshot(snapshot: StoredSnapshot) -> tuple[AssessmentRecord, ...]:
    """One record per defined scope, in the engine's own scope order.

    Raises ``cfi.decision.context.InvalidSnapshotError`` when the payload is not a supported
    Phase 21 snapshot - the caller decides what that means. Missing or unavailable *evidence* never
    raises: an ``Insufficient Evidence`` assessment is a valid, persistable result."""
    return tuple(
        record_from_context(
            build_decision_context(snapshot.payload, scope, snapshot_ref=snapshot.ref()), snapshot
        )
        for scope in SCOPE_DOMAINS
    )
