"""Bybit V5 public market data — spot klines (no authentication).

Verified 2026-09-23 against the official documentation
(https://bybit-exchange.github.io/docs/v5/market/kline):
- base URL ``https://api.bybit.com``; ``GET /v5/market/kline?category=spot&symbol=&interval=
  &start=&end=&limit=`` — ``start``/``end`` in epoch milliseconds, ``limit`` 1-1000 (default 200);
  intervals include ``1``, ``5``, ``15``, ``60``, ``240`` and ``D``;
- response ``{"retCode": 0, "retMsg": "OK", "result": {"category", "symbol", "list": [[startTime,
  openPrice, highPrice, lowPrice, closePrice, volume, turnover], …]}, …}`` — all strings, sorted
  newest first; the current, unclosed candle is included (its close is the last traded price);
  ``volume`` is in the base coin, ``turnover`` in the quote coin.

Spot pairs used here are quoted in **USDT** (unit ``usdt``). Access: Bybit has been blocked by
Philippine ISPs since August 2025; failures are recorded and shown in provider health.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError, ProviderPermanentError
from cfi.core.time import floor_to_period, from_epoch, parse_period
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalBar
from cfi.market.universe import ohlcv_dataset_id
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

PROVIDER_ID = "bybit"
VENUE = "bybit"
QUOTE = "usdt"
SYMBOLS: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"}
INTERVALS: dict[str, str] = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
MAX_KLINES = 1000
KLINE_PATH = "/v5/market/kline"

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Bybit Spot",
    base_url="https://api.bybit.com",
    datasets=frozenset(ohlcv_dataset_id(QUOTE, tf) for tf in INTERVALS),
    rate_limit=RateLimitSpec(5, 1.0),
    timeout_seconds=10.0,
    max_pages=5000,
    original_source="bybit",
    terms_verified=False,
    notes=(
        "Public market data, no key. Pairs are quoted in USDT (unit 'usdt'). May be unreachable "
        "from the Philippines (ISP blocking since August 2025). Terms of use not yet reviewed by "
        "the user."
    ),
)


def instrument_ref(symbol: str) -> str:
    return f"{VENUE}:spot:{symbol.removesuffix('USDT')}-USDT"


def _asset_for(symbol: str) -> str:
    for asset, known in SYMBOLS.items():
        if known == symbol:
            return asset
    raise DataValidationError(f"unknown Bybit symbol {symbol!r}")


def _timeframe_for(interval: str) -> str:
    for tf, known in INTERVALS.items():
        if known == interval:
            return tf
    raise DataValidationError(f"unknown Bybit interval {interval!r}")


class BybitSpot(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if window.subject is None or window.subject not in SYMBOLS:
            raise ProviderNotConfiguredError(
                f"Bybit requests need one supported subject {sorted(SYMBOLS)}, "
                f"got {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        timeframe = dataset_id.rsplit(".", 1)[-1]
        period = parse_period(timeframe)
        assert period is not None  # noqa: S101 — bar datasets always have a period
        start_ms = int(floor_to_period(window.start, period).timestamp() * 1000)
        end_ms = int(window.end.timestamp() * 1000)
        return self._klines(
            SYMBOLS[window.subject], INTERVALS[timeframe], period, start_ms, end_ms, 1
        )

    @staticmethod
    def _klines(
        symbol: str, interval: str, period: timedelta, start_ms: int, window_end_ms: int, page: int
    ) -> RequestSpec:
        period_ms = int(period.total_seconds() * 1000)
        chunk_end = min(window_end_ms, start_ms + MAX_KLINES * period_ms)
        return RequestSpec(
            KLINE_PATH,
            params={
                "category": "spot",
                "symbol": symbol,
                "interval": interval,
                "start": str(start_ms),
                "end": str(chunk_end - 1),  # keep the window half-open
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
        period = parse_period(_timeframe_for(interval))
        assert period is not None  # noqa: S101
        return self._klines(
            previous.params["symbol"], interval, period, chunk_end, window_end, previous.page + 1
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if raw.endpoint != KLINE_PATH:
            raise schema_error(raw, "unexpected endpoint")
        if not isinstance(data, dict) or "retCode" not in data:
            raise schema_error(raw, "expected an object with 'retCode'")
        if data["retCode"] != 0:
            raise ProviderPermanentError(
                f"Bybit error {data['retCode']}: {data.get('retMsg', '')}",
                provider_id=PROVIDER_ID,
            )
        result = data.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("list"), list):
            raise schema_error(raw, "expected 'result.list'")
        symbol = raw.request_params.get("symbol", "")
        timeframe = _timeframe_for(raw.request_params.get("interval", ""))
        records = []
        for item in result["list"]:
            if not isinstance(item, list) or len(item) != 7:
                raise schema_error(raw, "each kline must be an array of 7 fields")
            start, o, h, low, c, vol, turnover = item
            if not isinstance(start, str) or not start.isdigit():
                raise schema_error(raw, "kline startTime must be a string of digits")
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    ohlcv_dataset_id(QUOTE, timeframe),
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "start": int(start),
                        "open": o,
                        "high": h,
                        "low": low,
                        "close": c,
                        "volume": vol,
                        "turnover": turnover,
                    },
                )
            )
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalBar:
        p = record.payload
        dataset = ctx.dataset
        if p["timeframe"] != dataset.period:
            raise DataValidationError(
                f"kline {p['timeframe']} does not match dataset period {dataset.period}"
            )
        symbol = str(p["symbol"])
        event_time = from_epoch(p["start"], "ms")
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
            open=to_decimal(p["open"], "openPrice"),
            high=to_decimal(p["high"], "highPrice"),
            low=to_decimal(p["low"], "lowPrice"),
            close=to_decimal(p["close"], "closePrice"),
            volume_base=to_decimal(p["volume"], "volume"),
            volume_quote=to_decimal(p["turnover"], "turnover"),
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=("event_time: epoch milliseconds -> UTC",),
        )
