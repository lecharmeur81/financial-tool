"""Deribit public market data — futures curve, option chain and DVOL (no key).

Verified 2026-09-26 against real responses (and the official documentation,
https://docs.deribit.com/):

- base URL ``https://www.deribit.com/api/v2``; responses are JSON-RPC ``{"jsonrpc": "2.0",
  "result": …, "usIn", "usOut", "usDiff", "testnet"}``; ``usOut`` is the server's response time in
  epoch microseconds (used as the snapshot time);
- ``GET /public/get_book_summary_by_currency?currency=BTC&kind=future`` → one row per dated future
  and the perpetual: ``instrument_name`` (``BTC-29SEP26``, ``BTC-PERPETUAL``), ``mark_price``,
  ``bid_price``, ``ask_price`` (USD), ``estimated_delivery_price`` (index, USD),
  ``open_interest`` (USD for inverse futures), ``volume`` (24 h, coins), ``volume_usd``;
- ``… &kind=option`` → one row per option: ``instrument_name`` (``BTC-30OCT26-84000-C``),
  ``mark_price``, ``bid_price``, ``ask_price`` (in BTC), ``mark_iv`` (percent),
  ``underlying_price`` (forward of the expiry, USD), ``estimated_delivery_price`` (index),
  ``open_interest`` and ``volume`` (coins; one contract = one coin), ``volume_usd``;
- ``GET /public/get_volatility_index_data?currency=BTC&resolution=3600&start_timestamp=&
  end_timestamp=`` (milliseconds, both inclusive) → ``result: {"data": [[ts, open, high, low,
  close], …], "continuation"}``; ``continuation`` (when not null) is the ``end_timestamp`` of the
  next, older page.

Instruments expire at 08:00 UTC on the date in their name. Implied volatility and DVOL are
converted from percent to ratios (recorded in ``transformations``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import (
    DataValidationError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
)
from cfi.derivatives.records import PERCENT_TO_RATIO, epoch_ms, epoch_us, ms, scalar
from cfi.derivatives.universe import OPTION_ASSETS, dataset, deribit_ref, dvol_ref
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation, CanonicalQuote, ObservedRecord
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

PROVIDER_ID = "deribit"
VENUE = "deribit"
SUMMARY_PATH = "/public/get_book_summary_by_currency"
DVOL_PATH = "/public/get_volatility_index_data"
KINDS: dict[str, str] = {"futures_curve": "future", "option_chain": "option"}
METRICS = ("futures_curve", "option_chain", "volatility_index")
EXPIRY_HOUR = 8  # Deribit instruments expire at 08:00 UTC
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    )
}
_FUTURE = re.compile(r"^(?P<asset>[A-Z]+)-(?:(?P<date>\d{1,2}[A-Z]{3}\d{2})|PERPETUAL)$")
_OPTION = re.compile(
    r"^(?P<asset>[A-Z]+)-(?P<date>\d{1,2}[A-Z]{3}\d{2})-(?P<strike>\d+(?:d\d+)?)-(?P<type>[CP])$"
)
_DATE = re.compile(r"^(?P<day>\d{1,2})(?P<month>[A-Z]{3})(?P<year>\d{2})$")
ATTRIBUTION = {"text": "Source: Deribit public market data", "url": "https://www.deribit.com"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Deribit",
    base_url="https://www.deribit.com/api/v2",
    datasets=frozenset(dataset(m, a).dataset_id for m in METRICS for a in OPTION_ASSETS),
    rate_limit=RateLimitSpec(5, 1.0, burst=2),
    max_retry_wait_seconds=60.0,
    timeout_seconds=20.0,
    max_pages=100,
    original_source="deribit",
    terms_verified=False,
    notes=(
        "BTC and ETH: futures curve and option chain snapshots (mark, implied volatility, open "
        "interest, 24 h volume), hourly DVOL. No key. Terms of use not yet reviewed by the user."
    ),
    gap_note="Deribit published no DVOL value for this hour",
)


def expiry_of(code: str) -> datetime:
    """``30OCT26`` → 2026-10-30 08:00 UTC."""
    m = _DATE.fullmatch(code)
    if not m or m.group("month") not in MONTHS:
        raise DataValidationError(f"not a Deribit expiry date: {code!r}")
    try:
        return datetime(
            2000 + int(m.group("year")),
            MONTHS[m.group("month")],
            int(m.group("day")),
            EXPIRY_HOUR,
            tzinfo=UTC,
        )
    except ValueError as exc:
        raise DataValidationError(f"not a valid date: {code!r}") from exc


def _metric(dataset_id: str, asset: str | None) -> str:
    for metric in METRICS:
        if asset in OPTION_ASSETS and dataset(metric, asset).dataset_id == dataset_id:
            return metric
    raise ProviderNotConfiguredError(
        f"Deribit: {dataset_id!r} is not configured for {asset!r}.", provider_id=PROVIDER_ID
    )


def _body(raw: RawResponse) -> dict[str, Any]:
    body = load_json(raw)
    if not isinstance(body, dict):
        raise schema_error(raw, "expected a JSON-RPC object")
    if "error" in body:
        error = body["error"] if isinstance(body["error"], dict) else {}
        raise ProviderPermanentError(
            f"Deribit error {error.get('code')}: {error.get('message', '')}",
            provider_id=PROVIDER_ID,
        )
    if "result" not in body:
        raise schema_error(raw, "JSON-RPC object without 'result'")
    return body


def _optional(value: object, field: str) -> Decimal | None:
    return None if value is None else to_decimal(value, field)


class Deribit(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        metric = _metric(dataset_id, window.subject)
        asset = window.subject
        assert asset is not None  # noqa: S101 — checked by _metric
        state = {"asset": asset, "metric": metric, "dataset_id": dataset_id}
        if metric == "volatility_index":
            end = window.end - timedelta(milliseconds=1)  # inclusive
            params = {
                "currency": asset,
                "resolution": "3600",
                "start_timestamp": ms(window.start),
                "end_timestamp": ms(end),
            }
            return RequestSpec(DVOL_PATH, params, state=state)
        # A snapshot of the venue now; the window only says when the job ran.
        return RequestSpec(SUMMARY_PATH, {"currency": asset, "kind": KINDS[metric]}, state=state)

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        if previous.path != DVOL_PATH:
            return None
        result = _body(raw)["result"]
        continuation = result.get("continuation") if isinstance(result, dict) else None
        if continuation is None:
            return None
        if isinstance(continuation, bool) or not isinstance(continuation, int):
            raise schema_error(raw, f"continuation is not an integer: {continuation!r}")
        start, end = int(previous.params["start_timestamp"]), int(previous.params["end_timestamp"])
        if not start <= continuation < end:
            return None
        return RequestSpec(
            DVOL_PATH,
            params={**previous.params, "end_timestamp": str(continuation)},
            page=previous.page + 1,
            state=previous.state,
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise NotImplementedError("Deribit pages are parsed with their request")

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        asset, metric, dataset_id = (
            spec.state["asset"],
            spec.state["metric"],
            spec.state["dataset_id"],
        )
        body = _body(raw)
        result = body["result"]
        if spec.path == DVOL_PATH:
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise schema_error(raw, "result without a 'data' list")
            out = []
            for row in result["data"]:
                if not isinstance(row, list) or len(row) != 5:
                    raise schema_error(raw, "each DVOL row must be [ts, open, high, low, close]")
                payload = {"asset": asset, "metric": metric, "time": row[0], "close": row[4]}
                out.append(ProviderRecord(PROVIDER_ID, dataset_id, payload))
            return out
        if not isinstance(result, list) or not all(isinstance(r, dict) for r in result):
            raise schema_error(raw, "result must be a list of objects")
        if isinstance(body.get("usOut"), bool) or not isinstance(body.get("usOut"), int):
            raise schema_error(raw, "usOut (response time) missing")
        return [
            ProviderRecord(
                PROVIDER_ID,
                dataset_id,
                {"asset": asset, "metric": metric, "us_out": body["usOut"], "row": row},
            )
            for row in result
        ]

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> ObservedRecord:
        p = record.payload
        asset, metric = str(p["asset"]), str(p["metric"])
        if metric == "volatility_index":
            return self._dvol(p, asset, ctx)
        return self._quote(p, asset, metric, ctx)

    @staticmethod
    def _dvol(p: dict[str, Any] | Any, asset: str, ctx: NormaliseContext) -> CanonicalObservation:
        event_time = epoch_ms(p["time"], "ts")
        close = _optional(p["close"], "close")
        return scalar(
            ctx,
            provider_id=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            asset=asset,
            subject_ref=dvol_ref(asset),
            venue=VENUE,
            event_time=event_time,
            value=None if close is None else close / 100,
            transformations=(PERCENT_TO_RATIO, "value: close of the hourly DVOL candle"),
        )

    @staticmethod
    def _quote(
        p: dict[str, Any] | Any, asset: str, metric: str, ctx: NormaliseContext
    ) -> CanonicalQuote:
        spec = ctx.dataset
        row: dict[str, Any] = p["row"]
        name = row.get("instrument_name")
        if not isinstance(name, str):
            raise DataValidationError(f"instrument_name is not a string: {name!r}")
        if row.get("base_currency") != asset:
            raise DataValidationError(f"{name}: base currency {row.get('base_currency')!r}")
        event_time = epoch_us(p["us_out"], "usOut")
        transformations = ["event_time: usOut (epoch microseconds) -> UTC"]
        published = event_time
        if published > ctx.ingested_at:
            published = ctx.ingested_at
            transformations.append("available_at: Deribit clock ahead of ours, set to receipt")
        available_at, estimated = spec.available_at(event_time, published, ctx.ingested_at)
        fields: dict[str, Any] = {}
        if metric == "futures_curve":
            m = _FUTURE.fullmatch(name)
            if not m or m.group("asset") != asset or row.get("quote_currency") != "USD":
                raise DataValidationError(f"not a {asset} inverse future: {name!r}")
            date = m.group("date")
            fields = {
                "instrument_kind": "perpetual" if date is None else "future",
                "expiry": None if date is None else expiry_of(date),
                "open_interest_usd": _optional(row.get("open_interest"), "open_interest"),
                "volume_native": _optional(row.get("volume"), "volume"),
            }
        else:
            m = _OPTION.fullmatch(name)
            if not m or m.group("asset") != asset or row.get("quote_currency") != asset:
                raise DataValidationError(f"not a {asset} option: {name!r}")
            iv = _optional(row.get("mark_iv"), "mark_iv")
            if iv is not None:
                transformations.append("mark_iv: " + PERCENT_TO_RATIO.split(": ", 1)[1])
            fields = {
                "instrument_kind": "option",
                "expiry": expiry_of(m.group("date")),
                "strike": Decimal(m.group("strike").replace("d", ".")),
                "option_type": "call" if m.group("type") == "C" else "put",
                "mark_iv": None if iv is None else iv / 100,
                "underlying_price": _optional(row.get("underlying_price"), "underlying_price"),
                "open_interest_native": _optional(row.get("open_interest"), "open_interest"),
                "volume_native": _optional(row.get("volume"), "volume"),
            }
        mark = _optional(row.get("mark_price"), "mark_price")
        quality = QualityStatus.OK if mark is not None else QualityStatus.MISSING
        return CanonicalQuote(
            dataset_id=spec.dataset_id,
            metric=spec.metric,
            asset=asset,
            subject_ref=deribit_ref(name),
            venue=VENUE,
            period=spec.period,
            unit=spec.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=quality,
            quality_note=None if mark is not None else "Deribit reported no mark price",
            pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations),
            instrument=name,
            mark_price=mark,
            bid_price=_optional(row.get("bid_price"), "bid_price"),
            ask_price=_optional(row.get("ask_price"), "ask_price"),
            index_price=_optional(row.get("estimated_delivery_price"), "estimated_delivery_price"),
            volume_usd=_optional(row.get("volume_usd"), "volume_usd"),
            **fields,
        )
