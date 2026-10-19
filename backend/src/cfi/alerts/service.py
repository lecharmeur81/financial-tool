"""``AlertService`` — orchestrates one alert-evaluation cycle (Phase 23 spec).

Reuses, entirely unchanged: ``cfi.analyst.snapshot.build_snapshot`` (the same 14-tool evidence
snapshot Phases 21/22 already build), ``cfi.analyst.repository.AnalystRepository.insert_snapshot``/
``latest_snapshot`` (``ai.snapshot`` is not duplicated — see that method's docstring), and
``cfi.brief.changes.compute_changes`` (Phase 22's snapshot-diff, reused here to produce the
evaluation cycle's own audit-trail change set — see the module docstring in ``cfi.alerts.rules``
for why it is NOT what decides whether any individual alert type fires).

No AI/Claude component at all (Phase 23 spec: this is a fully deterministic rule engine) — no
client, no prompt, no budget check, no validator for LLM output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.investment_adapter import SnapshotReader
from cfi.alerts.investment_block import InvestmentCycleResult, run_investment_cycle
from cfi.alerts.lifecycle import Action, Candidate, decide
from cfi.alerts.repository import AlertRepository
from cfi.alerts.rules import AlertCandidate, cleared_dedup_keys, evaluate_all
from cfi.alerts.stage_timing import timed_stage
from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS, cooldown_period
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.snapshot import Snapshot, build_snapshot
from cfi.brief.changes import ChangeSet, compute_changes
from cfi.core.config import Settings
from cfi.core.logging import get_logger
from cfi.decision_store.repository import DecisionAssessmentRepository

log = get_logger(__name__)

# The three "flagged-state" alert types (see cfi.alerts.rules module docstring): their evaluators
# only emit a candidate while the flag holds, so a previously active alert whose dedup key is not
# re-emitted this cycle must be auto-resolved rather than left active forever.
_FLAGGED_STATE_TYPES = ("divergence", "anomaly", "capital_rotation")


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """One candidate's outcome from one evaluation cycle — additive detail ``EvaluationResult``
    did not previously expose (Phase 35, "Real-Time Intelligence"), needed by
    ``cfi.realtime.service.RealtimeIntelligenceService`` to build an intelligence event without
    re-deciding or re-reading anything this method has already computed (R13: extend, never
    duplicate, the one place a candidate's fate is decided)."""

    candidate: AlertCandidate
    action: Action
    alert_id: int | None  # set only for "create"/"rearm" — the two actions that write a row
    previous_observed_value: str | None  # the dedup key's prior value, if any existed


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    created: int
    rearmed: int
    resolved: int
    skipped_unchanged: int
    skipped_cooldown: int
    candidates_evaluated: int
    comparison_basis: str
    # Additive (Phase 35): the per-candidate detail needed to build an intelligence event, and the
    # snapshot this cycle's candidates were read from — both already computed above, now simply
    # not thrown away. Defaulted so every existing construction of this dataclass (tests included)
    # stays valid unchanged.
    decisions: tuple[CandidateDecision, ...] = field(default_factory=tuple)
    snapshot_id: int | None = None
    snapshot: Snapshot | None = None
    # Additive (Phase 51 Stage 6): the investment-alert block's result for this cycle's stored
    # snapshot (evaluation and a persistence-disabled plan; nothing is persisted). Kept apart from
    # ``decisions`` and from every counter above, which describe the 11 existing alert types only.
    investment: InvestmentCycleResult | None = None


class AlertService:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        *,
        snapshot_reader: SnapshotReader | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.repo = AlertRepository(engine)
        # Reused unchanged for the (shared, not alert-specific) snapshot insert/lookup — never a
        # second, parallel implementation (Phase 23 spec "Phase 21/22 Integration").
        self.analyst_repo = AnalystRepository(engine)
        # Phase 51 Stage 6: the read-only reader for the investment-alert block (one get_snapshot
        # per cycle). Injectable so unit tests need no database; constructing the real repository
        # opens no connection.
        self._snapshot_reader: SnapshotReader = (
            snapshot_reader if snapshot_reader is not None else DecisionAssessmentRepository(engine)
        )

    async def evaluate(
        self, *, as_of: datetime, knowledge_time: datetime, now: datetime
    ) -> EvaluationResult:
        previous = await self.analyst_repo.latest_snapshot()
        previous_payload = previous[1] if previous else None

        with timed_stage(log, "alert_evaluate_stage_timing", stage="build_snapshot"):
            snapshot = await build_snapshot(
                self.engine,
                self.settings,
                as_of=as_of,
                knowledge_time=knowledge_time,
                question=None,
            )
        with timed_stage(log, "alert_evaluate_stage_timing", stage="persist_snapshot"):
            snapshot_id, _snapshot_uuid = await self.analyst_repo.insert_snapshot(
                created_at=snapshot.created_at,
                as_of=snapshot.as_of,
                knowledge_time=snapshot.knowledge_time,
                snapshot_version=snapshot.snapshot_version,
                payload=snapshot.payload(),
                payload_hash=snapshot.snapshot_id,
            )

        # Reused for the cycle's own audit trail (Phase 23 spec "Phase 21/22 Integration": "reuse
        # Phase 22 snapshot/change infrastructure where appropriate") — logged, not what decides
        # whether any individual alert fires (see cfi.alerts.rules's module docstring).
        changes: ChangeSet = compute_changes(snapshot, previous_payload)
        log.info(
            "alert_cycle_changes",
            comparison_basis=changes.comparison_basis,
            field_changes=len(changes.changes),
        )

        with timed_stage(log, "alert_evaluate_stage_timing", stage="evaluate_rules"):
            candidates = evaluate_all(snapshot)
        cooldown_seconds = cooldown_period().total_seconds()

        created = rearmed = resolved = skipped_unchanged = skipped_cooldown = 0
        seen_keys: dict[str, set[str]] = {t: set() for t in _FLAGGED_STATE_TYPES}
        decisions: list[CandidateDecision] = []

        with timed_stage(log, "alert_evaluate_stage_timing", stage="process_candidates") as stage:
            for candidate in candidates:
                if candidate.alert_type in seen_keys:
                    seen_keys[candidate.alert_type].add(candidate.dedup_key)

                existing = await self.repo.latest_active_for_key(candidate.dedup_key)
                action = decide(
                    existing,
                    Candidate(observed_value=candidate.observed_value),
                    now=now,
                    cooldown_seconds=cooldown_seconds,
                )

                if action == "skip_unchanged":
                    skipped_unchanged += 1
                    continue
                if action == "skip_cooldown":
                    skipped_cooldown += 1
                    continue

                new_id, _new_uuid = await self.repo.insert_alert(
                    now=now,
                    alert_type=candidate.alert_type,
                    severity=candidate.severity,
                    domain=candidate.domain,
                    dedup_key=candidate.dedup_key,
                    trigger_condition=candidate.trigger_condition,
                    observed_value=candidate.observed_value,
                    reference_value=candidate.reference_value,
                    evidence_field_ids=list(candidate.evidence_field_ids),
                    snapshot_id=snapshot_id,
                    source_tool_id=candidate.source_tool_id,
                    component_status=candidate.component_status,
                    data_quality_state=snapshot.data_quality_state,
                )

                if action == "create":
                    created += 1
                else:  # "rearm"
                    rearmed += 1
                    old_id = await self.repo.latest_active_id_for_key(candidate.dedup_key)
                    # old_id is this candidate's own just-inserted row only if two evaluators ever
                    # shared a dedup_key (they never do, by construction); guard anyway (R3: never
                    # silently supersede the wrong row).
                    if old_id is not None and old_id != new_id:
                        await self.repo.supersede(old_id, now=now, superseded_by=new_id)

                decisions.append(
                    CandidateDecision(
                        candidate=candidate,
                        action=action,
                        alert_id=new_id,
                        previous_observed_value=existing.observed_value if existing else None,
                    )
                )
            stage["candidates"] = len(candidates)

        with timed_stage(log, "alert_evaluate_stage_timing", stage="auto_resolve"):
            resolved += await self._auto_resolve_cleared(
                seen_keys, cleared_dedup_keys(snapshot), now=now
            )

        # Phase 51 Stage 6: strictly after the 11 existing types are fully processed (their rows
        # are persisted and cleared alerts resolved), so nothing here can change their outcome. An
        # ordinary failure is contained inside the block; a time-limit or cancellation signal
        # propagates out of this method unchanged. Persistence of investment alerts stays disabled.
        investment = await run_investment_cycle(
            self._snapshot_reader, snapshot_id, now=now, logger=log
        )

        return EvaluationResult(
            created=created,
            rearmed=rearmed,
            resolved=resolved,
            skipped_unchanged=skipped_unchanged,
            skipped_cooldown=skipped_cooldown,
            candidates_evaluated=len(candidates),
            comparison_basis=changes.comparison_basis,
            decisions=tuple(decisions),
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            investment=investment,
        )

    async def _auto_resolve_cleared(
        self, seen_keys: dict[str, set[str]], cleared_keys: frozenset[str], *, now: datetime
    ) -> int:
        """Resolve a flagged-state alert (divergence/anomaly/capital_rotation) ONLY when this
        cycle's evidence explicitly shows its condition cleared (``cleared_keys``, from
        ``cfi.alerts.rules.cleared_dedup_keys``). A key whose candidate is simply absent (missing
        item, failed or unavailable tool, unavailable reading, degraded or conflicting data) is
        unknown, not cleared: the alert keeps its status (Phase 52)."""
        resolved = held = 0
        for alert_type in _FLAGGED_STATE_TYPES:
            entries = await self.repo.active_entries_with_prefix(f"{alert_type}:")
            still_flagged = seen_keys[alert_type]
            for dedup_key, alert_id in entries:
                if dedup_key in still_flagged:
                    continue
                if dedup_key in cleared_keys:
                    await self.repo.resolve(alert_id, now=now)
                    resolved += 1
                else:
                    held += 1
        if held:
            log.info("alert_auto_resolve_held", unknown_not_cleared=held)
        return resolved

    # ------------------------------------------------------------------ reads (API)

    async def get_alert(self, alert_id: Any) -> dict[str, Any] | None:
        return await self.repo.get_by_uuid(alert_id)

    async def list_alerts(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        return await self.repo.list_alerts(status=status, limit=limit)

    async def set_status(self, alert_id: Any, *, status: str, now: datetime) -> bool:
        return await self.repo.set_status(alert_id, status=status, now=now)


__all__ = ["ALERT_TYPE_TOOL_IDS", "AlertService", "CandidateDecision", "EvaluationResult"]
