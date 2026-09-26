"""Scheduled sources: "recent window + one history chunk per run" jobs (Phases 7 and 8).

Every run goes through the Phase 4 :class:`IngestionEngine` (job run, request log, raw payloads,
quality findings). A run:

1. re-reads the source's recent window (new values, provider revisions, late data) — after
   downtime it reaches back to the newest stored value, within ``max_catch_up``;
2. then, while the history is not complete, loads **one** older chunk (``ops.backfill_state``
   checkpoint), so a first start spreads the history load over several runs and never exhausts a
   provider's request budget in one go.

With ``align`` set (e.g. one day or one hour), windows end at the start of the current period:
only complete periods are requested.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Table, func, select

from cfi.core.time import floor_to_period
from cfi.db import tables as t
from cfi.domain.datasets import DatasetSpec
from cfi.ingestion.engine import IngestionResult
from cfi.market.jobs import JobContext
from cfi.providers.base import FetchWindow, ProviderAdapter

DAY = timedelta(days=1)
TABLES: dict[str, Table] = {
    "scalar": t.observation,
    "transfer": t.large_transfer,
    "quote": t.derivative_quote,
}


@dataclass(frozen=True, slots=True)
class ScheduledSource:
    provider_id: str
    dataset: DatasetSpec
    subject: str
    interval_seconds: int
    queue: str
    # Each run re-reads this recent window (new values, revisions, late data).
    recent: timedelta
    # Windows end at the start of the current period of this length (complete periods only).
    align: timedelta | None = None
    # History loaded once, one chunk per run, back to this depth (zero: none).
    history: timedelta = timedelta(0)
    chunk: timedelta = timedelta(days=30)
    # After downtime, a run reaches back to the newest stored value, at most this far.
    max_catch_up: timedelta = timedelta(0)

    @property
    def history_days(self) -> int:
        return self.history.days


async def latest_stored(ctx: JobContext, item: ScheduledSource) -> datetime | None:
    """Newest event time with a value for this source (any series of its dataset)."""
    table = TABLES[item.dataset.kind]
    stmt = (
        select(func.max(table.c.event_time))
        .select_from(table.join(t.series, t.series.c.series_id == table.c.series_id))
        .where(
            t.series.c.dataset_id == item.dataset.dataset_id,
            t.series.c.asset == item.subject,
            table.c.source_provider == item.provider_id,
            table.c.quality_status != "missing",
        )
    )
    async with ctx.db.connect() as conn:
        latest: datetime | None = (await conn.execute(stmt)).scalar()
    return latest


def _end(item: ScheduledSource, now: datetime) -> datetime:
    return floor_to_period(now, item.align) if item.align else now


async def recent_window(ctx: JobContext, item: ScheduledSource) -> FetchWindow:
    end = _end(item, ctx.clock())
    start = end - item.recent
    if item.max_catch_up:
        latest = await latest_stored(ctx, item)
        if latest is not None and latest < start:
            start = max(latest, end - item.max_catch_up)
    return FetchWindow(start, end, item.subject)


async def history_step(
    ctx: JobContext, item: ScheduledSource, adapter: ProviderAdapter
) -> IngestionResult | None:
    """Load the next older history chunk; ``None`` when history is complete (or not wanted)."""
    if item.history <= timedelta(0):
        return None
    repo = ctx.engine.repo
    dataset_id, provider = item.dataset.dataset_id, item.provider_id
    state = await repo.backfill_state(dataset_id, provider, item.subject)
    now = ctx.clock()
    if state is None:
        anchor = floor_to_period(now, item.align or DAY)
        state = {
            "covered_from": anchor,
            "covered_to": anchor,
            "target_start": anchor - item.history,
            "complete": False,
            "empty_chunks": 0,
        }
    if state["complete"]:
        return None
    end: datetime = state["covered_from"]
    target: datetime = state["target_start"]
    start = max(target, end - item.chunk)
    result = None
    if start < end:
        result = await ctx.engine.ingest(
            item.dataset,
            adapter,
            ctx.clients[provider],
            FetchWindow(start, end, item.subject),
            job_type="backfill",
        )
        if result.status == "failed":
            return result  # not advanced: the same chunk is retried on the next run
    complete = start <= target
    await repo.save_backfill_state(
        dataset_id,
        provider,
        item.subject,
        covered_from=start,
        covered_to=state["covered_to"],
        target_start=target,
        complete=complete,
        empty_chunks=0,
        note=f"history loaded back to {target.date().isoformat()}" if complete else None,
        now=ctx.clock(),
    )
    return result


async def ingest_scheduled(
    ctx: JobContext, item: ScheduledSource, adapters: Mapping[str, ProviderAdapter]
) -> list[IngestionResult]:
    adapter = adapters[item.provider_id]
    window = await recent_window(ctx, item)
    results = [
        await ctx.engine.ingest(item.dataset, adapter, ctx.clients[item.provider_id], window)
    ]
    step = await history_step(ctx, item, adapter)
    if step is not None:
        results.append(step)
    return results
