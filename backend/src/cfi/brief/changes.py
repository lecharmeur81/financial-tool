"""Change detection (Phase 22 spec, Section 5): compare the current snapshot's own fields against
the snapshot payload stored on the previous *valid* (``completed``) brief, and nothing else.

There is no live "re-run the pipeline and diff" comparison and no second calculation path: the
previous brief's own stored ``ai.snapshot.payload`` (already reproducible, ADR-0041) is the sole
comparison basis, so "what changed" is always traceable back to two concrete, already-persisted
snapshots. When no previous completed brief exists yet, there is no defined comparison basis at
all — ``comparison_basis="none"`` — and ``cfi.brief.validator`` then refuses any ``change_ids``
citation anywhere in the response (Section 5: "do not call something a meaningful change without a
defined comparison basis").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from cfi.analyst.snapshot import Snapshot

ComparisonBasis = Literal["previous_brief", "none"]


@dataclass(frozen=True, slots=True)
class FieldChange:
    change_id: str
    field_id: str
    previous_display: str | None  # None means the field is new (absent from the previous snapshot)
    current_display: str
    delta: str | None  # numeric delta as a string, when both sides parse as numbers; else None


@dataclass(frozen=True, slots=True)
class ChangeSet:
    comparison_basis: ComparisonBasis
    changes: list[FieldChange] = field(default_factory=list)
    change_index: dict[str, FieldChange] = field(default_factory=dict)

    def is_valid_change_id(self, change_id: str) -> bool:
        return change_id in self.change_index


def compute_changes(current: Snapshot, previous_payload: dict[str, Any] | None) -> ChangeSet:
    """Diff ``current``'s own fields against a previous brief's stored snapshot payload fields.

    Only fields whose ``display`` text actually differs are reported (Section 5: the brief must
    focus on what changed, not repeat the entire dashboard) — a field present and unchanged is not
    a change. A field present now but absent from the previous snapshot is reported as a change
    with ``previous_display=None`` (a newly populated metric is itself a meaningful change, e.g. a
    newly detected anomaly or a newly surfaced divergence, Section 5's own examples)."""
    if previous_payload is None:
        return ChangeSet(comparison_basis="none")

    previous_fields: dict[str, dict[str, Any]] = previous_payload.get("fields") or {}
    changes: list[FieldChange] = []
    for f in current.fields:
        prev = previous_fields.get(f.field_id)
        prev_display = prev.get("display") if prev else None
        if prev_display == f.display:
            continue
        changes.append(
            FieldChange(
                change_id=f"chg.{f.field_id}",
                field_id=f.field_id,
                previous_display=prev_display,
                current_display=f.display,
                delta=_numeric_delta(prev_display, f.display),
            )
        )
    index = {c.change_id: c for c in changes}
    return ChangeSet(comparison_basis="previous_brief", changes=changes, change_index=index)


def _numeric_delta(previous: str | None, current: str) -> str | None:
    if previous is None:
        return None
    try:
        return str(Decimal(current) - Decimal(previous))
    except InvalidOperation:
        return None
