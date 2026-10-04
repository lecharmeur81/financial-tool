"""Paper trading endpoints (Phase 24).

Every endpoint runs its work inline in the API request — unlike every other compute-triggering
route in this codebase (``analyst``, ``brief``, ``alerts``), there is no AI call and no periodic
sweep here, only a database write plus a handful of already-cheap, already-tested reads
(``cfi.divergence.adapters.Adapters.price_close``), so queuing a worker task would be unnecessary
new infrastructure for no benefit (R13) — a deliberate, documented difference from those three
routers, not an oversight.

No exchange order endpoint, no trading credential, no API key, and no real execution pathway
anywhere in this router (Phase 24 "Security / safety")."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from cfi.api.auth import require_api_key
from cfi.api.limiter import MUTATION_LIMIT, limiter
from cfi.core.errors import NotFoundError, ServiceUnavailableError
from cfi.paper.service import PaperTradingService
from cfi.paper.stats import PerformanceStats
from cfi.paper.universe import STATUS_VALUES

router = APIRouter(prefix="/api/v1/paper", tags=["paper"])


class CreateTradeRequest(BaseModel):
    asset: str
    direction: str
    notional: Decimal = Field(gt=0)
    leverage: Decimal | None = Field(default=None, gt=0)
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    cost_model_version: str | None = None
    strategy_tag: str | None = None
    notes: str | None = None


class TradeStatus(BaseModel):
    trade_id: uuid.UUID
    asset: str
    direction: str
    status: str
    entry_time: datetime
    entry_price_observed: Decimal
    entry_price_execution: Decimal
    entry_price_source: str
    notional: Decimal
    leverage: Decimal
    margin: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    exit_time: datetime | None
    exit_price_observed: Decimal | None
    exit_price_execution: Decimal | None
    exit_price_source: str | None
    cost_model_version: str
    gross_pnl: Decimal | None
    slippage_cost: Decimal | None
    fees_total: Decimal | None
    realized_pnl: Decimal | None
    return_pct: Decimal | None
    max_favorable_move_pct: Decimal | None
    max_adverse_move_pct: Decimal | None
    strategy_tag: str | None
    notes: str | None
    decision_snapshot_id: int | None
    market_brief_id: int | None
    relevant_alert_ids: list[str]
    created_at: datetime
    updated_at: datetime


class OpenPositionStatus(BaseModel):
    trade: TradeStatus
    current_price_observed: Decimal | None
    unrealized_gross_pnl: Decimal | None
    unrealized_net_pnl: Decimal | None
    unrealized_return_pct: Decimal | None
    data_quality_state: str


class PerformanceStatsResponse(BaseModel):
    total_trades: int
    open_trades: int
    closed_trades: int
    cancelled_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    gross_pnl: Decimal
    net_pnl: Decimal
    average_win: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    max_drawdown: Decimal | None
    disclaimer: str = (
        "Simulated performance on hypothetical trades. Not a guarantee or prediction of future "
        "results."
    )


def _service(request: Request) -> PaperTradingService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings = request.app.state.settings
    return PaperTradingService(engine, settings)


def _to_status(row: dict[str, Any]) -> TradeStatus:
    return TradeStatus(
        trade_id=row["uuid"],
        asset=row["asset"],
        direction=row["direction"],
        status=row["status"],
        entry_time=row["entry_time"],
        entry_price_observed=row["entry_price_observed"],
        entry_price_execution=row["entry_price_execution"],
        entry_price_source=row["entry_price_source"],
        notional=row["notional"],
        leverage=row["leverage"],
        margin=row["margin"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        exit_time=row["exit_time"],
        exit_price_observed=row["exit_price_observed"],
        exit_price_execution=row["exit_price_execution"],
        exit_price_source=row["exit_price_source"],
        cost_model_version=row["cost_model_version"],
        gross_pnl=row["gross_pnl"],
        slippage_cost=row["slippage_cost"],
        fees_total=row["fees_total"],
        realized_pnl=row["realized_pnl"],
        return_pct=row["return_pct"],
        max_favorable_move_pct=row["max_favorable_move_pct"],
        max_adverse_move_pct=row["max_adverse_move_pct"],
        strategy_tag=row["strategy_tag"],
        notes=row["notes"],
        decision_snapshot_id=row["decision_snapshot_id"],
        market_brief_id=row["market_brief_id"],
        relevant_alert_ids=list(row["relevant_alert_ids"] or []),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_stats_response(stats: PerformanceStats) -> PerformanceStatsResponse:
    return PerformanceStatsResponse(
        total_trades=stats.total_trades,
        open_trades=stats.open_trades,
        closed_trades=stats.closed_trades,
        cancelled_trades=stats.cancelled_trades,
        winning_trades=stats.winning_trades,
        losing_trades=stats.losing_trades,
        win_rate=stats.win_rate,
        gross_pnl=stats.gross_pnl,
        net_pnl=stats.net_pnl,
        average_win=stats.average_win,
        average_loss=stats.average_loss,
        profit_factor=stats.profit_factor,
        expectancy=stats.expectancy,
        max_drawdown=stats.max_drawdown,
    )


@router.post("/trades", response_model=TradeStatus, dependencies=[Depends(require_api_key)])
@limiter.limit(MUTATION_LIMIT)
async def create_trade(request: Request, body: CreateTradeRequest) -> TradeStatus:
    svc = _service(request)
    row = await svc.create_trade(
        asset=body.asset,
        direction=body.direction,
        notional=body.notional,
        leverage=body.leverage,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        cost_model_version=body.cost_model_version,
        strategy_tag=body.strategy_tag,
        notes=body.notes,
    )
    return _to_status(row)


@router.get("/trades", response_model=list[TradeStatus])
async def list_trades(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[TradeStatus]:
    if status is not None and status not in STATUS_VALUES:
        raise NotFoundError(f"Unknown trade status {status!r} (known: {', '.join(STATUS_VALUES)}).")
    rows = await _service(request).list_trades(status=status, limit=limit)
    return [_to_status(r) for r in rows]


@router.get("/positions", response_model=list[OpenPositionStatus])
async def open_positions(request: Request) -> list[OpenPositionStatus]:
    positions = await _service(request).open_positions()
    results: list[OpenPositionStatus] = []
    for pos in positions:
        unrealized = pos.unrealized_pnl
        results.append(
            OpenPositionStatus(
                trade=_to_status(pos.trade),
                current_price_observed=pos.current_price_observed,
                unrealized_gross_pnl=unrealized.gross_pnl if unrealized else None,
                unrealized_net_pnl=unrealized.net_pnl if unrealized else None,
                unrealized_return_pct=unrealized.return_pct if unrealized else None,
                data_quality_state=pos.data_quality_state,
            )
        )
    return results


@router.get("/performance", response_model=PerformanceStatsResponse)
async def performance(request: Request) -> PerformanceStatsResponse:
    stats = await _service(request).performance_stats()
    return _to_stats_response(stats)


@router.get("/trades/{trade_id}", response_model=TradeStatus)
async def get_trade(request: Request, trade_id: uuid.UUID) -> TradeStatus:
    row = await _service(request).get_trade(trade_id)
    return _to_status(row)


@router.post(
    "/trades/{trade_id}/close",
    response_model=TradeStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def close_trade(request: Request, trade_id: uuid.UUID) -> TradeStatus:
    row = await _service(request).close_trade(trade_id)
    return _to_status(row)


@router.post(
    "/trades/{trade_id}/cancel",
    response_model=TradeStatus,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(MUTATION_LIMIT)
async def cancel_trade(request: Request, trade_id: uuid.UUID) -> TradeStatus:
    row = await _service(request).cancel_trade(trade_id)
    return _to_status(row)
