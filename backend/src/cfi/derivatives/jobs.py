"""Derivatives ingestion jobs: the shared scheduled-source runner (``cfi.ingestion.scheduled``)
with the derivatives adapters — the recent window, then one history chunk per run while history
is incomplete. Hourly datasets ask for complete hours only."""

from __future__ import annotations

from cfi.derivatives.sources import ADAPTERS
from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.market.jobs import JobContext


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
