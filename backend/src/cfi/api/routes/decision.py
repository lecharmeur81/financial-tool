"""Read-only Decision Center endpoint (Phase 39).

``GET /api/v1/decision/current?asset=BTC|ETH|SOL|XRP`` reads the **latest stored** ``ai.snapshot``
row, builds the Phase 38.3 ``DecisionContext`` from its payload and returns the curated decision
view (``cfi.decision.read_service``). It never builds a snapshot, never runs the (slow) regime or
similarity calculation, never calls a provider or Claude, and never writes: one ``SELECT``, then
pure computation. Like every other read route here it is an unauthenticated GET (``cfi.api.auth``
protects only mutating and AI-triggering endpoints).

Errors (RFC 9457, ``cfi.core.errors``): an unsupported asset is 422; no stored snapshot is 404
(``not_found``) - a normal first-run state, not a fault; a stored payload the context layer refuses
is 503, with the reason."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.analyst.repository import AnalystRepository, SnapshotRow
from cfi.core.errors import DataValidationError, NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError, UnsupportedScopeError
from cfi.decision.identity import SnapshotRef
from cfi.decision.read_service import DEFAULT_ASSET, build_decision_view

router = APIRouter(prefix="/api/v1/decision", tags=["decision"])


class ScopeLabel(BaseModel):
    code: str
    text: str


class TextItem(BaseModel):
    id: str
    text: str | None


class StanceOut(BaseModel):
    final: str
    raw: str
    confidence: str
    posture: str
    differs_from_raw: bool
    cap_u_applied: bool
    headline: str | None


class WhyOut(BaseModel):
    directional: list[TextItem]
    limits: list[TextItem]
    missing_context: list[TextItem]


class CapUOut(BaseModel):
    rule_id: str
    cap_source: str
    source_field_id: str
    binding: bool
    raw_stance: str
    applied_ceiling: str
    final_stance: str
    final_posture: str
    text: str | None
    template_id: str


class ObservedCapOut(BaseModel):
    rule_id: str
    ceiling: str
    binding: bool
    text: str | None


class EvidenceItemOut(BaseModel):
    side: str
    domain: str
    scope_label: ScopeLabel | None
    strength: str
    band: str | None
    text: str | None
    template_id: str | None
    quality_flags: list[str]
    field_ids: list[str]


class EvidenceOut(BaseModel):
    supportive: list[EvidenceItemOut]
    adverse: list[EvidenceItemOut]
    neutral: list[EvidenceItemOut]


class ConflictOut(BaseModel):
    directional: bool
    contradictions: list[str]
    conflicting_tools: list[str]


class RiskOut(BaseModel):
    dimension: str
    level: str
    text: str | None


class CoverageOut(BaseModel):
    available: int
    expected: int
    missing: list[str]
    missing_context: list[str]


class ReasonOut(BaseModel):
    kind: str
    text: str
    path: str


class FreshnessInfoOut(BaseModel):
    status_counts: dict[str, int]
    latest: str | None
    expected_latest: str | None
    rule: str | None
    note: str | None


class DomainOut(BaseModel):
    domain: str
    component: str
    role: str
    scope_label: ScopeLabel | None
    status: str
    freshness: str
    evidence_state: str
    quality_flags: list[str]
    direction: str | None
    strength: str | None
    band: str | None
    freshness_info: FreshnessInfoOut
    reasons: list[ReasonOut]


class DataQualityOut(BaseModel):
    unavailable_components: list[str]
    stale_components: list[str]
    partial_components: list[str]
    not_assessed_components: list[str]
    unavailable_tools: list[str]
    degraded_tools: list[str]
    look_ahead_violations: list[str]
    platform_limits: list[str]


class SnapshotOut(BaseModel):
    row_id: int | None
    uuid: str | None
    row_created_at: str | None
    as_of: str
    knowledge_time: str
    snapshot_version: str
    producer_payload_hash: str | None
    producer_hash_check: str
    decision_input_hash: str


class MethodologyOut(BaseModel):
    methodology_version: str
    parameter_version: str
    template_version: str
    fired_rule_ids: list[str]
    confidence_rule_ids: list[str]
    posture_rule_id: str


class FieldOut(BaseModel):
    field_id: str
    display: str
    evidence_category: str | None
    quality_status: str | None
    unit: str | None
    source: str | None


class TechnicalOut(BaseModel):
    fields: list[FieldOut]
    fields_without_display: int


class DecisionCurrentOut(BaseModel):
    contract_version: str
    asset: str
    stance: StanceOut
    why: WhyOut
    cap_u: list[CapUOut]
    observed_caps: list[ObservedCapOut]
    evidence: EvidenceOut
    conflict: ConflictOut
    risks: list[RiskOut]
    max_risk: str
    coverage: CoverageOut
    domains: list[DomainOut]
    scope_notes: list[str]
    limitations: list[TextItem]
    data_quality: DataQualityOut
    snapshot: SnapshotOut
    methodology: MethodologyOut
    technical: TechnicalOut


class SnapshotSource(Protocol):
    """What the route needs from storage: the latest stored snapshot row, or ``None``."""

    async def latest_snapshot_row(self) -> SnapshotRow | None: ...


def get_snapshot_source(request: Request) -> SnapshotSource:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return AnalystRepository(engine)


@router.get("/current", response_model=DecisionCurrentOut)
async def current_decision(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
    asset: Annotated[str, Query(description="BTC, ETH, SOL or XRP (default BTC)")] = DEFAULT_ASSET,
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is no decision to show.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        return build_decision_view(row.payload, asset, snapshot_ref=ref)
    except UnsupportedScopeError as exc:
        raise DataValidationError(str(exc)) from exc
    except InvalidSnapshotError as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used as a decision input: {exc}"
        ) from exc
