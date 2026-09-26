"""Retail ingestion jobs: the shared scheduled-source runner (``cfi.ingestion.scheduled``) with
the retail adapters — the recent window, then one history chunk per run while history is
incomplete (only the small-output-count source backfills; trending has no history to catch up
on, see ``retail/sources.py``)."""

from __future__ import annotations

from cfi.ingestion.engine import IngestionResult
from cfi.ingestion.scheduled import ScheduledSource, ingest_scheduled
from cfi.market.jobs import JobContext
from cfi.retail.sources import ADAPTERS


async def ingest_source(ctx: JobContext, item: ScheduledSource) -> list[IngestionResult]:
    return await ingest_scheduled(ctx, item, ADAPTERS)
