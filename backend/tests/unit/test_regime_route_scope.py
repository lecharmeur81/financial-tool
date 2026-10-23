"""``GET /api/v1/regime/current`` runs its service call inside one request-scoped PIT memo and with
the bounded interactive concurrency; the service default (used by alerts) stays sequential."""

from __future__ import annotations

import inspect
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.api.app import create_app
from cfi.api.routes import regime as route
from cfi.core import pit_memo
from cfi.core.config import Settings
from cfi.regime.service import RegimeService
from cfi.regime.universe import INTERACTIVE_HISTORICAL_CONCURRENCY


def test_the_route_calls_the_service_inside_a_pit_scope_with_bounded_concurrency(
    monkeypatch: Any,
) -> None:
    seen: dict[str, Any] = {}

    class FakeService:
        def __init__(self, engine: Any) -> None:
            seen["engine"] = engine

        async def current(
            self, *, as_of: Any, knowledge_time: Any, historical_concurrency: int = 1
        ) -> dict[str, Any]:
            seen["scope_active"] = pit_memo._scope.get() is not None
            seen["concurrency"] = historical_concurrency
            return {"status": "ok"}

    monkeypatch.setattr(route, "RegimeService", FakeService)
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})
    app.state.engine = object()
    with TestClient(app) as client:
        response = client.get("/api/v1/regime/current")
    assert response.status_code == 200
    assert seen["scope_active"] is True
    assert seen["concurrency"] == INTERACTIVE_HISTORICAL_CONCURRENCY == 3
    assert pit_memo._scope.get() is None  # the scope does not leak past the request


def test_the_service_default_stays_sequential_for_other_callers() -> None:
    default = inspect.signature(RegimeService.current).parameters["historical_concurrency"].default
    assert default == 1
