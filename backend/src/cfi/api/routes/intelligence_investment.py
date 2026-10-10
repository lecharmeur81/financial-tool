"""Read-only Investment Decision endpoint (Phase 49; ADR-0086).

``GET /api/v1/intelligence/investment-decision`` reads the **latest stored** ``ai.snapshot`` row,
derives ``unified_snapshot.v0`` (Phase 44), ``cross_domain_confirmation.v0`` (Phase 45),
``opportunity_discovery.v0`` (Phase 46), ``opportunity_ranking.v0`` (Phase 47),
``risk_invalidation.v0`` (Phase 48) and ``risk_view.v0`` from that one payload and returns
``investment_decision.v0`` (``cfi.intelligence.investment``). It never builds a snapshot, ingests,
calls a provider or a model, or writes, and nothing is persisted. Errors follow
``/intelligence/risk-invalidation``: no stored snapshot is 404 (``not_found``); a payload or input
an engine refuses, including inconsistent inputs, is 503 with the reason and no partial result. A
decision state is a research classification, not a recommendation, a confirmed thesis or advice."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.api.routes.intelligence_confirmation import LimitationOut
from cfi.api.routes.intelligence_opportunities import GatesOut, NoticeOut
from cfi.api.routes.intelligence_snapshot import DataQualityOut, SnapshotIdOut
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
    build_confirmation,
    build_investment_decision,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
    build_risk_view,
    build_unified_snapshot,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class EvidenceRefOut(BaseModel):
    domain: str
    component: str | None
    family: str | None
    state: str
    scope_basis: str | None
    shared_across_assets: bool | None
    direction: str | None
    strength: str | None
    freshness: str | None
    freshness_verified: bool
    quality_flags: list[str]
    source_ids: list[str]
    field_ids: list[str]
    exclusion_reason: str | None


class EvidenceOut(BaseModel):
    supporting: list[EvidenceRefOut]
    contradicting: list[EvidenceRefOut]
    other_eligible: list[EvidenceRefOut]
    missing_or_unusable: list[EvidenceRefOut]


class FindingRefOut(BaseModel):
    check_id: str
    category: str
    scope: str
    result: str
    level: str | None
    reason_ids: list[str]
    engine_reason_ids: list[str]
    freshness_verified: bool | None
    field_ids: list[str]
    source_ids: list[str]


class RiskGroupsOut(BaseModel):
    detected: list[FindingRefOut]
    unverified: list[FindingRefOut]
    unavailable: list[FindingRefOut]
    not_applicable: list[FindingRefOut]
    withheld: list[FindingRefOut]
    passed: list[FindingRefOut]


class ConditionOut(BaseModel):
    condition_id: str
    name: str
    meaning: str
    result: str
    reason_ids: list[str]
    monitor_field_ids: list[str]
    detail: dict[str, Any]


class MonitorOut(BaseModel):
    condition_id: str
    field_ids: list[str]
    when: str


class InvalidationOut(BaseModel):
    summary: str
    conditions: list[ConditionOut]
    monitor: list[MonitorOut]


class RankingContextOut(BaseModel):
    scored: bool
    evidence_depth: int | None
    rank: int | None
    rank_scope: str | None
    used_for_risk: bool
    used_for_decision: bool


class UnresolvedOut(BaseModel):
    reason_id: str
    ref: str


class ReassessmentOut(BaseModel):
    kind: str
    ref: str
    condition_result: str
    when: str
    field_ids: list[str]
    evaluable: bool


class RiskAssessmentOut(BaseModel):
    state: str
    reasons: list[str]
    counts: dict[str, int]


class AssetDecisionOut(BaseModel):
    status: str
    discovery_type: str | None
    reasons: list[str]
    ranking_context: RankingContextOut
    decision_state: str
    decision_reasons: list[str]
    evidence: EvidenceOut
    risk_assessment: RiskAssessmentOut
    risk_findings: RiskGroupsOut | None
    invalidation: InvalidationOut | None
    market_risks_detected: list[str]
    why_not_conclusive: list[UnresolvedOut]
    reassessment: list[ReassessmentOut]


class ParametersOut(BaseModel):
    version: str
    states_version: str
    precedence: list[str]
    experimental: bool


class StateOut(BaseModel):
    id: str
    meaning: str


class AssessmentOut(BaseModel):
    performed: bool
    gate_reasons: list[str]


class DeclaredUnavailableOut(BaseModel):
    check_id: str
    category: str
    result: str
    reason_ids: list[str]
    note: str


class InvestmentDecisionOut(BaseModel):
    contract_version: str
    source_contracts: dict[str, str]
    risk_decision_engine: dict[str, str]
    snapshot: SnapshotIdOut
    parameters: ParametersOut
    states: list[StateOut]
    evidence_dependence: dict[str, Any]
    gates: GatesOut
    assessment: AssessmentOut
    integrity: list[FindingRefOut]
    market_risks: list[FindingRefOut]
    declared_unavailable: list[DeclaredUnavailableOut]
    assets: dict[str, AssetDecisionOut]
    counts: dict[str, int]
    data_quality: DataQualityOut
    upstream_limitations: list[LimitationOut]
    notice: NoticeOut
    limitations: list[LimitationOut]


@router.get("/investment-decision", response_model=InvestmentDecisionOut)
async def investment_decision(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is nothing to assess.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        unified = build_unified_snapshot(row.payload, snapshot_ref=ref)
        opportunities = build_opportunities(unified, build_confirmation(unified))
        ranking = build_ranking(opportunities)
        view = build_risk_view(row.payload, snapshot_ref=ref)
        risk = build_risk_invalidation(opportunities, ranking, view)
        return build_investment_decision(opportunities, ranking, risk, view)
    except (
        InvalidSnapshotError,
        ConfirmationInputError,
        OpportunityInputError,
        RankingInputError,
        RiskInputError,
        InvestmentInputError,
    ) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used for an investment decision: {exc}"
        ) from exc
