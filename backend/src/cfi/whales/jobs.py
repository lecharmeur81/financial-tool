"""Whale ingestion jobs: the shared scheduled-source runner (``cfi.ingestion.scheduled``) with the
whale adapters — the recent window, then one history chunk per run while history is incomplete.
Daily datasets ask for complete UTC days only (the current day is not final)."""

from __future__ import annotations

from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.market.jobs import JobContext
from cfi.whales.sources import ADAPTERS


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
