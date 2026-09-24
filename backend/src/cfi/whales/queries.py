"""Point-in-time read queries for whale data (ADR-0018, R3).

Every query takes both cut-offs explicitly: ``as_of`` on ``available_at`` (what the world could
know) and ``knowledge_time`` on ``ingested_at`` (what this system had stored). Each returns the
latest revision per (series, event time) visible under both.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from cfi.market.queries import MarketQueries

OBS_COLUMNS = (
    "o.event_time, o.value, o.quality_status, o.quality_note, o.revision, o.pit_reliability, "
    "o.available_at, o.available_at_estimated, o.ingested_at, o.source_provider, "
    "o.original_source"
)
TRANSFER_COLUMNS = (
    "x.event_time, x.chain, x.tx_hash, x.output_index, x.block_height, x.sender, x.recipient, "
    "x.value_native, x.value_usd, x.quality_status, x.quality_note, x.revision, "
    "x.pit_reliability, x.available_at, x.available_at_estimated, x.ingested_at, "
    "x.source_provider, x.original_source"
)


class WhaleQueries(MarketQueries):
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
        """Scalar rows in [start, end), latest visible revision each, oldest first."""
        return await self._all(
            f"""
            SELECT DISTINCT ON (s.series_id, o.event_time) s.subject_ref, {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset
               AND o.event_time >= :start AND o.event_time < :end
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY s.series_id, o.event_time, o.revision DESC
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def latest_observation(
        self, dataset_id: str, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any] | None:
        """Newest non-missing row of a dataset (any series) visible under both cut-offs."""
        return await self._one(
            f"""
            SELECT s.subject_ref, {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset AND o.quality_status <> 'missing'
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY o.event_time DESC, o.revision DESC
             LIMIT 1
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            asset=asset,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def latest_observation_for(
        self, dataset_id: str, *, subject_ref: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any] | None:
        """Newest non-missing row of one series (e.g. one address balance)."""
        return await self._one(
            f"""
            SELECT s.subject_ref, {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.subject_ref = :ref AND o.quality_status <> 'missing'
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY o.event_time DESC, o.revision DESC
             LIMIT 1
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            ref=subject_ref,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def transfers(
        self,
        dataset_id: str,
        *,
        asset: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
        min_value: Decimal,
    ) -> list[dict[str, Any]]:
        """Large transfers in [start, end) of at least ``min_value`` (the provider's value filter
        may be approximate, so the exact threshold is applied here), newest first."""
        return await self._all(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (s.series_id) s.subject_ref, {TRANSFER_COLUMNS}
                  FROM obs.large_transfer x
                  JOIN obs.series s USING (series_id)
                 WHERE s.dataset_id = :d AND s.asset = :asset
                   AND x.event_time >= :start AND x.event_time < :end
                   AND x.available_at <= :as_of AND x.ingested_at <= :kt
                 ORDER BY s.series_id, x.revision DESC
            ) latest
             WHERE latest.value_native >= :min
             ORDER BY latest.event_time DESC, latest.tx_hash, latest.output_index
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
            min=min_value,
        )
