"""Which provider supplies which retail dataset, how often, and how far back (Phase 10).

Two providers, both already integrated by earlier phases and extended here with one new endpoint
each (no new provider adapter needed):

- **CoinGecko** (``cfi.providers.coingecko``, Phase 5/6): new ``/search/trending`` endpoint.
  Polled every 3 h — one call returns a live snapshot, not a queryable history, so there is
  nothing to backfill (``history=0``). The scheduled subject is a **sentinel**
  (``TRENDING_SUBJECT``): one response covers a dynamic, not-known-in-advance set of coins, so
  there is no single fixed subject to key staleness/catch-up checks on — both are effectively
  disabled for this source (``max_catch_up=0``), which is correct for a feed with no history to
  catch up on.
- **Blockchair** (``cfi.providers.blockchair``, Phase 7): new ``small_output_count`` daily
  aggregate (Bitcoin only). Scheduled exactly like the other Blockchair daily aggregations
  already running for whale intelligence (``cfi.whales.sources``) — same interval, recency and
  history depth.
"""

from __future__ import annotations

from datetime import timedelta

from cfi.ingestion.scheduled import ScheduledSource
from cfi.providers import blockchair, coingecko
from cfi.providers.base import ProviderAdapter
from cfi.retail.universe import SMALL_OUTPUT_COUNT, TRENDING, TRENDING_SUBJECT

RetailSource = ScheduledSource
DAY = timedelta(days=1)


def _sources() -> tuple[RetailSource, ...]:
    return (
        RetailSource(
            coingecko.PROVIDER_ID,
            TRENDING,
            TRENDING_SUBJECT,
            3 * 3600,
            "ingest",
            recent=timedelta(hours=1),
        ),
        RetailSource(
            blockchair.PROVIDER_ID,
            SMALL_OUTPUT_COUNT,
            "BTC",
            12 * 3600,
            "backfill",
            recent=timedelta(days=10),
            align=DAY,
            history=timedelta(days=120),
            chunk=timedelta(days=30),
        ),
    )


SOURCES: tuple[RetailSource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {
    coingecko.PROVIDER_ID: coingecko.CoinGecko(),
    blockchair.PROVIDER_ID: blockchair.Blockchair(),
}
PRIORITY: dict[str, int] = {coingecko.PROVIDER_ID: 10, blockchair.PROVIDER_ID: 10}
ATTRIBUTION: dict[str, dict[str, str]] = {
    coingecko.PROVIDER_ID: coingecko.ATTRIBUTION,
    blockchair.PROVIDER_ID: blockchair.ATTRIBUTION,
}


def sources_for(provider_ids: list[str]) -> list[RetailSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown retail provider(s) {', '.join(unknown)} "
            f"(known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> RetailSource:
    for item in SOURCES:
        if (item.provider_id, item.dataset.dataset_id, item.subject) == (
            provider_id,
            dataset_id,
            subject,
        ):
            return item
    raise KeyError((provider_id, dataset_id, subject))
