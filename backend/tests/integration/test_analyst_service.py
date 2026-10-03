"""AI Analyst against real PostgreSQL (Phase 21): the repository's persisted shape, the queued-
then-run job lifecycle end to end (with a fake Anthropic transport — no real network access, same
convention as every other provider's own integration coverage), the monthly budget ceiling, and
that every audit field Section 13 asks for actually lands in the database. The API's ``/analyze``
endpoint is checked only for creating the queued row and returning a stable ``analysis_id`` —
running the Celery task itself is this file's job, not a live worker's.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Mapping
from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.client import anthropic_capabilities
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.service import AnalystService
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.providers.http import ProviderHttpClient
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 9, 28, tzinfo=UTC)

VALID_RESPONSE = {
    "summary": "Insufficient data.",
    "evidence": [],
    "contradicting_evidence": [],
    "market_regime": "Insufficient data.",
    "key_changes": [],
    "capital_participant_behavior": [],
    "derivatives_liquidity_context": [],
    "historical_context": [],
    "risks_uncertainties": [],
    "scenarios": [],
    "invalidation_conditions": [],
    "data_quality": "Insufficient data.",
}


def _claude_success_body(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": "end_turn",
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 500, "output_tokens": 300},
        }
    ).encode()


Handler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]


def _fake_http(settings: Settings, handler: Handler) -> ProviderHttpClient:
    return ProviderHttpClient(
        anthropic_capabilities(settings),
        transport=httpx2.MockTransport(handler),
        environ={"CFI_ANTHROPIC_API_KEY": "test-key"},
    )


async def test_repository_round_trip(db: AsyncEngine) -> None:
    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    interpretation_id, analysis_uuid = await repo.create_queued_interpretation(
        now=now, question="What changed?"
    )
    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "queued"
    assert row["question"] == "What changed?"

    await repo.mark_running(interpretation_id, now=now)
    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "running"

    snapshot_id, _snapshot_uuid = await repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload={"fields": {}},
        payload_hash="deadbeef",
    )
    await repo.mark_completed(
        interpretation_id,
        now=now,
        snapshot_id=snapshot_id,
        prompt_version="analyst_prompt.v1",
        model="claude-sonnet-5",
        response=VALID_RESPONSE,
        validation_status="ok",
        validation_errors=[],
        attempt_count=1,
        tools_called=["get_market_data"],
        data_quality_state="ok",
    )
    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "completed"
    assert row["response"] == VALID_RESPONSE
    assert row["attempt_count"] == 1

    await repo.insert_usage(
        interpretation_id=interpretation_id,
        now=now,
        model="claude-sonnet-5",
        input_tokens=500,
        output_tokens=300,
        latency_ms=1200,
        cost_usd=Decimal("0.006"),
        attempt=1,
    )
    total = await repo.monthly_cost_usd(now)
    assert total == Decimal("0.006")


async def test_run_analysis_end_to_end_with_a_fake_claude_transport(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """Empty database: every domain tool comes back with nothing loaded (matching the same
    "insufficient data" empty-database convention every other engine's own integration suite
    proves — see test_regime_api.py), and the fake Claude transport returns the minimal, fully
    grounded ``"Insufficient data."`` response, so validation passes on the first attempt."""

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=_claude_success_body(VALID_RESPONSE),
            headers={"content-type": "application/json"},
        )

    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    _interpretation_id, analysis_uuid = await repo.create_queued_interpretation(
        now=now, question=None
    )

    http = _fake_http(test_settings, handle)
    try:
        service = AnalystService(db, test_settings, http=http)
        await service.run_analysis(analysis_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "completed", row["error"]
    assert row["response"] == VALID_RESPONSE
    assert row["validation_status"] == "ok"
    assert row["attempt_count"] == 1
    assert row["tools_called"] is not None
    assert len(row["tools_called"]) == 14
    assert row["data_quality_state"] in {"ok", "degraded", "insufficient"}
    assert row["prompt_version"] == "analyst_prompt.v1"
    assert row["model"] == test_settings.anthropic_model


async def test_run_analysis_retries_once_then_fails_on_persistently_invalid_output(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """A response that never passes validation (a fabricated number with no snapshot backing) is
    retried exactly once (Section 12) and then recorded ``failed`` with the validator's own
    errors — never silently reinterpreted or accepted."""
    bad_response = {**VALID_RESPONSE, "summary": "Institutional inflows hit 123456 BTC today."}
    attempts = {"n": 0}

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        attempts["n"] += 1
        return httpx2.Response(
            200,
            content=_claude_success_body(bad_response),
            headers={"content-type": "application/json"},
        )

    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    _interpretation_id, analysis_uuid = await repo.create_queued_interpretation(
        now=now, question=None
    )

    http = _fake_http(test_settings, handle)
    try:
        service = AnalystService(db, test_settings, http=http)
        await service.run_analysis(analysis_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    assert attempts["n"] == 2  # one call, one retry — never more
    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "failed"
    assert "123456" in (row["error"] or "")


async def test_run_analysis_refuses_when_monthly_budget_is_exceeded(
    db: AsyncEngine, test_settings: Settings
) -> None:
    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    over_budget = test_settings.model_copy(update={"ai_monthly_budget_usd": 0.0})
    _interpretation_id, analysis_uuid = await repo.create_queued_interpretation(
        now=now, question=None
    )

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Claude must never be called once the budget is exceeded")

    http = _fake_http(over_budget, handle)
    try:
        service = AnalystService(db, over_budget, http=http)
        await service.run_analysis(analysis_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    row = await repo.get_by_uuid(analysis_uuid)
    assert row is not None
    assert row["status"] == "failed"
    assert "ai_budget_exceeded" in (row["error"] or "")


async def test_analyze_endpoint_creates_a_queued_analysis(
    test_settings: Settings, db: AsyncEngine
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.post("/api/v1/analyst/analyze", json={"question": "What changed?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["analysis_id"]
