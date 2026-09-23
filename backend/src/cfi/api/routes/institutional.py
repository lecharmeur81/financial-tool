"""Institutional capital endpoints (read-only — Phase 6).

ETF flows (daily, weekly, monthly), per-fund breakdown, listed-company treasuries and the
transparent Institutional Flow Score. Every metric carries source, timestamp, unit, calculation,
freshness and data quality; amounts are exact decimal **strings**.

Point-in-time parameters (ADR-0018): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now. No recommendations are produced here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from cfi.api.params import aware
from cfi.api.routes.market import JobSummary
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.institutional.queries import InstitutionalQueries
from cfi.institutional.service import InstitutionalService

router = APIRouter(prefix="/api/v1/institutional", tags=["institutional"])

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(description="Only data this system had stored by then (timezone-aware; default now)"),
]
Asset = Annotated[str, Query(description="Canonical asset symbol, e.g. BTC")]
Interval = Annotated[str, Query(description="1d (daily), 1w (weekly) or 1mo (monthly)")]
StartDate = Annotated[date | None, Query(description="First date (inclusive)")]
EndDate = Annotated[date | None, Query(description="End date (exclusive)")]


class Attribution(BaseModel):
    text: str
    url: str


class Source(BaseModel):
    provider_id: str
    provider_name: str
    original_source: str
    dataset_id: str
    enabled: bool
    terms_verified: bool
    attribution: Attribution | None


class FreshnessInfo(BaseModel):
    status: Literal["fresh", "stale", "no_data"]
    latest: datetime | date | None
    expected_latest: date | None
    age_seconds: int | None
    rule: str
    note: str


class Quality(BaseModel):
    status: str
    days_expected: int | None
    days_present: int | None
    flagged: int
    revised: int
    backfilled: int
    estimated_availability: int
    notes: list[str]
    missing_days: list[date] = []
    not_loaded: int | None = None
    not_due: int | None = None


class Metric(BaseModel):
    metric_id: str
    label: str
    evidence_category: Literal["observed", "metric"]
    evidence_class: str | None
    value: str | None
    unit: str
    timestamp: datetime | date | None
    calculation: str
    source: Source
    freshness: FreshnessInfo
    quality: Quality


class IngestionInfo(BaseModel):
    last_run: JobSummary | None


class DateRange(BaseModel):
    start: date
    end: date


class OptionalDateRange(BaseModel):
    start: date | None
    end: date | None


class Reconciliation(BaseModel):
    funds_reporting: int
    funds_total_usd: str | None
    difference_usd: str | None
    reconciles: bool
    tolerance_usd: str


class EtfBucket(BaseModel):
    start: date
    end: date
    net_flow_usd: str | None
    net_assets_usd: str | None
    net_assets_date: date | None
    value_traded_usd: str | None
    inflow_days: int
    outflow_days: int
    status: Literal["complete", "partial", "in_progress", "not_due", "not_loaded", "no_data"]
    quality: Quality
    reconciliation: Reconciliation | None


class FlowDefinition(BaseModel):
    metric_id: str
    label: str
    unit: str
    calculation: str
    sign: str
    event_time: str


class EtfFlowsResponse(BaseModel):
    asset: str
    interval: str
    as_of: datetime
    knowledge_time: datetime
    range: DateRange
    evidence_category: Literal["observed", "metric"]
    evidence_class: str
    definition: FlowDefinition
    source: Source
    buckets: list[EtfBucket]
    latest_day: date | None
    coverage_start: date | None
    freshness: FreshnessInfo
    ingestion: IngestionInfo
    warnings: list[str]


class Fund(BaseModel):
    ticker: str
    name: str | None
    latest_day: date
    net_assets_usd: str | None
    share_of_net_assets_pct: str | None
    premium_discount: str | None
    cum_flow_usd: str | None
    range_flow_usd: str | None
    days_present: int
    freshness: FreshnessInfo
    quality: Quality


class EtfFundsResponse(BaseModel):
    asset: str
    as_of: datetime
    knowledge_time: datetime
    range: DateRange
    evidence_category: Literal["metric"]
    evidence_class: str
    definition: dict[str, str]
    source: Source
    funds: list[Fund]
    total_net_assets_usd: str | None
    ingestion: IngestionInfo
    warnings: list[str]


class PurchaseBucket(BaseModel):
    start: date
    end: date
    btc_acquired: str | None
    cost_usd: str | None
    cost_known_events: int
    events: int
    companies: int
    quality: Quality


class PurchaseEvent(BaseModel):
    date: date
    company: str | None
    ticker: str
    btc_acquired: str | None
    cost_usd: str | None
    unit_cost_usd: str | None
    holdings_after_btc: str | None
    available_at: datetime
    available_at_estimated: bool
    pit_reliability: str
    quality_status: str
    quality_note: str | None


class Holder(BaseModel):
    ticker: str
    company: str | None
    holdings_btc: str | None
    as_of_purchase_date: date
    pit_reliability: str


class Purchases(BaseModel):
    definition: dict[str, Any]
    source: Source
    buckets: list[PurchaseBucket]
    recent: list[PurchaseEvent]
    top_holders: list[Holder]
    reported_holdings: Metric
    companies_tracked: int
    freshness: FreshnessInfo
    ingestion: IngestionInfo


class HoldingsChange(BaseModel):
    days: int
    compared_with: datetime | None
    change_native: str | None
    change_pct: str | None
    note: str | None


class HoldingsTotals(BaseModel):
    holdings: Metric
    value_usd: Metric
    changes: list[HoldingsChange]
    ingestion: IngestionInfo


class TreasuryResponse(BaseModel):
    asset: str
    interval: str
    as_of: datetime
    knowledge_time: datetime
    range: DateRange
    evidence_class: str
    evidence_note: str
    purchases: Purchases | None
    holdings_totals: HoldingsTotals | None
    warnings: list[str]


class ScoreComponent(BaseModel):
    component_id: str
    status: Literal["ok", "unavailable"]
    reason: str | None
    definition: str
    evidence: str
    weight: str
    effective_weight: str | None
    reference_scale: str | None
    sub_score: str | None
    contribution: str | None
    window: OptionalDateRange
    inputs: dict[str, str | int | None]
    metric: Metric


class ScoreResponse(BaseModel):
    score_id: str
    version: str
    asset: str
    as_of: datetime
    knowledge_time: datetime
    evidence_category: Literal["metric"]
    status: Literal["ok", "insufficient_data"]
    value: str | None
    unit: str
    band: str | None
    reason: str | None
    available_weight: str
    calculation: str
    etf_due_until: date
    components: list[ScoreComponent]
    interpretation_limits: list[str]
    bands_note: str


class OverviewScore(BaseModel):
    status: Literal["ok", "insufficient_data"]
    value: str | None
    band: str | None
    reason: str | None
    available_weight: str


class OverviewLatestDay(BaseModel):
    date: date | None
    net_flow_usd: str | None
    net_assets_usd: str | None
    quality_status: str | None


class OverviewFlow(BaseModel):
    status: Literal["ok", "unavailable"]
    net_flow_usd: str | int | None
    pct_of_net_assets: str | None
    window: OptionalDateRange
    reason: str | None


class OverviewAsset(BaseModel):
    asset: str
    score: OverviewScore
    latest_day: OverviewLatestDay
    flow_5d: OverviewFlow
    freshness: FreshnessInfo


class OverviewResponse(BaseModel):
    as_of: datetime
    knowledge_time: datetime
    evidence_category: Literal["metric"]
    assets: list[OverviewAsset]
    source: Source
    interpretation_limits: list[str]


def _service(request: Request) -> InstitutionalService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return InstitutionalService(InstitutionalQueries(engine), settings.institutional_provider_ids)


def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Tracked datasets, providers, schedule, the score definition and what is not tracked."""
    return _service(request).catalog()


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> OverviewResponse:
    a, k = _times(as_of, knowledge_time)
    return OverviewResponse(**await _service(request).overview(as_of=a, knowledge_time=k))


@router.get("/etf-flows", response_model=EtfFlowsResponse)
async def etf_flows(
    request: Request,
    asset: Asset,
    interval: Interval = "1d",
    start: StartDate = None,
    end: EndDate = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> EtfFlowsResponse:
    a, k = _times(as_of, knowledge_time)
    data = await _service(request).etf_flows(
        asset=asset.upper(), interval=interval, start=start, end=end, as_of=a, knowledge_time=k
    )
    return EtfFlowsResponse(**data)


@router.get("/etf-funds", response_model=EtfFundsResponse)
async def etf_funds(
    request: Request,
    asset: Asset,
    start: StartDate = None,
    end: EndDate = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> EtfFundsResponse:
    a, k = _times(as_of, knowledge_time)
    data = await _service(request).etf_funds(
        asset=asset.upper(), start=start, end=end, as_of=a, knowledge_time=k
    )
    return EtfFundsResponse(**data)


@router.get("/treasury", response_model=TreasuryResponse)
async def treasury(
    request: Request,
    asset: Asset,
    interval: Interval = "1w",
    start: StartDate = None,
    end: EndDate = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> TreasuryResponse:
    a, k = _times(as_of, knowledge_time)
    data = await _service(request).treasury(
        asset=asset.upper(), interval=interval, start=start, end=end, as_of=a, knowledge_time=k
    )
    return TreasuryResponse(**data)


@router.get("/score", response_model=ScoreResponse)
async def score(
    request: Request, asset: Asset, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> ScoreResponse:
    a, k = _times(as_of, knowledge_time)
    data = await _service(request).score(asset=asset.upper(), as_of=a, knowledge_time=k)
    return ScoreResponse(**data)
