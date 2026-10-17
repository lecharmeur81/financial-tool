"""Per-process worker runtime.

Each Celery worker process keeps one event loop, one database engine and one HTTP client per
provider for its whole life, so rate limiters and circuit breakers remember earlier calls
(they are per process — ADR-0046; a shared Redis limiter comes when several processes need it).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.cache.redis import create_redis
from cfi.core.config import Settings
from cfi.core.logging import get_logger
from cfi.db.engine import create_engine
from cfi.derivatives import sources as derivatives
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.institutional import sources as institutional
from cfi.liquidity import sources as liquidity
from cfi.macro import sources as macro
from cfi.market.jobs import JobContext
from cfi.market.sources import ADAPTERS, PRIORITY, datasets_for
from cfi.market_structure import sources as market_structure
from cfi.providers.base import ProviderAdapter
from cfi.providers.http import ProviderHttpClient
from cfi.retail import sources as retail
from cfi.whales import sources as whales
from cfi.whales.label_store import import_seed_files

log = get_logger(__name__)

# How long ``run_guarded`` waits for an interrupted coroutine to finish its cleanup. Celery's hard
# limit follows the soft limit by 20 s for ``alerts.evaluate``, so cleanup must be shorter.
DRAIN_TIMEOUT_SECONDS = 10.0


class WorkerRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.loop = asyncio.new_event_loop()
        self._context: JobContext | None = None
        self._engine: AsyncEngine | None = None
        self._redis: Redis | None = None

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        return self.loop.run_until_complete(coro)

    def run_guarded[T](
        self, coro: Coroutine[Any, Any, T], *, drain_timeout: float = DRAIN_TIMEOUT_SECONDS
    ) -> T:
        """Like :meth:`run`, but an interruption never leaves the coroutine alive on the loop.

        ``run_until_complete`` does not cancel its task when an exception (Celery's
        ``SoftTimeLimitExceeded``, raised by a signal handler while the loop is idle) leaves it
        from the loop machinery: the coroutine stays suspended on this process-long loop and resumes
        inside the next task, still holding its locks and connections. Here, any such exception
        cancels the task and drives the loop until the task has run its ``finally`` blocks (at most
        ``drain_timeout`` seconds), then the original exception is re-raised unchanged. Nothing is
        suppressed. Used only by tasks that opt in; :meth:`run` is unchanged."""
        task = self.loop.create_task(coro)
        try:
            return self.loop.run_until_complete(task)
        except BaseException:
            if not task.done():
                self._cancel_and_drain(task, drain_timeout)
            raise

    def _cancel_and_drain(self, task: asyncio.Task[Any], drain_timeout: float) -> None:
        task.cancel()
        try:
            done, _pending = self.loop.run_until_complete(
                asyncio.wait({task}, timeout=drain_timeout)
            )
        except BaseException:
            log.error("worker_task_drain_interrupted", exc_info=True)
            raise
        if not done:
            log.error("worker_task_drain_timed_out", drain_timeout_seconds=drain_timeout)
            return
        if task.cancelled():
            log.warning("worker_task_cancelled_after_interrupt")
        elif (error := task.exception()) is not None:
            # Cleanup itself failed; the interrupt that caused it is what the caller must see.
            log.error("worker_task_cleanup_failed", error_type=type(error).__name__)

    def redis(self) -> Redis:
        """One Redis client per process (Phase 35, "Real-Time Intelligence"), the same broker
        connection every worker process already depends on (ADR-0023) — not a second Redis
        dependency, and not reused across worker processes (ADR-0046's own per-process posture,
        same as :meth:`engine`)."""
        if self._redis is None:
            self._redis = create_redis(self.settings)
        return self._redis

    def engine(self) -> AsyncEngine:
        """A bare DB engine, without :meth:`context`'s ingestion-specific adapter/client/dataset
        registration setup — the AI Analyst task (Phase 21) only ever reads through existing
        domain services and writes ``ai.*`` rows; it needs no provider client, no dataset registry
        (R13: no unneeded setup for a task that does not ingest)."""
        if self._engine is None:
            self._engine = create_engine(self.settings)
        return self._engine

    async def context(self) -> JobContext:
        if self._context is None:
            db = create_engine(self.settings)
            repo = IngestionRepository(db)
            engine = IngestionEngine(repo, FileSystemArchive(self.settings.raw_archive_dir))
            clients: dict[str, ProviderHttpClient] = {}

            def client_for(adapter: ProviderAdapter) -> None:
                # one client (rate limiter, circuit breaker) per provider, shared by all its data
                if adapter.provider_id not in clients:
                    clients[adapter.provider_id] = ProviderHttpClient(
                        adapter.capabilities, recorder=RepositoryRecorder(repo)
                    )

            for provider_id in self.settings.market_provider_ids:
                adapter = ADAPTERS[provider_id]
                client_for(adapter)
                for dataset in datasets_for(provider_id):
                    await engine.register(dataset, adapter, PRIORITY[provider_id])
            for item in institutional.sources_for(self.settings.institutional_provider_ids):
                adapter = institutional.ADAPTERS[item.provider_id]
                client_for(adapter)
                await engine.register(
                    item.dataset, adapter, institutional.PRIORITY[item.provider_id]
                )
            for w in whales.sources_for(self.settings.whale_provider_ids):
                adapter = whales.ADAPTERS[w.provider_id]
                client_for(adapter)
                await engine.register(w.dataset, adapter, whales.PRIORITY[w.provider_id])
            for d in derivatives.sources_for(self.settings.derivative_provider_ids):
                adapter = derivatives.ADAPTERS[d.provider_id]
                client_for(adapter)
                await engine.register(d.dataset, adapter, derivatives.PRIORITY[d.provider_id])
            for ms in market_structure.sources_for(self.settings.market_structure_provider_ids):
                adapter = market_structure.ADAPTERS[ms.provider_id]
                client_for(adapter)
                await engine.register(
                    ms.dataset, adapter, market_structure.PRIORITY[ms.provider_id]
                )
            for lq in liquidity.sources_for(self.settings.liquidity_provider_ids):
                adapter = liquidity.ADAPTERS[lq.provider_id]
                client_for(adapter)
                await engine.register(lq.dataset, adapter, liquidity.PRIORITY[lq.provider_id])
            for rt_item in retail.sources_for(self.settings.retail_provider_ids):
                adapter = retail.ADAPTERS[rt_item.provider_id]
                client_for(adapter)
                await engine.register(
                    rt_item.dataset, adapter, retail.PRIORITY[rt_item.provider_id]
                )
            # Registered whether or not the FRED key is set: the key is read only when a request
            # is made, and ``macro.ingest`` skips (never fails) while it is absent.
            for mc in macro.sources_for(self.settings.macro_provider_ids):
                adapter = macro.ADAPTERS[mc.provider_id]
                client_for(adapter)
                await engine.register(mc.dataset, adapter, macro.PRIORITY[mc.provider_id])
            # Address labels shipped with the code (idempotent; stored labels are never changed).
            await import_seed_files(db, engine.clock())
            self._context = JobContext(engine=engine, db=db, clients=clients)
        return self._context

    async def aclose(self) -> None:
        if self._context is not None:
            for client in self._context.clients.values():
                await client.aclose()
            await self._context.db.dispose()
            self._context = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
