"""Macroeconomic environment endpoints (read-only — Phase 11).

US rates, inflation, growth, risk-appetite and liquidity series from FRED; the yield-curve slope,
an approximate real policy rate, CPI/PCE year-over-year change, VIX condition, equity/dollar/oil
trend, the US net-liquidity proxy, and the Macro Environment Score with every component. Amounts
are exact decimal **strings**; percentages are strings in percent. Nothing here converts macro
data into a deterministic crypto prediction, and no recommendation is produced.

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
from cfi.macro.queries import MacroQueries
from cfi.macro.service import MacroService

router = APIRouter(prefix="/api/v1/macro", tags=["macro"])

HISTORY_DAYS_DEFAULT = 365
HISTORY_DAYS_MAX = 365 * 15

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
DatasetId = Annotated[str, Query(description="Tracked macro dataset id, e.g. 'macro.vix.1d'")]
Days = Annotated[int, Query(ge=1, le=HISTORY_DAYS_MAX, description="Days of history (default 365)")]


def _service(request: Request) -> MacroService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return MacroService(MacroQueries(engine), settings.macro_provider_ids)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Datasets, providers, schedule, thresholds, the score definition and what is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """The Macro Environment Score, yield-curve slope, real policy rate, CPI/PCE year-over-year
    change, VIX condition, equity/dollar/oil trend and the US net-liquidity proxy."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/history")
async def history(
    request: Request,
    dataset_id: DatasetId,
    days: Days = HISTORY_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Raw history for one tracked macro dataset (see ``/catalog`` for the full dataset list)."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).history(
        dataset_id=dataset_id, days=days, as_of=a, knowledge_time=k
    )
