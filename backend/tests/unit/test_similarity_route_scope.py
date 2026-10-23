"""``GET /api/v1/similarity/current`` runs its whole service call inside one request-scoped PIT
memo, and the scope is cleared afterwards even when the service fails."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.api.app import create_app
from cfi.api.routes import similarity as route
from cfi.core import pit_memo
from cfi.core.config import Settings

_AS_OF = "2026-01-01T00:00:00+00:00"


def _client(monkeypatch: Any, service: type, **kw: Any) -> TestClient:
    monkeypatch.setattr(route, "SimilarityService", service)
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})
    app.state.engine = object()
    return TestClient(app, **kw)


def test_the_route_calls_the_service_inside_a_pit_scope(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    class FakeService:
        def __init__(self, engine: Any) -> None:
            seen["engine"] = engine

        async def current(self, *, as_of: Any, knowledge_time: Any) -> dict[str, Any]:
            seen["scope_active"] = pit_memo._scope.get() is not None
            seen["as_of"], seen["knowledge_time"] = as_of, knowledge_time
            return {"status": "ok"}

    with _client(monkeypatch, FakeService) as client:
        # An explicit as_of is the live path; the default view is precomputed (see
        # test_similarity_precompute.py).
        response = client.get("/api/v1/similarity/current", params={"as_of": _AS_OF})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert seen["scope_active"] is True
    assert seen["as_of"] == seen["knowledge_time"]  # knowledge_time defaults to as_of (ADR-0060)
    assert pit_memo._scope.get() is None  # the scope does not leak past the request


def test_explicit_times_are_passed_through_unchanged(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    class FakeService:
        def __init__(self, engine: Any) -> None:
            pass

        async def current(self, *, as_of: Any, knowledge_time: Any) -> dict[str, Any]:
            seen["pair"] = (as_of.isoformat(), knowledge_time.isoformat())
            return {}

    with _client(monkeypatch, FakeService) as client:
        response = client.get(
            "/api/v1/similarity/current",
            params={
                "as_of": "2026-01-01T00:00:00+00:00",
                "knowledge_time": "2026-01-02T00:00:00+00:00",
            },
        )
    assert response.status_code == 200
    assert seen["pair"] == ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")


def test_the_scope_is_cleared_when_the_service_fails(monkeypatch: Any) -> None:
    class BoomService:
        def __init__(self, engine: Any) -> None:
            pass

        async def current(self, *, as_of: Any, knowledge_time: Any) -> dict[str, Any]:
            assert pit_memo._scope.get() is not None
            raise RuntimeError("boom")

    with _client(monkeypatch, BoomService, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/similarity/current", params={"as_of": _AS_OF})
    assert response.status_code == 500
    assert pit_memo._scope.get() is None
