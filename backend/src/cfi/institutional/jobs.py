"""Institutional ingestion jobs.

Each run goes through the Phase 4 :class:`IngestionEngine` (job run, request log, raw payloads,
quality findings). The provider decides how much history it serves (SoSoValue ETF data: the most
recent month; purchase history: what the provider holds), so every run re-reads the whole
available window: new days are inserted, unchanged days are counted as duplicates, and changed
days become revisions — nothing is overwritten.
"""

from __future__ import annotations

from datetime import timedelta

from cfi.ingestion.engine import IngestionResult
from cfi.institutional.sources import ADAPTERS, InstitutionalSource
from cfi.market.jobs import JobContext
from cfi.providers.base import FetchWindow


async def ingest_source(ctx: JobContext, item: InstitutionalSource) -> list[IngestionResult]:
    adapter = ADAPTERS[item.provider_id]
    client = ctx.clients[item.provider_id]
    now = ctx.clock()
    window_start = now - timedelta(days=item.lookback_days)
    results = []
    for subject in item.subjects:
        window = FetchWindow(window_start, now, subject)
        results.append(await ctx.engine.ingest(item.dataset, adapter, client, window))
    return results
