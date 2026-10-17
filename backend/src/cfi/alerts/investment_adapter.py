"""Investment-alert adapter (Phase 51 Stage 5): a stored snapshot row to ``investment_decision.v0``.

Specification: ``METHODOLOGY_INVESTMENT_ALERTS.md`` revision 6 (§4 item 5, §5.4) and ADR-0087.
**Experimental and not validated against historical outcomes.** This module contains no alert
logic: it validates one stored ``ai.snapshot`` row, runs the seven public Phase 44 to 49 builders
in the order the Phase 49 route uses, and hands the decision and the stored identity to the pure
evaluator (``investment_alerts.evaluate_investment_alerts``) in a later stage. It creates, persists,
resolves or clears nothing, and it does not evaluate: evaluation and orchestration are Stage 6.

Boundaries
* **Injected reader.** The row comes from a ``SnapshotReader`` the caller supplies (the real
  repository is wired in Stage 6). This module imports no repository, database,
  ``cfi.decision_store`` package, service, realtime or API module, and performs no I/O of its own.
* **Pure core.** ``build_decision_from_row`` is synchronous and pure; ``read_and_build`` makes
  exactly one ``await reader.get_snapshot(...)`` and delegates to it.

Failure behavior (fail closed; a refusal never carries a decision)
* ``snapshot_not_found``: the reader returned ``None``.
* ``snapshot_row_invalid``: a row came back but its identity, times or payload type are unusable.
  Checked before any builder runs.
* ``decision_inputs_refused``: a builder raised one of the six known input-refusal types. Only
  those exact classes are caught.
* Everything else propagates untouched: a plain ``ValueError``, ``KeyError``, ``TypeError`` and
  every other programming error; reader and database errors; Celery time-limit exceptions (which
  derive from ``Exception``); and ``asyncio.CancelledError`` (a ``BaseException``). Nothing here
  converts an execution-control signal or a bug into an ordinary refusal.

Hash policy (decided). A ``producer_hash_check`` of ``mismatch`` is **not** refused here: the
existing Phase 46 integrity gate already turns it into ``OD-SNAPSHOT-INTEGRITY`` and the decision
into ``withheld_integrity_gate`` for every asset (``assessment.performed`` false), which the
evaluator records as class B ``request_gated``. Because this adapter always supplies the stored hash
(a validated non-empty string), the check it produces is ``verified`` or ``mismatch``, never
``unverified``. No claim is made here that real database snapshots verify.

``AdapterOutcome.detail`` holds only the name of the known exception class, never a message or any
payload content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol, TypeGuard

from cfi.alerts.investment_alerts import (
    ADAPTER_REFUSAL_REASONS,
    InvestmentAlertValidationError,
    StoredSnapshotIdentity,
)
from cfi.decision.context import InvalidSnapshotError
from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    ConfirmationInputError,
    InvestmentInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
    build_confirmation,
    build_investment_decision,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
    build_risk_view,
    build_unified_snapshot,
)

__all__ = [
    "KNOWN_BUILDER_REFUSALS",
    "AdapterOutcome",
    "SnapshotReader",
    "StoredSnapshotRow",
    "build_decision_from_row",
    "read_and_build",
]

NOT_FOUND: Final = "snapshot_not_found"
ROW_INVALID: Final = "snapshot_row_invalid"
INPUTS_REFUSED: Final = "decision_inputs_refused"

# The six input-refusal types of the Phase 44 to 49 builders (the Phase 49 route catches exactly
# these). All derive from ``ValueError``, but ``ValueError`` itself is deliberately not caught.
KNOWN_BUILDER_REFUSALS: Final[tuple[type[Exception], ...]] = (
    InvalidSnapshotError,
    ConfirmationInputError,
    OpportunityInputError,
    RankingInputError,
    RiskInputError,
    InvestmentInputError,
)
_KNOWN_NAMES: Final = frozenset(cls.__name__ for cls in KNOWN_BUILDER_REFUSALS)


class StoredSnapshotRow(Protocol):
    """One stored ``ai.snapshot`` row, as the repository's snapshot read returns it."""

    @property
    def row_id(self) -> int: ...
    @property
    def uuid(self) -> str: ...
    @property
    def payload_hash(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def as_of(self) -> datetime: ...
    @property
    def knowledge_time(self) -> datetime: ...
    @property
    def payload(self) -> dict[str, Any]: ...


class SnapshotReader(Protocol):
    """What the adapter needs from storage: one snapshot row by id, or ``None``."""

    async def get_snapshot(self, snapshot_id: int) -> StoredSnapshotRow | None: ...


@dataclass(frozen=True, slots=True)
class AdapterOutcome:
    """A usable decision with the stored identity, or a refusal. Never both, never neither."""

    decision: dict[str, Any] | None
    identity: StoredSnapshotIdentity | None
    refusal_reason: str | None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.refusal_reason is None:
            if (
                not isinstance(self.decision, dict)
                or not isinstance(self.identity, StoredSnapshotIdentity)
                or self.detail is not None
            ):
                raise InvestmentAlertValidationError("a success has a decision and an identity")
            return
        if self.refusal_reason not in ADAPTER_REFUSAL_REASONS:
            raise InvestmentAlertValidationError("unknown adapter refusal reason")
        if self.decision is not None or self.identity is not None:
            raise InvestmentAlertValidationError("a refusal carries no decision and no identity")
        if (self.refusal_reason == INPUTS_REFUSED) != (self.detail is not None):
            raise InvestmentAlertValidationError("only decision_inputs_refused has a detail")
        if self.detail is not None and self.detail not in _KNOWN_NAMES:
            raise InvestmentAlertValidationError("detail is a known exception class name only")

    @property
    def refused(self) -> bool:
        return self.refusal_reason is not None


def _refuse(reason: str, detail: str | None = None) -> AdapterOutcome:
    return AdapterOutcome(decision=None, identity=None, refusal_reason=reason, detail=detail)


# Run-time type tests take ``object`` so they stay meaningful for values that bypass static types.
def _not_plain_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)


def _is_plain_int(value: object) -> TypeGuard[int]:
    return not _not_plain_int(value)


def _is_clean_str(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _is_datetime(value: object) -> TypeGuard[datetime]:
    return isinstance(value, datetime)


def _validated_identity(
    row: object, snapshot_id: int
) -> tuple[SnapshotRef, StoredSnapshotIdentity, dict[str, Any]] | None:
    """The identity and payload of the row, or ``None`` if anything is unusable (no builder ran)."""
    row_id = getattr(row, "row_id", None)
    uuid = getattr(row, "uuid", None)
    payload_hash = getattr(row, "payload_hash", None)
    created_at = getattr(row, "created_at", None)
    as_of = getattr(row, "as_of", None)
    knowledge_time = getattr(row, "knowledge_time", None)
    payload = getattr(row, "payload", None)
    if (
        not _is_plain_int(row_id)
        or row_id != snapshot_id
        or not _is_clean_str(uuid)
        or not _is_clean_str(payload_hash)
        or not _is_datetime(created_at)
        or not _is_datetime(as_of)
        or not _is_datetime(knowledge_time)
        or not isinstance(payload, dict)
    ):
        return None
    ref = SnapshotRef(row_id=row_id, uuid=uuid, payload_hash=payload_hash, created_at=created_at)
    identity = StoredSnapshotIdentity(
        row_id=row_id,
        uuid=uuid,
        payload_hash=payload_hash,
        as_of=as_of,
        knowledge_time=knowledge_time,
    )
    return ref, identity, payload


def _known_name(exc: Exception) -> str:
    for cls in KNOWN_BUILDER_REFUSALS:
        if isinstance(exc, cls):
            return cls.__name__
    raise InvestmentAlertValidationError("not a known builder refusal")  # unreachable by design


def build_decision_from_row(row: StoredSnapshotRow | None, snapshot_id: int) -> AdapterOutcome:
    """Build ``investment_decision.v0`` from one stored row. Synchronous and pure.

    The builders are the public Phase 44 to 49 functions, called in the order of the Phase 49
    route. The payload is passed through unchanged (the builders do not mutate it). Only the six
    known input-refusal types become ``decision_inputs_refused``; anything else propagates.
    """
    if _not_plain_int(snapshot_id):
        raise InvestmentAlertValidationError("snapshot_id must be a plain integer")
    if row is None:
        return _refuse(NOT_FOUND)
    checked = _validated_identity(row, snapshot_id)
    if checked is None:
        return _refuse(ROW_INVALID)
    ref, identity, payload = checked
    try:
        unified = build_unified_snapshot(payload, snapshot_ref=ref)
        opportunities = build_opportunities(unified, build_confirmation(unified))
        ranking = build_ranking(opportunities)
        view = build_risk_view(payload, snapshot_ref=ref)
        risk = build_risk_invalidation(opportunities, ranking, view)
        decision = build_investment_decision(opportunities, ranking, risk, view)
    except KNOWN_BUILDER_REFUSALS as exc:
        return _refuse(INPUTS_REFUSED, _known_name(exc))
    return AdapterOutcome(decision=decision, identity=identity, refusal_reason=None)


async def read_and_build(reader: SnapshotReader, snapshot_id: int) -> AdapterOutcome:
    """Read the cycle's stored snapshot (exactly once) and build its decision.

    A reader error, a cancellation and any execution-control exception propagate unchanged.
    """
    if _not_plain_int(snapshot_id):
        raise InvestmentAlertValidationError("snapshot_id must be a plain integer")
    row = await reader.get_snapshot(snapshot_id)
    return build_decision_from_row(row, snapshot_id)
