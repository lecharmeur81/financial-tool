"""Alert endpoints (Phase 23).

``POST /evaluate`` triggers one evaluation cycle via the existing worker infrastructure (the
``alerts.evaluate`` Celery task, same ``send_task`` helper every other route in this module uses) —
it does not run the evaluation inline in the API process, mirroring every other compute-triggering
route in this codebase. ``GET /`` lists alerts (optionally filtered by lifecycle status); ``GET
/{alert_id}`` reads one; ``POST /{alert_id}/acknowledge`` and ``POST /{alert_id}/resolve`` are the
user-driven lifecycle transitions ("Persistence": "active, acknowledged, resolved, expired")."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.alerts.repository import AlertRepository
from cfi.alerts.universe import STATUS_VALUES
from cfi.api.auth import require_api_key
from cfi.api.limiter import MUTATION_LIMIT, limiter
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.worker.client import send_task

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


class EvaluateResponse(BaseModel):
    status: str


class AlertStatus(BaseModel):
    alert_id: uuid.UUID
    alert_type: str
    severity: str
    domain: str
    trigger_condition: str
    observed_value: str
    reference_value: str | None
    evidence_field_ids: list[str]
    snapshot_id: int | None
    source_tool_id: str
    component_status: str
    data_quality_state: str
    status: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _repo(request: Request) -> AlertRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return AlertRepository(engine)


def _to_status(row: dict[str, Any]) -> AlertStatus:
    return AlertStatus(
        alert_id=row["uuid"],
        alert_type=row["alert_type"],
        severity=row["severity"],
        domain=row["domain"],
        trigger_condition=row["trigger_condition"],
        observed_value=row["observed_value"],
        reference_value=row["reference_value"],
        evidence_field_ids=row["evidence_field_ids"],
        snapshot_id=row["snapshot_id"],
        source_tool_id=row["source_tool_id"],
        component_status=row["component_status"],
        data_quality_state=row["data_quality_state"],
        status=row["status"],
        acknowledged_at=row["acknowledged_at"],
        resolved_at=row["resolved_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/evaluate", response_model=EvaluateResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(MUTATION_LIMIT)
async def evaluate(request: Request) -> EvaluateResponse:
    send_task(request.app.state.settings, "alerts.evaluate", args=(), queue="ingest")
    return EvaluateResponse(status="queued")


@router.get("/", response_model=list[AlertStatus])
async def list_alerts(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[AlertStatus]:
    if status is not None and status not in STATUS_VALUES:
        raise NotFoundError(f"Unknown alert status {status!r} (known: {', '.join(STATUS_VALUES)}).")
    rows = await _repo(request).list_alerts(status=status, limit=limit)
    return [_to_status(r) for r in rows]


@router.get("/{alert_id}", response_model=AlertStatus)
async def get_alert(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    row = await _repo(request).get_by_uuid(alert_id)
    if row is None:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    return _to_status(row)


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def acknowledge(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    repo = _repo(request)
    changed = await repo.set_status(alert_id, status="acknowledged", now=utc_now())
    if not changed:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    row = await repo.get_by_uuid(alert_id)
    if row is None:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    return _to_status(row)


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def resolve(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    repo = _repo(request)
    changed = await repo.set_status(alert_id, status="resolved", now=utc_now())
    if not changed:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    row = await repo.get_by_uuid(alert_id)
    if row is None:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    return _to_status(row)
