"""Read-only Unified Intelligence Snapshot endpoint (Phase 44; ADR-0081).

``GET /api/v1/intelligence/snapshot`` reads the **latest stored** ``ai.snapshot`` row and returns
``unified_snapshot.v0`` (``cfi.intelligence``): every evidence domain with its availability,
freshness, quality flags and provenance, as the Decision Context holds them. It never builds a
snapshot, never ingests, never calls a provider or Claude, and never writes: one ``SELECT``, then
pure computation. Errors follow ``/decision/current``: no stored snapshot is 404 (``not_found``,
a normal first-run state); a stored payload the context layer refuses is 503, with the reason."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import build_unified_snapshot

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class FreshnessRecordOut(BaseModel):
    path: str
    status: str | None
    latest: str | None
    expected_latest: str | None
    age_seconds: int | None
    rule: str | None
    note: str | None
    after_knowledge_time: bool


class DomainEntryOut(BaseModel):
    domain: str
    component: str
    role: str
    independent_vote: bool
    status: str
    freshness: str
    evidence_state: str
    insufficient_data: bool
    quality_flags: list[str]
    direction: str | None
    strength: str | None
    band: str | None
    source_ids: list[str]
    field_ids: list[str]
    freshness_records: list[FreshnessRecordOut]


class AssetOut(BaseModel):
    domains: list[DomainEntryOut]
    not_tracked_domains: list[str]


class SnapshotIdOut(BaseModel):
    row_id: int | None
    uuid: str | None
    row_created_at: str | None
    as_of: str
    knowledge_time: str
    snapshot_version: str
    producer_payload_hash: str | None
    producer_hash_check: str
    decision_input_hash: str
    snapshot_data_quality_state: str | None
    source_conflicts: bool


class CoverageOut(BaseModel):
    entries: int
    available: int
    insufficient: int
    by_evidence_state: dict[str, int]


class DataQualityOut(BaseModel):
    unavailable_tools: list[str]
    degraded_tools: list[str]
    conflicting_tools: list[str]
    look_ahead_violations: list[str]
    platform_limits: list[str]


class UnifiedSnapshotOut(BaseModel):
    contract_version: str
    snapshot: SnapshotIdOut
    global_domains: list[DomainEntryOut]
    assets: dict[str, AssetOut]
    coverage: CoverageOut
    data_quality: DataQualityOut


@router.get("/snapshot", response_model=UnifiedSnapshotOut)
async def unified_snapshot(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is no intelligence to show.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        return build_unified_snapshot(row.payload, snapshot_ref=ref)
    except InvalidSnapshotError as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used as an intelligence input: {exc}"
        ) from exc
