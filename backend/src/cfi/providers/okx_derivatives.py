"""OKX public derivatives data — open interest, funding, account ratio, liquidations (no key).

Verified 2026-09-26 against real responses (and the official documentation,
https://www.okx.com/docs-v5/en/):

- base URL ``https://openapi.okx.com``; every response is ``{"code": "0", "msg": "", "data":
  […]}`` (a non-zero code is an error);
- ``GET /api/v5/rubik/stat/contracts/open-interest-history?instId=BTC-USDT-SWAP&period=1H&
  limit=100&end=`` → ``data: [[ts, oi (contracts), oiCcy (coins), oiUsd], …]`` newest first;
  ``end`` is exclusive (records earlier than it); at least 28 days of hourly history;
- ``GET /api/v5/public/funding-rate-history?instId=&limit=100&after=`` → ``data: [{"fundingRate",
  "fundingTime", "instId", "method", "realizedRate", …}]`` newest first; ``after`` is exclusive;
  about three months of history;
- ``GET /api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H&begin=&end=`` →
  ``data: [[ts, ratio], …]`` newest first, ``begin`` and ``end`` inclusive, at most 500 rows per
  response. The population is every account holding OKX contracts on the coin;
- ``GET /api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP`` → ``ctVal`` (contract
  value, "0.01") and ``ctValCcy`` ("BTC");
- ``GET /api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled&limit=100&
  after=`` → ``data: [{"instId", "details": [{"posSide", "side", "sz" (contracts), "bkPx",
  "ts"}, …]}]``, details newest first, ``after`` exclusive. Only about one day is retained.

Liquidations are stored as hourly totals in coins (Σ ``sz`` × ``ctVal``) for long and short
positions. A long position is liquidated by a sell (``posSide`` "long", or "net" with ``side``
"sell"), a short one by a buy. Every page back to the start of the window is read; an hour is
emitted only when all of its orders were read and it lies within the retention period (older
hours become explicit missing points). Orders sharing the millisecond at a page boundary are
re-read on the next page and counted once.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import (
    DataValidationError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
)
from cfi.derivatives.records import epoch_ms, ms, on_the_hour, scalar
from cfi.derivatives.universe import (
    HOUR,
    PERP_ASSETS,
    contracts_ref,
    dataset,
    liquidation_ref,
    perp_ref,
)
from cfi.domain.enums import QualityStatus
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

PROVIDER_ID = "okx_derivatives"
VENUE = "okx"
SWAPS: dict[str, str] = {a: f"{a}-USDT-SWAP" for a in PERP_ASSETS}
OI_PATH = "/api/v5/rubik/stat/contracts/open-interest-history"
FUNDING_PATH = "/api/v5/public/funding-rate-history"
RATIO_PATH = "/api/v5/rubik/stat/contracts/long-short-account-ratio"
INSTRUMENTS_PATH = "/api/v5/public/instruments"
LIQUIDATIONS_PATH = "/api/v5/public/liquidation-orders"
PAGE_LIMIT = 100
METRICS = ("open_interest", "funding_rate", "long_short_account_ratio", "liquidations")
# Liquidation orders are kept for about one day; hours older than this are not trusted complete.
LIQUIDATION_REACH = timedelta(hours=18)
ATTRIBUTION = {"text": "Source: OKX public market data", "url": "https://www.okx.com"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="OKX derivatives",
    base_url="https://openapi.okx.com",
    datasets=frozenset(dataset(m, a).dataset_id for m in METRICS for a in PERP_ASSETS),
    # Documented limits: 5 requests / 2 s (statistics), 10 / 2 s (funding), 40 / 2 s
    # (liquidations). Paced below the lowest, one at a time.
    rate_limit=RateLimitSpec(2, 1.0, burst=1),
    max_retry_wait_seconds=60.0,
    timeout_seconds=15.0,
    max_pages=500,
    original_source="okx",
    terms_verified=False,
    notes=(
        "USDT perpetuals BTC, ETH, SOL, XRP: hourly open interest (coins), funding rate history, "
        "hourly long/short account ratio (all OKX contracts on the coin), hourly liquidation "
        "totals (about one day retained by OKX). No key. May be unreachable from the Philippines "
        "(ISP blocking since August 2025). Terms of use not yet reviewed by the user."
    ),
    gap_note="OKX published no value for this hour (or its liquidation orders were no longer "
    "retained)",
)


def _metric(dataset_id: str, asset: str | None) -> str:
    for metric in METRICS:
        if asset in SWAPS and dataset(metric, asset).dataset_id == dataset_id:
            return metric
    raise ProviderNotConfiguredError(
        f"OKX derivatives: {dataset_id!r} is not configured for {asset!r}.",
        provider_id=PROVIDER_ID,
    )


def _data(raw: RawResponse) -> list[Any]:
    body = load_json(raw)
    if not isinstance(body, dict) or "code" not in body or "data" not in body:
        raise schema_error(raw, "expected an object with 'code' and 'data'")
    if body["code"] != "0":
        raise ProviderPermanentError(
            f"OKX error {body['code']}: {body.get('msg', '')}", provider_id=PROVIDER_ID
        )
    if not isinstance(body["data"], list):
        raise schema_error(raw, "'data' must be a list")
    return body["data"]


def _ts(raw: RawResponse, value: object, field: str) -> int:
    """Epoch milliseconds of a row (validated), for pagination."""
    try:
        return int(ms(epoch_ms(value, field)))
    except DataValidationError as exc:
        raise schema_error(raw, str(exc)) from exc


def _array_rows(raw: RawResponse, width: int) -> list[list[Any]]:
    rows = _data(raw)
    for row in rows:
        if not isinstance(row, list) or len(row) < width:
            raise schema_error(raw, f"each row must be an array of at least {width} fields")
    return rows


class OkxDerivatives(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    # ------------------------------------------------------------------ requests

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        metric = _metric(dataset_id, window.subject)
        asset = window.subject
        assert asset is not None  # noqa: S101 — checked by _metric
        state = {
            "asset": asset,
            "metric": metric,
            "dataset_id": dataset_id,
            "start_ms": ms(window.start),
            "end_ms": ms(window.end),
        }
        swap = SWAPS[asset]
        if metric == "open_interest":
            params = {"instId": swap, "period": "1H", "limit": str(PAGE_LIMIT)}
            return RequestSpec(OI_PATH, {**params, "end": ms(window.end)}, state=state)
        if metric == "funding_rate":
            params = {"instId": swap, "limit": str(PAGE_LIMIT)}
            return RequestSpec(FUNDING_PATH, {**params, "after": ms(window.end)}, state=state)
        if metric == "long_short_account_ratio":
            end = window.end - timedelta(milliseconds=1)  # inclusive
            params = {"ccy": asset, "period": "1H", "begin": ms(window.start), "end": ms(end)}
            return RequestSpec(RATIO_PATH, params, state=state)
        return RequestSpec(INSTRUMENTS_PATH, {"instType": "SWAP", "instId": swap}, state=state)

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        start_ms = int(previous.state["start_ms"])
        page = previous.page + 1
        if previous.path == OI_PATH:
            rows = _array_rows(raw, 3)
            if len(rows) < PAGE_LIMIT:
                return None
            oldest = min(_ts(raw, r[0], "ts") for r in rows)
            if oldest <= start_ms:
                return None
            params = {**previous.params, "end": str(oldest)}
            return RequestSpec(OI_PATH, params, page=page, state=previous.state)
        if previous.path == FUNDING_PATH:
            events = _data(raw)
            if len(events) < PAGE_LIMIT:
                return None
            if not all(isinstance(e, dict) for e in events):
                raise schema_error(raw, "funding rows must be objects")
            oldest = min(_ts(raw, e.get("fundingTime"), "fundingTime") for e in events)
            if oldest <= start_ms:
                return None
            params = {**previous.params, "after": str(oldest)}
            return RequestSpec(FUNDING_PATH, params, page=page, state=previous.state)
        if previous.path == RATIO_PATH:
            rows = _array_rows(raw, 2)
            if not rows:
                return None
            oldest = min(_ts(raw, r[0], "ts") for r in rows)
            if oldest <= start_ms:
                return None
            params = {**previous.params, "end": str(oldest - 1)}
            return RequestSpec(RATIO_PATH, params, page=page, state=previous.state)
        if previous.path == INSTRUMENTS_PATH:
            state = {**previous.state, "ct_val": str(self._contract_value(raw, previous))}
            return self._liquidation_page(state, after=int(state["end_ms"]), page=page)
        # liquidation pages
        progress = _Liquidations.advance(raw, previous)
        if progress.done:
            return None
        return self._liquidation_page(progress.state, after=progress.boundary + 1, page=page)

    @staticmethod
    def _liquidation_page(state: dict[str, str], after: int, page: int) -> RequestSpec:
        params = {
            "instType": "SWAP",
            "uly": f"{state['asset']}-USDT",
            "state": "filled",
            "limit": str(PAGE_LIMIT),
            "after": str(after),
        }
        return RequestSpec(LIQUIDATIONS_PATH, params, page=page, state=state)

    @staticmethod
    def _contract_value(raw: RawResponse, spec: RequestSpec) -> Decimal:
        rows = _data(raw)
        asset = spec.state["asset"]
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise schema_error(raw, "expected exactly one instrument")
        row = rows[0]
        if row.get("instId") != SWAPS[asset]:
            raise schema_error(raw, f"instrument {row.get('instId')!r}, expected {SWAPS[asset]}")
        if row.get("ctValCcy") != asset or row.get("ctType") != "linear":
            raise schema_error(
                raw,
                f"contract value in {row.get('ctValCcy')!r} ({row.get('ctType')!r}); expected a "
                f"linear contract valued in {asset}",
            )
        try:
            value = to_decimal(row.get("ctVal"), "ctVal")
        except DataValidationError as exc:
            raise schema_error(raw, str(exc)) from exc
        if value <= 0:
            raise schema_error(raw, f"ctVal {value} is not positive")
        return value

    # ------------------------------------------------------------------ parsing

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise NotImplementedError("OKX derivatives pages are parsed with their request")

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        asset, metric, dataset_id = (
            spec.state["asset"],
            spec.state["metric"],
            spec.state["dataset_id"],
        )

        def record(time: object, value: object, **extra: object) -> ProviderRecord:
            payload = {"asset": asset, "metric": metric, "time": time, "value": value, **extra}
            return ProviderRecord(PROVIDER_ID, dataset_id, payload)

        if spec.path == OI_PATH:
            return [record(r[0], r[2]) for r in _array_rows(raw, 3)]
        if spec.path == RATIO_PATH:
            return [record(r[0], r[1]) for r in _array_rows(raw, 2)]
        if spec.path == FUNDING_PATH:
            out = []
            for row in _data(raw):
                if not isinstance(row, dict) or row.get("instId") != SWAPS[asset]:
                    raise schema_error(raw, f"funding row not for {SWAPS[asset]}")
                if "fundingTime" not in row or "fundingRate" not in row:
                    raise schema_error(raw, "funding row without fundingTime or fundingRate")
                out.append(record(row["fundingTime"], row["fundingRate"]))
            return out
        if spec.path == INSTRUMENTS_PATH:
            self._contract_value(raw, spec)  # validated here; carried by next_request
            return []
        progress = _Liquidations.advance(raw, spec)
        if not progress.done:
            return []
        return [
            record(
                ms(hour),
                str(totals[i]),
                side=side,
                ct_val=progress.state["ct_val"],
                unclassified=str(totals[2]),
            )
            for hour, totals in progress.complete_hours(raw.received_at)
            for i, side in enumerate(("long", "short"))
        ]

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        p = record.payload
        asset, metric = str(p["asset"]), str(p["metric"])
        event_time = epoch_ms(p["time"], "fundingTime" if metric == "funding_rate" else "ts")
        if metric != "funding_rate":
            on_the_hour(event_time, "ts")
        transformations: tuple[str, ...] = ()
        quality, note = QualityStatus.OK, None
        if metric == "funding_rate":
            subject, value = perp_ref(asset), _number(p["value"], "fundingRate")
        elif metric == "open_interest":
            subject, value = perp_ref(asset), _number(p["value"], "oiCcy")
        elif metric == "long_short_account_ratio":
            subject, value = contracts_ref(asset), _number(p["value"], "ratio")
        else:
            side = p["side"]
            if side not in ("long", "short"):
                raise DataValidationError(f"unknown liquidation side {side!r}")
            subject = liquidation_ref(asset, "long" if side == "long" else "short")
            value = to_decimal(p["value"], "liquidations")
            transformations = (
                f"value: Σ sz (contracts) × ctVal {p['ct_val']} {asset}, hourly total of OKX "
                "liquidation orders",
            )
            unclassified = to_decimal(p["unclassified"], "unclassified")
            if unclassified:
                quality = QualityStatus.SUSPECT
                note = (
                    f"{unclassified} {asset} liquidated in this hour had a position side and "
                    "order side that do not match; not counted on either side"
                )
        return scalar(
            ctx,
            provider_id=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            asset=asset,
            subject_ref=subject,
            venue=VENUE,
            event_time=event_time,
            value=value,
            transformations=transformations,
            quality=quality,
            note=note,
        )


def _number(value: object, field: str) -> Decimal | None:
    return None if value in (None, "") else to_decimal(value, field)


class _Liquidations:
    """Running hourly totals across liquidation pages, carried in ``RequestSpec.state``."""

    def __init__(self, state: dict[str, str], boundary: int, done: bool) -> None:
        self.state = state
        self.boundary = boundary
        self.done = done

    @classmethod
    def advance(cls, raw: RawResponse, spec: RequestSpec) -> _Liquidations:
        state = dict(spec.state)
        asset = state["asset"]
        start_ms, end_ms = int(state["start_ms"]), int(state["end_ms"])
        ct_val = Decimal(state["ct_val"])
        totals: dict[str, list[str]] = json.loads(state.get("totals", "{}"))
        previous = int(state["boundary"]) if "boundary" in state else None
        skip = int(state.get("skip", "0"))
        details: list[tuple[int, dict[str, Any]]] = []
        for item in _data(raw):
            if not isinstance(item, dict) or item.get("instId") != SWAPS[asset]:
                raise schema_error(raw, f"liquidation data not for {SWAPS[asset]}")
            if not isinstance(item.get("details"), list):
                raise schema_error(raw, "liquidation data without a 'details' list")
            for d in item["details"]:
                if not isinstance(d, dict):
                    raise schema_error(raw, "liquidation detail is not an object")
                details.append((_ts(raw, d.get("ts"), "ts"), d))
        details.sort(key=lambda x: x[0], reverse=True)
        reached_start = False
        skipped = 0
        for ts, d in details:
            if previous is not None and ts == previous and skipped < skip:
                skipped += 1  # counted on the previous page
                continue
            if ts >= end_ms:
                continue
            if ts < start_ms:
                reached_start = True
                continue
            hour = str(ts - ts % 3_600_000)
            side = _side(d)
            try:
                size = to_decimal(d.get("sz"), "sz")
            except DataValidationError as exc:
                raise schema_error(raw, str(exc)) from exc
            row = [Decimal(v) for v in totals.get(hour, ["0", "0", "0"])]
            row[{"long": 0, "short": 1, None: 2}[side]] += size * ct_val
            totals[hour] = [str(v) for v in row]
        done = len(details) < PAGE_LIMIT or reached_start
        boundary = previous if previous is not None else end_ms
        if details:
            boundary = details[-1][0]
            at_boundary = sum(1 for ts, _ in details if ts == boundary)
            if previous is not None and boundary == previous and not done:
                raise schema_error(
                    raw, f"more than {PAGE_LIMIT} liquidation orders share one millisecond"
                )
            state["skip"] = str(at_boundary)
            state["boundary"] = str(boundary)
        state["totals"] = json.dumps(totals, sort_keys=True)
        return cls(state, boundary, done)

    def complete_hours(self, received_at: datetime) -> list[tuple[datetime, list[Decimal]]]:
        """Every hour of the window, when its orders were all read and are still retained."""
        start = epoch_ms(int(self.state["start_ms"]), "start")
        end = epoch_ms(int(self.state["end_ms"]), "end")
        totals: dict[str, list[str]] = json.loads(self.state.get("totals", "{}"))
        out = []
        hour = start
        while hour + HOUR <= end:
            if hour >= received_at - LIQUIDATION_REACH:
                values = totals.get(ms(hour), ["0", "0", "0"])
                out.append((hour, [Decimal(v) for v in values]))
            hour += HOUR
        return out


def _side(detail: dict[str, Any]) -> str | None:
    """Which position was liquidated: ``long``, ``short``, or ``None`` when inconsistent."""
    pos, side = detail.get("posSide"), detail.get("side")
    if pos == "long":
        return "long" if side == "sell" else None
    if pos == "short":
        return "short" if side == "buy" else None
    if pos == "net":
        return {"sell": "long", "buy": "short"}.get(str(side))
    return None
