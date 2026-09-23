"""Migrations on the isolated test database: downgrade refuses to destroy data (R10)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from alembic import command
from sqlalchemy import make_url

from cfi.core.config import get_settings
from tests.integration.conftest import (
    DATA_TABLES,
    alembic_config,
    head_revision,
    requires_services,
)

pytestmark = [pytest.mark.integration, requires_services]


@contextmanager
def _pointing_at(url: str) -> Iterator[None]:
    previous = os.environ["CFI_DATABASE_URL"]
    os.environ["CFI_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        os.environ["CFI_DATABASE_URL"] = previous
        get_settings.cache_clear()


def _plain(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _execute(url: str, statement: str) -> None:
    with psycopg.connect(_plain(url), autocommit=True) as conn:
        conn.execute(statement.encode())  # fixed test SQL, no user input


def _scalar(url: str, query: str) -> object:
    with psycopg.connect(_plain(url), autocommit=True) as conn:
        row = conn.execute(query.encode()).fetchone()
    return row[0] if row else None


def _empty_all(url: str) -> None:
    _execute(url, f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE")


def test_downgrade_refuses_when_data_exists_then_round_trips(test_database_url: str) -> None:
    url = test_database_url
    _empty_all(url)  # earlier tests may have left rows in this database
    _execute(
        url,
        "INSERT INTO ops.provider"
        " (provider_id, display_name, base_url, auth_type, original_source)"
        " VALUES ('keep_me', 'k', 'https://k.invalid', 'none', 'unknown')",
    )
    with _pointing_at(url):
        with pytest.raises(RuntimeError, match=r"Refusing to downgrade: .*ops\.provider"):
            command.downgrade(alembic_config(), "0001")
        assert _scalar(url, "SELECT count(*) FROM ops.provider") == 1  # data untouched
        assert _scalar(url, "SELECT version_num FROM alembic_version") == head_revision()

        _empty_all(url)
        command.downgrade(alembic_config(), "0001")  # empty tables: allowed
        assert _scalar(url, "SELECT to_regclass('obs.observation')::text") is None
        command.upgrade(alembic_config(), "head")
        assert _scalar(url, "SELECT version_num FROM alembic_version") == head_revision()


def _flow_series(url: str) -> None:
    _execute(
        url,
        "INSERT INTO ops.dataset (dataset_id, metric, unit, period, availability_rule,"
        " freshness_limit_seconds, conflict_tolerance, revisable, expect_continuous, description,"
        " updated_at, kind) VALUES ('institutional.etf_flow.us_spot.1d', 'etf_flow', 'usd', '1d',"
        " '{}', 60, 0, true, false, 'test', now(), 'flow')",
    )
    _execute(
        url,
        "INSERT INTO obs.series (dataset_id, metric, asset, subject_ref, period, unit, created_at)"
        " VALUES ('institutional.etf_flow.us_spot.1d', 'etf_flow', 'BTC', 'US-SPOT-ETF:BTC',"
        " '1d', 'usd', now())",
    )


def test_institutional_downgrade_refuses_when_flows_exist(test_database_url: str) -> None:
    url = test_database_url
    _empty_all(url)
    _flow_series(url)
    _execute(
        url,
        "INSERT INTO obs.institutional_flow (series_id, event_time, available_at,"
        " available_at_estimated, ingested_at, entity_type, evidence_class, flow_usd,"
        " source_provider, original_source, revision, pit_reliability, quality_status)"
        " SELECT series_id, '2026-09-04', now(), true, now(), 'etf_group', 'direct', 1,"
        " 'sosovalue', 'sosovalue', 0, 'native', 'ok' FROM obs.series",
    )
    with _pointing_at(url):
        with pytest.raises(RuntimeError, match=r"obs\.institutional_flow"):
            command.downgrade(alembic_config(), "0003")
        assert _scalar(url, "SELECT count(*) FROM obs.institutional_flow") == 1
        assert _scalar(url, "SELECT version_num FROM alembic_version") == head_revision()
    _empty_all(url)


def test_institutional_flow_rejects_inferred_labels_and_silent_missing(
    test_database_url: str,
) -> None:
    url = test_database_url
    _empty_all(url)
    _flow_series(url)
    base = (
        "INSERT INTO obs.institutional_flow (series_id, event_time, available_at,"
        " available_at_estimated, ingested_at, entity_type, evidence_class, flow_usd,"
        " source_provider, original_source, revision, pit_reliability, quality_status)"
        " SELECT series_id, '2026-09-04', now(), true, now(), 'etf_group', {cls}, {flow},"
        " 'p', 'p', 0, 'native', {status} FROM obs.series"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        _execute(url, base.format(cls="'inferred'", flow="1", status="'ok'"))
    with pytest.raises(psycopg.errors.CheckViolation):  # no values but not marked missing
        _execute(url, base.format(cls="'direct'", flow="NULL", status="'ok'"))
    _empty_all(url)
