"""Liquidity / stablecoin endpoints (read-only — Phase 9).

Stablecoin circulating supply (USDT, USDC, total), growth, contraction, market share, growth
acceleration/deceleration, the (always unavailable) exchange liquidity change, and the Liquidity
Score with every component. Amounts are exact decimal **strings**; percentages are strings in
percent. No reading is labelled bullish or bearish, and no recommendation is produced.

Point-in-time parameters (ADR-0018): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now and never look beyond it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.api.params import aware
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.liquidity.queries import LiquidityQueries
from cfi.liquidity.service import LiquidityService

router = APIRouter(prefix="/api/v1/liquidity", tags=["liquidity"])

HISTORY_DAYS_DEFAULT = 90
HISTORY_DAYS_MAX = 365 * 3

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(description="Only data this system had stored by then (timezone-aware; default now)"),
]
Subject = Annotated[str, Query(description="Tracked subject: USDT, USDC or TOTAL")]
Days = Annotated[
    int, Query(ge=1, le=HISTORY_DAYS_MAX, description="Days of daily history (default 90)")
]


def _service(request: Request) -> LiquidityService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return LiquidityService(LiquidityQueries(engine), settings.liquidity_provider_ids)


def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Datasets, providers, schedule, thresholds, the score definition and what is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """The Liquidity Score, per-subject supply growth, market share, growth acceleration and the
    (always unavailable) exchange liquidity change."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/history")
async def history(
    request: Request,
    subject: Subject,
    days: Days = HISTORY_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Daily circulating-supply history for one subject (USDT, USDC or TOTAL)."""
    a, k = _times(as_of, knowledge_time)
    subject = subject.upper()
    return await _service(request).history(subject=subject, days=days, as_of=a, knowledge_time=k)
