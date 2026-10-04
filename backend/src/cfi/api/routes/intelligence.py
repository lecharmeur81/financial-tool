"""Read-only intelligence-event endpoints (Phase 35).

Explicitly a minimal view over ``sig.intelligence_event`` for the events
``cfi.realtime.service.RealtimeIntelligenceService`` persists — not the final dashboard, not an
Executive Dashboard redesign (out of this phase's scope). ``GET /`` lists recent events, optionally
filtered by domain/severity/event type/time; ``GET /{event_id}`` reads one by its UUID. Both are
unauthenticated GETs, matching every other read-only route in this codebase (``cfi.api.auth``
protects only mutating endpoints, and these two never mutate anything)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.realtime.repository import IntelligenceEventRepository

router = APIRouter(prefix="/api/v1/intelligence-events", tags=["intelligence-events"])


class IntelligenceEventOut(BaseModel):
    event_id: uuid.UUID
    created_at: datetime
    observed_at: datetime
    domain: str
    event_type: str
    severity: str
    previous_value: str | None
    current_value: str
    change_magnitude: Decimal | None
    detection_method: str
    data_quality_state: str
    component_status: str
    dedup_key: str
    correlation_key: str
    snapshot_id: int | None
    status: str
    ai_interpretation_id: int | None


def _repo(request: Request) -> IntelligenceEventRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return IntelligenceEventRepository(engine)


def _to_out(row: dict[str, Any]) -> IntelligenceEventOut:
    return IntelligenceEventOut(
        event_id=row["uuid"],
        created_at=row["created_at"],
        observed_at=row["observed_at"],
        domain=row["domain"],
        event_type=row["event_type"],
        severity=row["severity"],
        previous_value=row["previous_value"],
        current_value=row["current_value"],
        change_magnitude=row["change_magnitude"],
        detection_method=row["detection_method"],
        data_quality_state=row["data_quality_state"],
        component_status=row["component_status"],
        dedup_key=row["dedup_key"],
        correlation_key=row["correlation_key"],
        snapshot_id=row["snapshot_id"],
        status=row["status"],
        ai_interpretation_id=row["ai_interpretation_id"],
    )


@router.get("/", response_model=list[IntelligenceEventOut])
async def list_intelligence_events(
    request: Request,
    domain: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    since: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[IntelligenceEventOut]:
    rows = await _repo(request).list_events(
        domain=domain, severity=severity, event_type=event_type, since=since, limit=limit
    )
    return [_to_out(r) for r in rows]


@router.get("/{event_id}", response_model=IntelligenceEventOut)
async def get_intelligence_event(request: Request, event_id: uuid.UUID) -> IntelligenceEventOut:
    row = await _repo(request).get_event(event_id)
    if row is None:
        raise NotFoundError(f"No intelligence event found for event_id={event_id}.")
    return _to_out(row)
