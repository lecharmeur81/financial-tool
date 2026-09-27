"""Point-in-time read queries for market-structure data (ADR-0018, R3).

Only one dataset is directly ingested by this module (TOTAL market capitalisation,
``cfi.market_structure.universe.TOTAL_MARKET_CAP_USD``) — everything else this module reads is
already-tracked OHLCV bars and per-asset market caps from Phase 5/6, read through the inherited
``MarketQueries`` methods (``series_id``, ``bars``, ``latest_scalars``), never re-ingested. Mirrors
``cfi.macro.queries.MacroQueries`` exactly for the one new dataset, which — like every macro
series — has no venue or per-asset dimension: it is one global reading keyed by the sentinel
``GLOBAL_SUBJECT``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cfi.market.queries import MarketQueries

OBS_COLUMNS = (
    "o.event_time, o.value, o.quality_status, o.quality_note, o.revision, o.pit_reliability, "
    "o.available_at, o.available_at_estimated, o.ingested_at, o.source_provider, "
    "o.original_source"
)


class MarketStructureQueries(MarketQueries):
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
        first."""
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
