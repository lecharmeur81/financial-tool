"""Retail activity intelligence endpoints (read-only — Phase 10).

Derivatives-positioning proxy, meme-coin trending proxy, small-transaction proxy, historical
percentiles, retail sentiment, and the two scores (Retail Activity Score, Retail Speculation
Score). **Every metric is a RETAIL PROXY, never DIRECT RETAIL DATA** — see
``retail/universe.py``. Amounts are exact decimal **strings**; percentages are strings in
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
from cfi.retail.queries import RetailQueries
from cfi.retail.service import RetailService

router = APIRouter(prefix="/api/v1/retail", tags=["retail"])

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
Series = Annotated[
    str, Query(description="History series: small_transaction_count or meme_trending_count")
]
Days = Annotated[int, Query(ge=1, le=HISTORY_DAYS_MAX, description="Days of history (default 90)")]


def _service(request: Request) -> RetailService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return RetailService(RetailQueries(engine), settings.retail_provider_ids)


def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Datasets (own and reused from derivatives), providers, schedule, thresholds, both score
    definitions and what is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Both scores, the three proxy metrics, retail sentiment, and each metric's historical
    percentile."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/history")
async def history(
    request: Request,
    series: Series,
    days: Days = HISTORY_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """History for one series: small_transaction_count or meme_trending_count."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).history(series=series, days=days, as_of=a, knowledge_time=k)
