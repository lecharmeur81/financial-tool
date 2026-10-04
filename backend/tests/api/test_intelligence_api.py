"""Read-only intelligence-event endpoints (Phase 35): that both GET routes fail explicitly, never
silently, when no database is available — the same ``ServiceUnavailableError`` convention every
other route in this codebase follows. The real list/detail behavior against persisted events needs
a real database and is covered by the integration suite (``test_realtime_service.py``), not here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping

import pytest
from fastapi.testclient import TestClient

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


def test_list_without_a_database_fails_explicitly(client: TestClient) -> None:
    """``health_checks`` replaces the real database probe in this test harness, so
    ``app.state.engine`` is never set — the route must refuse with a clear 503, never a silent
    hang or an unhandled exception."""
    response = client.get("/api/v1/intelligence-events/")
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_get_one_without_a_database_fails_explicitly(client: TestClient) -> None:
    response = client.get(f"/api/v1/intelligence-events/{uuid.uuid4()}")
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_list_rejects_bad_query_params(client: TestClient) -> None:
    # limit above the documented ceiling is a 422, never silently clamped or passed through.
    response = client.get("/api/v1/intelligence-events/", params={"limit": 10_000})
    assert response.status_code == 422
