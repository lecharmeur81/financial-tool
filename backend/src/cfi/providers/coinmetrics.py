"""Coin Metrics Community API — exchange flows, exchange supply, supply and issuance (no key).

Verified 2026-09-24 against the official documentation (https://docs.coinmetrics.io/api/v4) and
real responses (fetched 2026-09-24 for BTC and ETH, days 2026-09-18 … 2026-09-23):

- base URL ``https://community-api.coinmetrics.io/v4``; no key; limit 10 requests per 6 seconds
  per IP address;
- ``GET /timeseries/asset-metrics?assets=btc&metrics=FlowInExNtv&frequency=1d&start_time=&
  end_time=&paging_from=start&page_size=`` → ``{"data": [{"asset": "btc", "time":
  "2026-09-20T00:00:00.000000000Z", "FlowInExNtv": "12118.44914273", "FlowInExNtv-status":
  "flash", "FlowInExNtv-status-time": "2026-09-21T02:30:30.281487000Z"}, …], "next_page_token":
  …, "next_page_url": …}``. Values are decimal strings; ``time`` is the start of the UTC day the
  value covers; ``start_time`` / ``end_time`` are inclusive. ``next_page_token`` is absent on the
  last page;
- exchange metrics (``FlowInExNtv``, ``FlowOutExNtv``, ``SplyExNtv``) carry a status (``flash`` =
  preliminary, ``reviewed``) and a status time — the time the value was published, used as
  ``available_at``. Network metrics (``SplyCur``, ``IssTotNtv``) carry no status: their
  availability is estimated by the dataset rule;
- the Community catalogue has these metrics for BTC and ETH; not for SOL or XRP exchange flows,
  and no holder-age, balance-band or miner-flow metrics.

Terms: Community data is licensed CC BY-NC 4.0 (attribution required, non-commercial use only).
Recorded in THIRD_PARTY_NOTICES.md; commercial use needs a Coin Metrics licence.

A ``flash`` value is stored with ``quality_status = estimated`` (a preliminary figure the provider
may revise on review); a changed value later becomes a new revision.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.errors import DataValidationError, NotYetFinalError, ProviderNotConfiguredError
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
from cfi.whales.universe import WHALE_ASSETS, dataset, exchange_ref, network_ref

PROVIDER_ID = "coinmetrics"
PATH = "/timeseries/asset-metrics"
PAGE_SIZE = 1000
ASSET_IDS: dict[str, str] = {"BTC": "btc", "ETH": "eth"}
# dataset metric → Coin Metrics metric id
METRIC_IDS: dict[str, str] = {
    "exchange_inflow": "FlowInExNtv",
    "exchange_outflow": "FlowOutExNtv",
    "exchange_supply": "SplyExNtv",
    "supply": "SplyCur",
    "issuance": "IssTotNtv",
}
EXCHANGE_METRICS = frozenset({"exchange_inflow", "exchange_outflow", "exchange_supply"})
ATTRIBUTION = {
    "text": "Source: Coin Metrics Community Network Data (CC BY-NC 4.0)",
    "url": "https://coinmetrics.io/community-network-data/",
}
_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$")

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Coin Metrics Community",
    base_url="https://community-api.coinmetrics.io/v4",
    datasets=frozenset(
        dataset(metric, asset).dataset_id for metric in METRIC_IDS for asset in WHALE_ASSETS
    ),
    # Documented: 10 requests per 6 s per IP. Paced well below it, one request at a time.
    rate_limit=RateLimitSpec(5, 6.0, burst=1),
    max_retry_wait_seconds=60.0,
    timeout_seconds=30.0,
    max_pages=50,
    original_source="coinmetrics",
    terms_verified=True,
    notes=(
        "Community Network Data: daily exchange inflow/outflow and exchange supply (attributed "
        "by Coin Metrics), supply and issuance for BTC and ETH. No key; 10 requests per 6 s. "
        "Licence CC BY-NC 4.0: attribution required, non-commercial use only."
    ),
    gap_note="Coin Metrics published no value for this day",
)


def parse_time(value: object, field: str) -> tuple[datetime, bool]:
    """Coin Metrics RFC 3339 time with up to nanoseconds → (UTC datetime, truncated?)."""
    if not isinstance(value, str) or not (m := _TIME.fullmatch(value)):
        raise DataValidationError(f"{field} is not an RFC 3339 UTC time: {value!r}")
    fraction = m.group(2) or ""
    micro = int((fraction + "000000")[:6])
    base = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return base + timedelta(microseconds=micro), len(fraction) > 6 and set(fraction[6:]) != {"0"}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CoinMetrics(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        metric = next(
            (m for m in METRIC_IDS for a in WHALE_ASSETS if dataset(m, a).dataset_id == dataset_id),
            None,
        )
        asset = window.subject
        if (
            metric is None
            or asset not in ASSET_IDS
            or dataset(metric, asset).dataset_id != (dataset_id)
        ):
            raise ProviderNotConfiguredError(
                f"Coin Metrics: {dataset_id!r} is not configured for {asset!r}.",
                provider_id=PROVIDER_ID,
            )
        return RequestSpec(
            PATH,
            params={
                "assets": ASSET_IDS[asset],
                "metrics": METRIC_IDS[metric],
                "frequency": "1d",
                "start_time": _iso(window.start),
                # end_time is inclusive: stop one second before the (exclusive) window end
                "end_time": _iso(window.end - timedelta(seconds=1)),
                "paging_from": "start",
                "page_size": str(PAGE_SIZE),
            },
            state={"asset": asset, "metric": metric},
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        body = load_json(raw)
        token = body.get("next_page_token") if isinstance(body, dict) else None
        if not token:
            return None
        if not isinstance(token, str):
            raise schema_error(raw, "next_page_token is not a string")
        return RequestSpec(
            PATH,
            params={**previous.params, "next_page_token": token},
            page=previous.page + 1,
            state=previous.state,
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        metric_id = raw.request_params.get("metrics")
        metric = next((m for m, cm in METRIC_IDS.items() if cm == metric_id), None)
        asset = next(
            (a for a, cm in ASSET_IDS.items() if cm == raw.request_params.get("assets")), None
        )
        if metric is None or asset is None:
            raise schema_error(raw, "request parameters name no configured asset and metric")
        body = load_json(raw)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise schema_error(raw, "expected an object with a 'data' list")
        dataset_id = dataset(metric, asset).dataset_id
        records = []
        for row in body["data"]:
            if not isinstance(row, dict) or "time" not in row:
                raise schema_error(raw, "data row is not an object with 'time'")
            if row.get("asset") != ASSET_IDS[asset]:
                raise schema_error(raw, f"row for asset {row.get('asset')!r}, expected {asset}")
            payload: dict[str, Any] = {
                "asset": asset,
                "metric": metric,
                "time": row["time"],
                "value": row.get(metric_id),
                "status": row.get(f"{metric_id}-status"),
                "status_time": row.get(f"{metric_id}-status-time"),
            }
            records.append(ProviderRecord(PROVIDER_ID, dataset_id, payload))
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        p = record.payload
        spec = ctx.dataset
        asset, metric = str(p["asset"]), str(p["metric"])
        event_time, _ = parse_time(p["time"], "time")
        if (event_time.hour, event_time.minute, event_time.second, event_time.microsecond) != (
            0,
            0,
            0,
            0,
        ):
            raise DataValidationError(f"daily value not at 00:00 UTC: {p['time']!r}")
        if event_time + timedelta(days=1) > ctx.ingested_at:
            raise NotYetFinalError(f"day {event_time.date()} has not ended")
        transformations = ["event_time: RFC 3339 nanoseconds -> UTC"]
        published: datetime | None = None
        if p.get("status_time") is not None:
            published, truncated = parse_time(p["status_time"], "status_time")
            if truncated:
                transformations.append("available_at: status time truncated to microseconds")
        available_at, estimated = spec.available_at(event_time, published, ctx.ingested_at)
        value: Decimal | None = None if p.get("value") is None else to_decimal(p["value"], metric)
        status = p.get("status")
        if value is None:
            quality, note = QualityStatus.MISSING, "row carries no value for this metric"
        elif status == "flash":
            quality = QualityStatus.ESTIMATED
            note = "Coin Metrics 'flash' value: preliminary, may be revised on review"
        elif status in (None, "reviewed"):
            quality, note = QualityStatus.OK, None
        else:
            raise DataValidationError(f"unknown Coin Metrics status {status!r}")
        subject = exchange_ref(asset) if metric in EXCHANGE_METRICS else network_ref(asset)
        return CanonicalObservation(
            dataset_id=spec.dataset_id,
            metric=spec.metric,
            asset=asset,
            subject_ref=subject,
            venue=None,
            period=spec.period,
            unit=spec.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=quality,
            quality_note=note,
            pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations),
        )
