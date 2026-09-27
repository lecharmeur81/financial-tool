"""Which provider supplies the one new market-structure dataset, how often, and how far back
(Phase 12).

One provider, already integrated by Phase 5/6 and extended here with one new endpoint (no new
provider adapter needed):

- **CoinGecko** (``cfi.providers.coingecko``): new ``/global`` endpoint for TOTAL market
  capitalisation. Polled every 5 minutes — the same cadence already used for per-asset market caps
  (``cfi.market.universe.MARKET_CAP_USD``, see ``worker/schedule.py``'s ``INTERVAL_SECONDS
  ["market_cap"]``). One call returns a live snapshot, not a queryable history, so there is nothing
  to backfill (``history=0``, mirrors ``cfi.retail.sources``'s ``TRENDING`` source). The scheduled
  subject is a **sentinel** (``GLOBAL_SUBJECT``): a single global reading has no per-asset subject,
  so both staleness catch-up and history depth are effectively disabled for this source
  (``max_catch_up=0``), which is correct for a feed with no history to catch up on.

Everything else this phase calculates (moving averages, RSI, ATR, volatility, volume trend, VWAP,
relative strength, support/resistance, market breadth, BTC/ETH dominance, TOTAL2, TOTAL3, ETH/BTC)
needs no new provider at all — it is a Calculated Metric derived at read time from Phase 5's
already-ingested OHLCV bars and market caps (see ``market_structure/metrics.py``).
"""

from __future__ import annotations

from datetime import timedelta

from cfi.ingestion.scheduled import ScheduledSource
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD
from cfi.providers import coingecko
from cfi.providers.base import ProviderAdapter

MarketStructureSource = ScheduledSource

#: Same cadence as the per-asset market-cap dataset this reuses the provider from.
TOTAL_MARKET_CAP_INTERVAL_SECONDS = 300


def _sources() -> tuple[MarketStructureSource, ...]:
    return (
        MarketStructureSource(
            coingecko.PROVIDER_ID,
            TOTAL_MARKET_CAP_USD,
            GLOBAL_SUBJECT,
            TOTAL_MARKET_CAP_INTERVAL_SECONDS,
            "ingest",
            recent=timedelta(hours=1),
        ),
    )


SOURCES: tuple[MarketStructureSource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {coingecko.PROVIDER_ID: coingecko.CoinGecko()}
PRIORITY: dict[str, int] = {coingecko.PROVIDER_ID: 10}
ATTRIBUTION: dict[str, dict[str, str]] = {coingecko.PROVIDER_ID: coingecko.ATTRIBUTION}


def sources_for(provider_ids: list[str]) -> list[MarketStructureSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown market-structure provider(s) {', '.join(unknown)} "
            f"(known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> MarketStructureSource:
    for item in SOURCES:
        if (item.provider_id, item.dataset.dataset_id, item.subject) == (
            provider_id,
            dataset_id,
            subject,
        ):
            return item
    raise KeyError((provider_id, dataset_id, subject))
