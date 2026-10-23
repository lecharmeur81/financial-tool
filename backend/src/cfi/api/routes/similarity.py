"""Historical Similarity Engine endpoints (read-only — Phase 15).

Compares the current 9-feature market state (institutional flows, whale flows, retail activity,
liquidity, funding, open interest, volatility, market structure, macro) against sampled historical
dates. For each historical analogue: date, similarity score, that date's own Phase 14 regime label,
7/30/90-day forward return, maximum drawdown and volatility — plus a distribution/range across
analogues for each forward-return horizon. Never a predicted future return, and a horizon is only
shown once it would genuinely have been knowable as of ``as_of`` (this phase's explicit
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
from cfi.similarity.precompute import read_current
from cfi.similarity.service import SimilarityService

router = APIRouter(prefix="/api/v1/similarity", tags=["similarity"])

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


def _service(request: Request) -> SimilarityService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return SimilarityService(engine)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """The 9-feature definition (weights, normalization, evidence) and every parameter used."""
    return _service(request).catalog()


@router.get("/current")
async def current(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """The current historical-analogue search: similarity score, regime, forward returns, maximum
    drawdown and volatility per analogue, plus a distribution across analogues per horizon."""
    if as_of is None and knowledge_time is None:
        # The default "now" view is precomputed by a scheduled job (about 25 s to compute live,
        # over the 8 s client timeout): served from Redis with its age, or a controlled 503 when
        # missing/expired/malformed — never a stale result presented as current, never an
        # uncontrolled live computation.
        return await read_current(getattr(request.app.state, "redis", None))
    a, k = resolve_query_times(as_of, knowledge_time)
    # One request-scoped memo (Phase 51), as for the regime route: the ~103 historical candidate
    # snapshots and the per-analogue regime lookups share point-in-time reads and revision windows
    # instead of re-querying. Every read is keyed by its own ``as_of``/``knowledge_time`` (each
    # candidate's own date), so results are identical; the scope ends with the request.
    with pit_read_scope():
        return await _service(request).current(as_of=a, knowledge_time=k)
