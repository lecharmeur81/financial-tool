"""Macro ingestion jobs: the shared scheduled-source runner (``cfi.ingestion.scheduled``) with the
FRED adapter — the recent window, then one history chunk per run while history is incomplete."""

from __future__ import annotations

from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.macro.sources import ADAPTERS
from cfi.market.jobs import JobContext


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
