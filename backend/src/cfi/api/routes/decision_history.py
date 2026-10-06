"""Read-only decision history / change intelligence endpoint (Phase 41).

``GET /api/v1/decision/history?asset=BTC|ETH|SOL|XRP&limit=N`` compares each persisted
``sig.decision_assessment`` row of one scope with the row recorded immediately before it
(``cfi.decision_history``). Ordering is by ``snapshot_id`` - the same definition of "current" as
``/api/v1/decision/current`` - and the caller-supplied ``as_of`` never reorders anything; it is
reported as stored, with ``out_of_order_as_of`` marking an entry recorded after a later-``as_of``
predecessor. Nothing is recalculated: one ``SELECT``, then a pure comparison. No write, no provider,
no Claude. ``decision_view.v0`` (``/decision/current``) is untouched; this is its own contract,
``decision_history.v0``.

Errors (RFC 9457, ``cfi.core.errors``): an unsupported asset or an out-of-range limit is 422; no
persisted assessment for the scope is 404 (``not_found``, a normal first-run state); a persisted
row that lacks a field the Phase 40 contract guarantees is 503."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from cfi.core.errors import DataValidationError, NotFoundError, ServiceUnavailableError
from cfi.decision.read_service import DEFAULT_ASSET
from cfi.decision.universe import (
    METHODOLOGY_VERSION,
    PARAMETER_VERSION,
    SCOPE_DOMAINS,
    TEMPLATE_VERSION,
)
from cfi.decision_history import (
    HISTORY_CONTRACT_VERSION,
    DecisionHistoryRepository,
    MalformedAssessmentError,
    PersistedAssessment,
    build_history,
)

router = APIRouter(prefix="/api/v1/decision", tags=["decision"])

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


class HistoryEntryOut(BaseModel):
    snapshot_id: int
    snapshot_as_of: str
    recorded_at: str
    stance: str
    confidence: str
    posture: str
    decision_input_hash: str
    producer_hash_check: str
    methodology_version: str
    parameter_version: str
    template_version: str
    state: str
    previous_snapshot_id: int | None
    previous_methodology_version: str | None
    previous_parameter_version: str | None
    out_of_order_as_of: bool
    change: dict[str, Any] | None


class HistoryVersionsOut(BaseModel):
    methodology_version: str
    parameter_version: str
    template_version: str


class DecisionHistoryOut(BaseModel):
    contract_version: str
    asset: str
    ordering: str
    limit: int
    returned: int
    running_versions: HistoryVersionsOut
    current: HistoryEntryOut
    history: list[HistoryEntryOut]


class HistorySource(Protocol):
    """What the route needs from storage: the newest persisted assessments of one scope."""

    async def recent_for_scope(
        self, scope: str, *, count: int
    ) -> tuple[PersistedAssessment, ...]: ...


def get_history_source(request: Request) -> HistorySource:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ServiceUnavailableError("Database connection is not available.")
    return DecisionHistoryRepository(engine)


@router.get("/history", response_model=DecisionHistoryOut)
async def decision_history(
    source: Annotated[HistorySource, Depends(get_history_source)],
    asset: Annotated[str, Query(description="BTC, ETH, SOL or XRP (default BTC)")] = DEFAULT_ASSET,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if asset not in SCOPE_DOMAINS:
        raise DataValidationError(
            f"asset {asset!r} is not defined; defined: {sorted(SCOPE_DOMAINS)}"
        )
    # one extra, older row so the oldest returned entry still has its predecessor
    rows = await source.recent_for_scope(asset, count=limit + 1)
    if not rows:
        raise NotFoundError(f"No persisted decision assessment exists yet for {asset}.")
    try:
        entries = [e.to_dict() for e in build_history(rows, limit=limit)]
    except MalformedAssessmentError as exc:
        raise ServiceUnavailableError(
            f"A persisted decision assessment cannot be compared: {exc}"
        ) from exc
    return {
        "contract_version": HISTORY_CONTRACT_VERSION,
        "asset": asset,
        "ordering": "snapshot_id",
        "limit": limit,
        "returned": len(entries),
        "running_versions": {
            "methodology_version": METHODOLOGY_VERSION,
            "parameter_version": PARAMETER_VERSION,
            "template_version": TEMPLATE_VERSION,
        },
        "current": entries[0],
        "history": entries,
    }
