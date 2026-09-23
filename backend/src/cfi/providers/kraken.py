"""Kraken public market data — OHLC (no authentication).

Verified 2026-09-23 against the official documentation
(https://docs.kraken.com/api/docs/rest-api/get-ohlc-data):
- ``GET https://api.kraken.com/0/public/OHLC?pair=&interval=&since=`` — ``interval`` in minutes:
  1, 5, 15, 30, 60, 240, 1440, 10080, 21600;
- response ``{"error": [], "result": {"<pair name>": [[time, open, high, low, close, vwap, volume,
  count], …], "last": <id>}}`` — time in epoch seconds, prices/volume as strings, count = number
  of trades;
- "Returns up to 720 of the most recent entries (older data cannot be retrieved, regardless of the
  value of ``since``)"; the last entry is the current, not-yet-committed candle.

**History is therefore limited to the 720 most recent bars per timeframe** (12 hours of 1m bars,
about 2 years of daily bars); backfill records where it stops. Prices are in **USD**. Kraken's
``vwap`` is not stored (no column for it; never used to estimate quote volume).
Access: Kraken has been blocked by Philippine ISPs since August 2025; failures are recorded.
"""

from __future__ import annotations

from collections.abc import Sequence

from cfi.core.errors import (
    DataValidationError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
    ProviderTransientError,
)
from cfi.core.time import from_epoch, parse_period
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

PROVIDER_ID = "kraken"
VENUE = "kraken"
QUOTE = "usd"
# Request with Kraken's alternative pair names; the response is keyed by Kraken's own name, so the
# adapter reads the single pair key it receives rather than assuming one.
PAIRS: dict[str, str] = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD"}
INTERVALS: dict[str, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "1440",
}
MAX_ENTRIES = 720
OHLC_PATH = "/0/public/OHLC"

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Kraken",
    base_url="https://api.kraken.com",
    datasets=frozenset(ohlcv_dataset_id(QUOTE, tf) for tf in INTERVALS),
    rate_limit=RateLimitSpec(1, 1.0),
    timeout_seconds=10.0,
    max_pages=10,
    original_source="kraken",
    terms_verified=False,
    notes=(
        "Public market data, no key. Prices in USD. Only the 720 most recent bars per timeframe "
        "are available. May be unreachable from the Philippines (ISP blocking since August 2025). "
        "Terms of use not yet reviewed by the user."
    ),
)


def instrument_ref(asset: str) -> str:
    return f"{VENUE}:spot:{asset}-USD"


def _timeframe_for(interval: str) -> str:
    for tf, known in INTERVALS.items():
        if known == interval:
            return tf
    raise DataValidationError(f"unknown Kraken interval {interval!r}")


def _asset_for(pair: str) -> str:
    for asset, known in PAIRS.items():
        if known == pair:
            return asset
    raise DataValidationError(f"unknown Kraken pair {pair!r}")


class KrakenSpot(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if window.subject is None or window.subject not in PAIRS:
            raise ProviderNotConfiguredError(
                f"Kraken requests need one supported subject {sorted(PAIRS)}, "
                f"got {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        timeframe = dataset_id.rsplit(".", 1)[-1]
        period = parse_period(timeframe)
        assert period is not None  # noqa: S101 — bar datasets always have a period
        # `since` one period early so the bar opening exactly at window.start is included.
        since = int((window.start - period).timestamp())
        return RequestSpec(
            OHLC_PATH,
            params={
                "pair": PAIRS[window.subject],
                "interval": INTERVALS[timeframe],
                "since": str(since),
            },
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if raw.endpoint != OHLC_PATH:
            raise schema_error(raw, "unexpected endpoint")
        if not isinstance(data, dict) or not isinstance(data.get("error"), list):
            raise schema_error(raw, "expected an object with an 'error' list")
        if data["error"]:
            message = "; ".join(str(e) for e in data["error"])
            error = (
                ProviderTransientError
                if any(str(e).startswith(("EAPI:Rate limit", "EService")) for e in data["error"])
                else ProviderPermanentError
            )
            raise error(f"Kraken error: {message}", provider_id=PROVIDER_ID)
        result = data.get("result")
        if not isinstance(result, dict):
            raise schema_error(raw, "expected 'result'")
        pair_keys = [k for k in result if k != "last"]
        if len(pair_keys) != 1 or not isinstance(result[pair_keys[0]], list):
            raise schema_error(raw, "expected exactly one pair in 'result'")
        pair = raw.request_params.get("pair", "")
        timeframe = _timeframe_for(raw.request_params.get("interval", ""))
        records = []
        for item in result[pair_keys[0]]:
            if not isinstance(item, list) or len(item) != 8:
                raise schema_error(raw, "each OHLC entry must be an array of 8 fields")
            time, o, h, low, c, _vwap, volume, count = item
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    ohlcv_dataset_id(QUOTE, timeframe),
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        "time": time,
                        "open": o,
                        "high": h,
                        "low": low,
                        "close": c,
                        "volume": volume,
                        "count": count,
                    },
                )
            )
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalBar:
        p = record.payload
        dataset = ctx.dataset
        if p["timeframe"] != dataset.period:
            raise DataValidationError(
                f"entry {p['timeframe']} does not match dataset period {dataset.period}"
            )
        if not isinstance(p["time"], int) or not isinstance(p["count"], int):
            raise DataValidationError("OHLC time and count must be integers")
        asset = _asset_for(str(p["pair"]))
        event_time = from_epoch(p["time"], "s")
        # The newest entry is Kraken's uncommitted candle: skipped here as not yet final.
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        return CanonicalBar(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=asset,
            subject_ref=instrument_ref(asset),
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
            trade_count=p["count"],
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=("event_time: epoch seconds -> UTC",),
        )
