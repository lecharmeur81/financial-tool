"""The market-data universe: assets, timeframes and dataset definitions (Phase 5).

Datasets are defined per *quote currency*, because a price in USDT is a different measurement
from a price in USD (DATA_DICTIONARY §1: units are never conflated).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec


@dataclass(frozen=True, slots=True)
class Asset:
    symbol: str  # canonical symbol (DATA_DICTIONARY §1)
    name: str


ASSETS: tuple[Asset, ...] = (
    Asset("BTC", "Bitcoin"),
    Asset("ETH", "Ethereum"),
    Asset("SOL", "Solana"),
    Asset("XRP", "XRP"),
)
ASSET_SYMBOLS: tuple[str, ...] = tuple(a.symbol for a in ASSETS)

TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

# How old the newest *bar open time* may be before a series counts as stale. A bar can only be
# stored after it has closed (+ availability delay), so the newest bar is normally 1-2 periods old.
FRESHNESS: dict[str, timedelta] = {
    "1m": timedelta(minutes=5),
    "5m": timedelta(minutes=15),
    "15m": timedelta(minutes=45),
    "1h": timedelta(hours=3),
    "4h": timedelta(hours=10),
    "1d": timedelta(hours=50),
}

# A closed bar is treated as final this long after its period ends (exchange settlement latency).
BAR_AVAILABILITY_DELAY = timedelta(seconds=60)


def ohlcv_dataset_id(quote: str, timeframe: str) -> str:
    return f"market.ohlcv.{quote}.{timeframe}"


def ohlcv_dataset(quote: str, timeframe: str) -> DatasetSpec:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe {timeframe!r}")
    return DatasetSpec(
        dataset_id=ohlcv_dataset_id(quote, timeframe),
        metric="spot_ohlcv",
        unit=quote,
        period=timeframe,
        availability=AvailabilityRule("period_end_plus", BAR_AVAILABILITY_DELAY),
        freshness_limit=FRESHNESS[timeframe],
        conflict_tolerance=Decimal("0.001"),
        revisable=False,
        expect_continuous=True,
        kind="bar",
        description=(
            f"Spot OHLCV bars quoted in {quote.upper()}, {timeframe}. event_time = bar open. "
            f"Prices in {quote}; volume_base in the base asset; volume_quote in {quote} "
            "when the venue reports it."
        ),
    )


SPOT_PRICE_USD = DatasetSpec(
    dataset_id="market.spot_price.usd",
    metric="spot_price",
    unit="usd",
    period="event",
    availability=AvailabilityRule("provider"),
    freshness_limit=timedelta(minutes=5),
    conflict_tolerance=Decimal("0.005"),
    description="Last traded spot price in USD at the venue (event_time = trade time).",
)

MARKET_CAP_USD = DatasetSpec(
    dataset_id="market.market_cap.usd",
    metric="market_cap",
    unit="usd",
    period="event",
    availability=AvailabilityRule("provider"),
    freshness_limit=timedelta(minutes=30),
    conflict_tolerance=Decimal("0.02"),
    revisable=True,
    description=(
        "Market capitalisation in USD as published by the provider "
        "(event_time = provider's last update time)."
    ),
)

MARKET_CAP_USD_1D = DatasetSpec(
    dataset_id="market.market_cap.usd.1d",
    metric="market_cap",
    unit="usd",
    period="1d",
    availability=AvailabilityRule("event_time_plus", timedelta(minutes=10)),
    freshness_limit=timedelta(hours=50),
    conflict_tolerance=Decimal("0.02"),
    revisable=True,
    expect_continuous=True,
    description=(
        "Daily market capitalisation snapshot in USD at 00:00 UTC, as published by the provider. "
        "History is shown as the provider reports it today (may include later corrections)."
    ),
)


def all_datasets() -> list[DatasetSpec]:
    specs = [ohlcv_dataset(q, tf) for q in ("usd", "usdt") for tf in TIMEFRAMES]
    return [*specs, SPOT_PRICE_USD, MARKET_CAP_USD, MARKET_CAP_USD_1D]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in all_datasets():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)
