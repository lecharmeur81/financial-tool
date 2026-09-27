"""Capital Flow Divergence Engine endpoints (read-only — Phase 13).

The 10 standardized comparisons (institutional/whale/retail flow vs. price and vs. each other,
liquidity, open interest, funding, stablecoin supply, derivatives leverage, and macro conditions
vs. crypto market structure) and the Capital Flow Map. Nothing here labels a divergence "bullish"
or "bearish", forecasts a price, or gives an automatic trading recommendation — it reports the
observed direction, magnitude, historical percentile, duration, and supporting/contradicting
evidence, and states plainly when data is insufficient (this phase's explicit instruction).

Point-in-time parameters (ADR-0018): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now when both are omitted; if only ``as_of`` is given, ``knowledge_time``
defaults to ``as_of`` (ADR-0060) rather than now, so only what was knowable *by that same
date* is used unless a later ``knowledge_time`` is explicitly requested. Neither ever looks
beyond now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.api.params import resolve_query_times
from cfi.core.errors import ServiceUnavailableError
from cfi.divergence.service import DivergenceService
from cfi.divergence.universe import WINDOW_DAYS_DEFAULT, WINDOW_DAYS_MAX, WINDOW_DAYS_MIN

router = APIRouter(prefix="/api/v1/divergence", tags=["divergence"])

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
ComparisonId = Annotated[
    str, Query(description="One of the 10 standardized comparison ids (see /catalog)")
]
Asset = Annotated[
    str | None,
    Query(description="Asset symbol where the comparison is asset-specific (see /catalog)"),
]
WindowDays = Annotated[
    int,
    Query(
        ge=WINDOW_DAYS_MIN,
        le=WINDOW_DAYS_MAX,
        description=f"Trailing window used to classify direction (default {WINDOW_DAYS_DEFAULT})",
    ),
]


def _service(request: Request) -> DivergenceService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return DivergenceService(engine)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """The 10 standardized comparisons, the Capital Flow Map's nodes, and every parameter used."""
    return _service(request).catalog()


@router.get("/pair")
async def pair(
    request: Request,
    comparison_id: ComparisonId,
    asset: Asset = None,
    window_days: WindowDays = WINDOW_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """One comparison's full detail: observed quadrant, magnitude, historical percentile,
    duration, historical examples, and supporting/contradicting evidence."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).pair(
        comparison_id=comparison_id, asset=asset, window_days=window_days, as_of=a, knowledge_time=k
    )


@router.get("/matrix")
async def matrix(
    request: Request,
    window_days: WindowDays = WINDOW_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """All 10 standardized comparisons at once (each asset defaulted to its comparison's first
    tracked asset — call ``/pair`` directly to choose a different one)."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).matrix(window_days=window_days, as_of=a, knowledge_time=k)


@router.get("/capital-flow-map")
async def capital_flow_map(
    request: Request,
    window_days: WindowDays = WINDOW_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """The Institutions → Whales → Liquidity → BTC → ETH → SOL → Large Caps → Mid Caps → DeFi →
    AI-related assets → Meme assets → Retail chain: each node's own observed reading, and hedged
    'inferred rotation' hypotheses between adjacent nodes (never a claim that money moved)."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).capital_flow_map(
        window_days=window_days, as_of=a, knowledge_time=k
    )
