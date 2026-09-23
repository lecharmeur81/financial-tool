"""Operational read endpoints: provider health and ingestion runs (failure tracking).

These describe the *pipeline*, not the market. They never contain market values.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.ingestion.repository import IngestionRepository

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


class ProviderHealth(BaseModel):
    provider_id: str
    display_name: str
    requests: int
    successes: int
    success_rate: float | None
    consecutive_failures: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    last_job_status: str | None


class ProviderHealthResponse(BaseModel):
    window_hours: int
    generated_at: datetime
    providers: list[ProviderHealth]


class JobRun(BaseModel):
    job_run_id: int
    job_type: str
    dataset_id: str
    provider_id: str
    subject: str | None
    status: str
    window_start: datetime
    window_end: datetime
    started_at: datetime
    finished_at: datetime | None
    pages: int
    records_received: int
    inserted: int
    duplicates: int
    revisions: int
    missing: int
    conflicts: int
    rejected: int
    skipped: int
    suspect: int
    stale: bool | None
    error_code: str | None
    error_detail: str | None


def _repo(request: Request) -> IngestionRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return IngestionRepository(engine)


@router.get("/providers/health", response_model=ProviderHealthResponse)
async def provider_health(
    request: Request, hours: int = Query(default=24, ge=1, le=24 * 30)
) -> ProviderHealthResponse:
    rows = await _repo(request).provider_health(utc_now() - timedelta(hours=hours))
    providers = []
    for row in rows:
        requests_ = int(row["requests"])
        data: dict[str, Any] = {**row, "requests": requests_}
        data["success_rate"] = round(int(row["successes"]) / requests_, 4) if requests_ else None
        providers.append(ProviderHealth(**data))
    return ProviderHealthResponse(window_hours=hours, generated_at=utc_now(), providers=providers)


@router.get("/ingestion/runs", response_model=list[JobRun])
async def ingestion_runs(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> list[JobRun]:
    rows = await _repo(request).recent_jobs(limit)
    return [JobRun(**row) for row in rows]
