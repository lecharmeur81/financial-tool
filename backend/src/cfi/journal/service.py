"""``DecisionJournalService`` — orchestrates decision creation, outcome recording, lifecycle
transitions, paper-trade linking, and the two read-only review/stats views (Phase 25 spec).

Reuses, entirely unchanged (R13 — never a parallel implementation):
``cfi.analyst.snapshot.build_snapshot``/``AnalystRepository.insert_snapshot`` (the same
immutable, 14-tool evidence snapshot Phases 21-24 already build — "Decision-time context":
"Reuse the Phase 21 snapshot infrastructure"), ``cfi.alerts.repository.AlertRepository.
list_alerts`` and ``cfi.brief.repository.BriefRepository.latest_completed_brief`` (read-only;
"Integration with Alerts and Briefs": "context only"), ``cfi.paper.repository.
PaperTradeRepository.trade_id_for_uuid`` (read-only; resolves a paper-trade link without
touching Phase 24's own code at all), and ``cfi.divergence.adapters.Adapters.price_close`` +
``cfi.paper.pnl.current_price`` (the platform's one canonical point-in-time price source, used
only at outcome time to compute ``actual_price_at_outcome``/``actual_market_movement_pct``).

Hindsight protection ("Do not rewrite the original thesis after the outcome becomes known")
holds here because this service calls ``repo.insert_decision`` exactly once, at creation, and
every later method (``record_outcome``, ``update_notes``, ``cancel_decision``,
``link_paper_trade``, ``unlink_paper_trade``) calls a repository method that only ever touches
its own disjoint column set (see ``cfi.journal.repository``'s own docstring) — there is no code
path anywhere in this service that can reach the decision-time columns after creation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.snapshot import build_snapshot
from cfi.brief.repository import BriefRepository
from cfi.core.config import Settings
from cfi.core.errors import ComputationError, DataValidationError, NotFoundError
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.divergence.adapters import Adapters
from cfi.journal import context
from cfi.journal.repository import DecisionJournalRepository
from cfi.journal.stats import DecisionReview, DecisionStats, decision_review, decision_stats
from cfi.journal.universe import ASSET_SYMBOLS, RELEVANT_ALERTS_LIMIT, VALID_TRANSITIONS
from cfi.paper import pnl
from cfi.paper.repository import PaperTradeRepository

log = get_logger(__name__)

# Self-assessment booleans/outcome labels the user supplies — never inferred by the system
# ("Do not automatically judge the user's intelligence, competence, or ability").
OUTCOME_VALUES: tuple[str, ...] = ("as_expected", "partially_as_expected", "not_as_expected")


@dataclass(frozen=True, slots=True)
class DecisionJournalOutcomeInput:
    outcome: str | None
    thesis_supported: bool | None
    thesis_contradicted: bool | None
    invalidation_occurred: bool | None
    evidence_changed_notes: str | None
    actual_market_movement_text: str | None
    lessons_notes: str | None
    status: str  # "resolved" | "invalidated" — the user's own call, not a system judgment


class DecisionJournalService:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
        self.repo = DecisionJournalRepository(engine)
        # Reused unchanged — never a second, parallel implementation (R13).
        self.analyst_repo = AnalystRepository(engine)
        self.alert_repo = AlertRepository(engine)
        self.brief_repo = BriefRepository(engine)
        self.paper_repo = PaperTradeRepository(engine)
        self.adapters = Adapters(engine)

    # ------------------------------------------------------------------ create

    async def create_decision(
        self,
        *,
        asset: str,
        decision_type: str,
        thesis: str,
        expected_scenario: str | None = None,
        alternative_scenario: str | None = None,
        time_horizon: str | None = None,
        entry_price: Decimal | None = None,
        invalidation_condition: str | None = None,
        key_risks: str | None = None,
        confidence: Decimal | None = None,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record a new decision "as of now" — ``decision_time`` is always the real current time
        (or the test-only override below); there is no backdating, so the decision-time snapshot
        can never use future information by construction ("Do NOT use future information when
        creating the decision-time snapshot"). ``asset``/``decision_type``/``thesis`` are the only
        required fields — every other field the user did not supply stays ``None`` rather than
        being invented ("Do not invent user decisions or confidence levels")."""
        if not asset or not asset.strip():
            raise DataValidationError("asset must not be empty.")
        if not decision_type or not decision_type.strip():
            raise DataValidationError("decision_type must not be empty.")
        if not thesis or not thesis.strip():
            raise DataValidationError("thesis must not be empty.")
        if confidence is not None and not (Decimal(0) <= confidence <= Decimal(1)):
            raise DataValidationError("confidence must be between 0 and 1 if provided.")

        now = now if now is not None else utc_now()

        # "Decision-time context" — the same immutable, 14-tool evidence snapshot Phases 21-24
        # already build. Contextual evidence only; this service never reads it back to decide
        # anything for the user.
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

        # Denormalized, zero-new-I/O extraction over the snapshot just built — never a second
        # source of truth (the snapshot itself is `decision_snapshot_id`).
        market_regime_label = context.regime_label(snapshot)
        observed_price_at_decision = (
            context.observed_price(snapshot, asset) if asset in ASSET_SYMBOLS else None
        )

        _decision_id, decision_uuid = await self.repo.insert_decision(
            now=now,
            decision_time=now,
            asset=asset,
            decision_type=decision_type,
            thesis=thesis,
            expected_scenario=expected_scenario,
            alternative_scenario=alternative_scenario,
            time_horizon=time_horizon,
            entry_price=entry_price,
            observed_price_at_decision=observed_price_at_decision,
            invalidation_condition=invalidation_condition,
            key_risks=key_risks,
            confidence=confidence,
            notes=notes,
            decision_snapshot_id=snapshot_id,
            market_brief_id=market_brief_id,
            relevant_alert_ids=relevant_alert_ids,
            market_regime_label=market_regime_label,
        )
        row = await self.repo.get_by_uuid(decision_uuid)
        if row is None:
            raise ComputationError(
                f"Decision journal entry {decision_uuid} was inserted but could not be read back."
            )
        return row

    # ------------------------------------------------------------------ post-creation writes

    async def update_notes(
        self, decision_id: uuid.UUID, *, notes: str | None, now: datetime | None = None
    ) -> dict[str, Any]:
        """``notes`` is the one freely mutable field on a journal entry — everything else
        decision-time stays untouched by this call."""
        row = await self._get_row_or_raise(decision_id)
        now = now if now is not None else utc_now()
        await self.repo.update_notes(row["id"], now=now, notes=notes)
        return await self._get_row_or_raise(decision_id)

    async def record_outcome(
        self,
        decision_id: uuid.UUID,
        *,
        outcome_input: DecisionJournalOutcomeInput,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record what actually happened, in columns wholly disjoint from the decision-time
        evidence ("Later outcome information must be stored separately. Never silently modify
        the original decision record based on the outcome"). Whether the thesis was supported or
        contradicted, and whether invalidation occurred, are the user's own self-assessment —
        this service never infers them ("Do not automatically judge")."""
        row = await self._get_row_or_raise(decision_id)
        self._require_transition(row["status"], outcome_input.status)
        if outcome_input.outcome is not None and outcome_input.outcome not in OUTCOME_VALUES:
            raise DataValidationError(
                f"Unknown outcome {outcome_input.outcome!r} "
                f"(must be one of {OUTCOME_VALUES} or omitted)."
            )

        now = now if now is not None else utc_now()

        # Pure arithmetic from two observed prices — computed only when both are available, never
        # invented ("Actual market movement"). A fresh, lightweight price lookup only; no snapshot,
        # no re-run of any evidence-gathering tool.
        actual_price_at_outcome: Decimal | None = None
        actual_market_movement_pct: Decimal | None = None
        if row["asset"] in ASSET_SYMBOLS:
            series = await self.adapters.price_close(row["asset"], now)
            actual_price_at_outcome = pnl.current_price(series, now)
            decision_price = row.get("observed_price_at_decision") or row.get("entry_price")
            if actual_price_at_outcome is not None and decision_price is not None:
                decision_price = Decimal(decision_price)
                if decision_price != 0:
                    actual_market_movement_pct = (
                        (actual_price_at_outcome - decision_price) / decision_price
                    ) * Decimal(100)

        await self.repo.record_outcome(
            row["id"],
            now=now,
            status=outcome_input.status,
            outcome=outcome_input.outcome,
            thesis_supported=outcome_input.thesis_supported,
            thesis_contradicted=outcome_input.thesis_contradicted,
            invalidation_occurred=outcome_input.invalidation_occurred,
            evidence_changed_notes=outcome_input.evidence_changed_notes,
            actual_market_movement_text=outcome_input.actual_market_movement_text,
            actual_price_at_outcome=actual_price_at_outcome,
            actual_market_movement_pct=actual_market_movement_pct,
            lessons_notes=outcome_input.lessons_notes,
        )
        return await self._get_row_or_raise(decision_id)

    async def cancel_decision(
        self, decision_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Withdraw an open decision before any outcome exists — no exit price, no outcome
        fields, mirroring Phase 24's own ``cancel_trade``."""
        row = await self._get_row_or_raise(decision_id)
        self._require_transition(row["status"], "cancelled")
        now = now if now is not None else utc_now()
        await self.repo.cancel(row["id"], now=now)
        return await self._get_row_or_raise(decision_id)

    async def link_paper_trade(
        self, decision_id: uuid.UUID, *, paper_trade_id: uuid.UUID, now: datetime | None = None
    ) -> dict[str, Any]:
        """Attach a cross-reference to an existing Phase 24 paper trade — a genuinely mutable
        relationship, not hindsight-sensitive evidence ("Integration with Paper Trading": "Keep
        the two systems logically separate but linkable"). Never creates a paper trade and never
        reads/writes anything else on the paper-trade record."""
        row = await self._get_row_or_raise(decision_id)
        trade_id = await self.paper_repo.trade_id_for_uuid(paper_trade_id)
        if trade_id is None:
            raise NotFoundError(f"No paper trade found for trade_id={paper_trade_id}.")
        now = now if now is not None else utc_now()
        await self.repo.link_paper_trade(row["id"], now=now, paper_trade_id=trade_id)
        return await self._get_row_or_raise(decision_id)

    async def unlink_paper_trade(
        self, decision_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        row = await self._get_row_or_raise(decision_id)
        now = now if now is not None else utc_now()
        await self.repo.unlink_paper_trade(row["id"], now=now)
        return await self._get_row_or_raise(decision_id)

    # ------------------------------------------------------------------ internal helpers

    @staticmethod
    def _require_transition(current_status: str, target_status: str) -> None:
        allowed = VALID_TRANSITIONS.get(current_status, ())
        if target_status not in allowed:
            raise DataValidationError(
                f"Cannot transition a decision journal entry from "
                f"{current_status!r} to {target_status!r}."
            )

    async def _get_row_or_raise(self, decision_id: uuid.UUID) -> dict[str, Any]:
        row = await self.repo.get_by_uuid(decision_id)
        if row is None:
            raise NotFoundError(f"No decision journal entry found for decision_id={decision_id}.")
        return row

    # ------------------------------------------------------------------ reads

    async def get_decision(self, decision_id: uuid.UUID) -> dict[str, Any]:
        return await self._get_row_or_raise(decision_id)

    async def list_decisions(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        return await self.repo.list_decisions(status=status, limit=limit)

    async def review(self) -> DecisionReview:
        """Descriptive patterns only — grouped counts by exact-match string, never a ranking or a
        "best strategy" ("Do not produce a 'best strategy' or rank the user's decisions")."""
        rows = await self.repo.all_for_stats()
        return decision_review(rows)

    async def stats(self) -> DecisionStats:
        rows = await self.repo.all_for_stats()
        return decision_stats(rows)


__all__ = [
    "OUTCOME_VALUES",
    "DecisionJournalOutcomeInput",
    "DecisionJournalService",
    "DecisionReview",
    "DecisionStats",
]
