"""Point-in-time read queries for macro data (ADR-0018, R3).

Every query takes both cut-offs explicitly: ``as_of`` on ``available_at`` (what the world could
know) and ``knowledge_time`` on ``ingested_at`` (what this system had stored). Each returns the
latest revision per event time visible under both. Every macro series is one nationwide (US)
series (``cfi.macro.universe.US_SUBJECT``) — there is no venue or per-asset dimension to group by,
unlike every other module in this project (mirrors ``cfi.liquidity.queries``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cfi.core.pit_memo import pit_revision_window
from cfi.market.queries import MarketQueries

OBS_COLUMNS = (
    "o.event_time, o.value, o.quality_status, o.quality_note, o.revision, o.pit_reliability, "
    "o.available_at, o.available_at_estimated, o.ingested_at, o.source_provider, "
    "o.original_source"
)


class MacroQueries(MarketQueries):
    async def observations(
        self,
        dataset_id: str,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Scalar rows in [start, end) for one subject, latest visible revision each, oldest
        first. Inside a ``pit_read_scope`` this may be served from a revision window (see
        ``cfi.core.pit_memo``); the result is identical to :meth:`_observations_sql`."""
        return await pit_revision_window(
            ("macro.observations", dataset_id, subject),
            self.engine,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
            load=lambda s, e, cutoff: self._observation_revisions(
                dataset_id, subject, s, e, cutoff
            ),
            direct=lambda: self._observations_sql(
                dataset_id,
                subject=subject,
                start=start,
                end=end,
                as_of=as_of,
                knowledge_time=knowledge_time,
            ),
        )

    async def _observation_revisions(
        self, dataset_id: str, subject: str, start: datetime, end: datetime, cutoff: datetime
    ) -> list[dict[str, Any]]:
        """Every revision :meth:`_observations_sql` could choose from for any request whose
        ``as_of`` and ``knowledge_time`` are both ``<= cutoff`` (same series and range
        predicates; no ``DISTINCT ON``)."""
        return await self._all(
            f"""
            SELECT {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :subject
               AND o.event_time >= :start AND o.event_time < :end
               AND o.available_at <= :cutoff AND o.ingested_at <= :cutoff
             ORDER BY o.event_time, o.revision DESC
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            subject=subject,
            start=start,
            end=end,
            cutoff=cutoff,
        )

    async def _observations_sql(
        self,
        dataset_id: str,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        return await self._all(
            f"""
            SELECT DISTINCT ON (o.event_time) {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :subject
               AND o.event_time >= :start AND o.event_time < :end
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY o.event_time, o.revision DESC
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            subject=subject,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )
