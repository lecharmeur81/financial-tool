"""``BriefService`` — orchestrates the Daily Market Brief (Phase 22 spec, Sections 5-10).

Reuses, entirely unchanged: ``cfi.analyst.snapshot.build_snapshot`` (the same 14-tool evidence
snapshot Phase 21 already builds over every domain this brief needs — Section 1/2: no new data
access path), ``cfi.analyst.client.ClaudeClient``/``parse_json_response`` (the same Claude call
machinery), and ``cfi.analyst.repository.AnalystRepository.insert_snapshot``/``monthly_cost_usd``
(Section 9: the brief's own Claude usage shares Phase 21's exact, unmodified monthly-budget-
ceiling query via the ``ai.usage.brief_id`` column added in migration 0008). Only the response
schema, change detection, prompt, validator and ``ai.brief`` persistence are new — the minimum
surface area a different *presentation* artifact over the same evidence needs (Section 2: do not
rebuild Phase 21, do not redesign ``AnalystResponse``).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.client import ClaudeClient, parse_json_response
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.snapshot import Snapshot, build_snapshot
from cfi.brief.changes import ChangeSet, compute_changes
from cfi.brief.prompts import PROMPT_VERSION_ID, SYSTEM_PROMPT, user_prompt
from cfi.brief.repository import BriefRepository
from cfi.brief.schema import BriefResponse
from cfi.brief.universe import BRIEF_ANALYST_VERSION, MAX_VALIDATION_ATTEMPTS
from cfi.brief.validator import validate
from cfi.core.config import Settings
from cfi.core.errors import AIBudgetExceededError, AIValidationError, CFIError
from cfi.core.logging import get_logger
from cfi.providers.http import ProviderHttpClient

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class QueuedBrief:
    brief_id: uuid.UUID
    status: str


def _changes_payload(changes: ChangeSet) -> dict[str, Any]:
    return {
        "comparison_basis": changes.comparison_basis,
        "changes": [
            {
                "change_id": c.change_id,
                "field_id": c.field_id,
                "previous_display": c.previous_display,
                "current_display": c.current_display,
                "delta": c.delta,
            }
            for c in changes.changes
        ],
    }


class BriefService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, *, http: ProviderHttpClient
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.repo = BriefRepository(engine)
        # Reused unchanged for the budget query and the (shared, not brief-specific) snapshot
        # insert (Section 9) — never a second, parallel implementation of either.
        self.analyst_repo = AnalystRepository(engine)
        self.client = ClaudeClient(
            http, model=settings.anthropic_model, max_tokens=settings.anthropic_max_tokens
        )

    # ------------------------------------------------------------------ queue

    async def create_queued_brief(
        self, *, now: datetime, reporting_period_start: datetime, reporting_period_end: datetime
    ) -> QueuedBrief:
        previous = await self.repo.latest_completed_brief()
        previous_brief_id = int(previous["id"]) if previous else None
        _brief_db_id, brief_uuid = await self.repo.create_queued_brief(
            now=now,
            reporting_period_start=reporting_period_start,
            reporting_period_end=reporting_period_end,
            previous_brief_id=previous_brief_id,
        )
        return QueuedBrief(brief_id=brief_uuid, status="queued")

    async def get_brief(self, brief_id: uuid.UUID) -> dict[str, Any] | None:
        return await self.repo.get_by_uuid(brief_id)

    # ------------------------------------------------------------------ run

    async def run_brief(
        self,
        brief_id: uuid.UUID,
        *,
        as_of: datetime,
        knowledge_time: datetime,
        now: datetime,
    ) -> None:
        """Run one queued brief end to end. Mirrors ``AnalystService.run_analysis``'s own error-
        recording convention exactly (Section 10: fail safely, never silently substitute a
        fabricated/default value) — an expected failure mode (budget exceeded, malformed/
        ungrounded Claude output that still fails validation after the retry) is caught and
        recorded ``failed`` with its own error text; an unanticipated exception is left to
        propagate (R3: swallowing it here would hide a real bug)."""
        row = await self.repo.get_by_uuid(brief_id)
        if row is None:
            raise CFIError(f"No queued brief found for brief_id={brief_id}.")
        brief_db_id = int(row["id"])

        await self.repo.mark_running(brief_db_id, now=now)

        try:
            monthly_cost = await self.analyst_repo.monthly_cost_usd(now)
            if monthly_cost >= Decimal(str(self.settings.ai_monthly_budget_usd)):
                raise AIBudgetExceededError(
                    f"This month's recorded AI usage (${monthly_cost}) has met or exceeded the "
                    f"configured budget ceiling (${self.settings.ai_monthly_budget_usd})."
                )

            snapshot = await build_snapshot(
                self.engine,
                self.settings,
                as_of=as_of,
                knowledge_time=knowledge_time,
                question=None,
            )
            snapshot_id, _snapshot_uuid = await self.analyst_repo.insert_snapshot(
                created_at=snapshot.created_at,
                as_of=snapshot.as_of,
                knowledge_time=snapshot.knowledge_time,
                snapshot_version=snapshot.snapshot_version,
                payload=snapshot.payload(),
                payload_hash=snapshot.snapshot_id,
            )

            changes = await self._compute_changes(snapshot, row.get("previous_brief_id"))
            changes_payload = _changes_payload(changes)

            response, validation_errors, attempt_count = await self._complete_with_retry(
                snapshot, changes, brief_id=brief_db_id, now=now
            )

            if response is None:
                await self.repo.mark_failed(
                    brief_db_id,
                    now=now,
                    error=(
                        "Claude's response failed validation after the retry: "
                        + "; ".join(validation_errors)
                    ),
                    snapshot_id=snapshot_id,
                    prompt_version=PROMPT_VERSION_ID,
                    analyst_version=BRIEF_ANALYST_VERSION,
                    model=self.settings.anthropic_model,
                    validation_status="failed",
                    validation_errors=validation_errors,
                    attempt_count=attempt_count,
                    tools_called=snapshot.tools_called,
                    data_quality_state=snapshot.data_quality_state,
                    changes=changes_payload,
                )
                return

            await self.repo.mark_completed(
                brief_db_id,
                now=now,
                snapshot_id=snapshot_id,
                prompt_version=PROMPT_VERSION_ID,
                analyst_version=BRIEF_ANALYST_VERSION,
                model=self.settings.anthropic_model,
                response=response.model_dump(mode="json"),
                validation_status="ok",
                validation_errors=[],
                attempt_count=attempt_count,
                tools_called=snapshot.tools_called,
                data_quality_state=snapshot.data_quality_state,
                changes=changes_payload,
            )
        except CFIError as exc:
            log.warning(
                "brief_run_failed",
                brief_id=str(brief_id),
                error_code=exc.error_code,
                detail=exc.detail,
            )
            await self.repo.mark_failed(
                brief_db_id, now=now, error=f"{exc.error_code}: {exc.detail}"
            )

    async def _compute_changes(
        self, snapshot: Snapshot, previous_brief_id: int | None
    ) -> ChangeSet:
        """The comparison basis is the previous *completed* brief's own stored snapshot payload
        (Section 5) — read via its internal id, recorded on this brief's row when it was queued
        (``create_queued_brief``), never re-derived or guessed at run time."""
        previous_payload: dict[str, Any] | None = None
        if previous_brief_id is not None:
            previous_brief = await self.repo.get_by_id(previous_brief_id)
            if previous_brief is not None and previous_brief.get("snapshot_id") is not None:
                previous_payload = await self.repo.get_snapshot_payload(
                    previous_brief["snapshot_id"]
                )
        return compute_changes(snapshot, previous_payload)

    async def _complete_with_retry(
        self, snapshot: Snapshot, changes: ChangeSet, *, brief_id: int, now: datetime
    ) -> tuple[BriefResponse | None, list[str], int]:
        retry_errors: list[str] | None = None
        last_errors: list[str] = []
        for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
            prompt = user_prompt(snapshot, changes, retry_errors=retry_errors)
            t0 = time.monotonic()
            claude_response = await self.client.complete(system=SYSTEM_PROMPT, user=prompt)
            latency_ms = round((time.monotonic() - t0) * 1000)

            cost = Decimal(claude_response.input_tokens) / Decimal(1_000_000) * Decimal(
                str(self.settings.anthropic_input_cost_per_mtok_usd)
            ) + Decimal(claude_response.output_tokens) / Decimal(1_000_000) * Decimal(
                str(self.settings.anthropic_output_cost_per_mtok_usd)
            )
            await self.repo.insert_usage_for_brief(
                brief_id=brief_id,
                now=now,
                model=claude_response.model,
                input_tokens=claude_response.input_tokens,
                output_tokens=claude_response.output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                attempt=attempt,
            )

            try:
                parsed = parse_json_response(claude_response.text)
                candidate = BriefResponse.model_validate(parsed)
            except (AIValidationError, ValueError) as exc:
                last_errors = [str(exc)]
                retry_errors = last_errors
                continue

            result = validate(candidate, snapshot, changes)
            if result.ok:
                return candidate, [], attempt
            last_errors = result.errors
            retry_errors = result.errors

        return None, last_errors, MAX_VALIDATION_ATTEMPTS
