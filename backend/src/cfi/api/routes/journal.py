"""Decision journal endpoints (Phase 25).

Runs inline in the API request, same posture as ``paper.py`` and for the same reason: no AI call
and no periodic sweep here, only a database write plus the already-cheap, already-tested
snapshot/alert/brief reads every one of those calls already performs for Phase 23/24, so a worker
queue would be unnecessary new infrastructure for no benefit (R13).

No automatic decision generation, no trading advice, and no autonomous judgment of the user
anywhere in this router (Phase 25 "Important constraints")."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.api.auth import require_api_key
from cfi.api.limiter import MUTATION_LIMIT, limiter
from cfi.core.errors import DataValidationError, NotFoundError, ServiceUnavailableError
from cfi.journal.service import (
    OUTCOME_VALUES,
    DecisionJournalOutcomeInput,
    DecisionJournalService,
)
from cfi.journal.stats import DecisionReview, DecisionStats
from cfi.journal.universe import STATUS_VALUES

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


class CreateDecisionRequest(BaseModel):
    asset: str
    decision_type: str
    thesis: str
    expected_scenario: str | None = None
    alternative_scenario: str | None = None
    time_horizon: str | None = None
    entry_price: Decimal | None = None
    invalidation_condition: str | None = None
    key_risks: str | None = None
    confidence: Decimal | None = None
    notes: str | None = None


class UpdateNotesRequest(BaseModel):
    notes: str | None = None


class RecordOutcomeRequest(BaseModel):
    status: str
    outcome: str | None = None
    thesis_supported: bool | None = None
    thesis_contradicted: bool | None = None
    invalidation_occurred: bool | None = None
    evidence_changed_notes: str | None = None
    actual_market_movement_text: str | None = None
    lessons_notes: str | None = None


class LinkPaperTradeRequest(BaseModel):
    paper_trade_id: uuid.UUID


class DecisionStatus(BaseModel):
    decision_id: uuid.UUID
    decision_time: datetime
    asset: str
    decision_type: str
    thesis: str
    expected_scenario: str | None
    alternative_scenario: str | None
    time_horizon: str | None
    entry_price: Decimal | None
    observed_price_at_decision: Decimal | None
    invalidation_condition: str | None
    key_risks: str | None
    confidence: Decimal | None
    notes: str | None
    status: str
    outcome: str | None
    thesis_supported: bool | None
    thesis_contradicted: bool | None
    invalidation_occurred: bool | None
    evidence_changed_notes: str | None
    actual_market_movement_text: str | None
    actual_price_at_outcome: Decimal | None
    actual_market_movement_pct: Decimal | None
    lessons_notes: str | None
    outcome_timestamp: datetime | None
    decision_snapshot_id: int | None
    market_brief_id: int | None
    relevant_alert_ids: list[str]
    market_regime_label: str | None
    paper_trade_id: int | None
    created_at: datetime
    updated_at: datetime


class DecisionStatsResponse(BaseModel):
    total_decisions: int
    open_decisions: int
    resolved_decisions: int
    invalidated_decisions: int
    cancelled_decisions: int
    thesis_supported_count: int
    thesis_contradicted_count: int
    invalidation_occurred_count: int
    average_time_to_resolution_hours: Decimal | None
    disclaimer: str = (
        "Descriptive statistics over the user's own recorded decisions. Not a recommendation, "
        "ranking, or prediction of future performance."
    )


class DecisionReviewResponse(BaseModel):
    decisions_by_type: dict[str, int]
    decisions_by_regime: dict[str, int]
    decisions_by_invalidation_condition: dict[str, int]
    decisions_by_outcome: dict[str, int]
    disclaimer: str = (
        "These are descriptive groupings of the user's own past decisions, not recommendations "
        "and not a ranking of strategies."
    )


def _service(request: Request) -> DecisionJournalService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings = request.app.state.settings
    return DecisionJournalService(engine, settings)


def _to_status(row: dict[str, Any]) -> DecisionStatus:
    return DecisionStatus(
        decision_id=row["uuid"],
        decision_time=row["decision_time"],
        asset=row["asset"],
        decision_type=row["decision_type"],
        thesis=row["thesis"],
        expected_scenario=row["expected_scenario"],
        alternative_scenario=row["alternative_scenario"],
        time_horizon=row["time_horizon"],
        entry_price=row["entry_price"],
        observed_price_at_decision=row["observed_price_at_decision"],
        invalidation_condition=row["invalidation_condition"],
        key_risks=row["key_risks"],
        confidence=row["confidence"],
        notes=row["notes"],
        status=row["status"],
        outcome=row["outcome"],
        thesis_supported=row["thesis_supported"],
        thesis_contradicted=row["thesis_contradicted"],
        invalidation_occurred=row["invalidation_occurred"],
        evidence_changed_notes=row["evidence_changed_notes"],
        actual_market_movement_text=row["actual_market_movement_text"],
        actual_price_at_outcome=row["actual_price_at_outcome"],
        actual_market_movement_pct=row["actual_market_movement_pct"],
        lessons_notes=row["lessons_notes"],
        outcome_timestamp=row["outcome_timestamp"],
        decision_snapshot_id=row["decision_snapshot_id"],
        market_brief_id=row["market_brief_id"],
        relevant_alert_ids=list(row["relevant_alert_ids"] or []),
        market_regime_label=row["market_regime_label"],
        paper_trade_id=row["paper_trade_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_stats_response(stats: DecisionStats) -> DecisionStatsResponse:
    return DecisionStatsResponse(
        total_decisions=stats.total_decisions,
        open_decisions=stats.open_decisions,
        resolved_decisions=stats.resolved_decisions,
        invalidated_decisions=stats.invalidated_decisions,
        cancelled_decisions=stats.cancelled_decisions,
        thesis_supported_count=stats.thesis_supported_count,
        thesis_contradicted_count=stats.thesis_contradicted_count,
        invalidation_occurred_count=stats.invalidation_occurred_count,
        average_time_to_resolution_hours=stats.average_time_to_resolution_hours,
    )


def _to_review_response(review: DecisionReview) -> DecisionReviewResponse:
    return DecisionReviewResponse(
        decisions_by_type=review.decisions_by_type,
        decisions_by_regime=review.decisions_by_regime,
        decisions_by_invalidation_condition=review.decisions_by_invalidation_condition,
        decisions_by_outcome=review.decisions_by_outcome,
    )


@router.post("/decisions", response_model=DecisionStatus, dependencies=[Depends(require_api_key)])
@limiter.limit(MUTATION_LIMIT)
async def create_decision(request: Request, body: CreateDecisionRequest) -> DecisionStatus:
    svc = _service(request)
    row = await svc.create_decision(
        asset=body.asset,
        decision_type=body.decision_type,
        thesis=body.thesis,
        expected_scenario=body.expected_scenario,
        alternative_scenario=body.alternative_scenario,
        time_horizon=body.time_horizon,
        entry_price=body.entry_price,
        invalidation_condition=body.invalidation_condition,
        key_risks=body.key_risks,
        confidence=body.confidence,
        notes=body.notes,
    )
    return _to_status(row)


@router.get("/decisions", response_model=list[DecisionStatus])
async def list_decisions(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[DecisionStatus]:
    if status is not None and status not in STATUS_VALUES:
        raise NotFoundError(
            f"Unknown decision status {status!r} (known: {', '.join(STATUS_VALUES)})."
        )
    rows = await _service(request).list_decisions(status=status, limit=limit)
    return [_to_status(r) for r in rows]


@router.get("/review", response_model=DecisionReviewResponse)
async def review(request: Request) -> DecisionReviewResponse:
    result = await _service(request).review()
    return _to_review_response(result)


@router.get("/stats", response_model=DecisionStatsResponse)
async def stats(request: Request) -> DecisionStatsResponse:
    result = await _service(request).stats()
    return _to_stats_response(result)


@router.get("/decisions/{decision_id}", response_model=DecisionStatus)
async def get_decision(request: Request, decision_id: uuid.UUID) -> DecisionStatus:
    row = await _service(request).get_decision(decision_id)
    return _to_status(row)


@router.patch(
    "/decisions/{decision_id}/notes",
    response_model=DecisionStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def update_notes(
    request: Request, decision_id: uuid.UUID, body: UpdateNotesRequest
) -> DecisionStatus:
    row = await _service(request).update_notes(decision_id, notes=body.notes)
    return _to_status(row)


@router.post(
    "/decisions/{decision_id}/outcome",
    response_model=DecisionStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def record_outcome(
    request: Request, decision_id: uuid.UUID, body: RecordOutcomeRequest
) -> DecisionStatus:
    if body.status not in ("resolved", "invalidated"):
        raise DataValidationError(
            f"status must be one of 'resolved' or 'invalidated' (got {body.status!r})."
        )
    if body.outcome is not None and body.outcome not in OUTCOME_VALUES:
        raise DataValidationError(
            f"Unknown outcome {body.outcome!r} (must be one of {OUTCOME_VALUES} or omitted)."
        )
    outcome_input = DecisionJournalOutcomeInput(
        outcome=body.outcome,
        thesis_supported=body.thesis_supported,
        thesis_contradicted=body.thesis_contradicted,
        invalidation_occurred=body.invalidation_occurred,
        evidence_changed_notes=body.evidence_changed_notes,
        actual_market_movement_text=body.actual_market_movement_text,
        lessons_notes=body.lessons_notes,
        status=body.status,
    )
    row = await _service(request).record_outcome(decision_id, outcome_input=outcome_input)
    return _to_status(row)


@router.post(
    "/decisions/{decision_id}/cancel",
    response_model=DecisionStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def cancel_decision(request: Request, decision_id: uuid.UUID) -> DecisionStatus:
    row = await _service(request).cancel_decision(decision_id)
    return _to_status(row)


@router.post(
    "/decisions/{decision_id}/paper-trade",
    response_model=DecisionStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def link_paper_trade(
    request: Request, decision_id: uuid.UUID, body: LinkPaperTradeRequest
) -> DecisionStatus:
    row = await _service(request).link_paper_trade(decision_id, paper_trade_id=body.paper_trade_id)
    return _to_status(row)


@router.delete(
    "/decisions/{decision_id}/paper-trade",
    response_model=DecisionStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def unlink_paper_trade(request: Request, decision_id: uuid.UUID) -> DecisionStatus:
    row = await _service(request).unlink_paper_trade(decision_id)
    return _to_status(row)
