"""``AnalystService`` — the orchestrator (Phase 21 spec, Sections 8-13).

Two entry points, matching the queued-then-worker-runs job design (Section 13, ADR-0068):

- :meth:`create_queued_analysis` — the API calls this synchronously: insert an
  ``ai.interpretation`` row with ``status='queued'`` and return its ``uuid`` as a stable
  ``analysis_id`` immediately, before any Claude call is ever made.
- :meth:`run_analysis` — the Celery worker calls this once, out of band: build the snapshot, check
  the monthly budget (R3: an explicit refusal, never a silent skip), call Claude, validate the
  response deterministically (:mod:`cfi.analyst.validator`) allowing exactly one retry with the
  validator's own errors appended to the prompt (Section 12), persist the snapshot/interpretation/
  usage rows, and leave the interpretation ``completed`` or ``failed`` — never partially written.

Nothing here talks to Claude directly (that is :mod:`cfi.analyst.client`) or reads the database
directly (that is :mod:`cfi.analyst.repository`) — this module only sequences them.
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
from cfi.analyst.prompts import PROMPT_VERSION_ID, SYSTEM_PROMPT, user_prompt
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.schema import AnalystResponse
from cfi.analyst.snapshot import Snapshot, build_snapshot
from cfi.analyst.universe import MAX_VALIDATION_ATTEMPTS
from cfi.analyst.validator import validate
from cfi.core.config import Settings
from cfi.core.errors import AIBudgetExceededError, AIValidationError, CFIError
from cfi.core.logging import get_logger
from cfi.providers.http import ProviderHttpClient

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class QueuedAnalysis:
    analysis_id: uuid.UUID
    status: str


class AnalystService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, *, http: ProviderHttpClient
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.repo = AnalystRepository(engine)
        self.client = ClaudeClient(
            http, model=settings.anthropic_model, max_tokens=settings.anthropic_max_tokens
        )

    # ------------------------------------------------------------------ queue

    async def create_queued_analysis(
        self, *, question: str | None, now: datetime
    ) -> QueuedAnalysis:
        _interpretation_id, analysis_uuid = await self.repo.create_queued_interpretation(
            now=now, question=question
        )
        return QueuedAnalysis(analysis_id=analysis_uuid, status="queued")

    async def get_analysis(self, analysis_id: uuid.UUID) -> dict[str, Any] | None:
        return await self.repo.get_by_uuid(analysis_id)

    # ------------------------------------------------------------------ run

    async def run_analysis(
        self,
        analysis_id: uuid.UUID,
        *,
        as_of: datetime,
        knowledge_time: datetime,
        now: datetime,
    ) -> None:
        """Run one queued analysis end to end. Never raises on an *expected* failure mode (budget
        exceeded, malformed Claude output that still fails after the retry, a provider error) — each
        is caught, recorded on the interpretation row as ``failed`` with its ``error`` text, and
        this method returns normally, matching every other Celery task's own error-recording
        convention (they do not re-raise CFIError; they record it). An unanticipated exception is
        left to propagate (R3): swallowing it here would hide a real bug."""
        interpretation_id = await self.repo.interpretation_id_for_uuid(analysis_id)
        if interpretation_id is None:
            raise CFIError(f"No queued analysis found for analysis_id={analysis_id}.")

        await self.repo.mark_running(interpretation_id, now=now)

        try:
            monthly_cost = await self.repo.monthly_cost_usd(now)
            if monthly_cost >= Decimal(str(self.settings.ai_monthly_budget_usd)):
                raise AIBudgetExceededError(
                    f"This month's recorded AI usage (${monthly_cost}) has met or exceeded the "
                    f"configured budget ceiling (${self.settings.ai_monthly_budget_usd})."
                )

            row = await self.repo.get_by_uuid(analysis_id)
            question = row["question"] if row else None
            snapshot = await build_snapshot(
                self.engine,
                self.settings,
                as_of=as_of,
                knowledge_time=knowledge_time,
                question=question,
            )
            snapshot_id, _snapshot_uuid = await self.repo.insert_snapshot(
                created_at=snapshot.created_at,
                as_of=snapshot.as_of,
                knowledge_time=snapshot.knowledge_time,
                snapshot_version=snapshot.snapshot_version,
                payload=snapshot.payload(),
                payload_hash=snapshot.snapshot_id,
            )

            response, validation_errors, attempt_count = await self._complete_with_retry(
                snapshot, interpretation_id=interpretation_id, now=now
            )

            if response is None:
                await self.repo.mark_failed(
                    interpretation_id,
                    now=now,
                    error=(
                        "Claude's response failed validation after the retry: "
                        + "; ".join(validation_errors)
                    ),
                    snapshot_id=snapshot_id,
                    prompt_version=PROMPT_VERSION_ID,
                    model=self.settings.anthropic_model,
                    validation_status="failed",
                    validation_errors=validation_errors,
                    attempt_count=attempt_count,
                    tools_called=snapshot.tools_called,
                    data_quality_state=snapshot.data_quality_state,
                )
                return

            await self.repo.mark_completed(
                interpretation_id,
                now=now,
                snapshot_id=snapshot_id,
                prompt_version=PROMPT_VERSION_ID,
                model=self.settings.anthropic_model,
                response=response.model_dump(mode="json"),
                validation_status="ok",
                validation_errors=[],
                attempt_count=attempt_count,
                tools_called=snapshot.tools_called,
                data_quality_state=snapshot.data_quality_state,
            )
        except CFIError as exc:
            log.warning(
                "analyst_run_failed",
                analysis_id=str(analysis_id),
                error_code=exc.error_code,
                detail=exc.detail,
            )
            await self.repo.mark_failed(
                interpretation_id, now=now, error=f"{exc.error_code}: {exc.detail}"
            )

    async def _complete_with_retry(
        self, snapshot: Snapshot, *, interpretation_id: int, now: datetime
    ) -> tuple[AnalystResponse | None, list[str], int]:
        retry_errors: list[str] | None = None
        last_errors: list[str] = []
        for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
            prompt = user_prompt(snapshot, retry_errors=retry_errors)
            t0 = time.monotonic()
            claude_response = await self.client.complete(system=SYSTEM_PROMPT, user=prompt)
            latency_ms = round((time.monotonic() - t0) * 1000)

            cost = Decimal(claude_response.input_tokens) / Decimal(1_000_000) * Decimal(
                str(self.settings.anthropic_input_cost_per_mtok_usd)
            ) + Decimal(claude_response.output_tokens) / Decimal(1_000_000) * Decimal(
                str(self.settings.anthropic_output_cost_per_mtok_usd)
            )
            await self.repo.insert_usage(
                interpretation_id=interpretation_id,
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
                candidate = AnalystResponse.model_validate(parsed)
            except (AIValidationError, ValueError) as exc:
                last_errors = [str(exc)]
                retry_errors = last_errors
                continue

            result = validate(candidate, snapshot)
            if result.ok:
                return candidate, [], attempt
            last_errors = result.errors
            retry_errors = result.errors

        return None, last_errors, MAX_VALIDATION_ATTEMPTS
