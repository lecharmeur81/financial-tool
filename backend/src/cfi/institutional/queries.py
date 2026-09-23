"""Point-in-time read queries for institutional flows (ADR-0018, R3).

Two cut-offs (bitemporal model):

- ``as_of`` on ``available_at`` — what the world could know at that time;
- ``knowledge_time`` on ``ingested_at`` — what this system had stored at that time.

Each query returns the latest revision per (series, event time) visible under both cut-offs.
Computation code always passes both explicitly; there is no "latest" default here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from cfi.market.queries import MarketQueries

FLOW_COLUMNS = (
    "f.event_time, f.entity_type, f.evidence_class, f.entity_name, f.flow_usd, f.flow_native, "
    "f.holdings_usd, f.holdings_native, f.cum_flow_usd, f.value_traded_usd, f.premium_discount, "
    "f.unit_cost_usd, f.source_provider, f.original_source, f.available_at, "
    "f.available_at_estimated, f.ingested_at, f.revision, f.pit_reliability, f.quality_status, "
    "f.quality_note, f.transformations"
)


class InstitutionalQueries(MarketQueries):
    async def flows(
        self,
        dataset_id: str,
        *,
        asset: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
        subject_refs: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Latest visible revision per (series, event time) in [start, end), oldest first."""
        subject_filter = "AND s.subject_ref = ANY(:refs)" if subject_refs is not None else ""
        return await self._all(
            f"""
            SELECT DISTINCT ON (s.series_id, f.event_time)
                   s.series_id, s.subject_ref, s.asset, {FLOW_COLUMNS}
              FROM obs.institutional_flow f
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset {subject_filter}
               AND f.event_time >= :start AND f.event_time < :end
               AND f.available_at <= :as_of AND f.ingested_at <= :kt
             ORDER BY s.series_id, f.event_time, f.revision DESC
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
            **({"refs": list(subject_refs)} if subject_refs is not None else {}),
        )

    async def latest_per_series(
        self,
        dataset_id: str,
        *,
        asset: str,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Newest non-missing row per series (e.g. each company's latest reported holdings)."""
        return await self._all(
            f"""
            SELECT DISTINCT ON (s.series_id)
                   s.series_id, s.subject_ref, s.asset, {FLOW_COLUMNS}
              FROM obs.institutional_flow f
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset
               AND f.quality_status <> 'missing'
               AND f.available_at <= :as_of AND f.ingested_at <= :kt
             ORDER BY s.series_id, f.event_time DESC, f.revision DESC
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            asset=asset,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def snapshot_near(
        self,
        dataset_id: str,
        *,
        asset: str,
        at_or_before: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any] | None:
        """The newest non-missing snapshot at or before ``at_or_before`` (visible as of)."""
        return await self._one(
            f"""
            SELECT s.series_id, s.subject_ref, s.asset, {FLOW_COLUMNS}
              FROM obs.institutional_flow f
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset
               AND f.quality_status <> 'missing'
               AND f.event_time <= :t
               AND f.available_at <= :as_of AND f.ingested_at <= :kt
             ORDER BY f.event_time DESC, f.revision DESC
             LIMIT 1
            """,  # noqa: S608 — column list is a constant
            d=dataset_id,
            asset=asset,
            t=at_or_before,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def earliest_event(
        self, dataset_id: str, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> datetime | None:
        """First event time with data — earlier dates are "not loaded", not "missing"."""
        row = await self._one(
            """
            SELECT min(f.event_time) AS t
              FROM obs.institutional_flow f
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset
               AND f.quality_status <> 'missing'
               AND f.available_at <= :as_of AND f.ingested_at <= :kt
            """,
            d=dataset_id,
            asset=asset,
            as_of=as_of,
            kt=knowledge_time,
        )
        return row["t"] if row else None
