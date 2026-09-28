"""Capital Rotation Engine endpoints (read-only — Phase 20).

Analyzes relative behavior across BTC/ETH/SOL/XRP, this platform's "large caps" aggregate (the
same 4-asset universe), stablecoins (total and per-issuer), and discloses what is genuinely NOT
tracked (mid-caps, DeFi, AI-related assets — no fabricated data; meme assets get a retail-attention
proxy only, informational only, never a rotation leg — see /catalog's not_tracked). Every pair
distinguishes OBSERVED CAPITAL FLOW (each node's own market-share reading) from INFERRED CAPITAL
ROTATION (a hedged, never-stated-as-fact hypothesis, `cfi.divergence.capital_flow_map.classify_edge`
reused unchanged) and reports whether OBSERVED institutional ETF / whale exchange net-flow data
corroborates or contradicts each inferred rotation (this phase's explicit instruction).

Point-in-time parameters (ADR-0018/ADR-0060): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now when both are omitted; if only ``as_of`` is given, ``knowledge_time`` defaults to
``as_of`` rather than now. Neither ever looks beyond now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.api.params import resolve_query_times
from cfi.core.errors import ServiceUnavailableError
from cfi.rotation.service import RotationService
from cfi.rotation.universe import WINDOW_DAYS_DEFAULT, WINDOW_DAYS_MAX, WINDOW_DAYS_MIN

router = APIRouter(prefix="/api/v1/rotation", tags=["rotation"])

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
NodeId = Annotated[str, Query(description="One of the tracked rotation node ids (see /catalog)")]
WindowDays = Annotated[
    int,
    Query(
        ge=WINDOW_DAYS_MIN,
        le=WINDOW_DAYS_MAX,
        description=f"Trailing window used to classify direction (default {WINDOW_DAYS_DEFAULT})",
    ),
]


def _service(request: Request) -> RotationService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return RotationService(engine)


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Every tracked rotation node, which node pairs are excluded (strict aggregates of one
    another) and why, the versioned parameters, and what is genuinely not tracked."""
    return _service(request).catalog()


@router.get("/pair")
async def pair(
    request: Request,
    from_node_id: NodeId,
    to_node_id: NodeId,
    window_days: WindowDays = WINDOW_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """One node pair's full detail: each node's own OBSERVED market-share reading, the INFERRED
    rotation hypothesis (if their directions diverge), duration, historical examples, and whether
    OBSERVED institutional/whale flow data corroborates or contradicts the hypothesis."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).pair(
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        window_days=window_days,
        as_of=a,
        knowledge_time=k,
    )


@router.get("/matrix")
async def matrix(
    request: Request,
    window_days: WindowDays = WINDOW_DAYS_DEFAULT,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Every eligible node pair at once (excluded pairs and untracked-only nodes are omitted — see
    /catalog for both; call /pair directly for a specific untracked node's own disclosed status)."""
    a, k = resolve_query_times(as_of, knowledge_time)
    return await _service(request).matrix(window_days=window_days, as_of=a, knowledge_time=k)
