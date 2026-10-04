"""AI Analyst endpoints (Phase 21): the read-only ``/catalog`` (no database needed) and that the
DB-backed endpoints fail explicitly, never silently, when no database is available — matching
every other route's ``ServiceUnavailableError`` convention. The full queued-analysis flow (insert
row, enqueue Celery task, poll status) needs a real database and broker and is covered by the
integration suite, not here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping

import pytest
from fastapi.testclient import TestClient

from cfi.analyst.universe import RESPONSE_SECTIONS, TOOLS
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.core.health import HealthCheck


async def _ok() -> Mapping[str, str]:
    return {"note": "fake"}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    app = create_app(settings, health_checks=checks)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_catalog_lists_all_fourteen_tools_and_the_twelve_sections(client: TestClient) -> None:
    response = client.get("/api/v1/analyst/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["response_sections"] == list(RESPONSE_SECTIONS)
    assert {t["tool_id"] for t in body["tools"]} == {t.tool_id for t in TOOLS}
    assert len(body["tools"]) == 14


def test_analyze_without_a_database_fails_explicitly(client: TestClient) -> None:
    """``health_checks`` replaces the real database probe in this test harness, so
    ``app.state.engine`` is never set — the route must refuse with a clear 503, never a silent
    hang or an unhandled exception."""
    response = client.post("/api/v1/analyst/analyze", json={"question": "What changed?"})
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_get_analysis_without_a_database_fails_explicitly(client: TestClient) -> None:
    response = client.get(f"/api/v1/analyst/{uuid.uuid4()}")
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


# --------------------------------------------------------------------------- F-4: question length


def test_a_normal_length_question_passes_validation_and_reaches_the_service_layer(
    client: TestClient,
) -> None:
    """A realistic analyst question is well under the 4,000-character limit — the request must
    pass Pydantic validation and reach the normal (database-dependent) handler, evidenced by the
    503 "no database" response this no-DB test harness always gives past that point (the same
    signal ``test_analyze_without_a_database_fails_explicitly`` uses)."""
    response = client.post(
        "/api/v1/analyst/analyze",
        json={"question": "What is driving the divergence between ETF flows and funding rates?"},
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_an_oversized_question_is_rejected_with_the_normal_validation_response(
    client: TestClient,
) -> None:
    """A multi-thousand-character question (Phase 30 finding F-4) is rejected by request
    validation — the same 422 problem-details shape every other validation failure uses — before
    it ever reaches the service layer or could be queued for a paid Claude API call."""
    response = client.post("/api/v1/analyst/analyze", json={"question": "x" * 4001})
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "request_validation_error"
    assert "question" in body["detail"]


def test_a_question_at_exactly_the_limit_is_accepted(client: TestClient) -> None:
    response = client.post("/api/v1/analyst/analyze", json={"question": "x" * 4000})
    # Rejected only by the (absent) database in this harness, never by validation.
    assert response.status_code == 503


def test_no_question_at_all_is_still_accepted(client: TestClient) -> None:
    response = client.post("/api/v1/analyst/analyze", json={})
    assert response.status_code == 503
