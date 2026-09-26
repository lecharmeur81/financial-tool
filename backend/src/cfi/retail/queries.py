"""Point-in-time read queries for retail activity data (ADR-0018, R3).

Every query takes both cut-offs explicitly: ``as_of`` on ``available_at`` (what the world could
know) and ``knowledge_time`` on ``ingested_at`` (what this system had stored). Each returns the
latest revision per event time visible under both.

Two of these methods read datasets **owned by the derivatives module** (``deriv.funding_rate``,
``deriv.long_short_account_ratio.1h``), already ingested by Phase 8 — no new ingestion, a pure
read. This is a deliberate cross-module read, not a layering violation (R2's layer rule restricts
which *layers* a module reads — Observed Data is Observed Data regardless of which module's
ingestion job wrote it; every module already reads from the shared ``obs.observation`` table).
Explicitly filtered to venue ``"binance"``: Binance and OKX both publish an account-ratio for
different account populations and the two are never combined (see
``cfi.derivatives.universe.LONG_SHORT_RATIO``'s docstring) — only Binance's is used here, matching
the proxy described in ``retail/universe.py``.
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
DERIVATIVES_VENUE = "binance"


class RetailQueries(MarketQueries):
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
        """One subject's rows of a retail-owned dataset (small-output-count), latest revision
        each, oldest first."""
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

    async def trending_observations(
        self,
        *,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Every trending-coin row (any asset — the set is dynamic, not pre-registered), latest
        revision each, oldest first. dataset_id is ``retail.trending_coin_rank`` (fixed here, not
        parameterised, since this is the only dataset this shape applies to)."""
        return await self._all(
            """
            SELECT DISTINCT ON (s.asset, o.event_time)
                   s.asset, s.subject_ref, o.event_time, o.value, o.quality_status,
                   o.revision, o.available_at, o.ingested_at
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = 'retail.trending_coin_rank'
               AND o.event_time >= :start AND o.event_time < :end
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY s.asset, o.event_time, o.revision DESC
            """,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )

    async def derivatives_observations(
        self,
        dataset_id: str,
        *,
        asset: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> list[dict[str, Any]]:
        """Binance-only rows of a derivatives-owned dataset for one perp asset (see module
        docstring for why venue is filtered here)."""
        return await self._all(
            f"""
            SELECT DISTINCT ON (o.event_time) {OBS_COLUMNS}
              FROM obs.observation o
              JOIN obs.series s USING (series_id)
             WHERE s.dataset_id = :d AND s.asset = :asset AND s.venue = :venue
               AND o.event_time >= :start AND o.event_time < :end
               AND o.available_at <= :as_of AND o.ingested_at <= :kt
             ORDER BY o.event_time, o.revision DESC
            """,  # noqa: S608 — only constant fragments are interpolated
            d=dataset_id,
            asset=asset,
            venue=DERIVATIVES_VENUE,
            start=start,
            end=end,
            as_of=as_of,
            kt=knowledge_time,
        )
