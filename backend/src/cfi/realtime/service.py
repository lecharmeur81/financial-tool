"""``RealtimeIntelligenceService`` — orchestrates one real-time intelligence cycle (Phase 35).

Pipeline (module docstring, matches the phase spec exactly):

    DATA ARRIVAL -> CHANGE DETECTION -> INTELLIGENCE EVENT -> DETERMINISTIC ANALYSIS
    -> ALERT / INVESTIGATION TRIGGER -> OPTIONAL CLAUDE ANALYSIS

Reuses, entirely unchanged: ``cfi.alerts.service.AlertService.evaluate`` (change detection +
alert trigger — Phase 23's rule engine is not re-implemented or run twice; see that module's own
docstring), ``cfi.analyst.repository.AnalystRepository.create_queued_interpretation`` and
``cfi.worker.client.send_task`` (the exact same "queue an analysis, let the worker run it" path
``POST /api/v1/analyst/analyze`` already uses — Phase 21's budget check, validator, grounding and
usage tracking all still run, unbypassed, inside that existing task).

This service adds exactly three things Phase 23 did not need: (1) a persistent, queryable
intelligence-event record per meaningful transition, with the extra provenance (previous/current
value, change magnitude, detection method, correlation key) an alert row alone does not carry;
(2) an AI-trigger policy deciding whether any of this cycle's transitions are significant enough
to also request a Claude analysis, gated by severity, data quality, and a minimum interval between
requests; (3) a Redis-based lock so the same cycle is never processed twice concurrently (a worker
retry, two overlapping scheduled runs, or a data-arrival trigger firing while the periodic sweep is
already running) — the only new concurrency-control primitive this phase introduces, and the
standard one for exactly this problem (``SET key value NX EX ttl`` on the broker's own Redis).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.service import AlertService, EvaluationResult
from cfi.alerts.stage_timing import status_for
from cfi.analyst.repository import AnalystRepository
from cfi.core.config import Settings
from cfi.core.logging import get_logger
from cfi.realtime.ai_policy import question_for, significant_decisions
from cfi.realtime.events import (
    change_magnitude,
    correlation_key_for,
    detection_method_for,
    is_meaningful_decision,
)
from cfi.realtime.repository import IntelligenceEventRepository
from cfi.realtime.universe import (
    AI_MIN_INTERVAL_SECONDS,
    CYCLE_LOCK_KEY,
    CYCLE_LOCK_TTL_SECONDS,
    DATA_ARRIVAL_DEBOUNCE_KEY,
    DATA_ARRIVAL_DEBOUNCE_SECONDS,
)
from cfi.worker.client import send_task

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis

log = get_logger(__name__)

# An automatic (data-arrival) evaluation that has waited this long in the ``alerts`` queue is
# stale: the worker discards it on receipt instead of running it, and a later trigger or the
# scheduled run evaluates fresher data. Manual API triggers and Beat are deliberately unaffected.
DATA_ARRIVAL_ALERT_EXPIRES_SECONDS = 180

# Release the cycle lock only if it still holds this cycle's token (atomic compare-and-delete): a
# cycle whose lock already expired and was re-acquired by another cycle must not delete that
# cycle's lock. Returns 1 if deleted, 0 if the lock was absent or owned by someone else.
_RELEASE_IF_OWNER_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    locked_out: bool  # True if another cycle already held the lock — this run did nothing
    alerts: EvaluationResult | None
    events_created: int
    events_deduplicated: int  # a meaningful decision whose alert_id already had an event
    ai_requested: int


class RealtimeIntelligenceService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, *, redis: Redis | None = None
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.redis = redis
        self.alerts = AlertService(engine, settings)
        self.events = IntelligenceEventRepository(engine)
        self.analyst_repo = AnalystRepository(engine)

    async def process_cycle(
        self, *, as_of: datetime, knowledge_time: datetime, now: datetime
    ) -> ProcessResult:
        started = time.monotonic()
        token = await self._acquire_lock()
        lock_acquired_at = time.monotonic()
        if token is None:
            log.info("realtime_cycle_locked_out")
            log.info(
                "realtime_cycle_timing",
                status="locked_out",
                lock="not_acquired",
                lock_release="not_applicable",
                elapsed_ms=round((lock_acquired_at - started) * 1000),
            )
            return ProcessResult(
                locked_out=True,
                alerts=None,
                events_created=0,
                events_deduplicated=0,
                ai_requested=0,
            )
        error: BaseException | None = None
        lock_release: str
        try:
            result = await self.alerts.evaluate(as_of=as_of, knowledge_time=knowledge_time, now=now)
            events_created, events_deduplicated = await self._record_events(result, now=now)
            # Deliberately outside the events' own transactions (each already committed by
            # ``IntelligenceEventRepository.insert_event``) and deliberately swallowed here: a
            # failure requesting AI analysis (enqueue error, budget-check side effect, etc.) must
            # never undo or block on the deterministic events this cycle already persisted ("the
            # architecture should... fail gracefully" / "failure of Claude must NOT prevent
            # deterministic intelligence events from being persisted").
            try:
                ai_requested = await self._consider_ai_analysis(result, as_of=as_of, now=now)
            except Exception:
                log.warning("realtime_ai_trigger_failed", exc_info=True)
                ai_requested = 0
            return ProcessResult(
                locked_out=False,
                alerts=result,
                events_created=events_created,
                events_deduplicated=events_deduplicated,
                ai_requested=ai_requested,
            )
        except BaseException as exc:
            error = exc
            raise
        finally:
            lock_release = await self._release_lock(token)
            log.info(
                "realtime_cycle_timing",
                status=status_for(error),
                lock="acquired",
                lock_release=lock_release,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                lock_held_ms=round((time.monotonic() - lock_acquired_at) * 1000),
            )

    # ------------------------------------------------------------------ change detection -> events

    async def _record_events(self, result: EvaluationResult, *, now: datetime) -> tuple[int, int]:
        if result.snapshot_id is None or result.snapshot is None:
            return 0, 0
        snapshot_id = result.snapshot_id
        correlation_key = correlation_key_for(snapshot_id)
        created = deduplicated = 0
        for decision in result.decisions:
            if not is_meaningful_decision(decision):
                continue
            inserted = await self.events.insert_event(
                now=now,
                observed_at=result.snapshot.as_of,
                domain=decision.candidate.domain,
                event_type=decision.candidate.alert_type,
                severity=decision.candidate.severity,
                previous_value=decision.previous_observed_value,
                current_value=decision.candidate.observed_value,
                change_magnitude=change_magnitude(
                    decision.previous_observed_value, decision.candidate.observed_value
                ),
                detection_method=detection_method_for(decision.candidate.alert_type),
                data_quality_state=result.snapshot.data_quality_state,
                component_status=decision.candidate.component_status,
                dedup_key=decision.candidate.dedup_key,
                correlation_key=correlation_key,
                snapshot_id=snapshot_id,
                alert_id=decision.alert_id,
            )
            if inserted is None:
                deduplicated += 1
            else:
                created += 1
        return created, deduplicated

    # ------------------------------------------------------------------ AI-trigger policy

    async def _consider_ai_analysis(
        self, result: EvaluationResult, *, as_of: datetime, now: datetime
    ) -> int:
        if not self.settings.anthropic_api_key:
            return 0  # same "credential not configured" posture as every other AI task
        candidates = significant_decisions(result.decisions)
        if not candidates:
            return 0
        last_requested = await self.events.latest_ai_requested_at()
        if last_requested is not None:
            elapsed = (now - last_requested).total_seconds()
            if elapsed < AI_MIN_INTERVAL_SECONDS:
                log.info("realtime_ai_skipped_too_recent", elapsed_seconds=elapsed)
                return 0
        # One analysis per cycle, not one per significant event: the Analyst's own snapshot
        # already covers every domain at once (Phase 21), so asking it once about the most
        # severe transition is what "not continuously calling Claude for every market tick"
        # means in practice, while still surfacing the richest single question this cycle has.
        decision = max(candidates, key=lambda d: d.candidate.severity == "critical")
        (
            interpretation_id,
            interpretation_uuid,
        ) = await self.analyst_repo.create_queued_interpretation(
            now=now, question=question_for(decision)
        )
        send_task(
            self.settings,
            "analyst.analyze",
            args=(str(interpretation_uuid), as_of.isoformat(), as_of.isoformat()),
            queue="ai",
        )
        # Marked against the alert-sourced event that earned this request, so a later cycle's
        # "how recently did we last ask" check (above) reads one, unambiguous timeline.
        if decision.alert_id is not None:
            event = await self._event_for_alert(decision.alert_id)
            if event is not None:
                await self.events.mark_ai_requested(
                    event, interpretation_id=interpretation_id, now=now
                )
        log.info("realtime_ai_requested", interpretation_id=str(interpretation_uuid))
        return 1

    async def _event_for_alert(self, alert_id: int) -> int | None:
        """The ``sig.intelligence_event.id`` this cycle just inserted for ``alert_id`` — read
        back rather than threaded through every call, since only the rare AI-triggering path
        needs it (R13: no extra plumbing for the common case)."""
        from sqlalchemy import select

        from cfi.db import tables as t

        stmt = select(t.intelligence_event.c.id).where(t.intelligence_event.c.alert_id == alert_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row else None

    # ------------------------------------------------------------------ cycle lock

    async def _acquire_lock(self) -> str | None:
        """Take the global cycle lock; return this cycle's unique ownership token, or ``None`` if
        another cycle holds it. With no Redis client configured (e.g. a unit test) the cycle is the
        only runner and gets a token that is never released anywhere."""
        token = uuid.uuid4().hex
        if self.redis is None:
            return token
        acquired = await self.redis.set(CYCLE_LOCK_KEY, token, nx=True, ex=CYCLE_LOCK_TTL_SECONDS)
        return token if acquired else None

    async def _release_lock(self, token: str) -> str:
        """Release the lock only if it still carries ``token``. Returns ``released``, ``not_owner``
        (expired or taken over by another cycle — left untouched) or ``failed`` (Redis error: the
        TTL expires the lock; the error is logged, never allowed to replace the cycle's own
        outcome or exception)."""
        if self.redis is None:
            return "no_lock"
        try:
            # redis-py types ``eval`` as ``Awaitable[str] | str`` (one stub for sync and async)
            deleted = await cast(
                "Awaitable[Any]",
                self.redis.eval(_RELEASE_IF_OWNER_LUA, 1, CYCLE_LOCK_KEY, token),
            )
        except Exception:
            log.warning("realtime_cycle_lock_release_failed", exc_info=True)
            return "failed"
        if int(deleted) == 1:
            return "released"
        log.warning("realtime_cycle_lock_not_owner")
        return "not_owner"


async def trigger_cycle_if_due(redis: Redis, settings: Settings) -> bool:
    """Enqueue one ``alerts.evaluate`` run (the task ``RealtimeIntelligenceService`` now runs
    inside) shortly after new data arrives, debounced so a burst of ingestion ticks triggers at
    most one extra cycle per ``DATA_ARRIVAL_DEBOUNCE_SECONDS`` window — "a reasonable cadence",
    not a cycle per tick. Returns whether a cycle was actually enqueued (for logging/tests only;
    callers that only ingest data never need to branch on it)."""
    acquired = await redis.set(
        DATA_ARRIVAL_DEBOUNCE_KEY, "1", nx=True, ex=DATA_ARRIVAL_DEBOUNCE_SECONDS
    )
    if not acquired:
        return False
    send_task(
        settings,
        "alerts.evaluate",
        args=(),
        queue="alerts",
        expires=DATA_ARRIVAL_ALERT_EXPIRES_SECONDS,
    )
    return True


__all__ = ["ProcessResult", "RealtimeIntelligenceService", "trigger_cycle_if_due"]
