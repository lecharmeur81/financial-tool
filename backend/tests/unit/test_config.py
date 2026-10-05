from __future__ import annotations

import pytest
from pydantic import ValidationError

from cfi.core.config import Settings, get_settings


def test_required_urls_fail_fast_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CFI_DATABASE_URL", raising=False)
    monkeypatch.delenv("CFI_REDIS_URL", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        get_settings()
    missing = {err["loc"][0] for err in excinfo.value.errors()}
    assert missing == {"database_url", "redis_url"}


def test_reads_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CFI_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/cfi")
    monkeypatch.setenv("CFI_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CFI_ENVIRONMENT", "production")
    monkeypatch.setenv("CFI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("CFI_CORS_ORIGINS", '["http://localhost:3000"]')
    settings = get_settings()
    assert settings.environment == "production"
    assert settings.cors_origins == ["http://localhost:3000"]


def test_secrets_are_not_exposed_in_repr(settings: Settings) -> None:
    text = repr(settings) + str(settings.model_dump())
    assert "not-a-real-password" not in text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "postgresql://u:p@db/cfi"),  # wrong driver prefix
        ("redis_url", "http://redis:6379"),
    ],
)
def test_rejects_invalid_urls(settings: Settings, field: str, value: str) -> None:
    data = {
        "database_url": settings.database_url.get_secret_value(),
        "redis_url": settings.redis_url.get_secret_value(),
        field: value,
    }
    with pytest.raises(ValidationError):
        Settings(**data)  # type: ignore[arg-type]


def test_settings_are_immutable(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_blank_database_url_runtime_env_var_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the Phase 37 startup defect: ``compose.yaml`` always sets this env var to
    ``${CFI_DATABASE_URL_RUNTIME:-}`` (empty string when absent from ``.env``), which must behave
    exactly like the field being unset, not fail the psycopg-prefix check below."""
    monkeypatch.setenv("CFI_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/cfi")
    monkeypatch.setenv("CFI_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CFI_DATABASE_URL_RUNTIME", "")
    settings = get_settings()
    assert settings.database_url_runtime is None


def test_blank_api_key_env_var_is_still_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same blank-string-from-compose shape as the regression above, for the sibling field this
    pattern was first introduced for — guards against the two drifting apart again."""
    monkeypatch.setenv("CFI_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/cfi")
    monkeypatch.setenv("CFI_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CFI_API_KEY", "")
    settings = get_settings()
    assert settings.api_key is None
