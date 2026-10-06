"""Market-structure dataset registration in the worker runtime (Phase 42).

Regression protection for a gap the per-domain ingestion harnesses cannot see: they register their
own datasets by hand (``tests/integration/market_structure_support.py``), so the production path —
``WorkerRuntime.context()`` — could omit the market-structure group without any test noticing. In
the running worker that left ``market_structure.total_market_cap.usd`` out of ``ops.dataset``, and
every ``market_structure.ingest`` task crashed on ``obs.series``' ``series_dataset_id_fkey``.

These tests go through the real runtime and the real Celery task, never through a harness.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.repository import RepositoryRecorder
from cfi.market_structure.sources import ADAPTERS, SOURCES
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD, all_datasets
from cfi.providers import coingecko
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from cfi.worker.runtime import WorkerRuntime
from tests.integration.conftest import requires_services
from tests.market_structure_fakes import CoinGeckoGlobalFake, total_market_cap_at
from tests.support import FakeClock

pytestmark = [pytest.mark.integration, requires_services]

EXPECTED_DATASET_IDS = {"market_structure.total_market_cap.usd"}


def _connect(settings: Settings) -> psycopg.Connection:
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False))


def _runtime(settings: Settings) -> Iterator[WorkerRuntime]:
    runtime = WorkerRuntime(settings)
    try:
        yield runtime
    finally:
        runtime.run(runtime.aclose())
        runtime.loop.close()


@pytest.fixture
def runtime(db: AsyncEngine, test_settings: Settings) -> Iterator[WorkerRuntime]:
    # explicit provider lists: the test must not depend on the user's .env choices
    settings = test_settings.model_copy(
        update={
            "market_providers": "coinbase,kraken,coingecko",
            "institutional_providers": "",
            "whale_providers": "",
            "derivative_providers": "",
            "market_structure_providers": "coingecko",
        }
    )
    yield from _runtime(settings)


def test_the_intended_market_structure_dataset_set_is_pinned() -> None:
    """Fails loudly if a dataset is added to or removed from the module without the registration
    and this expectation being revisited."""
    assert {d.dataset_id for d in all_datasets()} == EXPECTED_DATASET_IDS
    assert {s.dataset.dataset_id for s in SOURCES} == EXPECTED_DATASET_IDS
    assert all(d.dataset_id.startswith("market_structure.") for d in all_datasets())


def test_runtime_registers_the_market_structure_datasets(
    runtime: WorkerRuntime, test_settings: Settings
) -> None:
    runtime.run(runtime.context())
    with _connect(test_settings) as conn:
        datasets = {
            r[0]
            for r in conn.execute(
                "SELECT dataset_id FROM ops.dataset WHERE dataset_id LIKE 'market_structure.%'"
            )
        }
        links = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT dataset_id, provider_id FROM ops.dataset_provider "
                "WHERE dataset_id LIKE 'market_structure.%'"
            )
        }
    assert datasets == EXPECTED_DATASET_IDS
    assert links == {(d, coingecko.PROVIDER_ID) for d in EXPECTED_DATASET_IDS}


def test_registration_is_idempotent_across_runtimes(
    runtime: WorkerRuntime, test_settings: Settings
) -> None:
    runtime.run(runtime.context())
    second = WorkerRuntime(runtime.settings)  # a worker restart
    try:
        second.run(second.context())
    finally:
        second.run(second.aclose())
        second.loop.close()
    with _connect(test_settings) as conn:
        row = conn.execute(
            "SELECT count(*) FROM ops.dataset WHERE dataset_id LIKE 'market_structure.%'"
        ).fetchone()
    assert row is not None
    assert row[0] == len(EXPECTED_DATASET_IDS)


def test_no_market_structure_datasets_when_the_group_is_disabled(
    db: AsyncEngine, test_settings: Settings
) -> None:
    settings = test_settings.model_copy(
        update={
            "market_providers": "coinbase",
            "institutional_providers": "",
            "whale_providers": "",
            "derivative_providers": "",
            "market_structure_providers": "",
        }
    )
    for rt in _runtime(settings):
        rt.run(rt.context())
    with _connect(test_settings) as conn:
        row = conn.execute(
            "SELECT count(*) FROM ops.dataset WHERE dataset_id LIKE 'market_structure.%'"
        ).fetchone()
    assert row is not None
    assert row[0] == 0


def test_the_provider_client_exists_even_when_the_provider_is_not_a_market_provider(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """``ingest_scheduled`` looks the client up by provider id, so a deployment that enables
    market-structure ingestion without CoinGecko market data must still get a client."""
    settings = test_settings.model_copy(
        update={
            "market_providers": "coinbase",
            "institutional_providers": "",
            "whale_providers": "",
            "derivative_providers": "",
            "market_structure_providers": "coingecko",
        }
    )
    for rt in _runtime(settings):
        ctx = rt.run(rt.context())
        assert coingecko.PROVIDER_ID in ctx.clients


def test_market_structure_ingest_task_ingests_without_the_foreign_key_failure(
    monkeypatch: pytest.MonkeyPatch, runtime: WorkerRuntime, test_settings: Settings
) -> None:
    """The production path end to end: the real Celery task, the real runtime registration, the
    real adapter and engine — only the HTTP transport is the in-process fake. Before the fix this
    raised ``IntegrityError`` on ``series_dataset_id_fkey`` and stored nothing."""
    from cfi.worker import app as worker

    ctx = runtime.run(runtime.context())
    ticks = FakeClock()
    fake = CoinGeckoGlobalFake(lambda: datetime.now(UTC))
    ctx.clients[coingecko.PROVIDER_ID] = ProviderHttpClient(
        ADAPTERS[coingecko.PROVIDER_ID].capabilities,
        transport=fake.transport(),
        retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
        recorder=RepositoryRecorder(ctx.engine.repo),
        environ={},
        sleep=ticks.sleep,
        clock=ticks,
    )
    monkeypatch.setattr(worker, "settings", runtime.settings)
    monkeypatch.setattr(worker, "_runtime", runtime)

    result = worker.market_structure_ingest_task.run(
        coingecko.PROVIDER_ID, TOTAL_MARKET_CAP_USD.dataset_id, GLOBAL_SUBJECT
    )

    assert result["runs"], result
    assert all(status == "succeeded" for _job, status, _ins, _rev in result["runs"])
    assert sum(inserted for _job, _status, inserted, _rev in result["runs"]) == 1
    assert len(fake.requests) == 1
    with _connect(test_settings) as conn:
        series = conn.execute(
            "SELECT asset, subject_ref FROM obs.series WHERE dataset_id = %s",
            (TOTAL_MARKET_CAP_USD.dataset_id,),
        ).fetchall()
        values = conn.execute(
            "SELECT o.event_time, o.value FROM obs.observation o "
            "JOIN obs.series s USING (series_id) WHERE s.dataset_id = %s",
            (TOTAL_MARKET_CAP_USD.dataset_id,),
        ).fetchall()
    assert series == [(GLOBAL_SUBJECT, GLOBAL_SUBJECT)]
    assert len(values) == 1
    event_time, value = values[0]
    assert value == total_market_cap_at(event_time)
