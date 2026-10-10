"""Read-only Opportunity Discovery endpoint (Phase 46; ADR-0083).

``GET /api/v1/intelligence/opportunities`` reads the **latest stored** ``ai.snapshot`` row, derives
``unified_snapshot.v0`` (Phase 44) and ``cross_domain_confirmation.v0`` (Phase 45) from that one
payload and returns ``opportunity_discovery.v0`` (``cfi.intelligence.opportunity``). It never
builds a snapshot, ingests, calls a provider or a model, or writes, and nothing is persisted.
Errors follow ``/decision/current``: no stored snapshot is 404 (``not_found``); a payload or input
the engines refuse is 503 with the reason. The result is research context, not advice."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.api.routes.intelligence_confirmation import (
    ConfirmationCoverageOut,
    KeyLayerOut,
    LimitationOut,
)
from cfi.api.routes.intelligence_snapshot import DataQualityOut, FreshnessRecordOut, SnapshotIdOut
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    ConfirmationInputError,
    OpportunityInputError,
    build_confirmation,
    build_opportunities,
    build_unified_snapshot,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class EvidenceRefOut(BaseModel):
    family: str | None
    domain: str
    component: str | None
    scope_basis: str
    shared_across_assets: bool
    state: str
    direction: str | None
    strength: str | None
    freshness: str | None
    evidence_state: str | None
    quality_flags: list[str]
    source_ids: list[str]
    field_ids: list[str]
    freshness_records: list[FreshnessRecordOut]


class ExcludedMemberOut(EvidenceRefOut):
    exclusion_reason: str | None


class ContextEntryOut(BaseModel):
    domain: str
    component: str
    role: str | None
    status: str
    freshness: str
    evidence_state: str | None
    quality_flags: list[str]
    band: str | None
    source_ids: list[str]
    field_ids: list[str]
    freshness_records: list[FreshnessRecordOut]


class ContextOut(BaseModel):
    used_for_discovery: bool
    entries: list[ContextEntryOut]


class BasisOut(BaseModel):
    confirmation_agreement: str
    confirmation_reasons: list[str]
    supportive_families: list[str]
    adverse_families: list[str]
    asset_specific_supporting_families: list[str]
    market_wide_supporting_families: list[str]
    key_layer: KeyLayerOut
    coverage: ConfirmationCoverageOut


class ComparabilityOut(BaseModel):
    expected_domains: list[str]
    not_tracked_domains: list[str]
    comparable_with: list[str]
    not_comparable_with: list[str]


class IndependenceOut(BaseModel):
    shares_market_wide_evidence_with: list[str]


class AssetOpportunityOut(BaseModel):
    status: str
    discovery_type: str | None
    reasons: list[str]
    notes: list[str]
    basis: BasisOut
    evidence_refs: list[EvidenceRefOut]
    excluded_members: list[ExcludedMemberOut]
    context: ContextOut
    comparability: ComparabilityOut
    independence: IndependenceOut


class SourceContractsOut(BaseModel):
    unified: str
    confirmation: str
    confirmation_parameters: str
    confirmation_families: str


class ParametersOut(BaseModel):
    version: str
    min_asset_specific_confirmers: int
    asset_led_min_asset_specific: int
    experimental: bool


class DiscoveryTypeOut(BaseModel):
    id: str
    meaning: str


class DiscoveryTypesOut(BaseModel):
    version: str
    types: list[DiscoveryTypeOut]


class LookAheadGateOut(BaseModel):
    triggered: bool
    violations: list[str]


class ProducerHashGateOut(BaseModel):
    check: str | None
    triggered: bool


class GatesOut(BaseModel):
    look_ahead: LookAheadGateOut
    producer_hash: ProducerHashGateOut


class SharedEvidenceOut(BaseModel):
    family: str
    assets: list[str]


class MarketContextOut(BaseModel):
    candidate_assets: list[str]
    shared_market_wide_evidence: list[SharedEvidenceOut]
    candidates_independent_of_each_other: bool


class NoticeOut(BaseModel):
    id: str
    text: str


class OpportunityOut(BaseModel):
    contract_version: str
    source_contracts: SourceContractsOut
    snapshot: SnapshotIdOut
    parameters: ParametersOut
    discovery_types: DiscoveryTypesOut
    gates: GatesOut
    assets: dict[str, AssetOpportunityOut]
    market_context: MarketContextOut
    data_quality: DataQualityOut
    notice: NoticeOut
    limitations: list[LimitationOut]


@router.get("/opportunities", response_model=OpportunityOut)
async def opportunity_discovery(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is nothing to discover.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        unified = build_unified_snapshot(row.payload, snapshot_ref=ref)
        return build_opportunities(unified, build_confirmation(unified))
    except (InvalidSnapshotError, ConfirmationInputError, OpportunityInputError) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used for opportunity discovery: {exc}"
        ) from exc
