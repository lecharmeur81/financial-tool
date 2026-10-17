"""Point-in-time read queries for market data (ADR-0018, R3).

Every query takes ``as_of`` and only sees rows that were both publicly knowable
(``available_at <= as_of``) and already stored (``ingested_at <= as_of``), keeping the latest
revision per point. With ``as_of = now`` this is simply the current view.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.pit_memo import pit_revision_window

BAR_COLUMNS = (
    "event_time, open, high, low, close, volume_base, volume_quote, trade_count, "
    "quality_status, quality_note, revision, available_at, ingested_at, pit_reliability, "
    "transformations"
)


class MarketQueries:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return [dict(r) for r in result.mappings()]

    async def _one(self, sql: str, **params: Any) -> dict[str, Any] | None:
        rows = await self._all(sql, **params)
        return rows[0] if rows else None

    async def series_id(self, dataset_id: str, subject_ref: str) -> int | None:
        row = await self._one(
            "SELECT series_id FROM obs.series WHERE dataset_id = :d AND subject_ref = :s",
            d=dataset_id,
            s=subject_ref,
        )
        return int(row["series_id"]) if row else None

    async def bars(
        self,
        series_id: int,
        provider_id: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        """Latest revision per bar in [start, end), as known at ``as_of``, oldest first. Inside a
        ``pit_read_scope`` this may be served from a revision window (see ``cfi.core.pit_memo``);
        the result is identical to :meth:`_bars_sql`."""
        return await pit_revision_window(
            ("market.bars", series_id, provider_id),
            self.engine,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=as_of,
            load=lambda s, e, cutoff: self._bar_revisions(series_id, provider_id, s, e, cutoff),
            direct=lambda: self._bars_sql(series_id, provider_id, start, end, as_of),
            copy_columns=("transformations",),
        )

    async def _bar_revisions(
        self, series_id: int, provider_id: str, start: datetime, end: datetime, cutoff: datetime
    ) -> list[dict[str, Any]]:
        """Every revision :meth:`_bars_sql` could choose from for any ``as_of <= cutoff`` (same
        series and range predicates; no ``DISTINCT ON``)."""
        return await self._all(
            f"""
            SELECT {BAR_COLUMNS}
              FROM obs.market_bar
             WHERE series_id = :sid AND source_provider = :p
               AND event_time >= :start AND event_time < :end
               AND available_at <= :cutoff AND ingested_at <= :cutoff
             ORDER BY event_time, revision DESC
            """,  # noqa: S608 — column list is a constant
            sid=series_id,
            p=provider_id,
            start=start,
            end=end,
            cutoff=cutoff,
        )

    async def _bars_sql(
        self,
        series_id: int,
        provider_id: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        return await self._all(
            f"""
            SELECT DISTINCT ON (event_time) {BAR_COLUMNS}
              FROM obs.market_bar
             WHERE series_id = :sid AND source_provider = :p
               AND event_time >= :start AND event_time < :end
               AND available_at <= :as_of AND ingested_at <= :as_of
             ORDER BY event_time, revision DESC
            """,  # noqa: S608 — column list is a constant
            sid=series_id,
            p=provider_id,
            start=start,
            end=end,
            as_of=as_of,
        )

    async def rollup(
        self,
        series_id: int,
        provider_id: str,
        bucket: timedelta,
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        """Aggregate stored bars into ``bucket``-sized bars (open=first, high=max, low=min,
        close=last, volumes=sum), counting the component bars and their quality."""
        return await self._all(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (event_time) {BAR_COLUMNS}
                  FROM obs.market_bar
                 WHERE series_id = :sid AND source_provider = :p
                   AND event_time >= :start AND event_time < :end
                   AND available_at <= :as_of AND ingested_at <= :as_of
                 ORDER BY event_time, revision DESC
            )
            SELECT time_bucket(:bucket, event_time) AS event_time,
                   first(open, event_time) FILTER (WHERE close IS NOT NULL) AS open,
                   max(high) AS high,
                   min(low) AS low,
                   last(close, event_time) FILTER (WHERE close IS NOT NULL) AS close,
                   sum(volume_base) AS volume_base,
                   CASE WHEN count(volume_quote) = count(close) THEN sum(volume_quote) END
                       AS volume_quote,
                   CASE WHEN count(trade_count) = count(close) THEN sum(trade_count) END
                       AS trade_count,
                   count(close) AS parts_present,
                   count(*) FILTER (WHERE quality_status IN ('suspect', 'conflicting'))
                       AS parts_flagged,
                   max(revision) AS revision,
                   max(available_at) AS available_at,
                   max(ingested_at) AS ingested_at
              FROM latest
             GROUP BY 1
             ORDER BY 1
            """,  # noqa: S608 — column list is a constant
            sid=series_id,
            p=provider_id,
            bucket=bucket,
            start=start,
            end=end,
            as_of=as_of,
        )

    async def coverage(self, series_id: int, provider_id: str, as_of: datetime) -> dict[str, Any]:
        """Earliest and latest bar holding data, and the newest ingestion time, as of ``as_of``."""
        row = await self._one(
            """
            SELECT min(event_time) FILTER (WHERE close IS NOT NULL) AS earliest,
                   max(event_time) FILTER (WHERE close IS NOT NULL) AS latest,
                   max(ingested_at) AS last_ingested_at
              FROM obs.market_bar
             WHERE series_id = :sid AND source_provider = :p
               AND available_at <= :as_of AND ingested_at <= :as_of
            """,
            sid=series_id,
            p=provider_id,
            as_of=as_of,
        )
        return row or {"earliest": None, "latest": None, "last_ingested_at": None}

    async def last_job(
        self, dataset_id: str, provider_id: str, subject: str | None
    ) -> dict[str, Any] | None:
        return await self._one(
            """
            SELECT job_run_id, job_type, status, started_at, finished_at, error_code, error_detail
              FROM ops.job_run
             WHERE dataset_id = :d AND provider_id = :p
               AND subject IS NOT DISTINCT FROM :s AND job_type = 'ingest'
             ORDER BY started_at DESC, job_run_id DESC
             LIMIT 1
            """,
            d=dataset_id,
            p=provider_id,
            s=subject,
        )

    async def last_successful_job(
        self, dataset_id: str, provider_id: str, subject: str | None
    ) -> datetime | None:
        row = await self._one(
            """
            SELECT max(finished_at) AS t FROM ops.job_run
             WHERE dataset_id = :d AND provider_id = :p
               AND subject IS NOT DISTINCT FROM :s AND status IN ('succeeded', 'partial')
            """,
            d=dataset_id,
            p=provider_id,
            s=subject,
        )
        return row["t"] if row else None

    async def backfill(
        self, dataset_id: str, provider_id: str, subject: str
    ) -> dict[str, Any] | None:
        return await self._one(
            """
            SELECT covered_from, covered_to, target_start, complete, note, updated_at
              FROM ops.backfill_state
             WHERE dataset_id = :d AND provider_id = :p AND subject = :s
            """,
            d=dataset_id,
            p=provider_id,
            s=subject,
        )

    async def latest_scalars(
        self, dataset_id: str, subject_refs: Sequence[str], as_of: datetime
    ) -> dict[str, dict[str, Any]]:
        """Newest non-missing value per subject (latest revision), as of ``as_of``."""
        if not subject_refs:
            return {}
        rows = await self._all(
            """
            SELECT DISTINCT ON (s.subject_ref)
                   s.subject_ref, s.unit, o.event_time, o.value, o.available_at, o.ingested_at,
                   o.source_provider, o.original_source, o.quality_status, o.quality_note,
                   o.revision, o.pit_reliability
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.subject_ref = ANY(:refs)
               AND o.value IS NOT NULL
               AND o.available_at <= :as_of AND o.ingested_at <= :as_of
             ORDER BY s.subject_ref, o.event_time DESC, o.revision DESC
            """,
            d=dataset_id,
            refs=list(subject_refs),
            as_of=as_of,
        )
        return {r["subject_ref"]: r for r in rows}

    async def latest_bars(
        self, dataset_id: str, subject_refs: Sequence[str], as_of: datetime
    ) -> dict[str, dict[str, Any]]:
        """Newest non-missing bar per instrument (latest revision), as of ``as_of``."""
        if not subject_refs:
            return {}
        rows = await self._all(
            """
            SELECT DISTINCT ON (s.subject_ref)
                   s.subject_ref, s.unit, b.event_time, b.close, b.available_at, b.ingested_at,
                   b.source_provider, b.original_source, b.quality_status, b.quality_note
              FROM obs.market_bar b
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.subject_ref = ANY(:refs)
               AND b.close IS NOT NULL
               AND b.available_at <= :as_of AND b.ingested_at <= :as_of
             ORDER BY s.subject_ref, b.event_time DESC, b.revision DESC
            """,
            d=dataset_id,
            refs=list(subject_refs),
            as_of=as_of,
        )
        return {r["subject_ref"]: r for r in rows}
