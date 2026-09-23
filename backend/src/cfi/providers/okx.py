"""OKX public market data (no authentication).

Verified 2026-09-23 against the official documentation (https://www.okx.com/docs-v5/en/):
- REST base URL ``https://openapi.okx.com`` (the docs name regional domains for US/AU and EU
  accounts; public market data here uses the global domain);
- ``GET /api/v5/market/candles`` (the latest 1,440 bars) and ``GET /api/v5/market/history-candles``
  (older bars), both with ``instId``, ``bar``, ``after`` (records *earlier* than a timestamp),
  ``before`` and ``limit`` (maximum 100); rate limit 20 requests per 2 seconds;
- ``bar`` values include 1m, 5m, 15m, 1H and — aligned to UTC — ``4Hutc`` and ``1Dutc`` (plain
  4H/1D bars follow Hong Kong time, so they are *not* used);
- response ``{"code": "0", "msg": "", "data": [[ts, o, h, l, c, vol, volCcy, volCcyQuote,
  confirm], …]}``, newest first; ``ts`` in epoch milliseconds; ``confirm`` "0" = bar not completed;
  ``vol`` in the base currency, ``volCcyQuote`` in the quote currency.

Spot pairs used here are quoted in **USDT** (unit ``usdt``). Access: OKX has been blocked by
Philippine ISPs since August 2025; failures are recorded and shown in provider health.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from cfi.core.errors import (
    DataValidationError,
    NotYetFinalError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
)
from cfi.core.time import from_epoch, parse_period, utc_now
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

PROVIDER_ID = "okx"
VENUE = "okx"
QUOTE = "usdt"
INSTRUMENTS: dict[str, str] = {
    "BTC": "BTC-USDT",
    "ETH": "ETH-USDT",
    "SOL": "SOL-USDT",
    "XRP": "XRP-USDT",
}
BARS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4Hutc",
    "1d": "1Dutc",
}
PAGE_LIMIT = 100
RECENT_BARS = 1440  # /market/candles serves at most the latest 1,440 bars
CANDLES_PATH = "/api/v5/market/candles"
HISTORY_PATH = "/api/v5/market/history-candles"

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="OKX",
    base_url="https://openapi.okx.com",
    datasets=frozenset(ohlcv_dataset_id(QUOTE, tf) for tf in BARS),
    rate_limit=RateLimitSpec(5, 1.0),
    timeout_seconds=10.0,
    max_pages=5000,
    original_source="okx",
    terms_verified=False,
    notes=(
        "Public market data, no key. Pairs are quoted in USDT (unit 'usdt'). 4h/1d use the UTC "
        "variants (4Hutc/1Dutc). May be unreachable from the Philippines (ISP blocking since "
        "August 2025). Terms of use not yet reviewed by the user."
    ),
)


def instrument_ref(inst_id: str) -> str:
    return f"{VENUE}:spot:{inst_id}"


def _asset_for(inst_id: str) -> str:
    for asset, known in INSTRUMENTS.items():
        if known == inst_id:
            return asset
    raise DataValidationError(f"unknown OKX instrument {inst_id!r}")


def _timeframe_for(bar: str) -> str:
    for tf, known in BARS.items():
        if known == bar:
            return tf
    raise DataValidationError(f"unknown OKX bar {bar!r}")


class OkxSpot(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if window.subject is None or window.subject not in INSTRUMENTS:
            raise ProviderNotConfiguredError(
                f"OKX requests need one supported subject {sorted(INSTRUMENTS)}, "
                f"got {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        timeframe = dataset_id.rsplit(".", 1)[-1]
        period = parse_period(timeframe)
        assert period is not None  # noqa: S101 — bar datasets always have a period
        return self._page(
            INSTRUMENTS[window.subject],
            BARS[timeframe],
            period,
            after_ms=int(window.end.timestamp() * 1000),
            start_ms=int(window.start.timestamp() * 1000),
            page=1,
        )

    @staticmethod
    def _page(
        inst_id: str, bar: str, period: timedelta, after_ms: int, start_ms: int, page: int
    ) -> RequestSpec:
        # Recent bars come from /candles; anything older than its 1,440-bar reach from history.
        reach = utc_now() - RECENT_BARS * period
        path = CANDLES_PATH if from_epoch(after_ms, "ms") > reach + period else HISTORY_PATH
        return RequestSpec(
            path,
            params={
                "instId": inst_id,
                "bar": bar,
                "after": str(after_ms),  # records strictly earlier than this time
                "limit": str(PAGE_LIMIT),
            },
            page=page,
            state={"start_ms": str(start_ms)},
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        if not records:
            return None
        oldest = min(int(r.payload["ts"]) for r in records)
        start_ms = int(previous.state["start_ms"])
        if oldest <= start_ms:
            return None
        bar = previous.params["bar"]
        period = parse_period(_timeframe_for(bar))
        assert period is not None  # noqa: S101
        return self._page(
            previous.params["instId"], bar, period, oldest, start_ms, previous.page + 1
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if raw.endpoint not in (CANDLES_PATH, HISTORY_PATH):
            raise schema_error(raw, "unexpected endpoint")
        if not isinstance(data, dict) or "code" not in data or "data" not in data:
            raise schema_error(raw, "expected an object with 'code' and 'data'")
        if data["code"] != "0":
            raise ProviderPermanentError(
                f"OKX error {data['code']}: {data.get('msg', '')}", provider_id=PROVIDER_ID
            )
        if not isinstance(data["data"], list):
            raise schema_error(raw, "'data' must be a list")
        inst_id = raw.request_params.get("instId", "")
        bar = raw.request_params.get("bar", "")
        timeframe = _timeframe_for(bar)
        records = []
        for item in data["data"]:
            if not isinstance(item, list) or len(item) < 9:
                raise schema_error(raw, "each candle must be an array of 9 fields")
            ts, o, h, low, c, vol, _vol_ccy, vol_quote, confirm = item[:9]
            if not isinstance(ts, str) or not ts.isdigit():
                raise schema_error(raw, "candle timestamp must be a string of digits")
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    ohlcv_dataset_id(QUOTE, timeframe),
                    {
                        "instId": inst_id,
                        "timeframe": timeframe,
                        "ts": int(ts),
                        "open": o,
                        "high": h,
                        "low": low,
                        "close": c,
                        "volume": vol,
                        "quote_volume": vol_quote,
                        "confirm": confirm,
                    },
                )
            )
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalBar:
        p = record.payload
        dataset = ctx.dataset
        if p["timeframe"] != dataset.period:
            raise DataValidationError(
                f"bar {p['timeframe']} does not match dataset period {dataset.period}"
            )
        inst_id = str(p["instId"])
        event_time = from_epoch(p["ts"], "ms")
        if p["confirm"] != "1":
            raise NotYetFinalError(f"OKX marks the {dataset.period} bar at {event_time} unfinished")
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        return CanonicalBar(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=_asset_for(inst_id),
            subject_ref=instrument_ref(inst_id),
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
            volume_base=to_decimal(p["volume"], "vol"),
            volume_quote=to_decimal(p["quote_volume"], "volCcyQuote"),
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=("event_time: epoch milliseconds -> UTC",),
        )
