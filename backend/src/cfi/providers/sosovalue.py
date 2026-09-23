"""SoSoValue OpenAPI — US spot ETF flows and listed-company bitcoin purchases (free API key).

Verified 2026-09-24 against the official documentation
(https://sosovalue.gitbook.io/soso-value-api-doc, "llms-full.txt" export):

- base URL ``https://openapi.sosovalue.com/openapi/v1``; key in header ``x-soso-api-key``
  (free key: register at https://sosovalue.com/developer/dashboard, then wait for approval);
- limits per key: 20 requests per minute and 100,000 per month; HTTP 429 with code 42901 and a
  ``retry_after`` value when exceeded;
- every response is wrapped: ``{"code": 0, "message": "success", "data": …}``; ``code`` ≠ 0 is an
  error (400001 invalid parameter, 400003 invalid value, 400101 invalid key, 402901 rate limit);
- ``GET /etfs/summary-history?symbol=&country_code=US&limit=`` → daily totals across all ETFs of
  an asset: ``date`` (yyyy-MM-dd), ``total_net_inflow``, ``total_value_traded``,
  ``total_net_assets``, ``cum_net_inflow`` (USD). Non-trading days excluded. **Only the most
  recent month** can be queried; ``limit`` default 50, max 300. US symbols include BTC, ETH, SOL
  and XRP;
- ``GET /etfs?symbol=&country_code=US`` → ``[{"ticker", "name", "exchange"}]``;
- ``GET /etfs/{ticker}/history`` → per-fund daily rows: ``date``, ``ticker``, ``net_inflow``,
  ``cum_inflow``, ``net_assets``, ``currency_share``, ``prem_dsc``, ``value_traded``, ``volume``
  (most recent month). Figures settle T+1: the current day's row exists with ``net_inflow`` etc.
  still ``null``. Documented known issue: ``volume`` repeats ``value_traded`` (and is a string),
  so it is **not** stored;
- ``GET /btc-treasuries`` → ``[{"ticker", "name", "list_location"}]``;
- ``GET /btc-treasuries/{ticker}/purchase-history?limit=`` (max 100; optional ``start_date`` /
  ``end_date``) → ``date``, ``ticker``, ``btc_holding``, ``btc_acq``, ``acq_cost`` (USD),
  ``avg_btc_cost`` (USD per BTC).

The documentation does not state the date format of ``start_date`` / ``end_date`` for purchase
history; ``yyyy-MM-dd`` (the format of the response dates) is used, and pagination stops as soon as
a page brings no older purchase — an ignored parameter can never cause a loop.

Terms of use: the API documentation contains no terms, licence or attribution requirements, and
none were found published for the API. Recorded as unverified (``terms_verified=False``); the
user's decision is pending (PROGRESS.md, Phase 6).

Listing pages (fund list, company list) are fetched in the same ingestion run as the history pages
that follow them, so every response is archived and counted on one job run. Names read from a
listing travel to the following pages in ``RequestSpec.state``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from cfi.core.calendars import date_label, previous_us_trading_day
from cfi.core.errors import (
    DataValidationError,
    NotYetFinalError,
    ProviderNotConfiguredError,
    ProviderPermanentError,
)
from cfi.domain.enums import AuthType, EvidenceClass, QualityStatus
from cfi.domain.observation import CanonicalFlow
from cfi.institutional.universe import (
    ETF_ASSETS,
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_PURCHASE_ASSETS,
    TREASURY_PURCHASE_BTC,
    company_ref,
    etf_fund_ref,
    etf_group_ref,
)
from cfi.providers.base import (
    AuthSpec,
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

PROVIDER_ID = "sosovalue"
API_KEY_ENV = "CFI_PROVIDER_SOSOVALUE_API_KEY"
COUNTRY = "US"
SUMMARY_PATH = "/etfs/summary-history"
ETF_LIST_PATH = "/etfs"
TREASURY_LIST_PATH = "/btc-treasuries"
_FUND_HISTORY = re.compile(r"^/etfs/(?P<ticker>[^/]+)/history$")
_PURCHASES = re.compile(r"^/btc-treasuries/(?P<ticker>[^/]+)/purchase-history$")
_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,19}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY_LIMIT = 300
PURCHASE_PAGE_LIMIT = 100
ATTRIBUTION = {"text": "Data: SoSoValue", "url": "https://sosovalue.com"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="SoSoValue",
    base_url="https://openapi.sosovalue.com/openapi/v1",
    datasets=frozenset(
        {
            ETF_FLOW_US_SPOT.dataset_id,
            ETF_FUND_FLOW_US_SPOT.dataset_id,
            TREASURY_PURCHASE_BTC.dataset_id,
        }
    ),
    auth=AuthSpec(AuthType.API_KEY_HEADER, "x-soso-api-key", API_KEY_ENV),
    # Documented: 20 per minute per key. 18 leaves headroom for clock skew between limiters.
    rate_limit=RateLimitSpec(18, 60.0),
    timeout_seconds=20.0,
    max_pages=600,
    original_source="sosovalue",
    terms_verified=False,
    notes=(
        "US spot ETF flows (aggregate and per fund, most recent month only) and listed-company "
        "bitcoin purchase history, compiled by SoSoValue. Free API key required (20 requests/min, "
        "100,000/month). API terms of use not published in the documentation — unverified."
    ),
    gap_note="SoSoValue reported no settled figures for this date",
)


def _wrapped_data(raw: RawResponse) -> Any:
    body = load_json(raw)
    if not isinstance(body, dict) or "code" not in body or "data" not in body:
        raise schema_error(raw, "expected the wrapper {code, message, data}")
    code = body["code"]
    if code != 0:
        raise ProviderPermanentError(
            f"SoSoValue returned error code {code}: {body.get('message')!s}",
            provider_id=PROVIDER_ID,
        )
    return body["data"]


def _list_of_objects(raw: RawResponse, data: Any, what: str) -> list[dict[str, Any]]:
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise schema_error(raw, f"expected 'data' to be a list of {what} objects")
    return data


def _parse_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise DataValidationError(f"date is not yyyy-MM-dd: {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataValidationError(f"invalid date: {value!r}") from exc


def _optional(payload: Mapping[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    return None if value is None else to_decimal(value, key)


def _directory(raw: RawResponse, data: Any) -> dict[str, str | None]:
    """Ticker → name from a listing page, in the provider's order."""
    out: dict[str, str | None] = {}
    for item in _list_of_objects(raw, data, "listing"):
        ticker = item.get("ticker")
        if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
            raise schema_error(raw, f"listing entry has an unusable ticker {ticker!r}")
        name = item.get("name")
        out[ticker] = name if isinstance(name, str) else None
    return out


class SoSoValue(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    # ------------------------------------------------------------------ requests

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        subject = window.subject
        if dataset_id in (ETF_FLOW_US_SPOT.dataset_id, ETF_FUND_FLOW_US_SPOT.dataset_id):
            if subject not in ETF_ASSETS:
                raise ProviderNotConfiguredError(
                    f"SoSoValue: no US spot ETF data configured for {subject!r}.",
                    provider_id=PROVIDER_ID,
                )
            if dataset_id == ETF_FLOW_US_SPOT.dataset_id:
                return RequestSpec(
                    SUMMARY_PATH,
                    params={
                        "symbol": subject,
                        "country_code": COUNTRY,
                        "limit": str(SUMMARY_LIMIT),
                    },
                    state={"asset": subject},
                )
            return RequestSpec(
                ETF_LIST_PATH,
                params={"symbol": subject, "country_code": COUNTRY},
                state={"asset": subject},
            )
        if dataset_id == TREASURY_PURCHASE_BTC.dataset_id:
            if subject not in TREASURY_PURCHASE_ASSETS:
                raise ProviderNotConfiguredError(
                    f"SoSoValue: treasury purchase history exists for BTC only, not {subject!r}.",
                    provider_id=PROVIDER_ID,
                )
            return RequestSpec(TREASURY_LIST_PATH, state={"asset": subject})
        raise ProviderNotConfiguredError(
            f"SoSoValue does not supply {dataset_id!r}.", provider_id=PROVIDER_ID
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        state = dict(previous.state)
        if raw.endpoint in (ETF_LIST_PATH, TREASURY_LIST_PATH):
            directory = _directory(raw, _wrapped_data(raw))
            state["directory"] = json.dumps(directory, sort_keys=True)
            state["queue"] = ",".join(directory)
            state["kind"] = "fund" if raw.endpoint == ETF_LIST_PATH else "company"
            return self._next_entity(state, previous.page)
        purchases = _PURCHASES.match(raw.endpoint)
        if purchases and len(records) >= PURCHASE_PAGE_LIMIT:
            oldest = min(_parse_date(r.payload["date"]) for r in records)
            cursor = state.get("cursor")
            if cursor is None or oldest < date.fromisoformat(cursor):
                # A full page: ask for purchases before the oldest one received.
                state["cursor"] = oldest.isoformat()
                return RequestSpec(
                    raw.endpoint,
                    params={
                        "limit": str(PURCHASE_PAGE_LIMIT),
                        "end_date": (oldest - timedelta(days=1)).isoformat(),
                    },
                    page=previous.page + 1,
                    state=state,
                )
        state.pop("cursor", None)
        return self._next_entity(state, previous.page)

    @staticmethod
    def _next_entity(state: dict[str, str], page: int) -> RequestSpec | None:
        queue = [t for t in state.get("queue", "").split(",") if t]
        if not queue:
            return None
        ticker, rest = queue[0], queue[1:]
        state = {**state, "queue": ",".join(rest), "ticker": ticker}
        encoded = quote(ticker, safe="")
        if state.get("kind") == "fund":
            return RequestSpec(f"/etfs/{encoded}/history", page=page + 1, state=state)
        return RequestSpec(
            f"/btc-treasuries/{encoded}/purchase-history",
            params={"limit": str(PURCHASE_PAGE_LIMIT)},
            page=page + 1,
            state=state,
        )

    # ------------------------------------------------------------------ parsing

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        return self.parse_page(RequestSpec(raw.endpoint, params=raw.request_params), raw)

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = _wrapped_data(raw)
        if raw.endpoint in (ETF_LIST_PATH, TREASURY_LIST_PATH):
            _directory(raw, data)  # validated here; used by next_request
            return []
        asset = spec.state.get("asset")
        if raw.endpoint == SUMMARY_PATH:
            asset = raw.request_params.get("symbol", asset)
            return [
                ProviderRecord(PROVIDER_ID, ETF_FLOW_US_SPOT.dataset_id, {**row, "asset": asset})
                for row in _list_of_objects(raw, data, "daily summary")
            ]
        fund = _FUND_HISTORY.match(raw.endpoint)
        purchases = _PURCHASES.match(raw.endpoint)
        if fund is None and purchases is None:
            raise schema_error(raw, "unexpected endpoint")
        directory: dict[str, str | None] = json.loads(spec.state.get("directory", "{}"))
        dataset_id = ETF_FUND_FLOW_US_SPOT.dataset_id if fund else TREASURY_PURCHASE_BTC.dataset_id
        records = []
        for row in _list_of_objects(raw, data, "history"):
            ticker = row.get("ticker")
            requested = spec.state.get("ticker")
            if requested is not None and ticker != requested:
                raise schema_error(raw, f"row for ticker {ticker!r} in the {requested!r} history")
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    dataset_id,
                    {**row, "asset": asset, "entity_name": directory.get(str(ticker))},
                )
            )
        return records

    # ------------------------------------------------------------------ normalisation

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalFlow:
        p = record.payload
        dataset = ctx.dataset
        asset = p.get("asset")
        if not isinstance(asset, str):
            raise DataValidationError("record carries no asset")
        day = _parse_date(p.get("date"))
        event_time = date_label(day)
        transformations = [f"event_time: date {day.isoformat()} -> 00:00 UTC label"]

        if dataset.dataset_id == TREASURY_PURCHASE_BTC.dataset_id:
            return self._purchase(p, ctx, asset, event_time, transformations)

        if dataset.dataset_id == ETF_FLOW_US_SPOT.dataset_id:
            flow = _optional(p, "total_net_inflow")
            assets_usd = _optional(p, "total_net_assets")
            cum = _optional(p, "cum_net_inflow")
            traded = _optional(p, "total_value_traded")
            premium = None
            subject, entity_type = etf_group_ref(asset), "etf_group"
            name = f"All US spot {asset} ETFs"
        else:
            ticker = str(p.get("ticker"))
            flow = _optional(p, "net_inflow")
            assets_usd = _optional(p, "net_assets")
            cum = _optional(p, "cum_inflow")
            traded = _optional(p, "value_traded")
            premium = _optional(p, "prem_dsc")
            subject, entity_type = etf_fund_ref(ticker), "etf_fund"
            listed = p.get("entity_name")
            name = listed if isinstance(listed, str) else ticker

        missing = flow is None and assets_usd is None
        if missing and day >= previous_us_trading_day(ctx.ingested_at.date()):
            # Documented: the latest trading day exists before its figures settle (T+1).
            raise NotYetFinalError(f"ETF figures for {day.isoformat()} have not settled yet")
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        return CanonicalFlow(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=asset,
            subject_ref=subject,
            venue=None,
            period=dataset.period,
            unit=dataset.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            entity_type=entity_type,
            evidence_class=EvidenceClass.DIRECT,
            entity_name=name,
            flow_usd=None if missing else flow,
            holdings_usd=None if missing else assets_usd,
            cum_flow_usd=None if missing else cum,
            value_traded_usd=None if missing else traded,
            premium_discount=None if missing else premium,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.MISSING if missing else QualityStatus.OK,
            quality_note=(
                "provider row has no settled net inflow or net assets for this date"
                if missing
                else None
            ),
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations),
        )

    def _purchase(
        self,
        p: Mapping[str, Any],
        ctx: NormaliseContext,
        asset: str,
        event_time: datetime,
        transformations: list[str],
    ) -> CanonicalFlow:
        dataset = ctx.dataset
        ticker = str(p.get("ticker"))
        coins = _optional(p, "btc_acq")
        cost = _optional(p, "acq_cost")
        holding = _optional(p, "btc_holding")
        unit_cost = _optional(p, "avg_btc_cost")
        missing = coins is None and cost is None and holding is None
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        name = p.get("entity_name")
        return CanonicalFlow(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=asset,
            subject_ref=company_ref(ticker),
            venue=None,
            period=dataset.period,
            unit=dataset.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            entity_type="public_company",
            evidence_class=EvidenceClass.ATTRIBUTED,
            entity_name=name if isinstance(name, str) else ticker,
            flow_native=coins,
            flow_usd=cost if cost is None or coins is None or coins >= 0 else -abs(cost),
            holdings_native=holding,
            unit_cost_usd=unit_cost,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.MISSING if missing else QualityStatus.OK,
            quality_note="purchase record carries no amounts" if missing else None,
            pit_reliability=dataset.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(
                [
                    *transformations,
                    *(
                        ["flow_usd: acquisition cost signed like btc_acq (sale → negative)"]
                        if coins is not None and coins < 0 and cost is not None
                        else []
                    ),
                ]
            ),
        )
