"""Liquidity, retail and macro dataset registration in the worker runtime (Phase 43).

Same class of gap Phase 42 closed for market structure: the per-domain ingestion harnesses register
their own datasets by hand, so the production path — ``WorkerRuntime.context()`` — could omit a
group without any test noticing, and every task of that group then crashed on
``obs.series``' ``series_dataset_id_fkey``.

These tests go through the real runtime and the real Celery tasks, never a harness. Only the HTTP
transports are the in-process fakes already used by the per-domain suites (synthetic, deterministic
data, clearly not market data), and the clock is the fakes' fixed ``NOW``. No real provider, secret
or network is involved; the macro key used where a key is needed is a throw-away test value.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace

import httpx2
import psycopg
import pytest
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.liquidity import sources as liquidity_sources
from cfi.macro import sources as macro_sources
from cfi.macro.sources import SOURCES as MACRO_SOURCES
from cfi.macro.universe import DXY_BROAD_PROXY, US_SUBJECT
from cfi.providers import blockchair, coingecko, defillama, fred
from cfi.providers.base import ProviderAdapter
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from cfi.retail import sources as retail_sources
from cfi.retail.universe import SMALL_OUTPUT_COUNT, TRENDING, TRENDING_SUBJECT
from cfi.worker.runtime import WorkerRuntime
from tests.integration.conftest import requires_services
from tests.liquidity_fakes import NOW as LIQUIDITY_NOW
from tests.liquidity_fakes import DefiLlamaFake
from tests.macro_fakes import FredFake
from tests.retail_fakes import BlockchairSmallOutputFake, CoinGeckoTrendingFake
from tests.support import FakeClock, WallClock

pytestmark = [pytest.mark.integration, requires_services]

# The intended sets, written out: adding or removing a dataset in a module must revisit this file.
LIQUIDITY_IDS = {"liquidity.stablecoin_supply.1d"}
RETAIL_IDS = {"retail.trending_coin_rank", "retail.small_output_count.btc.1d"}
MACRO_IDS = {
    "macro.dxy_broad_proxy.1d",
    "macro.ust_yield_2y.1d",
    "macro.ust_yield_10y.1d",
    "macro.fed_funds_effective.1d",
    "macro.vix.1d",
    "macro.sp500.1d",
    "macro.nasdaq_composite.1d",
    "macro.oil_wti.1d",
    "macro.reverse_repo.1d",
    "macro.fed_balance_sheet.1w",
    "macro.treasury_general_account.1w",
    "macro.m2_money_stock.1w",
    "macro.cpi.1mo",
    "macro.pce_price_index.1mo",
    "macro.unemployment_rate.1mo",
    "macro.m2_money_stock.1mo",
    "macro.fed_funds_target_upper.event",
    "macro.fed_funds_target_lower.event",
}
GROUP_IDS = {"liquidity": LIQUIDITY_IDS, "retail": RETAIL_IDS, "macro": MACRO_IDS}
ALL_IDS = LIQUIDITY_IDS | RETAIL_IDS | MACRO_IDS
LINKS = (
    {(i, defillama.PROVIDER_ID) for i in LIQUIDITY_IDS}
    | {("retail.trending_coin_rank", coingecko.PROVIDER_ID)}
    | {("retail.small_output_count.btc.1d", blockchair.PROVIDER_ID)}
    | {(i, fred.PROVIDER_ID) for i in MACRO_IDS}
)
PREFIXES = ("liquidity.%", "retail.%", "macro.%")
FAKE_KEY = "test-key"  # throw-away value for the in-process fake only


def _settings(test_settings: Settings, **groups: str) -> Settings:
    """Explicit provider lists (the tests must not depend on the user's .env); every group not
    named is disabled."""
    base = {
        "market_providers": "coinbase",
        "institutional_providers": "",
        "whale_providers": "",
        "derivative_providers": "",
        "market_structure_providers": "",
        "liquidity_providers": "",
        "retail_providers": "",
        "macro_providers": "",
    }
    base.update({f"{k}_providers": v for k, v in groups.items()})
    return test_settings.model_copy(update=base)


def _connect(settings: Settings) -> psycopg.Connection:
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False))


def _registered(settings: Settings) -> tuple[set[str], set[tuple[str, str]]]:
    with _connect(settings) as conn:
        datasets = {
            r[0]
            for p in PREFIXES
            for r in conn.execute(
                "SELECT dataset_id FROM ops.dataset WHERE dataset_id LIKE %s", (p,)
            )
        }
        links = {
            (r[0], r[1])
            for p in PREFIXES
            for r in conn.execute(
                "SELECT dataset_id, provider_id FROM ops.dataset_provider WHERE dataset_id LIKE %s",
                (p,),
            )
        }
    return datasets, links


def _count(settings: Settings, sql: str, *args: object) -> int:
    with _connect(settings) as conn:
        row = conn.execute(sql, args or None).fetchone()
    assert row is not None
    return int(row[0])


@contextmanager
def _runtime(settings: Settings) -> Iterator[WorkerRuntime]:
    runtime = WorkerRuntime(settings)
    try:
        yield runtime
    finally:
        runtime.run(runtime.aclose())
        runtime.loop.close()


def _client(
    pid: str,
    adapters: Mapping[str, ProviderAdapter],
    transport: httpx2.MockTransport,
    repo: IngestionRepository,
    ticks: FakeClock,
) -> ProviderHttpClient:
    return ProviderHttpClient(
        adapters[pid].capabilities,
        transport=transport,
        retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
        recorder=RepositoryRecorder(repo),
        environ={fred.API_KEY_ENV: FAKE_KEY},
        sleep=ticks.sleep,
        clock=ticks,
    )


# ------------------------------------------------------------------------- the intended sets


def test_the_intended_dataset_sets_are_pinned() -> None:
    from cfi.liquidity.universe import all_datasets as liquidity_datasets
    from cfi.macro.universe import all_datasets as macro_datasets
    from cfi.retail.universe import all_datasets as retail_datasets

    assert {d.dataset_id for d in liquidity_datasets()} == LIQUIDITY_IDS
    assert {d.dataset_id for d in retail_datasets()} == RETAIL_IDS
    assert {d.dataset_id for d in macro_datasets()} == MACRO_IDS
    assert {s.dataset.dataset_id for s in liquidity_sources.SOURCES} == LIQUIDITY_IDS
    assert {s.dataset.dataset_id for s in retail_sources.SOURCES} == RETAIL_IDS
    assert {s.dataset.dataset_id for s in macro_sources.SOURCES} == MACRO_IDS
    assert LIQUIDITY_IDS.isdisjoint(RETAIL_IDS)
    assert MACRO_IDS.isdisjoint(RETAIL_IDS | LIQUIDITY_IDS)


# ------------------------------------------------------------------------- registration


@pytest.fixture
def all_groups_runtime(db: AsyncEngine, test_settings: Settings) -> Iterator[WorkerRuntime]:
    settings = _settings(
        test_settings,
        liquidity="defillama",
        retail="coingecko,blockchair",
        macro="fred",
    )
    with _runtime(settings) as runtime:
        yield runtime


def test_runtime_registers_every_dataset_with_the_right_provider(
    all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    all_groups_runtime.run(all_groups_runtime.context())
    datasets, links = _registered(test_settings)
    assert datasets == ALL_IDS
    assert links == LINKS
    providers = _count(
        test_settings,
        "SELECT count(*) FROM ops.provider WHERE provider_id = ANY(%s)",
        [defillama.PROVIDER_ID, coingecko.PROVIDER_ID, blockchair.PROVIDER_ID, fred.PROVIDER_ID],
    )
    assert providers == 4


def test_every_group_has_a_provider_client_even_without_the_macro_key(
    all_groups_runtime: WorkerRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FRED key is read when a request is made, not when the client is built, so registering
    macro must not require (or read) a key."""
    monkeypatch.delenv(fred.API_KEY_ENV, raising=False)
    ctx = all_groups_runtime.run(all_groups_runtime.context())
    assert {
        defillama.PROVIDER_ID,
        coingecko.PROVIDER_ID,
        blockchair.PROVIDER_ID,
        fred.PROVIDER_ID,
    } <= set(ctx.clients)


@pytest.mark.parametrize("group", ["liquidity", "retail", "macro"])
def test_each_group_registers_only_its_own_datasets(
    group: str, db: AsyncEngine, test_settings: Settings
) -> None:
    providers = {"liquidity": "defillama", "retail": "coingecko,blockchair", "macro": "fred"}
    settings = _settings(test_settings, **{group: providers[group]})
    with _runtime(settings) as rt:
        rt.run(rt.context())
    datasets, _links = _registered(test_settings)
    assert datasets == GROUP_IDS[group]


def test_no_datasets_are_registered_when_the_groups_are_disabled(
    db: AsyncEngine, test_settings: Settings
) -> None:
    with _runtime(_settings(test_settings)) as rt:
        rt.run(rt.context())
    datasets, links = _registered(test_settings)
    assert datasets == set()
    assert links == set()


def test_registration_is_idempotent_across_runtimes(
    all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    all_groups_runtime.run(all_groups_runtime.context())
    with _runtime(all_groups_runtime.settings) as restart:  # a worker restart
        restart.run(restart.context())
    datasets, links = _registered(test_settings)
    assert datasets == ALL_IDS
    assert links == LINKS
    assert _count(
        test_settings, "SELECT count(*) FROM ops.dataset WHERE dataset_id LIKE 'macro.%'"
    ) == len(MACRO_IDS)


# ------------------------------------------------------------------------- ingestion paths


def _arm(
    runtime: WorkerRuntime,
    monkeypatch: pytest.MonkeyPatch,
    fakes: dict[str, tuple[Mapping[str, ProviderAdapter], httpx2.MockTransport]],
) -> None:
    """Build the runtime's context (real registration), then swap in fake-transport clients and the
    fixtures' fixed clock — and point the Celery task module at this runtime and its settings."""
    from cfi.worker import app as worker

    ctx = runtime.run(runtime.context())
    wall = WallClock(LIQUIDITY_NOW)
    ticks = FakeClock()
    ctx.engine.clock = wall
    swapped = {
        pid: _client(pid, adapters, transport, ctx.engine.repo, ticks)
        for pid, (adapters, transport) in fakes.items()
    }
    runtime._context = replace(ctx, clients={**ctx.clients, **swapped}, clock=wall)
    monkeypatch.setattr(worker, "settings", runtime.settings)
    monkeypatch.setattr(worker, "_runtime", runtime)


def test_liquidity_ingest_task_ingests_without_the_foreign_key_failure(
    monkeypatch: pytest.MonkeyPatch, all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    from cfi.worker import app as worker

    fake = DefiLlamaFake()
    _arm(
        all_groups_runtime,
        monkeypatch,
        {defillama.PROVIDER_ID: (liquidity_sources.ADAPTERS, fake.transport())},
    )
    for subject in ("USDT", "USDC", "TOTAL"):
        result = worker.liquidity_ingest_task.run(
            defillama.PROVIDER_ID, "liquidity.stablecoin_supply.1d", subject
        )
        assert result["runs"], result
        assert all(status == "succeeded" for _j, status, _i, _r in result["runs"]), result
    assert (
        _count(test_settings, "SELECT count(*) FROM obs.series WHERE dataset_id LIKE 'liquidity.%'")
        == 3
    )
    assert (
        _count(
            test_settings,
            "SELECT count(*) FROM obs.observation o JOIN obs.series s USING (series_id) "
            "WHERE s.dataset_id LIKE 'liquidity.%'",
        )
        > 0
    )


def test_retail_ingest_tasks_ingest_without_the_foreign_key_failure(
    monkeypatch: pytest.MonkeyPatch, all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    from cfi.worker import app as worker

    trending, small = CoinGeckoTrendingFake(), BlockchairSmallOutputFake()
    _arm(
        all_groups_runtime,
        monkeypatch,
        {
            coingecko.PROVIDER_ID: (retail_sources.ADAPTERS, trending.transport()),
            blockchair.PROVIDER_ID: (retail_sources.ADAPTERS, small.transport()),
        },
    )
    for pid, dataset_id, subject in (
        (coingecko.PROVIDER_ID, TRENDING.dataset_id, TRENDING_SUBJECT),
        (blockchair.PROVIDER_ID, SMALL_OUTPUT_COUNT.dataset_id, "BTC"),
    ):
        result = worker.retail_ingest_task.run(pid, dataset_id, subject)
        assert result["runs"], result
        assert all(status == "succeeded" for _j, status, _i, _r in result["runs"]), result
        assert (
            _count(
                test_settings,
                "SELECT count(*) FROM obs.observation o JOIN obs.series s USING (series_id) "
                "WHERE s.dataset_id = %s",
                dataset_id,
            )
            > 0
        )


def test_macro_ingest_task_skips_cleanly_when_the_fred_key_is_absent(
    monkeypatch: pytest.MonkeyPatch, all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    """The existing provider contract: no key means ``skipped``, never ``failed`` — and nothing is
    fabricated: no job run, no series, no observation."""
    from cfi.worker import app as worker

    monkeypatch.delenv(fred.API_KEY_ENV, raising=False)
    monkeypatch.setattr(worker, "settings", all_groups_runtime.settings)
    monkeypatch.setattr(worker, "_runtime", all_groups_runtime)
    result = worker.macro_ingest_task.run(fred.PROVIDER_ID, DXY_BROAD_PROXY.dataset_id, US_SUBJECT)
    assert result == {"skipped": "provider fred has no API key configured"}
    assert (
        _count(test_settings, "SELECT count(*) FROM ops.job_run WHERE dataset_id LIKE 'macro.%'")
        == 0
    )
    assert (
        _count(test_settings, "SELECT count(*) FROM obs.series WHERE dataset_id LIKE 'macro.%'")
        == 0
    )


def test_macro_ingest_task_ingests_when_a_key_is_configured(
    monkeypatch: pytest.MonkeyPatch, all_groups_runtime: WorkerRuntime, test_settings: Settings
) -> None:
    from cfi.worker import app as worker

    monkeypatch.setenv(fred.API_KEY_ENV, FAKE_KEY)
    fake = FredFake()
    _arm(
        all_groups_runtime,
        monkeypatch,
        {fred.PROVIDER_ID: (macro_sources.ADAPTERS, fake.transport())},
    )
    item = next(s for s in MACRO_SOURCES if s.dataset.dataset_id == DXY_BROAD_PROXY.dataset_id)
    result = worker.macro_ingest_task.run(item.provider_id, item.dataset.dataset_id, item.subject)
    assert result["runs"], result
    assert all(status == "succeeded" for _j, status, _i, _r in result["runs"]), result
    assert (
        _count(
            test_settings,
            "SELECT count(*) FROM obs.observation o JOIN obs.series s USING (series_id) "
            "WHERE s.dataset_id = %s",
            DXY_BROAD_PROXY.dataset_id,
        )
        > 0
    )
    # the other macro datasets were registered but nothing else was ingested
    assert (
        _count(test_settings, "SELECT count(*) FROM obs.series WHERE dataset_id LIKE 'macro.%'")
        == 1
    )


def test_a_disabled_group_task_is_skipped_without_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, db: AsyncEngine, test_settings: Settings
) -> None:
    from cfi.worker import app as worker

    with _runtime(_settings(test_settings)) as runtime:  # all three groups disabled
        monkeypatch.setattr(worker, "settings", runtime.settings)
        monkeypatch.setattr(worker, "_runtime", runtime)
        assert worker.liquidity_ingest_task.run(
            defillama.PROVIDER_ID, "liquidity.stablecoin_supply.1d", "USDT"
        ) == {"skipped": "provider defillama is disabled"}
        assert worker.retail_ingest_task.run(
            coingecko.PROVIDER_ID, TRENDING.dataset_id, TRENDING_SUBJECT
        ) == {"skipped": "provider coingecko is disabled"}
        assert runtime._context is None  # no runtime context was ever built
