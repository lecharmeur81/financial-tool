"""Alert endpoints (Phase 23).

``POST /evaluate`` triggers one evaluation cycle via the existing worker infrastructure (the
``alerts.evaluate`` Celery task, same ``send_task`` helper every other route in this module uses) —
it does not run the evaluation inline in the API process, mirroring every other compute-triggering
route in this codebase. ``GET /`` lists alerts (optionally filtered by lifecycle status); ``GET
/{alert_id}`` reads one; ``POST /{alert_id}/acknowledge`` and ``POST /{alert_id}/resolve`` are the
user-driven lifecycle transitions ("Persistence": "active, acknowledged, resolved, expired"). Since
Phase 52 they follow ``cfi.alerts.lifecycle.user_transition``: repeating a request is a no-op and a
terminal alert (``resolved``/``expired``) is never reopened or re-stamped (409)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.alerts.lifecycle import user_transition
from cfi.alerts.lifecycle_marker import (
    CurrentEvaluation,
    build_current_evaluation,
    derive_marker,
)
from cfi.alerts.repository import AlertRepository
from cfi.alerts.universe import STATUS_VALUES
from cfi.analyst.repository import AnalystRepository
from cfi.api.auth import require_api_key
from cfi.api.limiter import MUTATION_LIMIT, limiter
from cfi.core.errors import AlertTransitionError, NotFoundError, ServiceUnavailableError
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.worker.client import send_task

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
log = get_logger(__name__)


class EvaluateResponse(BaseModel):
    status: str


class LifecycleMarkerOut(BaseModel):
    """Derived, read-time label (Phase 52 P3): never stored, never changes ``status``."""

    kind: str
    reason: str
    evaluated_snapshot_id: int | None = None
    evaluated_as_of: str | None = None


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
    # Always derived (cfi.alerts.lifecycle_marker); status-change responses carry no evaluation,
    # so an open alert there reads ``not_evaluated``.
    lifecycle_marker: LifecycleMarkerOut | None = None


def _repo(request: Request) -> AlertRepository:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return AlertRepository(engine)


async def _current_evaluation(request: Request) -> CurrentEvaluation | None:
    """Evaluate the latest stored snapshot once per request; ``None`` if unavailable."""
    try:
        latest = await AnalystRepository(request.app.state.engine).latest_snapshot()
    except Exception:  # the marker is advisory; a failed lookup is reported as not evaluated
        log.warning("alert_marker_snapshot_unavailable", exc_info=True)
        return None
    return build_current_evaluation(*latest) if latest else None


def _to_status(row: dict[str, Any], current: CurrentEvaluation | None = None) -> AlertStatus:
    marker = derive_marker(row, current)
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
        lifecycle_marker=LifecycleMarkerOut(
            kind=marker.kind,
            reason=marker.reason,
            evaluated_snapshot_id=marker.evaluated_snapshot_id,
            evaluated_as_of=marker.evaluated_as_of,
        ),
    )


async def apply_user_transition(
    repo: AlertRepository, alert_id: uuid.UUID, target: str, *, now: datetime
) -> dict[str, Any]:
    """One user-driven status change, judged by ``user_transition`` and applied by a guarded UPDATE.

    ``noop`` (already in ``target``) returns the stored row unchanged. A rejected change raises
    ``AlertTransitionError`` (409, logged by the error handler); nothing is written. If the guarded
    write loses a race the row is re-read and judged again, so a terminal alert is never altered."""
    row = await repo.get_by_uuid(alert_id)
    if row is None:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    verdict = user_transition(row["status"], target)
    if verdict == "apply":
        before = row["status"]
        if await repo.set_status(alert_id, status=target, now=now):
            log.info(
                "alert_transition_applied",
                alert_id=str(alert_id),
                from_status=before,
                to_status=target,
            )
            fresh = await repo.get_by_uuid(alert_id)
            if fresh is None:
                raise NotFoundError(f"No alert found for alert_id={alert_id}.")
            return fresh
        row = await repo.get_by_uuid(alert_id)
        if row is None:
            raise NotFoundError(f"No alert found for alert_id={alert_id}.")
        verdict = user_transition(row["status"], target)
    if verdict == "noop":
        log.info("alert_transition_noop", alert_id=str(alert_id), status=target)
        return row
    raise AlertTransitionError(
        f"Alert {alert_id} is {row['status']!r} and cannot be set to {target!r}.",
        alert_id=str(alert_id),
        from_status=row["status"],
        to_status=target,
    )


@router.post("/evaluate", response_model=EvaluateResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(MUTATION_LIMIT)
async def evaluate(request: Request) -> EvaluateResponse:
    send_task(request.app.state.settings, "alerts.evaluate", args=(), queue="alerts")
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
    current = await _current_evaluation(request)
    return [_to_status(r, current) for r in rows]


@router.get("/{alert_id}", response_model=AlertStatus)
async def get_alert(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    row = await _repo(request).get_by_uuid(alert_id)
    if row is None:
        raise NotFoundError(f"No alert found for alert_id={alert_id}.")
    return _to_status(row, await _current_evaluation(request))


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def acknowledge(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    row = await apply_user_transition(_repo(request), alert_id, "acknowledged", now=utc_now())
    return _to_status(row)


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def resolve(request: Request, alert_id: uuid.UUID) -> AlertStatus:
    row = await apply_user_transition(_repo(request), alert_id, "resolved", now=utc_now())
    return _to_status(row)
