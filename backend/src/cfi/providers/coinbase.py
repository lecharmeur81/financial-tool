"""Coinbase Exchange public market data (no authentication).

Verified 2026-09-23 against the official documentation and a real response:
- docs: https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles
- ``GET /products/{product_id}/candles?granularity=&start=&end=`` — granularity in seconds, one of
  60, 300, 900, 3600, 21600, 86400 (**no 4-hour candles**); at most 300 candles per request;
  each candle is ``[time, low, high, open, close, volume]`` (time = bucket start, epoch seconds;
  newest first). ``end`` is inclusive (observed). The docs state that no candle is published for
  intervals without trades, and that the response may include candles before ``start``.
- ``GET /products/{product_id}/ticker`` — last trade: ``price`` (string), ``time`` (ISO-8601,
  nanosecond precision).
- Public rate limit: 10 requests/second per IP (burst 15). We use 3 per second per process.

Volume is in the base asset. Coinbase does not report quote volume or trade counts in candles, so
those fields are left empty (never estimated).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError
from cfi.core.time import floor_to_period, from_epoch, parse_period, parse_timestamp
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalBar, CanonicalObservation, ObservedRecord
from cfi.market.universe import SPOT_PRICE_USD, ohlcv_dataset_id
from cfi.providers.base import (
    FetchWindow,
    NormaliseContext,
    ProviderAdapter,
    ProviderCapabilities,
    ProviderRecord,
    RateLimitSpec,
    RawResponse,
    RequestSpec,
)
from cfi.providers.payload import load_json, schema_error, to_decimal

PROVIDER_ID = "coinbase"
VENUE = "coinbase"
QUOTE = "usd"
PRODUCTS: dict[str, str] = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD"}
GRANULARITY: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
MAX_CANDLES = 300
_CANDLES_PATH = re.compile(r"^/products/(?P<product>[A-Z0-9]+-[A-Z0-9]+)/candles$")
_TICKER_PATH = re.compile(r"^/products/(?P<product>[A-Z0-9]+-[A-Z0-9]+)/ticker$")
_FRACTION = re.compile(r"\.(\d+)")

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Coinbase Exchange",
    base_url="https://api.exchange.coinbase.com",
    datasets=frozenset(
        [ohlcv_dataset_id(QUOTE, tf) for tf in GRANULARITY] + [SPOT_PRICE_USD.dataset_id]
    ),
    rate_limit=RateLimitSpec(3, 1.0),
    timeout_seconds=10.0,
    max_pages=5000,
    original_source="coinbase_exchange",
    terms_verified=False,
    notes=(
        "Public market data, no key. 4h candles are not offered by Coinbase; the market API "
        "derives them from stored 1h candles and labels them as derived. Terms of use not yet "
        "reviewed by the user."
    ),
    gap_note=(
        "no candle delivered for this interval — Coinbase publishes no candle when there were "
        "no trades, so this may mean zero trading activity rather than a data failure"
    ),
)


def instrument_ref(product: str) -> str:
    return f"{VENUE}:spot:{product}"


def _asset_for(product: str) -> str:
    for asset, known in PRODUCTS.items():
        if known == product:
            return asset
    raise DataValidationError(f"unknown Coinbase product {product!r}")


class CoinbaseExchange(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    # ------------------------------------------------------------------ requests

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if window.subject is None or window.subject not in PRODUCTS:
            raise ProviderNotConfiguredError(
                f"Coinbase requests need one supported subject {sorted(PRODUCTS)}, "
                f"got {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        product = PRODUCTS[window.subject]
        if dataset_id == SPOT_PRICE_USD.dataset_id:
            return RequestSpec(f"/products/{product}/ticker")
        timeframe = dataset_id.rsplit(".", 1)[-1]
        granularity = GRANULARITY[timeframe]
        start = floor_to_period(window.start, timedelta(seconds=granularity))
        return self._candles(product, granularity, start.timestamp(), window.end.timestamp(), 1)

    @staticmethod
    def _candles(
        product: str, granularity: int, start: float, window_end: float, page: int
    ) -> RequestSpec:
        chunk_end = min(window_end, start + MAX_CANDLES * granularity)
        # Coinbase's `end` is inclusive: ask up to the last bucket *starting* before chunk_end.
        last_bucket = max(start, chunk_end - granularity)
        return RequestSpec(
            f"/products/{product}/candles",
            params={
                "granularity": str(granularity),
                "start": from_epoch(int(start), "s").isoformat(),
                "end": from_epoch(int(last_bucket), "s").isoformat(),
            },
            page=page,
            state={"chunk_end": str(int(chunk_end)), "window_end": str(int(window_end))},
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        match = _CANDLES_PATH.match(previous.path)
        if match is None:
            return None  # ticker: single request
        chunk_end = int(previous.state["chunk_end"])
        window_end = int(previous.state["window_end"])
        if chunk_end >= window_end:
            return None
        granularity = int(previous.params["granularity"])
        return self._candles(
            match["product"], granularity, chunk_end, window_end, previous.page + 1
        )

    # ------------------------------------------------------------------ parsing

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        candles = _CANDLES_PATH.match(raw.endpoint)
        if candles is not None:
            return self._parse_candles(raw, data, candles["product"])
        ticker = _TICKER_PATH.match(raw.endpoint)
        if ticker is not None:
            return self._parse_ticker(raw, data, ticker["product"])
        raise schema_error(raw, "unexpected endpoint")

    def _parse_candles(self, raw: RawResponse, data: object, product: str) -> list[ProviderRecord]:
        if not isinstance(data, list):
            raise schema_error(raw, "expected a list of candles")
        granularity = raw.request_params.get("granularity", "")
        dataset_id = ohlcv_dataset_id(
            QUOTE, next((tf for tf, g in GRANULARITY.items() if str(g) == granularity), "?")
        )
        records = []
        for item in data:
            if not isinstance(item, list) or len(item) != 6:
                raise schema_error(
                    raw, "each candle must be [time, low, high, open, close, volume]"
                )
            time, low, high, open_, close, volume = item
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    dataset_id,
                    {
                        "product": product,
                        "granularity": granularity,
                        "time": time,
                        "low": low,
                        "high": high,
                        "open": open_,
                        "close": close,
                        "volume": volume,
                    },
                )
            )
        return records

    def _parse_ticker(self, raw: RawResponse, data: object, product: str) -> list[ProviderRecord]:
        if not isinstance(data, dict) or "price" not in data or "time" not in data:
            raise schema_error(raw, "ticker must contain 'price' and 'time'")
        return [
            ProviderRecord(
                PROVIDER_ID,
                SPOT_PRICE_USD.dataset_id,
                {"product": product, "price": data["price"], "time": data["time"]},
            )
        ]

    # ------------------------------------------------------------------ normalisation

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> ObservedRecord:
        if record.dataset_id == SPOT_PRICE_USD.dataset_id:
            return self._normalise_ticker(record, ctx)
        return self._normalise_candle(record, ctx)

    def _normalise_candle(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalBar:
        p = record.payload
        dataset = ctx.dataset
        period = parse_period(dataset.period)
        if period is None or str(int(period.total_seconds())) != p["granularity"]:
            raise DataValidationError(
                f"candle granularity {p['granularity']} does not match dataset period "
                f"{dataset.period}"
            )
        product = str(p["product"])
        time = p["time"]
        if not isinstance(time, int):
            raise DataValidationError(f"candle time is not an integer epoch: {time!r}")
        event_time = from_epoch(time, "s")
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        return CanonicalBar(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=_asset_for(product),
            subject_ref=instrument_ref(product),
            venue=VENUE,
            period=dataset.period,
            unit=QUOTE,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            open=to_decimal(p["open"], "open"),
            high=to_decimal(p["high"], "high"),
            low=to_decimal(p["low"], "low"),
            close=to_decimal(p["close"], "close"),
            volume_base=to_decimal(p["volume"], "volume"),
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=(
                "event_time: epoch seconds -> UTC",
                "fields reordered from [time, low, high, open, close, volume]",
            ),
        )

    def _normalise_ticker(
        self, record: ProviderRecord, ctx: NormaliseContext
    ) -> CanonicalObservation:
        p = record.payload
        dataset = ctx.dataset
        product = str(p["product"])
        raw_time = str(p["time"])
        event_time = parse_timestamp(raw_time)
        transformations = ["time: ISO-8601 -> UTC"]
        fraction = _FRACTION.search(raw_time)
        if fraction is not None and len(fraction.group(1)) > 6:
            transformations.append("time: sub-microsecond digits truncated to microseconds")
        available_at, estimated = dataset.available_at(event_time, event_time, ctx.ingested_at)
        value = to_decimal(p["price"], "price")
        if value <= 0:
            raise DataValidationError(f"non-positive price {value}")
        return CanonicalObservation(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=_asset_for(product),
            subject_ref=instrument_ref(product),
            venue=VENUE,
            period=dataset.period,
            unit=QUOTE,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=PitReliability.NATIVE,
            transformations=tuple(transformations),
        )
