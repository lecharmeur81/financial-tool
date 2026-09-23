from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.core.errors import InsufficientDataError, ProviderTransientError
from cfi.core.health import HealthCheck


async def _ok() -> Mapping[str, str]:
    return {"note": "fake"}


async def _down() -> Mapping[str, str]:
    raise ConnectionError("down")


def _client(settings: Settings, checks: Mapping[str, HealthCheck]) -> Iterator[TestClient]:
    app = create_app(settings, health_checks=checks)

    boom = APIRouter()

    @boom.get("/_test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("internal detail that must not leak")

    @boom.get("/_test/provider")
    async def provider() -> None:
        raise ProviderTransientError("provider timed out")

    @boom.get("/_test/insufficient")
    async def insufficient() -> None:
        raise InsufficientDataError("no funding data for the window")

    @boom.get("/_test/validate")
    async def validate(limit: int) -> dict[str, int]:
        return {"limit": limit}

    app.include_router(boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    yield from _client(settings, {"database": _ok, "redis": _ok})


@pytest.fixture
def degraded_client(settings: Settings) -> Iterator[TestClient]:
    yield from _client(settings, {"database": _ok, "redis": _down})


def test_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_all_dependencies_ok(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["components"]) == {"database", "redis"}
    assert body["checked_at"].endswith("Z")


def test_ready_reports_503_with_the_failing_component(degraded_client: TestClient) -> None:
    response = degraded_client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["components"]["redis"] == {
        "status": "error",
        "latency_ms": body["components"]["redis"]["latency_ms"],
        "detail": {},
        "error": "ConnectionError",
    }
    assert body["components"]["database"]["status"] == "ok"


def test_request_id_is_generated_and_propagated(client: TestClient) -> None:
    generated = client.get("/health/live").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/health/live", headers={"X-Request-ID": "trace-123"})
    assert echoed.headers["X-Request-ID"] == "trace-123"
    replaced = client.get("/health/live", headers={"X-Request-ID": "bad id with spaces"})
    assert replaced.headers["X-Request-ID"] != "bad id with spaces"


def test_meta(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["api_version"] == "v1"
    assert body["environment"] == "test"
    assert body["data_sources_connected"] == 0
    assert "hypothesis" in body["evidence_categories"]


def test_not_found_is_problem_json(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unexpected_error_does_not_leak_details(client: TestClient) -> None:
    response = client.get("/_test/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "internal detail" not in response.text
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_typed_errors_map_to_their_status(client: TestClient) -> None:
    provider = client.get("/_test/provider")
    assert provider.status_code == 502
    assert provider.json()["error_code"] == "provider_transient_error"

    insufficient = client.get("/_test/insufficient")
    assert insufficient.status_code == 422
    assert insufficient.json()["title"] == "Insufficient data."


def test_validation_errors_are_problem_json(client: TestClient) -> None:
    response = client.get("/_test/validate", params={"limit": "abc"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "request_validation_error"
    assert "limit" in response.json()["detail"]


def test_openapi_is_served(client: TestClient) -> None:
    assert (
        client.get("/api/openapi.json").json()["info"]["title"] == "Capital Flow Intelligence API"
    )
