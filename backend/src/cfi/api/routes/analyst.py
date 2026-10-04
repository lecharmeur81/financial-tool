"""AI Analyst endpoints (Phase 21).

``POST /analyze`` never calls Claude inline: it creates a ``queued`` ``ai.interpretation`` row (so
its ``analysis_id`` is stable and can be returned immediately — Section 13) and hands the actual
work to the ``analyst.analyze`` Celery task, on its own ``ai`` queue, so a slow or rate-limited
Claude call never blocks an API worker (mirrors every other ingestion job's queued-then-processed
shape, ADR-0023). ``GET /{analysis_id}`` polls the same row for its current status.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.analyst.repository import AnalystRepository
from cfi.analyst.universe import RESPONSE_SECTIONS, TOOLS
from cfi.api.auth import require_api_key
from cfi.api.limiter import AI_TRIGGER_LIMIT, limiter
from cfi.api.params import resolve_query_times
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.worker.client import send_task

router = APIRouter(prefix="/api/v1/analyst", tags=["analyst"])

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(
        description="Only data this system had stored by then (timezone-aware); "
        "defaults to as_of if as_of is given, else now (ADR-0060)"
    ),
]


class AnalyzeRequest(BaseModel):
    question: str | None = None


class AnalyzeResponse(BaseModel):
    analysis_id: uuid.UUID
    status: str


class AnalysisStatus(BaseModel):
    analysis_id: uuid.UUID
    status: str
    question: str | None
    prompt_version: str | None
    model: str | None
    response: dict[str, Any] | None
    validation_status: str | None
    validation_errors: list[str] | None
    attempt_count: int
    tools_called: list[str] | None
    data_quality_state: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


def _repo(request: Request) -> AnalystRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return AnalystRepository(engine)


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    """The 14 tools the analyst may call (each backed by an existing, already-tested domain
    service — no raw database access, ARCHITECTURE.md 5.17) and the 12 required response sections,
    in their fixed order."""
    return {
        "response_sections": list(RESPONSE_SECTIONS),
        "tools": [
            {"tool_id": t.tool_id, "description": t.description, "domain_service": t.domain_service}
            for t in TOOLS
        ],
    }


@router.post("/analyze", response_model=AnalyzeResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(AI_TRIGGER_LIMIT)
async def analyze(
    request: Request,
    body: AnalyzeRequest,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> AnalyzeResponse:
    now = utc_now()
    a, k = resolve_query_times(as_of, knowledge_time)
    repo = _repo(request)
    _interpretation_id, analysis_uuid = await repo.create_queued_interpretation(
        now=now, question=body.question
    )
    send_task(
        request.app.state.settings,
        "analyst.analyze",
        args=(str(analysis_uuid), a.isoformat(), k.isoformat()),
        queue="ai",
    )
    return AnalyzeResponse(analysis_id=analysis_uuid, status="queued")


@router.get("/{analysis_id}", response_model=AnalysisStatus)
async def get_analysis(request: Request, analysis_id: uuid.UUID) -> AnalysisStatus:
    row = await _repo(request).get_by_uuid(analysis_id)
    if row is None:
        raise NotFoundError(f"No analysis found for analysis_id={analysis_id}.")
    return AnalysisStatus(
        analysis_id=analysis_id,
        status=row["status"],
        question=row["question"],
        prompt_version=row["prompt_version"],
        model=row["model"],
        response=row["response"],
        validation_status=row["validation_status"],
        validation_errors=row["validation_errors"],
        attempt_count=row["attempt_count"],
        tools_called=row["tools_called"],
        data_quality_state=row["data_quality_state"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
