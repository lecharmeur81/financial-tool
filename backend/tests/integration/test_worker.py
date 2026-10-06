"""Celery worker wiring: configuration, schedule and the per-process runtime (no broker needed)."""

from __future__ import annotations

import psycopg
import pytest
from pydantic import SecretStr
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.derivatives.universe import all_datasets as derivative_datasets
from cfi.institutional.universe import all_datasets as institutional_datasets
from cfi.market.universe import all_datasets
from cfi.market_structure.universe import all_datasets as market_structure_datasets
from cfi.whales.label_store import SEED_FILES, seed_text
from cfi.whales.labels import parse_label_csv
from cfi.whales.universe import all_datasets as whale_datasets
from cfi.worker.runtime import WorkerRuntime
from tests.integration.conftest import isolated_redis_url, requires_services

pytestmark = [pytest.mark.integration, requires_services]


def test_celery_app_is_configured_for_safe_task_handling() -> None:
    from cfi.worker import app as worker

    conf = worker.app.conf
    assert conf.task_acks_late is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_ignore_result is True
    assert "market.ingest_latest" in worker.app.tasks
    assert "market.backfill_round" in worker.app.tasks
    assert "analyst.analyze" in worker.app.tasks
    assert "brief.generate" in worker.app.tasks
    assert "alerts.evaluate" in worker.app.tasks
    queues = {entry["options"]["queue"] for entry in conf.beat_schedule.values()}
    assert queues == {"ingest_fast", "ingest", "backfill", "ai"}
    assert "brief:daily" in conf.beat_schedule
    assert conf.beat_schedule["brief:daily"]["options"]["queue"] == "ai"
    assert "alerts:evaluate" in conf.beat_schedule
    assert conf.beat_schedule["alerts:evaluate"]["options"]["queue"] == "ingest"


def test_brief_is_scheduled_once_daily_on_the_ai_queue() -> None:
    from cfi.worker.schedule import brief_entries

    entries = brief_entries()
    assert list(entries) == ["brief:daily"]
    entry = entries["brief:daily"]
    assert entry["task"] == "brief.generate"
    assert entry["options"]["queue"] == "ai"
    # a daily brief is a fixed time of day (crontab), not an "every N seconds" interval — the only
    # entry in this schedule that is not interval-based (Phase 22, Section 8).
    from celery.schedules import crontab

    assert isinstance(entry["schedule"], crontab)


def test_brief_task_skips_when_the_anthropic_api_key_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, db: AsyncEngine
) -> None:
    from cfi.worker import app as worker

    monkeypatch.setattr(
        worker, "settings", worker.settings.model_copy(update={"anthropic_api_key": None})
    )
    result = worker.brief_generate_task.run()
    assert result["skipped"] == "Anthropic API key not configured"
    assert "brief_id" in result


def test_alerts_are_evaluated_every_15_minutes_on_the_ingest_queue() -> None:
    from cfi.worker.schedule import alert_entries

    entries = alert_entries()
    assert list(entries) == ["alerts:evaluate"]
    entry = entries["alerts:evaluate"]
    assert entry["task"] == "alerts.evaluate"
    assert entry["schedule"] == 900.0
    assert entry["options"]["queue"] == "ingest"


def test_alerts_evaluate_task_runs_a_full_cycle(
    monkeypatch: pytest.MonkeyPatch, db: AsyncEngine, test_settings: Settings
) -> None:
    """No credential gate (Phase 23 has no AI component at all) — the task runs straight
    through, unlike ``brief_generate_task``/``analyst_analyze_task``.

    The task reads the module-level ``worker.settings`` and the process-wide ``worker._runtime``,
    both of which are built from the runtime configuration at import time. Both are replaced here
    so the cycle runs on the test database and on a Redis database of its own."""
    from cfi.worker import app as worker

    redis_url = isolated_redis_url(test_settings.redis_url.get_secret_value())
    settings = test_settings.model_copy(update={"redis_url": SecretStr(redis_url)})
    isolated = WorkerRuntime(settings)
    monkeypatch.setattr(worker, "settings", settings)
    monkeypatch.setattr(worker, "_runtime", isolated)
    try:
        result = worker.alerts_evaluate_task.run()
    finally:
        isolated.run(isolated.aclose())
        isolated.loop.close()
    assert "created" in result
    assert "comparison_basis" in result


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
            "whale_providers": "coinmetrics,blockchair",
            "derivative_providers": "binance_futures,okx_derivatives,deribit",
            "market_structure_providers": "coingecko",
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
            "coinmetrics",
            "blockchair",
            "binance_futures",
            "okx_derivatives",
            "deribit",
        }
        assert runtime.run(runtime.context()) is ctx  # one context per process
    finally:
        runtime.run(runtime.aclose())
        runtime.loop.close()
    url = make_url(test_settings.database_url.get_secret_value()).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        datasets = {r[0] for r in conn.execute("SELECT dataset_id FROM ops.dataset")}
        links = conn.execute("SELECT count(*) FROM ops.dataset_provider").fetchone()
        labels = conn.execute("SELECT count(*) FROM ref.entity_label").fetchone()
    expected = (
        {d.dataset_id for d in all_datasets()}
        | {d.dataset_id for d in institutional_datasets()}
        | {d.dataset_id for d in whale_datasets()}
        | {d.dataset_id for d in derivative_datasets()}
        | {d.dataset_id for d in market_structure_datasets()}
    )
    # the address labels shipped with the code are imported once at start
    assert labels is not None
    assert labels[0] == len(parse_label_csv(seed_text(SEED_FILES[0])).labels)
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


def test_whale_jobs_are_scheduled_per_asset_and_skip_disabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cfi.worker import app as worker
    from cfi.worker.schedule import whale_entries

    assert "whales.ingest" in worker.app.tasks
    entries = whale_entries(["coinmetrics", "blockchair"])
    assert "whales:coinmetrics:whale.exchange_inflow.btc.1d:BTC" in entries
    assert "whales:blockchair:whale.large_transfer.ethereum:ETH" in entries
    assert all(v["options"]["expires"] == v["schedule"] for v in entries.values())
    # Blockchair work shares one process (its daily request budget), Coin Metrics is light
    assert {v["options"]["queue"] for k, v in entries.items() if ":blockchair:" in k} == {
        "backfill"
    }
    monkeypatch.setattr(
        worker, "settings", worker.settings.model_copy(update={"whale_providers": "coinmetrics"})
    )
    result = worker.whale_ingest_task.run("blockchair", "whale.large_transfer.bitcoin", "BTC")
    assert result == {"skipped": "provider blockchair is disabled"}


def test_derivative_jobs_are_scheduled_per_asset_and_skip_disabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cfi.worker import app as worker
    from cfi.worker.schedule import derivative_entries

    assert "derivatives.ingest" in worker.app.tasks
    entries = derivative_entries(["binance_futures", "okx_derivatives", "deribit"])
    assert "derivatives:binance_futures:deriv.open_interest.btc.1h:BTC" in entries
    assert "derivatives:okx_derivatives:deriv.liquidations.xrp.1h:XRP" in entries
    assert "derivatives:deribit:deriv.option_chain.eth:ETH" in entries
    assert not any(":deribit:" in k and k.endswith((":SOL", ":XRP")) for k in entries)
    assert all(v["options"]["expires"] == v["schedule"] for v in entries.values())
    # the option chain (hundreds of instruments) stays off the minute-bar worker
    assert entries["derivatives:deribit:deriv.option_chain.btc:BTC"]["options"]["queue"] == (
        "backfill"
    )
    monkeypatch.setattr(
        worker, "settings", worker.settings.model_copy(update={"derivative_providers": "deribit"})
    )
    result = worker.derivative_ingest_task.run(
        "okx_derivatives", "deriv.open_interest.btc.1h", "BTC"
    )
    assert result == {"skipped": "provider okx_derivatives is disabled"}
