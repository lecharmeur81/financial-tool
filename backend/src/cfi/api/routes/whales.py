"""Whale intelligence endpoints (read-only — Phase 7).

On-chain exchange flows, coin-age activity, top-100 holders with their classification, large
transfers, address labels, the Whale Flow Score and contradiction indicators. Amounts are exact
decimal **strings**; every classification carries evidence, source and confidence.

Point-in-time parameters (ADR-0018): ``as_of`` limits data to what was publicly knowable
(``available_at``), ``knowledge_time`` to what this system had stored (``ingested_at``). Both
default to now. No recommendations are produced here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from cfi.api.params import aware
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.core.time import utc_now
from cfi.institutional.queries import InstitutionalQueries
from cfi.institutional.service import InstitutionalService
from cfi.whales.queries import WhaleQueries
from cfi.whales.service import WhaleService

router = APIRouter(prefix="/api/v1/whales", tags=["whales"])

AsOf = Annotated[
    datetime | None,
    Query(description="Point-in-time view: only data publicly knowable by then (timezone-aware)"),
]
KnowledgeTime = Annotated[
    datetime | None,
    Query(description="Only data this system had stored by then (timezone-aware; default now)"),
]
Asset = Annotated[str, Query(description="Canonical asset symbol: BTC or ETH")]
StartDate = Annotated[date | None, Query(description="First date (inclusive)")]
EndDate = Annotated[date | None, Query(description="End date (exclusive)")]
StartTime = Annotated[datetime | None, Query(description="Start (inclusive, timezone-aware)")]
EndTime = Annotated[datetime | None, Query(description="End (exclusive, timezone-aware)")]
Limit = Annotated[int, Query(ge=1, le=500, description="Maximum transfers listed")]


def _service(request: Request) -> WhaleService:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    settings: Settings = request.app.state.settings
    return WhaleService(
        WhaleQueries(engine),
        settings.whale_provider_ids,
        InstitutionalService(InstitutionalQueries(engine), settings.institutional_provider_ids),
    )


def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))


@router.get("/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    """Datasets, providers, schedule, thresholds, classification rules, the score definition and
    what is not tracked."""
    return _service(request).catalog()


@router.get("/overview")
async def overview(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    a, k = _times(as_of, knowledge_time)
    return await _service(request).overview(as_of=a, knowledge_time=k)


@router.get("/flows")
async def flows(
    request: Request,
    asset: Asset,
    start: StartDate = None,
    end: EndDate = None,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Daily exchange flows and supply, network supply and issuance, and (BTC) coin-age data."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).flows(
        asset=asset.upper(), start=start, end=end, as_of=a, knowledge_time=k
    )


@router.get("/holders")
async def holders(
    request: Request, asset: Asset, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Latest top-100 snapshot with each address's classification and 7-day change."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).holders(asset=asset.upper(), as_of=a, knowledge_time=k)


@router.get("/transfers")
async def transfers(
    request: Request,
    asset: Asset,
    start: StartTime = None,
    end: EndTime = None,
    limit: Limit = 200,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Large transfers (newest first) with sender / recipient classification."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).transfers(
        asset=asset.upper(),
        start=aware(start, "start"),
        end=aware(end, "end"),
        limit=limit,
        as_of=a,
        knowledge_time=k,
    )


@router.get("/addresses/{chain}/{address}")
async def address(
    request: Request,
    chain: str,
    address: str,
    as_of: AsOf = None,
    knowledge_time: KnowledgeTime = None,
) -> dict[str, Any]:
    """Classification of one address with every stored label, its evidence and source."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).address(
        chain=chain.lower(), address=address, as_of=a, knowledge_time=k
    )


@router.get("/entities")
async def entities(
    request: Request, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Known entities and the labelled addresses that count at ``as_of``."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).entities(as_of=a, knowledge_time=k)


@router.get("/score")
async def score(
    request: Request, asset: Asset, as_of: AsOf = None, knowledge_time: KnowledgeTime = None
) -> dict[str, Any]:
    """Whale Flow Score with every component, contradiction indicators and miner spending."""
    a, k = _times(as_of, knowledge_time)
    return await _service(request).score(asset=asset.upper(), as_of=a, knowledge_time=k)
