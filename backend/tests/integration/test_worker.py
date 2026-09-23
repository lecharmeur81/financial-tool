"""Celery worker wiring: configuration, schedule and the per-process runtime (no broker needed)."""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import make_url

from cfi.core.config import Settings
from cfi.institutional.universe import all_datasets as institutional_datasets
from cfi.market.universe import all_datasets
from cfi.worker.runtime import WorkerRuntime
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]


def test_celery_app_is_configured_for_safe_task_handling() -> None:
    from cfi.worker import app as worker

    conf = worker.app.conf
    assert conf.task_acks_late is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_ignore_result is True
    assert "market.ingest_latest" in worker.app.tasks
    assert "market.backfill_round" in worker.app.tasks
    queues = {entry["options"]["queue"] for entry in conf.beat_schedule.values()}
    assert queues == {"ingest_fast", "ingest", "backfill"}


def test_disabled_provider_is_not_ingested() -> None:
    from cfi.worker import app as worker

    result = worker.ingest_latest_task.run("not-enabled", "market.ohlcv.usd.1m")
    assert result == {"skipped": "provider not-enabled is disabled"}


def test_runtime_registers_every_enabled_dataset(test_settings: Settings) -> None:
    # explicit provider lists: the test must not depend on the user's .env choices
    settings = test_settings.model_copy(
        update={
            "market_providers": "coinbase,kraken,binance,okx,bybit,coingecko",
            "institutional_providers": "sosovalue,coingecko",
        }
    )
    runtime = WorkerRuntime(settings)
    try:
        ctx = runtime.run(runtime.context())
        assert set(ctx.clients) == {
            "coinbase",
            "kraken",
            "binance",
            "okx",
            "bybit",
            "coingecko",
            "sosovalue",
        }
        assert runtime.run(runtime.context()) is ctx  # one context per process
    finally:
        runtime.run(runtime.aclose())
        runtime.loop.close()
    url = make_url(test_settings.database_url.get_secret_value()).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        datasets = {r[0] for r in conn.execute("SELECT dataset_id FROM ops.dataset")}
        links = conn.execute("SELECT count(*) FROM ops.dataset_provider").fetchone()
    expected = {d.dataset_id for d in all_datasets()} | {
        d.dataset_id for d in institutional_datasets()
    }
    assert expected <= datasets  # (Coinbase 4h is derived at read time; Kraken supplies usd 4h)
    assert links is not None
    assert links[0] >= len(expected)


def test_institutional_jobs_are_scheduled_on_the_right_queues() -> None:
    from cfi.worker import app as worker

    entries = {
        k: v for k, v in worker.app.conf.beat_schedule.items() if k.startswith("institutional:")
    }
    assert "institutional.ingest" in worker.app.tasks
    expected = {"sosovalue": "backfill", "coingecko": "ingest"}  # one SoSoValue process
    for key, entry in entries.items():  # entries depend on CFI_INSTITUTIONAL_PROVIDERS
        assert entry["options"]["queue"] == expected[key.split(":")[1]]
    assert all(v["options"]["expires"] == v["schedule"] for v in entries.values())


def test_institutional_task_skips_disabled_provider_and_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cfi.worker import app as worker

    monkeypatch.setattr(
        worker,
        "settings",
        worker.settings.model_copy(update={"institutional_providers": "sosovalue,coingecko"}),
    )
    result = worker.institutional_ingest_task.run("not-enabled", "x")
    assert result == {"skipped": "provider not-enabled is disabled"}
    monkeypatch.delenv("CFI_PROVIDER_SOSOVALUE_API_KEY", raising=False)
    result = worker.institutional_ingest_task.run("sosovalue", "institutional.etf_flow.us_spot.1d")
    assert result == {"skipped": "provider sosovalue has no API key configured"}
