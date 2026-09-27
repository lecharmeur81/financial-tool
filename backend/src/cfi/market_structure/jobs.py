"""Market-structure ingestion jobs: the shared scheduled-source runner
(``cfi.ingestion.scheduled``) with the market-structure adapter (CoinGecko's ``/global``
extension) — the recent window only (no history to catch up on, see
``market_structure/sources.py``)."""

from __future__ import annotations

from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.market.jobs import JobContext
from cfi.market_structure.sources import ADAPTERS


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
