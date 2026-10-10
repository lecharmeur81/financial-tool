"""Read-only Cross-Domain Confirmation endpoint (Phase 45; ADR-0082).

``GET /api/v1/intelligence/confirmation`` reads the **latest stored** ``ai.snapshot`` row, derives
``unified_snapshot.v0`` (Phase 44) and returns ``cross_domain_confirmation.v0``
(``cfi.intelligence.confirmation``). It never builds a snapshot, ingests, calls a provider or a
model, or writes, and nothing is persisted. Errors follow ``/decision/current``: no stored snapshot
is 404 (``not_found``); a payload the context layer refuses is 503 with the reason."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.api.routes.intelligence_snapshot import DataQualityOut, FreshnessRecordOut, SnapshotIdOut
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import ConfirmationInputError, build_confirmation, build_unified_snapshot

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class MemberOut(BaseModel):
    family: str | None
    domain: str
    component: str | None
    scope_basis: str
    shared_across_assets: bool
    state: str
    eligible: bool
    exclusion_reason: str | None
    direction: str | None
    strength: str | None
    freshness: str | None
    evidence_state: str | None
    quality_flags: list[str]
    source_ids: list[str]
    field_ids: list[str]
    freshness_records: list[FreshnessRecordOut]


class KeyLayerOut(BaseModel):
    domains: list[str]
    supportive: bool
    adverse: bool


class ConfirmationCoverageOut(BaseModel):
    eligible: int
    expected: int
    floor: list[int]
    met: bool


class AssetConfirmationOut(BaseModel):
    agreement: str
    reasons: list[str]
    supportive_families: list[str]
    adverse_families: list[str]
    key_layer: KeyLayerOut
    coverage: ConfirmationCoverageOut
    counts_by_state: dict[str, int]
    members: list[MemberOut]


class ParametersOut(BaseModel):
    version: str
    min_families: int
    require_key_layer: bool
    coverage_floor: list[int]
    families_version: str


class FamilyOut(BaseModel):
    family: str
    lineage: str


class ExcludedOut(BaseModel):
    scope: str
    domain: str
    component: str
    role: str | None
    reason: str


class LimitationOut(BaseModel):
    id: str
    text: str


class ConfirmationOut(BaseModel):
    contract_version: str
    source_contract: str
    snapshot: SnapshotIdOut
    parameters: ParametersOut
    families: dict[str, FamilyOut]
    assets: dict[str, AssetConfirmationOut]
    excluded: list[ExcludedOut]
    data_quality: DataQualityOut
    limitations: list[LimitationOut]


@router.get("/confirmation", response_model=ConfirmationOut)
async def cross_domain_confirmation(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is no confirmation to show.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        return build_confirmation(build_unified_snapshot(row.payload, snapshot_ref=ref))
    except (InvalidSnapshotError, ConfirmationInputError) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used as a confirmation input: {exc}"
        ) from exc
