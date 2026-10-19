"""Read-only Advisor Brief endpoint (Phase 53; ADR-0093).

``GET /api/v1/advisor/brief?asset=BTC`` reads the **latest stored** ``ai.snapshot`` row, builds the
Decision Center view and the investment decision from it with the existing builders, and composes
``advisor_brief.v0`` (``cfi.advisor``). It never builds a snapshot, never ingests, never calls a
provider or Claude, and never writes: one ``SELECT``, then pure computation. Errors follow
``/decision/current``: no stored snapshot is 404 (a normal first-run state); an unsupported asset
is 422; a stored payload the engines refuse is 503, with the reason."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from cfi.advisor import AdvisorInputError, build_advisor_brief
from cfi.advisor.compose import build_investment_decision_for
from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.core.errors import DataValidationError, NotFoundError, ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError, UnsupportedScopeError
from cfi.decision.identity import SnapshotRef
from cfi.decision.read_service import DEFAULT_ASSET, build_decision_view
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
)

router = APIRouter(prefix="/api/v1/advisor", tags=["advisor"])


class AdvisorBriefOut(BaseModel):
    contract_version: str
    asset: str
    answered_from: dict[str, str]
    snapshot: dict[str, Any]
    layers: dict[str, str]
    assessment: dict[str, Any]
    signals: list[dict[str, Any]]
    readings: list[dict[str, Any]]
    uncertainty: dict[str, Any]
    data_gaps: dict[str, Any]
    risk: dict[str, Any]
    invalidation: dict[str, Any] | None
    reassessment: list[dict[str, Any]]
    field_trace: dict[str, dict[str, Any]]
    not_claimed: list[dict[str, str]]


@router.get("/brief", response_model=AdvisorBriefOut)
async def advisor_brief(
    source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
    asset: Annotated[str, Query(description="BTC, ETH, SOL or XRP (default BTC)")] = DEFAULT_ASSET,
) -> dict[str, Any]:
    row = await source.latest_snapshot_row()
    if row is None:
        raise NotFoundError("No stored snapshot exists yet, so there is nothing to brief.")
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        view = build_decision_view(row.payload, asset, snapshot_ref=ref)
        investment = build_investment_decision_for(row.payload, ref)
        return build_advisor_brief(view, investment, view["asset"])
    except UnsupportedScopeError as exc:
        raise DataValidationError(str(exc)) from exc
    except (
        InvalidSnapshotError,
        ConfirmationInputError,
        OpportunityInputError,
        RankingInputError,
        RiskInputError,
        InvestmentInputError,
        AdvisorInputError,
    ) as exc:
        raise ServiceUnavailableError(
            f"The latest stored snapshot cannot be used for an advisor brief: {exc}"
        ) from exc
