"""Daily Market Brief endpoints (Phase 22).

``POST /generate`` never calls Claude inline: it creates a ``queued`` ``ai.brief`` row (so its
``brief_id`` is stable and can be returned immediately, Section 9) and hands the actual work to
the ``brief.generate`` Celery task, on the same ``ai`` queue the Phase 21 analyst task already
uses — mirrors ``cfi.api.routes.analyst.analyze`` exactly (R13: reuse the established shape).
``GET /{brief_id}`` polls the same row for its current status; ``GET /latest`` returns the most
recently completed brief without needing its id.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from cfi.brief.repository import BriefRepository
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.worker.client import send_task

router = APIRouter(prefix="/api/v1/brief", tags=["brief"])


class GenerateResponse(BaseModel):
    brief_id: uuid.UUID
    status: str


class BriefStatus(BaseModel):
    brief_id: uuid.UUID
    status: str
    reporting_period_start: datetime
    reporting_period_end: datetime
    prompt_version: str | None
    analyst_version: str | None
    model: str | None
    response: dict[str, Any] | None
    validation_status: str | None
    validation_errors: list[str] | None
    attempt_count: int
    tools_called: list[str] | None
    data_quality_state: str | None
    changes: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


def _repo(request: Request) -> BriefRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return BriefRepository(engine)


def _to_status(row: dict[str, Any]) -> BriefStatus:
    return BriefStatus(
        brief_id=row["uuid"],
        status=row["status"],
        reporting_period_start=row["reporting_period_start"],
        reporting_period_end=row["reporting_period_end"],
        prompt_version=row["prompt_version"],
        analyst_version=row["analyst_version"],
        model=row["model"],
        response=row["response"],
        validation_status=row["validation_status"],
        validation_errors=row["validation_errors"],
        attempt_count=row["attempt_count"],
        tools_called=row["tools_called"],
        data_quality_state=row["data_quality_state"],
        changes=row["changes"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(request: Request) -> GenerateResponse:
    """Queue one Daily Market Brief covering the 24 hours ending now. The previous ``completed``
    brief (if any) becomes this brief's change-detection comparison basis (Section 5) — resolved
    once, here, and recorded on the row, so the worker task never has to re-derive it."""
    now = utc_now()
    repo = _repo(request)
    previous = await repo.latest_completed_brief()
    previous_brief_id = int(previous["id"]) if previous else None
    _brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now,
        reporting_period_start=now - timedelta(days=1),
        reporting_period_end=now,
        previous_brief_id=previous_brief_id,
    )
    send_task(
        request.app.state.settings,
        "brief.generate",
        args=(str(brief_uuid),),
        queue="ai",
    )
    return GenerateResponse(brief_id=brief_uuid, status="queued")


@router.get("/latest", response_model=BriefStatus)
async def latest(request: Request) -> BriefStatus:
    row = await _repo(request).latest_completed_brief()
    if row is None:
        raise NotFoundError("No completed Daily Market Brief exists yet.")
    return _to_status(row)


@router.get("/{brief_id}", response_model=BriefStatus)
async def get_brief(request: Request, brief_id: uuid.UUID) -> BriefStatus:
    row = await _repo(request).get_by_uuid(brief_id)
    if row is None:
        raise NotFoundError(f"No brief found for brief_id={brief_id}.")
    return _to_status(row)
