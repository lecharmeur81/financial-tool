"""Read-only Risk & Invalidation endpoint (Phase 48; ADR-0085).

``GET /api/v1/intelligence/risk-invalidation`` reads the **latest stored** ``ai.snapshot`` row,
derives ``unified_snapshot.v0`` (Phase 44), ``cross_domain_confirmation.v0`` (Phase 45),
``opportunity_discovery.v0`` (Phase 46), ``opportunity_ranking.v0`` (Phase 47) and ``risk_view.v0``
(the decision engine's own risk results) from that one payload and returns ``risk_invalidation.v0``
(``cfi.intelligence.risk``). It never builds a snapshot, ingests, calls a provider or a model, or
writes, and nothing is persisted. Errors follow ``/intelligence/opportunity-ranking``: no stored
snapshot is 404 (``not_found``); a payload or input the engines refuse, including inconsistent or
mismatched inputs, is 503 with the reason and no partial assessment. The findings are not a safety
rating, a probability of loss, a recommendation or advice."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.api.routes.intelligence_confirmation import LimitationOut
from cfi.api.routes.intelligence_opportunities import GatesOut, NoticeOut
from cfi.api.routes.intelligence_snapshot import DataQualityOut, FreshnessRecordOut, SnapshotIdOut
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    ConfirmationInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
    build_confirmation,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
    build_risk_view,
    build_unified_snapshot,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class ContributorOut(BaseModel):
    domain: str | None
    component: str | None
    freshness: str | None
    freshness_verified: bool


class FindingOut(BaseModel):
    check_id: str
    category: str
    scope: str
    applicable: bool
    result: str
    level: str | None
    reason_ids: list[str]
    engine_reason_ids: list[str]
    freshness_verified: bool | None
    field_ids: list[str]
    source_ids: list[str]
    contributors: list[ContributorOut]
    freshness_records: list[FreshnessRecordOut]
    detail: dict[str, Any]


class CountsOut(BaseModel):
    passed: int
    detected: int
    unverified: int
    unavailable: int
    not_applicable: int
    withheld: int


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


class AssetRiskOut(BaseModel):
    status: str
    discovery_type: str | None
    reasons: list[str]
    ranking_context: RankingContextOut
    assessment: str
    assessment_reasons: list[str]
    findings: list[FindingOut]
    counts: CountsOut
    invalidation: InvalidationOut | None
    market_risks_detected: list[str]


class SourceContractsOut(BaseModel):
    ranking: str
    opportunity: str
    risk_view: str
    unified: str
    confirmation: str
    confirmation_parameters: str
    confirmation_families: str
    opportunity_parameters: str
    ranking_parameters: str


class DecisionVersionsOut(BaseModel):
    methodology_version: str
    parameter_version: str


class ParametersOut(BaseModel):
    version: str
    detected_levels: list[str]
    visible_levels: list[str]
    experimental: bool


class CheckItemOut(BaseModel):
    check_id: str
    category: str
    scope: str
    condition: str


class VocabularyItemOut(BaseModel):
    id: str
    meaning: str


class ChecksOut(BaseModel):
    version: str
    items: list[CheckItemOut]
    results: list[VocabularyItemOut]
    invalidation_results: list[VocabularyItemOut]


class EvidenceDependenceOut(BaseModel):
    single_snapshot: bool
    inputs: list[str]
    independent_confirmation: bool
    note: str


class AssessmentOut(BaseModel):
    performed: bool
    gate_reasons: list[str]


class FindingsBlockOut(BaseModel):
    findings: list[FindingOut]


class MarketRisksOut(BaseModel):
    applies_to: list[str]
    findings: list[FindingOut]


class UnavailableCheckOut(BaseModel):
    check_id: str
    category: str
    result: str
    reason_ids: list[str]
    note: str


class RiskInvalidationOut(BaseModel):
    contract_version: str
    source_contracts: SourceContractsOut
    decision: DecisionVersionsOut
    snapshot: SnapshotIdOut
    parameters: ParametersOut
    checks: ChecksOut
    evidence_dependence: EvidenceDependenceOut
    gates: GatesOut
    assessment: AssessmentOut
    integrity: FindingsBlockOut
    market_risks: MarketRisksOut
    unavailable_checks: list[UnavailableCheckOut]
    assets: dict[str, AssetRiskOut]
    data_quality: DataQualityOut
    notice: NoticeOut
    limitations: list[LimitationOut]


@router.get("/risk-invalidation", response_model=RiskInvalidationOut)
async def risk_invalidation(
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
        return build_risk_invalidation(
            opportunities,
            build_ranking(opportunities),
            build_risk_view(row.payload, snapshot_ref=ref),
        )
    except (
        InvalidSnapshotError,
        ConfirmationInputError,
        OpportunityInputError,
        RankingInputError,
        RiskInputError,
    ) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used for risk and invalidation: {exc}"
        ) from exc
