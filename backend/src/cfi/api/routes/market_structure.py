"""Market structure endpoints (read-only — Phase 12).

Per-asset technical readout (trend, moving averages, RSI, ATR, realized volatility, volume trend,
a rolling VWAP, relative strength vs. BTC, support/resistance) for BTC/ETH/SOL/XRP; market breadth
across the tracked universe; BTC/ETH dominance and the TOTAL/TOTAL2/TOTAL3 market-cap family; the
ETH/BTC ratio; and the Market Structure Score with every component. Amounts are exact decimal
**strings**. Nothing here is turned into an automatic trading recommendation.

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
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.service import MarketStructureService

router = APIRouter(prefix="/api/v1/market-structure", tags=["market-structure"])

HISTORY_DAYS_DEFAULT = 365
HISTORY_DAYS_MAX = 365 * 3

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
Series = Annotated[
    str, Query(description="History series id, e.g. 'total_market_cap' (see /catalog)")
]
Days = Annotated[int, Query(ge=1, le=HISTORY_DAYS_MAX, description="Days of history (default 365)")]


def _service(request: Request) -> MarketStructureService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return MarketStructureService(
        MarketStructureQueries(engine), settings.market_structure_provider_ids
    )


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Tracked assets, datasets, providers, schedule, parameters, the score definition and what
    is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """The Market Structure Score, per-asset technical readout, market breadth, BTC/ETH
    dominance, TOTAL/TOTAL2/TOTAL3 and the ETH/BTC ratio."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/history")
async def history(
    request: Request,
    series: Series,
    days: Days = HISTORY_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Raw history for the one series this phase directly ingests (TOTAL market cap); per-asset
    OHLCV bars are already served by ``/api/v1/market/bars``."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).history(series=series, days=days, as_of=a, knowledge_time=k)
