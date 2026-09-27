"""CoinGecko public / Demo API — market capitalisation and listed-company treasury holdings
(optional free Demo key).

Verified 2026-09-23 against the official documentation (docs.coingecko.com, v3.0.1):
- base URL ``https://api.coingecko.com/api/v3``; Demo key in header ``x-cg-demo-api-key``
  (optional here: requests are sent without a key when ``CFI_PROVIDER_COINGECKO_API_KEY`` is empty);
- ``GET /simple/price?ids=&vs_currencies=usd&include_market_cap=true&include_last_updated_at=true``
  → ``{"bitcoin": {"usd": …, "usd_market_cap": …, "last_updated_at": <epoch s>}}``; Demo/keyless
  data is cached for 60 seconds;
- ``GET /coins/{id}/market_chart?vs_currency=usd&days=&interval=daily`` →
  ``{"market_caps": [[<epoch ms>, value], …], …}``; daily points are at 00:00 UTC and the last
  completed day is available from 00:10 UTC; Demo history is limited to the past 365 days.

- ``GET /companies/public_treasury/{coin_id}`` (verified 2026-09-24, Demo/keyless available;
  updated every 5 minutes) → ``{"total_holdings", "total_value_usd", "market_cap_dominance",
  "companies": [{"name", "symbol", "country", "total_holdings", "total_entry_value_usd",
  "total_current_value_usd", "percentage_of_total_supply"}]}``. Only the totals are stored as
  observations; the full company list stays in the raw archive. The response carries no
  timestamp: ``event_time`` is the time the snapshot was received.

- ``GET /search/trending`` (Phase 10; verified 2026-09-26 against
  docs.coingecko.com/reference/trending-search — Demo/keyless available, cached ~10 minutes by
  CoinGecko) → ``{"coins": [{"item": {"id", "coin_id", "name", "symbol", "market_cap_rank",
  "score", "data": {...}}}], "nfts": [...], "categories": [...]}``. Only ``coins`` is used; each
  item's own ``symbol`` (not a pre-registered id map, unlike every other CoinGecko call this
  adapter makes — the trending set is dynamic) becomes the stored ``asset``, and ``item.id``
  (CoinGecko's coin slug) the ``subject_ref``. ``score`` is the 0-based trending rank (0 = most
  trending of that poll's top ~15); a coin absent from one poll's list has no observation that
  poll, never a zero. The response carries no timestamp: ``event_time`` is the time the snapshot
  was received. This is a RETAIL PROXY for search/attention interest (``cfi.retail.universe``),
  never trade or holder data.

- ``GET /global`` (Phase 12; verified 2026-09-27 against docs.coingecko.com/reference/crypto-global
  — Demo/keyless available) → ``{"data": {"active_cryptocurrencies", "total_market_cap": {"usd":
  <number>, ...}, "market_cap_percentage": {"btc": <number>, "eth": <number>, ...},
  "market_cap_change_percentage_24h_usd", "updated_at": <epoch s>}}``. Only ``data.total_market_cap
  .usd`` and ``data.updated_at`` are stored (the TOTAL market-cap dataset,
  ``cfi.market_structure.universe.TOTAL_MARKET_CAP_USD``); CoinGecko's own
  ``market_cap_percentage`` is not used — BTC/ETH dominance are instead calculated from this TOTAL
  and the per-asset market caps this adapter already stores (``MARKET_CAP_USD``), keeping every
  dominance figure and its inputs point-in-time consistent with each other rather than mixing a
  CoinGecko-computed percentage with independently-fetched market caps.

Terms (https://www.coingecko.com/en/api_terms, brand attribution guide): attribution such as
"Data provided by CoinGecko" with a link must be shown next to the data; the terms discourage
storing data and ask that stored data be refreshed at least every 24 hours. The storage question is
recorded for the user's decision (PROGRESS.md, Phase 5).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import DataValidationError, NotYetFinalError, ProviderNotConfiguredError
from cfi.core.time import from_epoch
from cfi.domain.enums import AuthType, EvidenceClass, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalFlow, CanonicalObservation
from cfi.institutional.universe import (
    TREASURY_HOLDING_ASSETS,
    TREASURY_HOLDINGS_COMPANIES,
    companies_group_ref,
)
from cfi.market.universe import MARKET_CAP_USD, MARKET_CAP_USD_1D
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD
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
from cfi.retail.universe import TRENDING, coin_ref

PROVIDER_ID = "coingecko"
API_KEY_ENV = "CFI_PROVIDER_COINGECKO_API_KEY"
COIN_IDS: dict[str, str] = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple"}
SIMPLE_PRICE_PATH = "/simple/price"
_CHART_PATH = re.compile(r"^/coins/(?P<coin>[a-z0-9-]+)/market_chart$")
_TREASURY_PATH = re.compile(r"^/companies/public_treasury/(?P<coin>[a-z0-9-]+)$")
TRENDING_PATH = "/search/trending"
GLOBAL_PATH = "/global"
DAILY_ALIGNMENT_TOLERANCE = timedelta(minutes=5)
MAX_DAYS = 365
ATTRIBUTION = {"text": "Data provided by CoinGecko", "url": "https://www.coingecko.com"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="CoinGecko",
    base_url="https://api.coingecko.com/api/v3",
    datasets=frozenset(
        {
            MARKET_CAP_USD.dataset_id,
            MARKET_CAP_USD_1D.dataset_id,
            TREASURY_HOLDINGS_COMPANIES.dataset_id,
            TRENDING.dataset_id,
            TOTAL_MARKET_CAP_USD.dataset_id,
        }
    ),
    auth=AuthSpec(AuthType.API_KEY_HEADER, "x-cg-demo-api-key", API_KEY_ENV, optional=True),
    rate_limit=RateLimitSpec(5, 60.0),
    timeout_seconds=15.0,
    max_pages=10,
    original_source="coingecko",
    terms_verified=False,
    notes=(
        "Market capitalisation computed and published by CoinGecko; listed-company treasury "
        "totals compiled by CoinGecko from company disclosures; trending list (Phase 10, RETAIL "
        "PROXY) is CoinGecko's own search-interest ranking. Attribution required next to the "
        "data. Terms discourage storing data (refresh stored data at least every 24 h); "
        "retention decision pending with the user. Demo history limited to 365 days."
    ),
)


def _asset_for(coin_id: str) -> str:
    for asset, known in COIN_IDS.items():
        if known == coin_id:
            return asset
    raise DataValidationError(f"unknown CoinGecko coin id {coin_id!r}")


class CoinGecko(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if dataset_id == TRENDING.dataset_id:
            return RequestSpec(TRENDING_PATH)
        if dataset_id == TOTAL_MARKET_CAP_USD.dataset_id:
            return RequestSpec(GLOBAL_PATH)
        if window.subject is not None and window.subject not in COIN_IDS:
            raise ProviderNotConfiguredError(
                f"CoinGecko: unsupported subject {window.subject!r}.", provider_id=PROVIDER_ID
            )
        if dataset_id == TREASURY_HOLDINGS_COMPANIES.dataset_id:
            if window.subject not in TREASURY_HOLDING_ASSETS:
                raise ProviderNotConfiguredError(
                    f"CoinGecko: no listed-company treasury data configured for "
                    f"{window.subject!r}.",
                    provider_id=PROVIDER_ID,
                )
            return RequestSpec(f"/companies/public_treasury/{COIN_IDS[window.subject]}")
        if dataset_id == MARKET_CAP_USD.dataset_id:
            ids = [COIN_IDS[window.subject]] if window.subject else [COIN_IDS[a] for a in COIN_IDS]
            return RequestSpec(
                SIMPLE_PRICE_PATH,
                params={
                    "ids": ",".join(ids),
                    "vs_currencies": "usd",
                    "include_market_cap": "true",
                    "include_last_updated_at": "true",
                    "precision": "full",
                },
            )
        if window.subject is None:
            raise ProviderNotConfiguredError(
                "CoinGecko daily history needs one subject per request.", provider_id=PROVIDER_ID
            )
        days = min(MAX_DAYS, max(1, math.ceil((window.end - window.start) / timedelta(days=1))))
        return RequestSpec(
            f"/coins/{COIN_IDS[window.subject]}/market_chart",
            params={
                "vs_currency": "usd",
                "days": str(days),
                "interval": "daily",
                "precision": "full",
            },
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if raw.endpoint == TRENDING_PATH:
            if not isinstance(data, dict) or not isinstance(data.get("coins"), list):
                raise schema_error(raw, "expected an object with a 'coins' list")
            records = []
            for entry in data["coins"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("item"), dict):
                    raise schema_error(raw, "each 'coins' entry must have an 'item' object")
                item = entry["item"]
                missing = [k for k in ("id", "symbol", "score") if k not in item]
                if missing:
                    raise schema_error(raw, f"trending item lacks {', '.join(missing)}")
                records.append(
                    ProviderRecord(
                        PROVIDER_ID,
                        TRENDING.dataset_id,
                        {
                            "coin_id": item["id"],
                            "symbol": item["symbol"],
                            "score": item["score"],
                        },
                    )
                )
            return records
        if raw.endpoint == GLOBAL_PATH:
            if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
                raise schema_error(raw, "expected an object with a 'data' object")
            body = data["data"]
            missing = [k for k in ("total_market_cap", "updated_at") if k not in body]
            if missing:
                raise schema_error(raw, f"'data' lacks {', '.join(missing)}")
            cap = body["total_market_cap"]
            if not isinstance(cap, dict) or "usd" not in cap:
                raise schema_error(raw, "'data.total_market_cap' lacks a 'usd' figure")
            return [
                ProviderRecord(
                    PROVIDER_ID,
                    TOTAL_MARKET_CAP_USD.dataset_id,
                    {"total_market_cap_usd": cap["usd"], "updated_at": body["updated_at"]},
                )
            ]
        if raw.endpoint == SIMPLE_PRICE_PATH:
            if not isinstance(data, dict):
                raise schema_error(raw, "expected an object keyed by coin id")
            records = []
            for coin_id, entry in data.items():
                if not isinstance(entry, dict) or "last_updated_at" not in entry:
                    raise schema_error(raw, f"entry {coin_id!r} lacks 'last_updated_at'")
                records.append(
                    ProviderRecord(
                        PROVIDER_ID,
                        MARKET_CAP_USD.dataset_id,
                        {
                            "coin_id": coin_id,
                            "market_cap": entry.get("usd_market_cap"),
                            "last_updated_at": entry["last_updated_at"],
                        },
                    )
                )
            return records
        treasury = _TREASURY_PATH.match(raw.endpoint)
        if treasury is not None:
            if not isinstance(data, dict) or not isinstance(data.get("companies"), list):
                raise schema_error(raw, "expected an object with a 'companies' list")
            for key in ("total_holdings", "total_value_usd"):
                if key not in data:
                    raise schema_error(raw, f"treasury response lacks {key!r}")
            return [
                ProviderRecord(
                    PROVIDER_ID,
                    TREASURY_HOLDINGS_COMPANIES.dataset_id,
                    {
                        "coin_id": treasury["coin"],
                        "total_holdings": data["total_holdings"],
                        "total_value_usd": data["total_value_usd"],
                    },
                )
            ]
        chart = _CHART_PATH.match(raw.endpoint)
        if chart is None:
            raise schema_error(raw, "unexpected endpoint")
        if not isinstance(data, dict) or not isinstance(data.get("market_caps"), list):
            raise schema_error(raw, "expected 'market_caps' as a list of [timestamp, value]")
        records = []
        for point in data["market_caps"]:
            if not isinstance(point, list) or len(point) != 2:
                raise schema_error(raw, "each market_caps entry must be [timestamp_ms, value]")
            records.append(
                ProviderRecord(
                    PROVIDER_ID,
                    MARKET_CAP_USD_1D.dataset_id,
                    {"coin_id": chart["coin"], "time_ms": point[0], "market_cap": point[1]},
                )
            )
        return records

    def normalise(
        self, record: ProviderRecord, ctx: NormaliseContext
    ) -> CanonicalObservation | CanonicalFlow:
        p = record.payload
        dataset = ctx.dataset
        if dataset.dataset_id == TRENDING.dataset_id:
            return _trending_rank(p, ctx)
        if dataset.dataset_id == TOTAL_MARKET_CAP_USD.dataset_id:
            return _total_market_cap(p, ctx)
        asset = _asset_for(str(p["coin_id"]))
        if dataset.dataset_id == TREASURY_HOLDINGS_COMPANIES.dataset_id:
            return _treasury_totals(p, ctx, asset)
        transformations: list[str] = []
        if dataset.dataset_id == MARKET_CAP_USD.dataset_id:
            updated = p["last_updated_at"]
            if not isinstance(updated, int):
                raise DataValidationError(f"last_updated_at is not an epoch integer: {updated!r}")
            event_time = from_epoch(updated, "s")
            transformations.append("event_time: epoch seconds -> UTC")
            available_at, estimated = dataset.available_at(event_time, event_time, ctx.ingested_at)
            pit = PitReliability.NATIVE
        else:
            stamp = p["time_ms"]
            if not isinstance(stamp, int):
                raise DataValidationError(f"timestamp is not an epoch integer: {stamp!r}")
            reported = from_epoch(stamp, "ms")
            transformations.append("event_time: epoch milliseconds -> UTC")
            event_time = _align_to_midnight(reported)
            if event_time != reported:
                transformations.append(
                    f"event_time: provider time {reported.isoformat()} aligned to the 00:00 UTC "
                    "daily grid"
                )
            available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
            pit = dataset.pit_reliability(available_at, ctx.ingested_at)

        raw_value = p["market_cap"]
        value = None if raw_value is None else to_decimal(raw_value, "market_cap")
        if value is not None and value <= 0:
            raise DataValidationError(f"non-positive market cap {value}")
        return CanonicalObservation(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=asset,
            subject_ref=asset,
            venue=None,
            period=dataset.period,
            unit=dataset.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.OK if value is not None else QualityStatus.MISSING,
            quality_note=None if value is not None else "provider returned no market cap",
            pit_reliability=pit,
            transformations=tuple(transformations),
        )


def _align_to_midnight(reported: datetime) -> datetime:
    """Daily points are documented at 00:00 UTC. A point within a few minutes of midnight is
    placed on it (recorded as a transformation); any other point — CoinGecko appends the current
    value to the series — is not a daily snapshot and is skipped."""
    midnight = reported.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
    candidates = (midnight, midnight + timedelta(days=1))
    nearest = min(candidates, key=lambda m: abs(reported - m))
    if abs(reported - nearest) > DAILY_ALIGNMENT_TOLERANCE:
        raise NotYetFinalError(
            f"point at {reported.isoformat()} is the provider's running value, "
            "not a 00:00 UTC daily snapshot"
        )
    return nearest


def _trending_rank(p: Any, ctx: NormaliseContext) -> CanonicalObservation:
    """One trending coin from one poll (Phase 10, RETAIL PROXY). Unlike every other CoinGecko
    call this adapter makes, the set of assets is dynamic (not a pre-registered id map): the
    item's own ``symbol`` becomes the stored asset, and its CoinGecko slug the subject_ref."""
    dataset = ctx.dataset
    asset = str(p["symbol"]).upper()
    score = p["score"]
    if not isinstance(score, int):
        raise DataValidationError(f"trending score is not an integer: {score!r}")
    if score < 0:
        raise DataValidationError(f"trending score is negative: {score!r}")
    event_time = ctx.ingested_at
    available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
    return CanonicalObservation(
        dataset_id=dataset.dataset_id,
        metric=dataset.metric,
        asset=asset,
        subject_ref=coin_ref(str(p["coin_id"])),
        venue=None,
        period=dataset.period,
        unit=dataset.unit,
        event_time=event_time,
        available_at=available_at,
        available_at_estimated=estimated,
        ingested_at=ctx.ingested_at,
        value=Decimal(score),
        source_provider=PROVIDER_ID,
        original_source=CAPABILITIES.original_source,
        raw_ref=ctx.raw_ref,
        quality_status=QualityStatus.OK,
        quality_note=None,
        pit_reliability=PitReliability.NATIVE,
        transformations=("event_time: snapshot receipt time (trending endpoint has no timestamp)",),
    )


def _total_market_cap(p: Any, ctx: NormaliseContext) -> CanonicalObservation:
    """One TOTAL market-cap snapshot from ``/global`` (Phase 12) — a single global reading, not
    per-asset (``asset`` and ``subject_ref`` are both the sentinel ``GLOBAL_SUBJECT``)."""
    dataset = ctx.dataset
    updated = p["updated_at"]
    if not isinstance(updated, int):
        raise DataValidationError(f"updated_at is not an epoch integer: {updated!r}")
    event_time = from_epoch(updated, "s")
    value = to_decimal(p["total_market_cap_usd"], "total_market_cap_usd")
    if value <= 0:
        raise DataValidationError(f"non-positive total market cap {value}")
    available_at, estimated = dataset.available_at(event_time, event_time, ctx.ingested_at)
    return CanonicalObservation(
        dataset_id=dataset.dataset_id,
        metric=dataset.metric,
        asset=GLOBAL_SUBJECT,
        subject_ref=GLOBAL_SUBJECT,
        venue=None,
        period=dataset.period,
        unit=dataset.unit,
        event_time=event_time,
        available_at=available_at,
        available_at_estimated=estimated,
        ingested_at=ctx.ingested_at,
        value=value,
        source_provider=PROVIDER_ID,
        original_source=CAPABILITIES.original_source,
        raw_ref=ctx.raw_ref,
        quality_status=QualityStatus.OK,
        quality_note=None,
        pit_reliability=PitReliability.NATIVE,
        transformations=("event_time: epoch seconds -> UTC",),
    )


def _treasury_totals(p: Any, ctx: NormaliseContext, asset: str) -> CanonicalFlow:
    """Totals across the listed companies CoinGecko tracks for one coin (a snapshot)."""
    dataset = ctx.dataset
    coins = None if p["total_holdings"] is None else to_decimal(p["total_holdings"], "holdings")
    value = None if p["total_value_usd"] is None else to_decimal(p["total_value_usd"], "value")
    available_at, estimated = dataset.available_at(ctx.ingested_at, None, ctx.ingested_at)
    missing = coins is None and value is None
    return CanonicalFlow(
        dataset_id=dataset.dataset_id,
        metric=dataset.metric,
        asset=asset,
        subject_ref=companies_group_ref(asset),
        venue=None,
        period=dataset.period,
        unit=dataset.unit,
        event_time=ctx.ingested_at,
        available_at=available_at,
        available_at_estimated=estimated,
        ingested_at=ctx.ingested_at,
        entity_type="public_company_group",
        evidence_class=EvidenceClass.ATTRIBUTED,
        entity_name="Listed companies tracked by CoinGecko",
        holdings_native=coins,
        holdings_usd=value,
        source_provider=PROVIDER_ID,
        original_source=CAPABILITIES.original_source,
        raw_ref=ctx.raw_ref,
        quality_status=QualityStatus.MISSING if missing else QualityStatus.OK,
        quality_note="provider returned no totals" if missing else None,
        pit_reliability=PitReliability.NATIVE,
        transformations=("event_time: snapshot receipt time (the response has no timestamp)",),
    )
