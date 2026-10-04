"""Phase 28 "Security Corrections": API key auth, rate limiting, and production docs gating.

Follows the same harness as ``test_analyst_api.py`` — ``health_checks`` replaces the real
database/Redis probe so no real connections are made; a request that gets past authentication and
rate limiting but has no database configured fails with the project's existing 503
``service_unavailable`` (never a silent hang, never an unhandled exception), which is exactly how
we tell "reached normal logic" apart from "rejected by auth" (401) or "rejected by the limiter"
(429) without needing a real database.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.core.health import HealthCheck

TEST_DATABASE_URL = "postgresql+psycopg://user:not-a-real-password@localhost:5432/cfi_test"
TEST_REDIS_URL = "redis://:not-a-real-password@localhost:6379/0"

TRADE_BODY = {"asset": "BTC", "direction": "long", "notional": "100"}


async def _ok() -> Mapping[str, str]:
    return {"note": "fake"}


def _client_for(settings: Settings) -> Iterator[TestClient]:
    checks: dict[str, HealthCheck] = {"database": _ok, "redis": _ok}
    app = create_app(settings, health_checks=checks)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """No api_key configured, environment=test — dev-mode passthrough."""
    yield from _client_for(settings)


@pytest.fixture
def protected_client(settings: Settings) -> Iterator[TestClient]:
    """An api_key IS configured, so every protected route must require it."""
    guarded = settings.model_copy(update={"api_key": SecretStr("s3cret-key")})
    yield from _client_for(guarded)


# --------------------------------------------------------------------------------- API key auth


def test_dev_mode_passes_through_unauthenticated_when_no_key_is_configured(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/paper/trades", json=TRADE_BODY)
    # Not blocked by auth (401) — it reaches the normal handler, which fails on the missing
    # database exactly like every other route in this test harness.
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_unauthenticated_request_to_a_protected_endpoint_is_rejected(
    protected_client: TestClient,
) -> None:
    response = protected_client.post("/api/v1/paper/trades", json=TRADE_BODY)
    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_wrong_key_is_rejected(protected_client: TestClient) -> None:
    response = protected_client.post(
        "/api/v1/paper/trades", json=TRADE_BODY, headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_authenticated_request_reaches_normal_logic(protected_client: TestClient) -> None:
    response = protected_client.post(
        "/api/v1/paper/trades", json=TRADE_BODY, headers={"X-API-Key": "s3cret-key"}
    )
    # Past auth — the 503 below comes from the missing database, not from the key check.
    assert response.status_code == 503
    assert response.json()["error_code"] == "service_unavailable"


def test_get_endpoints_are_never_protected(protected_client: TestClient) -> None:
    """GETs must stay open even when an api_key is configured (the frontend only ever does GETs,
    Phase 27 audit) — no X-API-Key header is sent here."""
    response = protected_client.get("/api/v1/paper/trades")
    assert response.status_code != 401


def test_settings_refuse_to_construct_in_production_without_an_api_key() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="CFI_API_KEY must be set"):
        Settings(
            environment="production",
            database_url=SecretStr(TEST_DATABASE_URL),
            redis_url=SecretStr(TEST_REDIS_URL),
            api_key=None,
        )


def test_settings_construct_fine_in_production_with_an_api_key() -> None:
    settings = Settings(
        environment="production",
        database_url=SecretStr(TEST_DATABASE_URL),
        redis_url=SecretStr(TEST_REDIS_URL),
        api_key=SecretStr("prod-key"),
    )
    assert settings.api_key is not None


@pytest.mark.parametrize("blank", ["", "   "])
def test_settings_refuse_to_construct_in_production_with_a_blank_api_key(blank: str) -> None:
    """Phase 32 finding: ``compose.prod.yaml`` inherits ``CFI_API_KEY: ${CFI_API_KEY:-}`` from the
    base compose file, so an operator who forgets to set ``CFI_API_KEY`` in their ``.env`` gets
    the literal empty string as the container's env value — not an absent variable. Pydantic would
    otherwise parse that as ``SecretStr("")``, which is not ``None``, silently defeating the
    fail-secure check above. A blank/whitespace-only value must be treated exactly like ``None``."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="CFI_API_KEY must be set"):
        Settings(
            environment="production",
            database_url=SecretStr(TEST_DATABASE_URL),
            redis_url=SecretStr(TEST_REDIS_URL),
            api_key=blank,  # type: ignore[arg-type]
        )


def test_a_blank_api_key_normalizes_to_none_outside_production() -> None:
    """The same normalization applies in every environment, so a blank value never reaches
    ``cfi.api.auth.require_api_key`` as a (falsy-but-not-``None``) key that an empty
    ``X-API-Key`` header could then match via ``secrets.compare_digest("", "")``. Construct
    directly (rather than via ``model_copy``, which skips validators) so the ``mode="before"``
    normalizer actually runs."""
    settings = Settings(
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        redis_url=SecretStr(TEST_REDIS_URL),
        api_key="",  # type: ignore[arg-type]
    )
    assert settings.api_key is None


# --------------------------------------------------------------------------------- Rate limiting


def test_exceeding_the_ai_trigger_limit_returns_429(client: TestClient) -> None:
    """analyst/analyze is capped at 5/hour (cfi.api.limiter.AI_TRIGGER_LIMIT). No database is
    configured, so the first five requests fail with 503 — the sixth must be turned away by the
    limiter before it ever reaches that check."""
    responses = [
        client.post("/api/v1/analyst/analyze", json={"question": "What changed?"}) for _ in range(5)
    ]
    assert all(r.status_code == 503 for r in responses)

    limited = client.post("/api/v1/analyst/analyze", json={"question": "What changed?"})
    assert limited.status_code == 429
    assert limited.json()["error_code"] == "rate_limit_exceeded"


# --------------------------------------------------------------------------------- Docs gating


def test_docs_are_disabled_in_production() -> None:
    settings = Settings(
        environment="production",
        database_url=SecretStr(TEST_DATABASE_URL),
        redis_url=SecretStr(TEST_REDIS_URL),
        api_key=SecretStr("prod-key"),
    )
    for c in _client_for(settings):
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404


def test_docs_are_enabled_outside_production(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200
