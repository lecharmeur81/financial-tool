"""Read-only portfolio exposure endpoint (Phase 54 step 1; ADR-0095).

``GET /api/v1/portfolio/exposure`` summarises the SIMULATED open paper trades (Phase 24) and, for
each represented asset, shows the existing Advisor Brief's stance and decision state next to the
position. It reads open ``usr.paper_trade`` rows and prices through the existing
``PaperTradingService.open_positions`` (selects only), and at most one stored snapshot. It never
writes, never builds a snapshot, never ingests, and calls no provider or Claude. Nothing here is a
real holding; see ``cfi.portfolio.exposure``."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from cfi.advisor import AdvisorInputError, build_advisor_brief
from cfi.advisor.compose import build_investment_decision_for
from cfi.api.routes.decision import SnapshotSource, get_snapshot_source
from cfi.core.errors import ServiceUnavailableError
from cfi.decision.context import InvalidSnapshotError, UnsupportedScopeError
from cfi.decision.identity import SnapshotRef
from cfi.decision.read_service import build_decision_view
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
)
from cfi.paper.service import OpenPosition, PaperTradingService
from cfi.paper.universe import ASSET_SYMBOLS
from cfi.portfolio import build_exposure, summarize_brief

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])

_BRIEF_ERRORS = (
    UnsupportedScopeError,
    InvalidSnapshotError,
    ConfirmationInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
    InvestmentInputError,
    AdvisorInputError,
)


class PositionSource(Protocol):
    """What the route needs from paper trading: the open positions, read-only."""

    async def open_positions(self) -> list[OpenPosition]: ...


class PortfolioExposureOut(BaseModel):
    contract_version: str
    source: dict[str, Any]
    conventions: list[str]
    summary: dict[str, Any]
    assets: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    invalid_positions: list[dict[str, Any]]
    data_quality: dict[str, Any]
    unavailable: list[dict[str, str]]
    not_claimed: list[dict[str, str]]


def get_position_source(request: Request) -> PositionSource:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return PaperTradingService(engine, request.app.state.settings)


def _position_dict(p: OpenPosition) -> dict[str, Any]:
    t = p.trade
    return {
        "trade_id": t.get("uuid"),
        "asset": t.get("asset"),
        "direction": t.get("direction"),
        "notional": t.get("notional"),
        "leverage": t.get("leverage"),
        "margin": t.get("margin"),
        "price_status": "missing" if p.data_quality_state == "missing" else "ok",
    }


def _briefs_for(assets: list[str], row: Any) -> dict[str, dict[str, Any]]:
    """Advisor Brief summaries for ``assets``, or an explicit not-assessed reason for each."""
    if row is None:
        return {
            a: {"status": "not_assessed", "reason": "No stored snapshot exists yet."}
            for a in assets
        }
    ref = SnapshotRef(
        row_id=row.row_id,
        uuid=row.uuid,
        payload_hash=row.payload_hash,
        created_at=row.created_at,
    )
    try:
        investment = build_investment_decision_for(row.payload, ref)
    except _BRIEF_ERRORS as exc:
        reason = f"The latest stored snapshot cannot be used for an advisor brief: {exc}"
        return {a: {"status": "not_assessed", "reason": reason} for a in assets}
    out: dict[str, dict[str, Any]] = {}
    for asset in assets:
        try:
            view = build_decision_view(row.payload, asset, snapshot_ref=ref)
            brief = build_advisor_brief(view, investment, view["asset"])
            out[asset] = summarize_brief(brief)
        except _BRIEF_ERRORS as exc:
            out[asset] = {"status": "not_assessed", "reason": f"No usable brief: {exc}"}
    return out


@router.get("/exposure", response_model=PortfolioExposureOut)
async def portfolio_exposure(
    positions_source: Annotated[PositionSource, Depends(get_position_source)],
    snapshot_source: Annotated[SnapshotSource, Depends(get_snapshot_source)],
) -> dict[str, Any]:
    positions = [_position_dict(p) for p in await positions_source.open_positions()]
    assets = sorted({str(p["asset"]) for p in positions if p["asset"] in ASSET_SYMBOLS})
    briefs: dict[str, dict[str, Any]] = {}
    if assets:  # an empty portfolio needs no snapshot
        briefs = _briefs_for(assets, await snapshot_source.latest_snapshot_row())
    return build_exposure(positions, briefs, ASSET_SYMBOLS)
