"""Read-only Opportunity Ranking endpoint (Phase 47; ADR-0084).

``GET /api/v1/intelligence/opportunity-ranking`` reads the **latest stored** ``ai.snapshot`` row,
derives ``unified_snapshot.v0`` (Phase 44), ``cross_domain_confirmation.v0`` (Phase 45) and
``opportunity_discovery.v0`` (Phase 46) from that one payload and returns
``opportunity_ranking.v0`` (``cfi.intelligence.ranking``). It never builds a snapshot, ingests,
calls a provider or a model, or writes, and nothing is persisted. Errors follow
``/intelligence/opportunities``: no stored snapshot is 404 (``not_found``); a payload or input
the engines refuse, including an inconsistent candidate, is 503 with the reason and no partial
ranking. ``evidence_depth`` is a heuristic index, not a forecast, a recommendation or advice."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.api.routes.intelligence_confirmation import (
    ConfirmationCoverageOut,
    LimitationOut,
)
from cfi.api.routes.intelligence_opportunities import (
    GatesOut,
    MarketContextOut,
    NoticeOut,
)
from cfi.api.routes.intelligence_snapshot import DataQualityOut, FreshnessRecordOut, SnapshotIdOut
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    ConfirmationInputError,
    OpportunityInputError,
    RankingInputError,
    build_confirmation,
    build_opportunities,
    build_ranking,
    build_unified_snapshot,
)

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class MemberOut(BaseModel):
    domain: str
    component: str | None
    state: str
    direction: str | None
    strength: str | None
    freshness: str | None
    evidence_state: str | None
    quality_flags: list[str]
    source_ids: list[str]
    field_ids: list[str]
    freshness_records: list[FreshnessRecordOut]


class FamilyDetailOut(BaseModel):
    family: str
    domain: str
    base_points: int
    strong_bonus_points: int
    member_count: int
    members: list[MemberOut]


class MarketWideOut(BaseModel):
    families: list[str]
    points: int


class ComponentsOut(BaseModel):
    asset_specific_families: list[str]
    strong_families: list[str]
    base_points: int
    strong_bonus_points: int
    market_wide: MarketWideOut
    family_detail: list[FamilyDetailOut]


class AssetComparabilityOut(BaseModel):
    group_id: str
    verified: bool
    comparable_with: list[str]


class AssetRankingOut(BaseModel):
    status: str
    discovery_type: str | None
    reasons: list[str]
    ranking_reasons: list[str]
    notes: list[str]
    scored: bool
    evidence_depth: int | None
    max_attainable_depth: int
    score_withheld_reason: str | None
    components: ComponentsOut | None
    rank: int | None
    tied_with: list[str]
    rank_scope: str | None
    not_ranked_against: list[str]
    coverage: ConfirmationCoverageOut
    comparability: AssetComparabilityOut


class GroupOut(BaseModel):
    group_id: str
    members: list[str]
    comparability_verified: bool
    expected_domains: list[str]
    scored_assets: list[str]
    ranked: bool
    eligible_coverage: dict[str, ConfirmationCoverageOut]


class SourceContractsOut(BaseModel):
    opportunity: str
    opportunity_parameters: str
    discovery_types: str
    unified: str
    confirmation: str
    confirmation_parameters: str
    confirmation_families: str


class RankingParametersOut(BaseModel):
    version: str
    family_base_points: int
    strong_bonus_points: int
    market_wide_points: int
    min_scored_to_rank: int
    experimental: bool


class ComponentItemOut(BaseModel):
    id: str
    meaning: str


class ComponentsVocabularyOut(BaseModel):
    version: str
    items: list[ComponentItemOut]


class ScoringOut(BaseModel):
    performed: bool
    gate_reasons: list[str]


class RankingOut(BaseModel):
    contract_version: str
    source_contracts: SourceContractsOut
    snapshot: SnapshotIdOut
    parameters: RankingParametersOut
    components: ComponentsVocabularyOut
    gates: GatesOut
    scoring: ScoringOut
    assets: dict[str, AssetRankingOut]
    groups: list[GroupOut]
    market_context: MarketContextOut
    data_quality: DataQualityOut
    notice: NoticeOut
    limitations: list[LimitationOut]


@router.get("/opportunity-ranking", response_model=RankingOut)
async def opportunity_ranking(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is nothing to rank.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        unified = build_unified_snapshot(row.payload, snapshot_ref=ref)
        opportunities = build_opportunities(unified, build_confirmation(unified))
        return build_ranking(opportunities)
    except (
        InvalidSnapshotError,
        ConfirmationInputError,
        OpportunityInputError,
        RankingInputError,
    ) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used for opportunity ranking: {exc}"
        ) from exc
