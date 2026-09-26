"""Point-in-time read queries for derivatives data (ADR-0018, R3).

Every query takes both cut-offs explicitly: ``as_of`` on ``available_at`` (what the world could
know) and ``knowledge_time`` on ``ingested_at`` (what this system had stored). Each returns the
latest revision per (series, event time) visible under both.
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
QUOTE_COLUMNS = (
    "q.event_time, q.instrument, q.instrument_kind, q.expiry, q.strike, q.option_type, "
    "q.mark_price, q.bid_price, q.ask_price, q.mark_iv, q.underlying_price, q.index_price, "
    "q.open_interest_native, q.open_interest_usd, q.volume_native, q.volume_usd, "
    "q.quality_status, q.quality_note, q.revision, q.available_at, q.ingested_at, "
    "q.source_provider"
)


class DerivativesQueries(MarketQueries):
    async def observations(
        self,
        dataset_id: str,
        *,
        asset: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Scalar rows in [start, end) of every series of the dataset for the asset (subject and
        venue included), latest visible revision each, oldest first."""
        return await self._all(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (s.series_id, o.event_time)
                       s.subject_ref, s.venue, {OBS_COLUMNS}
                  FROM obs.observation o
                  JOIN obs.series s USING (series_id)
                 WHERE s.dataset_id = :d AND s.asset = :asset
                   AND o.event_time >= :start AND o.event_time < :end
                   AND o.available_at <= :as_of AND o.ingested_at <= :kt
                 ORDER BY s.series_id, o.event_time, o.revision DESC
            ) latest
             ORDER BY latest.event_time, latest.venue, latest.subject_ref
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def latest_snapshot(
        self, dataset_id: str, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> list[dict[str, Any]]:
        """Every instrument of the newest venue snapshot visible under both cut-offs."""
        snapshot = await self._one(
            """
            SELECT max(q.event_time) AS t
              FROM obs.derivative_quote q
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset
               AND q.available_at <= :as_of AND q.ingested_at <= :kt
            """,
            d=dataset_id,
            asset=asset,
            as_of=as_of,
            kt=knowledge_time,
        )
        if snapshot is None or snapshot["t"] is None:
            return []
        return await self._all(
            f"""
            SELECT DISTINCT ON (s.series_id) s.subject_ref, {QUOTE_COLUMNS}
              FROM obs.derivative_quote q
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset AND q.event_time = :t
               AND q.available_at <= :as_of AND q.ingested_at <= :kt
             ORDER BY s.series_id, q.revision DESC
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            asset=asset,
            t=snapshot["t"],
            as_of=as_of,
            kt=knowledge_time,
        )

    async def hourly_closes(
        self,
        dataset_id: str,
        *,
        subject_ref: str,
        provider_id: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Close of each stored bar in [start, end) (latest visible revision), oldest first."""
        return await self._all(
            """
            SELECT DISTINCT ON (b.event_time) b.event_time, b.close, b.quality_status
              FROM obs.market_bar b
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.subject_ref = :ref AND b.source_provider = :p
               AND b.event_time >= :start AND b.event_time < :end
               AND b.available_at <= :as_of AND b.ingested_at <= :kt
             ORDER BY b.event_time, b.revision DESC
            """,
            d=dataset_id,
            ref=subject_ref,
            p=provider_id,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )
