"""Market Regime Engine endpoints (read-only — Phase 14).

Classifies the current market into one of seven regimes (accumulation, recovery, expansion,
euphoria, distribution, capitulation, mixed/unclear) from the seven existing domain scores. The
classification is explainable: confidence, contributing metrics, contradicting metrics, historical
examples, regime start date and duration are all reported alongside the label. Confidence means
confidence that current conditions satisfy the regime's own definition — it is NOT a probability
that price will rise or fall, and this is not a trading recommendation (this phase's explicit
instruction).

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
from cfi.core.pit_memo import pit_read_scope
from cfi.regime.service import RegimeService
from cfi.regime.universe import INTERACTIVE_HISTORICAL_CONCURRENCY

router = APIRouter(prefix="/api/v1/regime", tags=["regime"])

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


def _service(request: Request) -> RegimeService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return RegimeService(engine)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """The seven regime definitions (conditions, weights, thresholds) and every parameter used."""
    return _service(request).catalog()


@router.get("/current")
async def current(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """The current regime classification: label, confidence, contributing/contradicting metrics,
    regime start date and duration, and historical examples of the same regime."""
    a, k = resolve_query_times(as_of, knowledge_time)
    # One request-scoped memo (Phase 51): the ~170 historical classifications behind the duration
    # walk and the examples share revision windows instead of issuing a query per day. Results are
    # identical (point-in-time reuse is exact-key or provably equivalent); the scope ends with the
    # request.
    with pit_read_scope():
        return await _service(request).current(
            as_of=a, knowledge_time=k, historical_concurrency=INTERACTIVE_HISTORICAL_CONCURRENCY
        )
