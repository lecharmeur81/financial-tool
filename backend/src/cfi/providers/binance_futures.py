"""Binance USDⓈ-M futures public market data — open interest, funding, account ratio (no key).

Verified 2026-09-26 against the official documentation
(https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api). No
live response could be captured from the development environment (Binance answers HTTP 451 to
requests from there); the shapes below are the documented ones:

- base URL ``https://fapi.binance.com``;
- ``GET /futures/data/openInterestHist?symbol=&period=1h&limit=&startTime=&endTime=`` (limit
  ≤ 500; only the latest month is available) → ``[{"symbol", "sumOpenInterest" (base asset),
  "sumOpenInterestValue" (quote asset), "timestamp"}]``, oldest first;
- ``GET /fapi/v1/fundingRate?symbol=&startTime=&endTime=&limit=`` (limit ≤ 1000; shares a limit
  of 500 requests / 5 min / IP) → ``[{"symbol", "fundingRate", "fundingTime", "markPrice"}]``,
  oldest first;
- ``GET /futures/data/globalLongShortAccountRatio?symbol=&period=1h&limit=&startTime=&endTime=``
  (limit ≤ 500; latest month; 1,000 requests / 5 min / IP) → ``[{"symbol", "longShortRatio",
  "longAccount", "shortAccount", "timestamp"}]``, oldest first.

Numbers arrive as decimal strings; times as epoch milliseconds (numbers or strings). Windows are
requested as ``startTime`` … ``endTime`` inclusive; pages continue after the last time received.
Open interest is stored in coins (``sumOpenInterest``); the USDT value is not stored (USD values
are calculated from coins × the Coinbase USD price, ADR-0050).

Access: Binance may be unreachable from some networks (it answered HTTP 451 to the development
environment); failures are recorded and shown in provider health.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError
from cfi.derivatives.records import epoch_ms, ms, on_the_hour, scalar
from cfi.derivatives.universe import PERP_ASSETS, dataset, perp_ref
from cfi.domain.observation import CanonicalObservation
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

PROVIDER_ID = "binance_futures"
VENUE = "binance"
SYMBOLS: dict[str, str] = {a: f"{a}USDT" for a in PERP_ASSETS}
OI_PATH = "/futures/data/openInterestHist"
FUNDING_PATH = "/fapi/v1/fundingRate"
RATIO_PATH = "/futures/data/globalLongShortAccountRatio"
LIMITS: dict[str, int] = {OI_PATH: 500, FUNDING_PATH: 1000, RATIO_PATH: 500}
# dataset metric → (path, field holding the value, time field)
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "open_interest": (OI_PATH, "sumOpenInterest", "timestamp"),
    "funding_rate": (FUNDING_PATH, "fundingRate", "fundingTime"),
    "long_short_account_ratio": (RATIO_PATH, "longShortRatio", "timestamp"),
}
ATTRIBUTION = {
    "text": "Source: Binance USDⓈ-M Futures public market data",
    "url": "https://www.binance.com",
}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Binance USDⓈ-M Futures",
    base_url="https://fapi.binance.com",
    datasets=frozenset(dataset(m, a).dataset_id for m in ENDPOINTS for a in PERP_ASSETS),
    # Documented: 500 funding requests / 5 min, 1,000 statistics requests / 5 min per IP.
    rate_limit=RateLimitSpec(1, 1.0, burst=2),
    max_retry_wait_seconds=60.0,
    timeout_seconds=15.0,
    max_pages=100,
    original_source="binance",
    terms_verified=False,
    notes=(
        "USDT perpetuals BTC, ETH, SOL, XRP: hourly open interest (coins) and all-account "
        "long/short ratio (latest month only), funding rate history. No key. May be "
        "unreachable from some networks (HTTP 451). Terms of use not yet reviewed by the user."
    ),
    gap_note="Binance published no value for this hour",
)


def _metric(dataset_id: str, asset: str | None) -> str:
    for metric in ENDPOINTS:
        if asset in SYMBOLS and dataset(metric, asset).dataset_id == dataset_id:
            return metric
    raise ProviderNotConfiguredError(
        f"Binance futures: {dataset_id!r} is not configured for {asset!r}.",
        provider_id=PROVIDER_ID,
    )


class BinanceFutures(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        metric = _metric(dataset_id, window.subject)
        assert window.subject is not None  # noqa: S101 — checked by _metric
        path = ENDPOINTS[metric][0]
        params = {"symbol": SYMBOLS[window.subject], "limit": str(LIMITS[path])}
        if path != FUNDING_PATH:
            params["period"] = "1h"
        end = window.end - timedelta(milliseconds=1)  # endTime is inclusive
        return RequestSpec(
            path,
            params={**params, "startTime": ms(window.start), "endTime": ms(end)},
            state={"asset": window.subject, "metric": metric, "dataset_id": dataset_id},
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        rows = _rows(raw)
        if len(rows) < LIMITS[previous.path]:
            return None
        time_field = ENDPOINTS[previous.state["metric"]][2]
        try:
            last = max(int(ms(epoch_ms(r.get(time_field), time_field))) for r in rows)
        except DataValidationError as exc:
            raise schema_error(raw, str(exc)) from exc
        if last >= int(previous.params["endTime"]):
            return None
        return RequestSpec(
            previous.path,
            params={**previous.params, "startTime": str(last + 1)},
            page=previous.page + 1,
            state=previous.state,
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise NotImplementedError("Binance futures pages are parsed with their request")

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        metric, asset = spec.state["metric"], spec.state["asset"]
        _, value_field, time_field = ENDPOINTS[metric]
        records = []
        for row in _rows(raw):
            if row.get("symbol") != SYMBOLS[asset]:
                raise schema_error(raw, f"row for symbol {row.get('symbol')!r}, expected {asset}")
            if time_field not in row or value_field not in row:
                raise schema_error(raw, f"row without {time_field!r} or {value_field!r}")
            payload: dict[str, Any] = {
                "asset": asset,
                "metric": metric,
                "time": row[time_field],
                "value": row[value_field],
            }
            records.append(ProviderRecord(PROVIDER_ID, spec.state["dataset_id"], payload))
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        p = record.payload
        asset, metric = str(p["asset"]), str(p["metric"])
        time_field = ENDPOINTS[metric][2]
        event_time = epoch_ms(p["time"], time_field)
        if metric != "funding_rate":
            on_the_hour(event_time, time_field)
        value = None if p["value"] in (None, "") else to_decimal(p["value"], metric)
        return scalar(
            ctx,
            provider_id=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            asset=asset,
            subject_ref=perp_ref(asset),
            venue=VENUE,
            event_time=event_time,
            value=value,
        )


def _rows(raw: RawResponse) -> list[dict[str, Any]]:
    body = load_json(raw)
    if not isinstance(body, list) or not all(isinstance(r, dict) for r in body):
        raise schema_error(raw, "expected a list of objects")
    return body
