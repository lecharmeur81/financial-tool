"""Which providers supply which market datasets, and how venues are presented.

Only adapters verified against official documentation appear here (Coinbase Exchange, Kraken,
Binance Spot, OKX, Bybit Spot, CoinGecko). Mock providers are never registered in the
application (R3). Each venue is its own series: prices from different venues are never blended.
"""

from __future__ import annotations

from dataclasses import dataclass

from cfi.domain.datasets import DatasetSpec
from cfi.market.universe import (
    MARKET_CAP_USD,
    MARKET_CAP_USD_1D,
    SPOT_PRICE_USD,
    TIMEFRAMES,
    ohlcv_dataset,
)
from cfi.providers import binance, bybit, coinbase, coingecko, kraken, okx
from cfi.providers.base import ProviderAdapter


@dataclass(frozen=True, slots=True)
class Venue:
    """A trading venue whose candles we store. One provider per venue for now."""

    venue_id: str
    display_name: str
    provider_id: str
    quote: str  # unit of prices (usd, usdt)
    instruments: dict[str, str]  # canonical asset -> canonical instrument id
    native_timeframes: tuple[str, ...]
    # timeframe -> (source timeframe, bars per bucket) for timeframes the venue does not publish
    derived_timeframes: dict[str, tuple[str, int]]
    priority: int  # lower = preferred default in the dashboard


VENUES: dict[str, Venue] = {
    "coinbase": Venue(
        venue_id="coinbase",
        display_name="Coinbase Exchange",
        provider_id=coinbase.PROVIDER_ID,
        quote=coinbase.QUOTE,
        instruments={a: coinbase.instrument_ref(p) for a, p in coinbase.PRODUCTS.items()},
        native_timeframes=tuple(coinbase.GRANULARITY),
        derived_timeframes={"4h": ("1h", 4)},
        priority=10,
    ),
    "binance": Venue(
        venue_id="binance",
        display_name="Binance Spot",
        provider_id=binance.PROVIDER_ID,
        quote=binance.QUOTE,
        instruments={a: binance.instrument_ref(s) for a, s in binance.SYMBOLS.items()},
        native_timeframes=tuple(binance.INTERVALS),
        derived_timeframes={},
        priority=20,
    ),
    "kraken": Venue(
        venue_id="kraken",
        display_name="Kraken",
        provider_id=kraken.PROVIDER_ID,
        quote=kraken.QUOTE,
        instruments={a: kraken.instrument_ref(a) for a in kraken.PAIRS},
        native_timeframes=tuple(kraken.INTERVALS),
        derived_timeframes={},
        priority=15,
    ),
    "okx": Venue(
        venue_id="okx",
        display_name="OKX",
        provider_id=okx.PROVIDER_ID,
        quote=okx.QUOTE,
        instruments={a: okx.instrument_ref(i) for a, i in okx.INSTRUMENTS.items()},
        native_timeframes=tuple(okx.BARS),
        derived_timeframes={},
        priority=30,
    ),
    "bybit": Venue(
        venue_id="bybit",
        display_name="Bybit Spot",
        provider_id=bybit.PROVIDER_ID,
        quote=bybit.QUOTE,
        instruments={a: bybit.instrument_ref(s) for a, s in bybit.SYMBOLS.items()},
        native_timeframes=tuple(bybit.INTERVALS),
        derived_timeframes={},
        priority=40,
    ),
}

ADAPTERS: dict[str, ProviderAdapter] = {
    coinbase.PROVIDER_ID: coinbase.CoinbaseExchange(),
    binance.PROVIDER_ID: binance.BinanceSpot(),
    kraken.PROVIDER_ID: kraken.KrakenSpot(),
    okx.PROVIDER_ID: okx.OkxSpot(),
    bybit.PROVIDER_ID: bybit.BybitSpot(),
    coingecko.PROVIDER_ID: coingecko.CoinGecko(),
}

PRIORITY: dict[str, int] = {
    "coinbase": 10,
    "kraken": 15,
    "binance": 20,
    "okx": 30,
    "bybit": 40,
    "coingecko": 10,
}


def datasets_for(provider_id: str) -> list[DatasetSpec]:
    """Every dataset this provider is scheduled to ingest (native data only)."""
    specs: list[DatasetSpec] = []
    for venue in VENUES.values():
        if venue.provider_id == provider_id:
            specs += [
                ohlcv_dataset(venue.quote, tf) for tf in TIMEFRAMES if tf in venue.native_timeframes
            ]
    if provider_id == coinbase.PROVIDER_ID:
        specs.append(SPOT_PRICE_USD)
    if provider_id == coingecko.PROVIDER_ID:
        specs += [MARKET_CAP_USD, MARKET_CAP_USD_1D]
    return specs
