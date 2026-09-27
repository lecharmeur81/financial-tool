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
default to now and never look beyond it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.api.params import aware
from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.regime.service import RegimeService

router = APIRouter(prefix="/api/v1/regime", tags=["regime"])

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(description="Only data this system had stored by then (timezone-aware; default now)"),
]


def _service(request: Request) -> RegimeService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return RegimeService(engine)


def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))


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
    a, k = _times(as_of, knowledge_time)
    return await _service(request).current(as_of=a, knowledge_time=k)
