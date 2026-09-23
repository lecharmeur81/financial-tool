"""Binance Spot public market data via the market-data-only endpoint (no authentication).

Verified 2026-09-23 against the official documentation
(https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md):
- base URL ``https://data-api.binance.vision`` — "for APIs that only send public market data";
- ``GET /api/v3/klines?symbol=&interval=&startTime=&endTime=&limit=`` — weight 2; limit default
  500, max 1000; intervals include 1m, 5m, 15m, 1h, 4h, 1d; "klines are uniquely identified by
  their open time"; each kline is ``[open time (ms), open, high, low, close, volume, close time
  (ms), quote asset volume, number of trades, taker buy base volume, taker buy quote volume,
  unused]`` with prices/volumes as strings;
- HTTP 429 when the rate limit is exceeded and HTTP 418 (automatic IP ban, 2 minutes to 3 days)
  for repeated violations, both with ``Retry-After`` — the shared client never retries early.

Binance spot pairs used here are quoted in **USDT**, so these bars are stored in unit ``usdt`` —
never presented as USD. Access: Binance has been blocked by Philippine ISPs since 2024; if this
provider is unreachable, provider health shows it and it can be disabled in settings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError
from cfi.core.time import floor_to_period, from_epoch, parse_period
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalBar
from cfi.market.universe import TIMEFRAMES, ohlcv_dataset_id
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

PROVIDER_ID = "binance"
VENUE = "binance"
QUOTE = "usdt"
SYMBOLS: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"}
INTERVALS: dict[str, str] = {tf: tf for tf in TIMEFRAMES}  # Binance uses the same notation
MAX_KLINES = 1000
KLINES_PATH = "/api/v3/klines"
_SYMBOL = re.compile(r"^(?P<base>[A-Z0-9]+)USDT$")

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Binance Spot (market data endpoint)",
    base_url="https://data-api.binance.vision",
    datasets=frozenset(ohlcv_dataset_id(QUOTE, tf) for tf in INTERVALS),
    rate_limit=RateLimitSpec(5, 1.0),
    timeout_seconds=10.0,
    max_pages=5000,
    original_source="binance",
    terms_verified=False,
    notes=(
        "Public market data, no key. Pairs are quoted in USDT (stored as unit 'usdt'). May be "
        "unreachable from the Philippines (ISP blocking since 2024). Terms of use not yet reviewed "
        "by the user."
    ),
)


def instrument_ref(symbol: str) -> str:
    match = _SYMBOL.match(symbol)
    if match is None:
        raise DataValidationError(f"unexpected Binance symbol {symbol!r}")
    return f"{VENUE}:spot:{match['base']}-USDT"


def _asset_for(symbol: str) -> str:
    for asset, known in SYMBOLS.items():
        if known == symbol:
            return asset
    raise DataValidationError(f"unknown Binance symbol {symbol!r}")


class BinanceSpot(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if window.subject is None or window.subject not in SYMBOLS:
            raise ProviderNotConfiguredError(
                f"Binance requests need one supported subject {sorted(SYMBOLS)}, "
                f"got {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        interval = dataset_id.rsplit(".", 1)[-1]
        period = parse_period(interval)
        assert period is not None  # noqa: S101 — bar datasets always have a period
        start_ms = int(floor_to_period(window.start, period).timestamp() * 1000)
        end_ms = int(window.end.timestamp() * 1000)
        return self._klines(SYMBOLS[window.subject], interval, period, start_ms, end_ms, 1)

    @staticmethod
    def _klines(
        symbol: str, interval: str, period: timedelta, start_ms: int, window_end_ms: int, page: int
    ) -> RequestSpec:
        period_ms = int(period.total_seconds() * 1000)
        chunk_end = min(window_end_ms, start_ms + MAX_KLINES * period_ms)
        return RequestSpec(
            KLINES_PATH,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": str(start_ms),
                "endTime": str(chunk_end - 1),  # inclusive bound → keep the window half-open
                "limit": str(MAX_KLINES),
            },
            page=page,
            state={"chunk_end": str(chunk_end), "window_end": str(window_end_ms)},
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        chunk_end = int(previous.state["chunk_end"])
        window_end = int(previous.state["window_end"])
        if chunk_end >= window_end:
            return None
        interval = previous.params["interval"]
        period = parse_period(interval)
        assert period is not None  # noqa: S101
        return self._klines(
            previous.params["symbol"], interval, period, chunk_end, window_end, previous.page + 1
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if raw.endpoint != KLINES_PATH:
            raise schema_error(raw, "unexpected endpoint")
        if not isinstance(data, list):
            raise schema_error(raw, "expected a list of klines")
        symbol = raw.request_params.get("symbol", "")
        interval = raw.request_params.get("interval", "")
        records = []
        for item in data:
            if not isinstance(item, list) or len(item) < 11:
                raise schema_error(raw, "each kline must be an array of at least 11 fields")
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    ohlcv_dataset_id(QUOTE, interval),
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "open_time": item[0],
                        "open": item[1],
                        "high": item[2],
                        "low": item[3],
                        "close": item[4],
                        "volume": item[5],
                        "close_time": item[6],
                        "quote_volume": item[7],
                        "trades": item[8],
                    },
                )
            )
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalBar:
        p = record.payload
        dataset = ctx.dataset
        if p["interval"] != dataset.period:
            raise DataValidationError(
                f"kline interval {p['interval']} does not match dataset period {dataset.period}"
            )
        period = parse_period(dataset.period)
        assert period is not None  # noqa: S101
        open_ms, close_ms = p["open_time"], p["close_time"]
        if not isinstance(open_ms, int) or not isinstance(close_ms, int):
            raise DataValidationError("kline open/close time must be integer milliseconds")
        if close_ms != open_ms + int(period.total_seconds() * 1000) - 1:
            raise DataValidationError(
                f"kline close time {close_ms} does not match a {dataset.period} bar opened at "
                f"{open_ms}"
            )
        trades = p["trades"]
        if not isinstance(trades, int):
            raise DataValidationError(f"number of trades is not an integer: {trades!r}")
        symbol = str(p["symbol"])
        event_time = from_epoch(open_ms, "ms")
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        return CanonicalBar(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=_asset_for(symbol),
            subject_ref=instrument_ref(symbol),
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
            volume_quote=to_decimal(p["quote_volume"], "quote_volume"),
            trade_count=trades,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=("event_time: epoch milliseconds -> UTC",),
        )
