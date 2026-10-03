"""``PaperTradingService`` — orchestrates paper-trade creation, closing, cancellation and the two
read-only aggregate views (open positions, performance stats), Phase 24 spec.

Reuses, entirely unchanged: ``cfi.analyst.snapshot.build_snapshot``/``AnalystRepository.
insert_snapshot`` (the same immutable, 14-tool evidence snapshot Phases 21-23 already build —
"Market-context snapshot": "Reuse the existing Phase 21/22 snapshot infrastructure"),
``cfi.divergence.adapters.Adapters.price_close`` (the platform's one canonical point-in-time
price source), ``cfi.backtest.costs`` (the versioned fee/slippage model),
``cfi.alerts.repository.AlertRepository.list_alerts`` (read-only; "relevant alerts" context) and
``cfi.brief.repository.BriefRepository.latest_completed_brief`` (read-only; "market brief"
context).

No AI/Claude component at all, no exchange connection, no order-routing, no credentials anywhere
in this module (Phase 24 "Important constraints" / "Security / safety")."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.snapshot import build_snapshot
from cfi.backtest import costs
from cfi.brief.repository import BriefRepository
from cfi.core.config import Settings
from cfi.core.errors import (
    ComputationError,
    DataValidationError,
    InsufficientDataError,
    NotFoundError,
)
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.divergence.adapters import Adapters
from cfi.paper import pnl
from cfi.paper.repository import PaperTradeRepository
from cfi.paper.stats import PerformanceStats, performance_stats
from cfi.paper.universe import (
    ASSET_SYMBOLS,
    DEFAULT_COST_MODEL_VERSION,
    DIRECTION_VALUES,
    RELEVANT_ALERTS_LIMIT,
    VALID_TRANSITIONS,
)

log = get_logger(__name__)

_PRICE_SOURCE = "coinbase daily close (cfi.divergence.adapters.Adapters.price_close)"


@dataclass(frozen=True, slots=True)
class OpenPosition:
    trade: dict[str, Any]
    current_price_observed: Decimal | None
    unrealized_pnl: pnl.PnLResult | None
    data_quality_state: str  # "ok" | "missing" — current price unavailable


class PaperTradingService:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
        self.repo = PaperTradeRepository(engine)
        # Reused unchanged — never a second, parallel implementation (R13).
        self.analyst_repo = AnalystRepository(engine)
        self.alert_repo = AlertRepository(engine)
        self.brief_repo = BriefRepository(engine)
        self.adapters = Adapters(engine)

    # ------------------------------------------------------------------ create

    async def create_trade(
        self,
        *,
        asset: str,
        direction: str,
        notional: Decimal,
        leverage: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        cost_model_version: str | None = None,
        strategy_tag: str | None = None,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Open a new paper trade, priced "as of now" (the decision-time snapshot and the entry
        price are both taken at the moment of creation — there is no backdated entry; a paper
        trade is a live decision log, not a historical backtest, which Phase 16 already covers,
        so this call can never use future information by construction — "Do NOT use future
        information when creating the decision-time snapshot"). ``now`` defaults to the real
        current time; an explicit value is for testing only (mirrors
        ``cfi.alerts.service.AlertService.evaluate``'s own ``now`` parameter)."""
        if asset not in ASSET_SYMBOLS:
            raise DataValidationError(
                f"Unknown asset {asset!r} (tracked assets: {', '.join(ASSET_SYMBOLS)})."
            )
        if direction not in DIRECTION_VALUES:
            raise DataValidationError(
                f"Unknown direction {direction!r} (must be one of {DIRECTION_VALUES})."
            )
        if notional <= 0:
            raise DataValidationError("notional must be positive.")
        leverage = leverage if leverage is not None else Decimal(1)
        if leverage <= 0:
            raise DataValidationError("leverage must be positive.")
        try:
            params = costs.parameters(cost_model_version)
        except KeyError as exc:
            raise DataValidationError(str(exc)) from exc

        now = now if now is not None else utc_now()

        series = await self.adapters.price_close(asset, now)
        entry_price_observed = pnl.current_price(series, now)
        if entry_price_observed is None:
            raise InsufficientDataError(
                f"No observed price available for {asset} as of {now.isoformat()}."
            )
        entry_price_execution = pnl.execution_price(
            entry_price_observed,
            direction=cast(pnl.Direction, direction),
            leg="entry",
            params=params,
        )

        # "Market-context snapshot" / "Integration with existing intelligence" — contextual
        # evidence only, never auto-converted into a trade decision (this service never reads
        # these to decide anything; it only records them for later review).
        snapshot = await build_snapshot(
            self.engine, self.settings, as_of=now, knowledge_time=now, question=None
        )
        snapshot_id, _snapshot_uuid = await self.analyst_repo.insert_snapshot(
            created_at=snapshot.created_at,
            as_of=snapshot.as_of,
            knowledge_time=snapshot.knowledge_time,
            snapshot_version=snapshot.snapshot_version,
            payload=snapshot.payload(),
            payload_hash=snapshot.snapshot_id,
        )
        active_alerts = await self.alert_repo.list_alerts(
            status="active", limit=RELEVANT_ALERTS_LIMIT
        )
        relevant_alert_ids = [str(a["uuid"]) for a in active_alerts]
        latest_brief = await self.brief_repo.latest_completed_brief()
        market_brief_id = latest_brief["id"] if latest_brief else None

        margin = notional / leverage
        _trade_id, trade_uuid = await self.repo.insert_trade(
            now=now,
            asset=asset,
            direction=direction,
            entry_time=now,
            entry_price_observed=entry_price_observed,
            entry_price_execution=entry_price_execution,
            entry_price_source=_PRICE_SOURCE,
            notional=notional,
            leverage=leverage,
            margin=margin,
            stop_loss=stop_loss,
            take_profit=take_profit,
            cost_model_version=params.version,
            strategy_tag=strategy_tag,
            notes=notes,
            decision_snapshot_id=snapshot_id,
            market_brief_id=market_brief_id,
            relevant_alert_ids=relevant_alert_ids,
        )
        row = await self.repo.get_by_uuid(trade_uuid)
        if row is None:
            raise ComputationError(
                f"Paper trade {trade_uuid} was inserted but could not be read back."
            )
        return row

    # ------------------------------------------------------------------ close / cancel

    async def close_trade(
        self, trade_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Realize P&L "as of now" using the same observed → execution → P&L pipeline as entry
        (``cfi.paper.pnl``). Rejects a trade that is not currently ``open`` ("Prevent invalid
        transitions"). ``now`` defaults to the real current time; an explicit value is for
        testing only."""
        row = await self.repo.get_by_uuid(trade_id)
        if row is None:
            raise NotFoundError(f"No paper trade found for trade_id={trade_id}.")
        self._require_transition(row["status"], "closed")

        now = now if now is not None else utc_now()
        series = await self.adapters.price_close(row["asset"], now)
        exit_price_observed = pnl.current_price(series, now)
        if exit_price_observed is None:
            raise InsufficientDataError(
                f"No observed price available for {row['asset']} as of {now.isoformat()}."
            )
        trade_direction = cast(pnl.Direction, row["direction"])
        params = costs.parameters(row["cost_model_version"])
        exit_price_execution = pnl.execution_price(
            exit_price_observed, direction=trade_direction, leg="exit", params=params
        )

        result = pnl.calculate_pnl(
            direction=trade_direction,
            notional=Decimal(row["notional"]),
            leverage=Decimal(row["leverage"]),
            entry_price_observed=Decimal(row["entry_price_observed"]),
            entry_price_execution=Decimal(row["entry_price_execution"]),
            exit_price_observed=exit_price_observed,
            exit_price_execution=exit_price_execution,
            params=params,
        )

        path = [
            p.value
            for p in series
            if p.has_value and row["entry_time"] <= p.time <= now and p.value is not None
        ]
        move = pnl.max_favorable_adverse(
            trade_direction, Decimal(row["entry_price_observed"]), path
        )

        await self.repo.close_trade(
            row["id"],
            now=now,
            exit_time=now,
            exit_price_observed=exit_price_observed,
            exit_price_execution=exit_price_execution,
            exit_price_source=_PRICE_SOURCE,
            gross_pnl=result.gross_pnl,
            slippage_cost=result.slippage_cost,
            fees_total=result.fees_total,
            realized_pnl=result.net_pnl,
            return_pct=result.return_pct,
            max_favorable_move_pct=move.favorable_pct,
            max_adverse_move_pct=move.adverse_pct,
        )
        updated = await self.repo.get_by_uuid(trade_id)
        if updated is None:
            raise ComputationError(f"Paper trade {trade_id} was closed but could not be read back.")
        return updated

    async def cancel_trade(
        self, trade_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Cancel an open trade without recording any exit price or P&L — the decision was
        withdrawn, not realized against the market ("Trade lifecycle": OPEN -> CANCELLED is a
        valid transition; CANCELLED carries no realized P&L)."""
        row = await self.repo.get_by_uuid(trade_id)
        if row is None:
            raise NotFoundError(f"No paper trade found for trade_id={trade_id}.")
        self._require_transition(row["status"], "cancelled")
        now = now if now is not None else utc_now()
        await self.repo.cancel_trade(row["id"], now=now)
        updated = await self.repo.get_by_uuid(trade_id)
        if updated is None:
            raise ComputationError(
                f"Paper trade {trade_id} was cancelled but could not be read back."
            )
        return updated

    @staticmethod
    def _require_transition(current_status: str, target_status: str) -> None:
        allowed = VALID_TRANSITIONS.get(current_status, ())
        if target_status not in allowed:
            raise DataValidationError(
                f"Cannot transition a paper trade from {current_status!r} to {target_status!r}."
            )

    # ------------------------------------------------------------------ reads

    async def get_trade(self, trade_id: uuid.UUID) -> dict[str, Any]:
        row = await self.repo.get_by_uuid(trade_id)
        if row is None:
            raise NotFoundError(f"No paper trade found for trade_id={trade_id}.")
        return row

    async def list_trades(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        return await self.repo.list_trades(status=status, limit=limit)

    async def open_positions(self, *, now: datetime | None = None) -> list[OpenPosition]:
        """Unrealized P&L is computed live, "as if closed now", using the identical
        ``cfi.paper.pnl.calculate_pnl`` methodology as a real close — never persisted (R3: a
        stored unrealized figure would go stale the instant the market moves again)."""
        open_rows = await self.repo.list_open()
        positions: list[OpenPosition] = []
        for row in open_rows:
            as_of = now if now is not None else utc_now()
            series = await self.adapters.price_close(row["asset"], as_of)
            current = pnl.current_price(series, as_of)
            if current is None:
                positions.append(
                    OpenPosition(
                        trade=row,
                        current_price_observed=None,
                        unrealized_pnl=None,
                        data_quality_state="missing",
                    )
                )
                continue
            trade_direction = cast(pnl.Direction, row["direction"])
            params = costs.parameters(row["cost_model_version"])
            hypothetical_exit_execution = pnl.execution_price(
                current, direction=trade_direction, leg="exit", params=params
            )
            result = pnl.calculate_pnl(
                direction=trade_direction,
                notional=Decimal(row["notional"]),
                leverage=Decimal(row["leverage"]),
                entry_price_observed=Decimal(row["entry_price_observed"]),
                entry_price_execution=Decimal(row["entry_price_execution"]),
                exit_price_observed=current,
                exit_price_execution=hypothetical_exit_execution,
                params=params,
            )
            positions.append(
                OpenPosition(
                    trade=row,
                    current_price_observed=current,
                    unrealized_pnl=result,
                    data_quality_state="ok",
                )
            )
        return positions

    async def performance_stats(self) -> PerformanceStats:
        counts = await self.repo.counts_by_status()
        closed = await self.repo.list_closed()
        return performance_stats(counts_by_status=counts, closed_trades=closed)


__all__ = [
    "DEFAULT_COST_MODEL_VERSION",
    "OpenPosition",
    "PaperTradingService",
    "PerformanceStats",
]
