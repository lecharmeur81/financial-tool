"""Per-process worker runtime.

Each Celery worker process keeps one event loop, one database engine and one HTTP client per
provider for its whole life, so rate limiters and circuit breakers remember earlier calls
(they are per process — ADR-0046; a shared Redis limiter comes when several processes need it).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from cfi.core.config import Settings
from cfi.db.engine import create_engine
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.market.sources import ADAPTERS, PRIORITY, datasets_for
from cfi.providers.http import ProviderHttpClient


class WorkerRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.loop = asyncio.new_event_loop()
        self._context: JobContext | None = None

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        return self.loop.run_until_complete(coro)

    async def context(self) -> JobContext:
        if self._context is None:
            db = create_engine(self.settings)
            repo = IngestionRepository(db)
            engine = IngestionEngine(repo, FileSystemArchive(self.settings.raw_archive_dir))
            clients = {}
            for provider_id in self.settings.market_provider_ids:
                adapter = ADAPTERS[provider_id]
                clients[provider_id] = ProviderHttpClient(
                    adapter.capabilities, recorder=RepositoryRecorder(repo)
                )
                for dataset in datasets_for(provider_id):
                    await engine.register(dataset, adapter, PRIORITY[provider_id])
            self._context = JobContext(engine=engine, db=db, clients=clients)
        return self._context

    async def aclose(self) -> None:
        if self._context is not None:
            for client in self._context.clients.values():
                await client.aclose()
            await self._context.db.dispose()
            self._context = None
