"""Liquidity ingestion jobs: the shared scheduled-source runner (``cfi.ingestion.scheduled``)
with the liquidity adapters — the recent window, then one history chunk per run while history
is incomplete. Daily datasets ask for complete days only."""

from __future__ import annotations

from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.liquidity.sources import ADAPTERS
from cfi.market.jobs import JobContext


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
