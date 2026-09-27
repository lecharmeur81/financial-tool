"""Derivatives endpoints (read-only — Phase 8).

Open interest, leverage, funding, futures basis, liquidations, options, long/short account ratios
and the Derivatives Health Score with every component. Amounts are exact decimal **strings**;
percentages are strings in percent. No reading is labelled bullish or bearish, and no
recommendation is produced.

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
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.derivatives.queries import DerivativesQueries
from cfi.derivatives.service import HISTORY_DAYS_DEFAULT, HISTORY_DAYS_MAX, DerivativesService

router = APIRouter(prefix="/api/v1/derivatives", tags=["derivatives"])

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
Asset = Annotated[str, Query(description="Canonical asset symbol: BTC, ETH, SOL or XRP")]
Days = Annotated[
    int, Query(ge=1, le=HISTORY_DAYS_MAX, description="Days of hourly history (default 7)")
]


def _service(request: Request) -> DerivativesService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return DerivativesService(DerivativesQueries(engine), settings.derivative_provider_ids)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Datasets, providers, schedule, thresholds, the score definition and what is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Health score, open interest, funding, basis, liquidations and active conditions for
    every tracked asset."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/asset")
async def asset(
    request: Request, asset: Asset, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Everything for one asset: score with components, conditions, open interest per venue,
    leverage, funding, basis curve, liquidations, options, positioning, price context and data
    quality."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).asset(asset=asset.upper(), as_of=a, knowledge_time=k)


@router.get("/history")
async def history(
    request: Request,
    asset: Asset,
    days: Days = HISTORY_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Hourly open interest (per venue and aggregate), funding, account ratios, liquidations,
    DVOL and USD price for charts."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).history(
        asset=asset.upper(), days=days, as_of=a, knowledge_time=k
    )
