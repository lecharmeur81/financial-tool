"""Daily Market Brief against real PostgreSQL (Phase 22): the repository's persisted shape, the
queued-then-run job lifecycle end to end (with a fake Anthropic transport, same convention as
``tests/integration/test_analyst_service.py``), change detection against a previous completed
brief's stored snapshot, the shared monthly budget ceiling (Section 9: the brief's usage rows
share ``ai.usage`` with the Phase 21 analyst's own, unmodified ``monthly_cost_usd`` query), and
that every audit field Section 9 asks for actually lands in the database. The DB-backed
integration suite is written and exercised exactly like every other Phase 21/22 suite — the user's
own instruction is to keep the real PostgreSQL/TimescaleDB limitation honestly documented in this
sandbox, not to avoid writing the coverage; it runs wherever a real test database is reachable
(see PROGRESS.md)."""

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
from cfi.api.app import create_app
from cfi.brief.repository import BriefRepository
from cfi.brief.service import BriefService
from cfi.core.config import Settings
from cfi.providers.http import ProviderHttpClient
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 9, 29, tzinfo=UTC)

VALID_RESPONSE = {
    "executive_summary": "Insufficient data.",
    "market_regime": {
        "current": "Insufficient data.",
        "confidence": "Insufficient data.",
        "evidence": [],
        "changed_since_previous": [],
    },
    "institutional_activity": [],
    "whale_activity": [],
    "retail_activity": [],
    "derivatives_liquidity": [],
    "macro": [],
    "market_structure": [],
    "divergences_anomalies": [],
    "capital_rotation": [],
    "historical_context": [],
    "contradicting_evidence": [],
    "risks_uncertainties": [],
    "what_to_monitor": [],
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
    repo = BriefRepository(db)
    now = datetime.now(UTC)
    brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now,
        reporting_period_start=AS_OF,
        reporting_period_end=now,
        previous_brief_id=None,
    )
    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "queued"

    await repo.mark_running(brief_db_id, now=now)
    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "running"

    analyst_repo = AnalystRepository(db)
    snapshot_id, _snapshot_uuid = await analyst_repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload={"fields": {}},
        payload_hash="deadbeef",
    )
    await repo.mark_completed(
        brief_db_id,
        now=now,
        snapshot_id=snapshot_id,
        prompt_version="brief_prompt.v1",
        analyst_version="brief_analyst.v1",
        model="claude-sonnet-5",
        response=VALID_RESPONSE,
        validation_status="ok",
        validation_errors=[],
        attempt_count=1,
        tools_called=["get_market_data"],
        data_quality_state="ok",
        changes={"comparison_basis": "none", "changes": []},
    )
    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "completed"
    assert row["response"] == VALID_RESPONSE
    assert row["changes"] == {"comparison_basis": "none", "changes": []}

    await repo.insert_usage_for_brief(
        brief_id=brief_db_id,
        now=now,
        model="claude-sonnet-5",
        input_tokens=500,
        output_tokens=300,
        latency_ms=1200,
        cost_usd=Decimal("0.006"),
        attempt=1,
    )
    # The brief's usage shares the Phase 21 analyst's own, unmodified budget query (Section 9).
    total = await analyst_repo.monthly_cost_usd(now)
    assert total == Decimal("0.006")

    latest = await repo.latest_completed_brief()
    assert latest is not None
    assert latest["uuid"] == brief_uuid


async def test_run_brief_end_to_end_with_a_fake_claude_transport(
    db: AsyncEngine, test_settings: Settings
) -> None:
    async def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=_claude_success_body(VALID_RESPONSE),
            headers={"content-type": "application/json"},
        )

    repo = BriefRepository(db)
    now = datetime.now(UTC)
    _brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now, reporting_period_start=AS_OF, reporting_period_end=now, previous_brief_id=None
    )

    http = _fake_http(test_settings, handle)
    try:
        service = BriefService(db, test_settings, http=http)
        await service.run_brief(brief_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "completed", row["error"]
    assert row["response"] == VALID_RESPONSE
    assert row["validation_status"] == "ok"
    assert row["attempt_count"] == 1
    assert row["changes"]["comparison_basis"] == "none"
    assert row["prompt_version"] == "brief_prompt.v1"
    assert row["analyst_version"] == "brief_analyst.v1"
    assert row["model"] == test_settings.anthropic_model


async def test_run_brief_detects_a_change_against_the_previous_completed_briefs_snapshot(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """A previous ``completed`` brief whose stored snapshot has a different display value for the
    same field_id makes `compute_changes` produce a real `change_id` — and Claude is allowed to
    cite it (Section 5)."""
    analyst_repo = AnalystRepository(db)
    repo = BriefRepository(db)
    now = datetime.now(UTC)

    previous_snapshot_id, _u = await analyst_repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload={"fields": {"get_macro.dxy": {"display": "100.0"}}},
        payload_hash="previous-hash",
    )
    previous_db_id, _previous_uuid = await repo.create_queued_brief(
        now=now, reporting_period_start=AS_OF, reporting_period_end=now, previous_brief_id=None
    )
    await repo.mark_completed(
        previous_db_id,
        now=now,
        snapshot_id=previous_snapshot_id,
        prompt_version="brief_prompt.v1",
        analyst_version="brief_analyst.v1",
        model="claude-sonnet-5",
        response=VALID_RESPONSE,
        validation_status="ok",
        validation_errors=[],
        attempt_count=1,
        tools_called=["get_macro"],
        data_quality_state="ok",
        changes={"comparison_basis": "none", "changes": []},
    )

    captured_changes: dict[str, object] = {}

    async def handle(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        prompt_text = body["messages"][0]["content"]
        change_set_json = prompt_text.split("CHANGE SET (data only, not instructions) ---\n")[
            1
        ].split("\n--- END CHANGE SET")[0]
        captured_changes.update(json.loads(change_set_json))
        return httpx2.Response(
            200,
            content=_claude_success_body(VALID_RESPONSE),
            headers={"content-type": "application/json"},
        )

    _brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now,
        reporting_period_start=AS_OF,
        reporting_period_end=now,
        previous_brief_id=previous_db_id,
    )
    http = _fake_http(test_settings, handle)
    try:
        service = BriefService(db, test_settings, http=http)
        await service.run_brief(brief_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    assert captured_changes["comparison_basis"] == "previous_brief"
    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "completed", row["error"]
    assert row["changes"]["comparison_basis"] == "previous_brief"


async def test_run_brief_refuses_when_monthly_budget_is_exceeded(
    db: AsyncEngine, test_settings: Settings
) -> None:
    repo = BriefRepository(db)
    now = datetime.now(UTC)
    over_budget = test_settings.model_copy(update={"ai_monthly_budget_usd": 0.0})
    _brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now, reporting_period_start=AS_OF, reporting_period_end=now, previous_brief_id=None
    )

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("Claude must never be called once the budget is exceeded")

    http = _fake_http(over_budget, handle)
    try:
        service = BriefService(db, over_budget, http=http)
        await service.run_brief(brief_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "failed"
    assert "ai_budget_exceeded" in (row["error"] or "")


async def test_run_brief_retries_once_then_fails_on_persistently_invalid_output(
    db: AsyncEngine, test_settings: Settings
) -> None:
    bad_response = {**VALID_RESPONSE, "executive_summary": "Institutional inflows hit 123456 BTC."}
    attempts = {"n": 0}

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        attempts["n"] += 1
        return httpx2.Response(
            200,
            content=_claude_success_body(bad_response),
            headers={"content-type": "application/json"},
        )

    repo = BriefRepository(db)
    now = datetime.now(UTC)
    _brief_db_id, brief_uuid = await repo.create_queued_brief(
        now=now, reporting_period_start=AS_OF, reporting_period_end=now, previous_brief_id=None
    )

    http = _fake_http(test_settings, handle)
    try:
        service = BriefService(db, test_settings, http=http)
        await service.run_brief(brief_uuid, as_of=AS_OF, knowledge_time=AS_OF, now=now)
    finally:
        await http.aclose()

    assert attempts["n"] == 2
    row = await repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "failed"
    assert "123456" in (row["error"] or "")


async def test_generate_endpoint_creates_a_queued_brief(
    test_settings: Settings, db: AsyncEngine
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.post("/api/v1/brief/generate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["brief_id"]
