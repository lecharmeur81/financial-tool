"""Market data endpoints (read-only, observed data only — Phase 5).

Every response carries its evidence category, ``as_of``, the data source and quality/freshness
information (ADR-0025 evidence envelope). Prices and volumes are exact decimal **strings**.
No signals, scores or recommendations are produced here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from cfi.api.params import aware
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.market.queries import MarketQueries
from cfi.market.service import MAX_BARS, MarketService

router = APIRouter(prefix="/api/v1/market", tags=["market"])


class Attribution(BaseModel):
    text: str
    url: str


class Source(BaseModel):
    provider_id: str
    provider_name: str
    original_source: str
    enabled: bool
    attribution: Attribution | None


class TimeframeInfo(BaseModel):
    timeframe: str
    source: Literal["native", "derived"]
    derived_from: str | None


class VenueInfo(BaseModel):
    venue_id: str
    display_name: str
    quote: str
    instruments: dict[str, str]
    timeframes: list[TimeframeInfo]
    source: Source


class AssetInfo(BaseModel):
    symbol: str
    name: str


class Catalog(BaseModel):
    assets: list[AssetInfo]
    timeframes: list[str]
    venues: list[VenueInfo]
    market_cap_source: Source


class Bar(BaseModel):
    time: datetime
    open: str | None
    high: str | None
    low: str | None
    close: str | None
    volume_base: str | None
    volume_quote: str | None
    trade_count: int | None
    quality_status: str
    quality_note: str | None
    revision: int


class Instrument(BaseModel):
    venue_id: str
    venue_name: str
    instrument_id: str
    price_unit: str
    volume_unit: str
    quote_volume_unit: str


class Derivation(BaseModel):
    from_timeframe: str
    bars_per_bucket: int
    method: str


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class BarQuality(BaseModel):
    expected: int
    present: int
    missing: int
    missing_times: list[datetime]
    not_loaded: int
    coverage_start: datetime | None
    suspect: int
    conflicting: int
    revised: int


class BarFreshness(BaseModel):
    status: Literal["fresh", "stale", "no_data"]
    latest_bar_time: datetime | None
    age_seconds: int | None
    limit_seconds: int
    last_ingested_at: datetime | None


class JobSummary(BaseModel):
    job_run_id: int
    job_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_detail: str | None


class BackfillSummary(BaseModel):
    covered_from: datetime
    covered_to: datetime
    target_start: datetime
    complete: bool
    note: str | None
    updated_at: datetime


class IngestionInfo(BaseModel):
    last_run: JobSummary | None
    backfill: BackfillSummary | None


class BarsResponse(BaseModel):
    evidence_category: Literal["observed"]
    as_of: datetime
    asset: str
    timeframe: str
    instrument: Instrument
    source: Source
    derivation: Derivation | None
    range: TimeRange
    bars: list[Bar]
    quality: BarQuality
    freshness: BarFreshness
    ingestion: IngestionInfo
    warnings: list[str]


class ScalarValue(BaseModel):
    value: str | None
    unit: str | None
    time: datetime | None
    ingested_at: datetime | None
    quality_status: str | None
    quality_note: str | None
    instrument_id: str | None
    freshness: Literal["fresh", "stale", "no_data"]
    age_seconds: int | None
    limit_seconds: int
    source: Source


class LatestBar(BaseModel):
    venue_id: str
    venue_name: str
    instrument_id: str
    timeframe: str
    bar_time: datetime | None
    close: str | None
    unit: str
    quality_status: str | None
    ingested_at: datetime | None
    freshness: Literal["fresh", "stale", "no_data"]
    age_seconds: int | None
    source: Source


class AssetOverview(BaseModel):
    symbol: str
    name: str
    last_trade: ScalarValue
    latest_bars: list[LatestBar]
    market_cap: ScalarValue


class OverviewResponse(BaseModel):
    evidence_category: Literal["observed"]
    as_of: datetime
    assets: list[AssetOverview]


def _service(request: Request) -> MarketService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return MarketService(MarketQueries(engine), settings.market_provider_ids)


def _as_of(value: datetime | None) -> datetime:
    now = utc_now()
    given = aware(value, "as_of")
    return now if given is None else min(given, now)


@router.get("/catalog", response_model=Catalog)
async def catalog(request: Request) -> Catalog:
    return Catalog(**_service(request).catalog())


@router.get("/bars", response_model=BarsResponse)
async def bars(
    request: Request,
    asset: Annotated[str, Query(description="Canonical asset symbol, e.g. BTC")],
    timeframe: Annotated[str, Query(description="1m, 5m, 15m, 1h, 4h or 1d")],
    venue: Annotated[str, Query(description="Venue ID from /market/catalog")] = "coinbase",
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 300,
    start: Annotated[datetime | None, Query(description="Inclusive, timezone-aware")] = None,
    end: Annotated[datetime | None, Query(description="Exclusive, timezone-aware")] = None,
    as_of: Annotated[
        datetime | None,
        Query(description="Point-in-time view: only data knowable and stored by then"),
    ] = None,
) -> BarsResponse:
    data = await _service(request).bars(
        asset=asset.upper(),
        timeframe=timeframe,
        venue_id=venue,
        as_of=_as_of(as_of),
        start=aware(start, "start"),
        end=aware(end, "end"),
        limit=limit,
    )
    return BarsResponse(**data)


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    request: Request,
    as_of: Annotated[datetime | None, Query(description="Point-in-time view")] = None,
) -> OverviewResponse:
    return OverviewResponse(**await _service(request).overview(_as_of(as_of)))
