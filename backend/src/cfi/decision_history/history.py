"""History entries from persisted assessments (Phase 41): pairing, states and ordering rules.

Pure. Input is the persisted assessments of ONE scope, newest first by ``snapshot_id`` (the order in
which the system recorded them; the same definition of "current" the Phase 39 endpoint uses - the
caller-supplied ``as_of`` never reorders anything). Each entry is compared with the row immediately
before it:

* no row before it                              -> ``No Previous Assessment``;
* the row before it has a different methodology
  or parameter version                          -> ``Not Comparable (version change)``;
* otherwise                                     -> ``Compared`` (``compare_assessments``).

``template_version`` is provenance, not identity (ADR-0076, D-M), so it never blocks a comparison.
``out_of_order_as_of`` is true when an entry's ``snapshot_as_of`` is earlier than its predecessor's:
the timestamp is reported as stored and never used to reorder or hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Any

from cfi.decision_history.compare import AssessmentChange, PersistedAssessment, compare_assessments

__all__ = [
    "HISTORY_CONTRACT_VERSION",
    "HistoryEntry",
    "HistoryState",
    "build_history",
]

HISTORY_CONTRACT_VERSION = "decision_history.v0"


class HistoryState(StrEnum):
    COMPARED = "Compared"
    NO_PREVIOUS = "No Previous Assessment"
    NOT_COMPARABLE = "Not Comparable (version change)"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    assessment: PersistedAssessment
    state: HistoryState
    previous_snapshot_id: int | None
    out_of_order_as_of: bool
    change: AssessmentChange | None
    # Set only for ``Not Comparable``: what differed between the two rows' identities.
    previous_methodology_version: str | None = None
    previous_parameter_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        a = self.assessment
        return {
            "snapshot_id": a.snapshot_id,
            "snapshot_as_of": a.snapshot_as_of.isoformat(),
            "recorded_at": a.created_at.isoformat(),
            "stance": a.stance,
            "confidence": a.confidence,
            "posture": a.posture,
            "decision_input_hash": a.decision_input_hash,
            "producer_hash_check": a.producer_hash_check,
            "methodology_version": a.methodology_version,
            "parameter_version": a.parameter_version,
            "template_version": a.template_version,
            "state": self.state.value,
            "previous_snapshot_id": self.previous_snapshot_id,
            "previous_methodology_version": self.previous_methodology_version,
            "previous_parameter_version": self.previous_parameter_version,
            "out_of_order_as_of": self.out_of_order_as_of,
            "change": None if self.change is None else self.change.to_dict(),
        }


def _entry(current: PersistedAssessment, previous: PersistedAssessment | None) -> HistoryEntry:
    if previous is None:
        return HistoryEntry(current, HistoryState.NO_PREVIOUS, None, False, None)
    out_of_order = current.snapshot_as_of < previous.snapshot_as_of
    if (current.methodology_version, current.parameter_version) != (
        previous.methodology_version,
        previous.parameter_version,
    ):
        return HistoryEntry(
            current,
            HistoryState.NOT_COMPARABLE,
            previous.snapshot_id,
            out_of_order,
            None,
            previous.methodology_version,
            previous.parameter_version,
        )
    return HistoryEntry(
        current,
        HistoryState.COMPARED,
        previous.snapshot_id,
        out_of_order,
        compare_assessments(previous, current),
    )


def build_history(rows: Sequence[PersistedAssessment], *, limit: int) -> tuple[HistoryEntry, ...]:
    """Entries for the newest ``limit`` rows. ``rows`` is one scope, newest first by
    ``snapshot_id``; it may hold one extra, older row so the oldest returned entry has its
    predecessor. Raises ``ValueError`` for a mixed-scope or mis-ordered input."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if len({r.scope for r in rows}) > 1:
        raise ValueError("history rows must all belong to one scope")
    ids = [r.snapshot_id for r in rows]
    if any(a <= b for a, b in pairwise(ids)):
        raise ValueError("history rows must be strictly newest-first by snapshot_id")
    return tuple(
        _entry(rows[i], rows[i + 1] if i + 1 < len(rows) else None)
        for i in range(min(limit, len(rows)))
    )
