"""CoinGecko public / Demo API — market capitalisation (optional free Demo key).

Verified 2026-09-23 against the official documentation (docs.coingecko.com, v3.0.1):
- base URL ``https://api.coingecko.com/api/v3``; Demo key in header ``x-cg-demo-api-key``
  (optional here: requests are sent without a key when ``CFI_PROVIDER_COINGECKO_API_KEY`` is empty);
- ``GET /simple/price?ids=&vs_currencies=usd&include_market_cap=true&include_last_updated_at=true``
  → ``{"bitcoin": {"usd": …, "usd_market_cap": …, "last_updated_at": <epoch s>}}``; Demo/keyless
  data is cached for 60 seconds;
- ``GET /coins/{id}/market_chart?vs_currency=usd&days=&interval=daily`` →
  ``{"market_caps": [[<epoch ms>, value], …], …}``; daily points are at 00:00 UTC and the last
  completed day is available from 00:10 UTC; Demo history is limited to the past 365 days.

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

from cfi.core.errors import DataValidationError, NotYetFinalError, ProviderNotConfiguredError
from cfi.core.time import from_epoch
from cfi.domain.enums import AuthType, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.market.universe import MARKET_CAP_USD, MARKET_CAP_USD_1D
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

PROVIDER_ID = "coingecko"
API_KEY_ENV = "CFI_PROVIDER_COINGECKO_API_KEY"
COIN_IDS: dict[str, str] = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple"}
SIMPLE_PRICE_PATH = "/simple/price"
_CHART_PATH = re.compile(r"^/coins/(?P<coin>[a-z0-9-]+)/market_chart$")
DAILY_ALIGNMENT_TOLERANCE = timedelta(minutes=5)
MAX_DAYS = 365
ATTRIBUTION = {"text": "Data provided by CoinGecko", "url": "https://www.coingecko.com"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="CoinGecko",
    base_url="https://api.coingecko.com/api/v3",
    datasets=frozenset({MARKET_CAP_USD.dataset_id, MARKET_CAP_USD_1D.dataset_id}),
    auth=AuthSpec(AuthType.API_KEY_HEADER, "x-cg-demo-api-key", API_KEY_ENV, optional=True),
    rate_limit=RateLimitSpec(5, 60.0),
    timeout_seconds=15.0,
    max_pages=10,
    original_source="coingecko",
    terms_verified=False,
    notes=(
        "Market capitalisation computed and published by CoinGecko. Attribution required next to "
        "the data. Terms discourage storing data (refresh stored data at least every 24 h); "
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
        if window.subject is not None and window.subject not in COIN_IDS:
            raise ProviderNotConfiguredError(
                f"CoinGecko: unsupported subject {window.subject!r}.", provider_id=PROVIDER_ID
            )
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

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        p = record.payload
        dataset = ctx.dataset
        asset = _asset_for(str(p["coin_id"]))
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
