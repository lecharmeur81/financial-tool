"""Market Anomaly Engine endpoints (read-only — Phase 19).

Detects unusual behavior in ETF flows, institutional flows, whale flows, exchange flows, funding,
open interest, liquidations, stablecoin supply, retail activity, social activity, volume,
volatility, and market structure — using each metric's own historical distribution and percentile
rank (never an arbitrary fixed threshold). For every anomaly: metric, current value, historical
percentile, magnitude, duration, source, timestamp, possible interpretations, contradicting
evidence, and data quality. Nothing here labels an anomaly "bullish" or "bearish", forecasts a
price, or gives an automatic trading recommendation (this phase's explicit instruction).

Point-in-time parameters (ADR-0018/ADR-0060): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now when both are omitted; if only ``as_of`` is given, ``knowledge_time`` defaults to
``as_of`` rather than now. Neither ever looks beyond now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.anomaly.service import AnomalyService
from cfi.api.params import resolve_query_times
from cfi.core.errors import ServiceUnavailableError

router = APIRouter(prefix="/api/v1/anomaly", tags=["anomaly"])

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(
        description="Only data this system had stored by then (timezone-aware); "
        "defaults to as_of if as_of is given, else now (ADR-0060)"
    ),
]
Asset = Annotated[
    str | None,
    Query(description="Asset symbol for asset-specific metrics (default BTC; see /catalog)"),
]
MetricId = Annotated[
    str, Query(description="One of the 13 tracked anomaly categories (see /catalog)")
]


def _service(request: Request) -> AnomalyService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return AnomalyService(engine)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """The 13 tracked anomaly categories, the versioned percentile-band parameters, and the
    magnitude methodology."""
    return _service(request).catalog()


@router.get("/scan")
async def scan(
    request: Request,
    asset: Asset = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Every tracked category's current reading at once: current value, historical percentile,
    band, magnitude, duration, possible interpretations, contradicting evidence, data quality."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).scan(asset=asset, as_of=a, knowledge_time=k)


@router.get("/metric")
async def metric(
    request: Request,
    metric_id: MetricId,
    asset: Asset = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """One category's full detail."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).detail(
        metric_id=metric_id, asset=asset, as_of=a, knowledge_time=k
    )
