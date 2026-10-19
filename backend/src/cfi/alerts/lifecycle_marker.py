"""Lifecycle marker: has an alert's state ended, or can it not be evaluated now? (Phase 52, P3.)

Owner-approved scope (METHODOLOGY_INVESTMENT_ALERTS.md §18.1 P3, marker only): a *read-time,
derived* label. Nothing is stored, no status is added or changed, no alert is resolved, expired,
reopened or re-stamped, and no age threshold is applied. The marker is computed on demand from the
alert row and ONE stored evaluation snapshot (the latest ``ai.snapshot``), by re-running the same
pure rules (``cfi.alerts.rules.evaluate_all``) the evaluation cycle uses. Persistence of
investment alerts stays disabled; investment alerts get ``not_evaluated`` (no evaluator here).

Five kinds, kept apart on purpose:

- ``still_holds``          evaluated against the snapshot; the recorded state is still current.
- ``state_ended``          evaluated against the snapshot; the recorded state is no longer current
                           (the value moved, or the snapshot explicitly shows a flagged condition
                           cleared).
- ``cannot_be_evaluated``  the snapshot cannot say: the source tool did not run, or the evaluator
                           withheld a reading (missing / unusable component). This is NOT "ended"
                           and NOT "invalidated": the alert's status is left alone.
- ``not_evaluated``        no usable evaluation was available (no snapshot, unreadable payload, or
                           an alert type this module has no evaluator for).
- ``closed``               the alert is already ``resolved``/``expired``; status is authoritative.

Limits (documented, not hidden): "stale" and "contradictory" evidence are recognised only through
the evaluators' existing unusable-component statuses and the source tool's own status; this module
adds no freshness or conflict rule. A ``still_holds`` reading is as of the snapshot named in the
marker, which may itself be old if the evaluation cycle is not running.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cfi.alerts.lifecycle import OPEN_STATUSES
from cfi.alerts.rules import AlertCandidate, _tool_data, cleared_dedup_keys, evaluate_all
from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS
from cfi.analyst.snapshot import Snapshot

__all__ = [
    "FLAGGED_STATE_TYPES",
    "CurrentEvaluation",
    "LifecycleMarker",
    "MarkerKind",
    "build_current_evaluation",
    "derive_marker",
]

MarkerKind = Literal["still_holds", "state_ended", "cannot_be_evaluated", "not_evaluated", "closed"]

# Alert types whose evaluator emits a candidate ONLY while its flag is positive; mirrors
# ``cfi.alerts.service._FLAGGED_STATE_TYPES`` (a unit test pins the two together).
FLAGGED_STATE_TYPES: tuple[str, ...] = ("divergence", "anomaly", "capital_rotation")


@dataclass(frozen=True, slots=True)
class LifecycleMarker:
    kind: MarkerKind
    reason: str
    evaluated_snapshot_id: int | None = None
    evaluated_as_of: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentEvaluation:
    """One stored snapshot, evaluated once, reusable for any number of alerts."""

    snapshot_id: int | None
    as_of: str
    snapshot: Snapshot
    candidates: Mapping[str, AlertCandidate]  # by dedup_key
    cleared: frozenset[str] = frozenset()  # explicit clearance evidence (rules.cleared_dedup_keys)


def build_current_evaluation(
    snapshot_id: int | None, payload: Mapping[str, Any] | None
) -> CurrentEvaluation | None:
    """Evaluate a stored ``ai.snapshot.payload``; ``None`` if it cannot be read (never raises).

    The rules read only ``Snapshot.raw`` (the payload's ``tool_results``), so the other Snapshot
    fields are filled from the payload without rebuilding the evidence field list."""
    try:
        if payload is None:
            return None
        raw = payload["tool_results"]
        if not isinstance(raw, dict):
            return None
        as_of = datetime.fromisoformat(str(payload["as_of"]))
        knowledge_time = datetime.fromisoformat(str(payload["knowledge_time"]))
        snapshot = Snapshot(
            snapshot_id=str(snapshot_id),
            snapshot_version=str(payload["snapshot_version"]),
            created_at=as_of,
            as_of=as_of,
            knowledge_time=knowledge_time,
            question=None,
            tools_called=list(payload.get("tools_called") or []),
            fields=[],
            field_index={},
            raw=raw,
            data_quality_state=str(payload.get("data_quality_state", "unknown")),
            has_conflicts=bool(payload.get("has_conflicts", False)),
        )
        candidates = {c.dedup_key: c for c in evaluate_all(snapshot)}
        cleared = cleared_dedup_keys(snapshot)
    except Exception:  # advisory label: an unreadable snapshot must never break a read
        return None
    return CurrentEvaluation(snapshot_id, as_of.isoformat(), snapshot, candidates, cleared)


def derive_marker(alert: Mapping[str, Any], current: CurrentEvaluation | None) -> LifecycleMarker:
    """The marker for one stored alert row, given one evaluation (or ``None``). Pure."""
    if alert["status"] not in OPEN_STATUSES:
        return LifecycleMarker(
            "closed", f"Alert is {alert['status']}; its status is authoritative and unchanged."
        )
    if current is None:
        return LifecycleMarker("not_evaluated", "No readable evaluation snapshot was available.")
    alert_type = alert["alert_type"]
    if alert_type not in ALERT_TYPE_TOOL_IDS:
        return LifecycleMarker(
            "not_evaluated",
            f"No evaluator is available here for alert type {alert_type!r}.",
            current.snapshot_id,
            current.as_of,
        )

    def marker(kind: MarkerKind, reason: str) -> LifecycleMarker:
        return LifecycleMarker(kind, reason, current.snapshot_id, current.as_of)

    match = current.candidates.get(alert["dedup_key"])
    if match is not None:
        if match.observed_value == alert["observed_value"]:
            return marker("still_holds", "The recorded state is still the current reading.")
        return marker(
            "state_ended",
            f"The recorded state {alert['observed_value']!r} is no longer current "
            f"(now {match.observed_value!r}). The alert is not invalidated by this.",
        )
    if _tool_data(current.snapshot, alert["source_tool_id"]) is None:
        return marker(
            "cannot_be_evaluated",
            "The source tool has no usable result in the snapshot; the state is unknown, "
            "not ended.",
        )
    if alert_type in FLAGGED_STATE_TYPES and alert["dedup_key"] in current.cleared:
        return marker("state_ended", "The snapshot explicitly shows the flagged condition cleared.")
    return marker(
        "cannot_be_evaluated",
        "The evaluator gave no usable or explicitly clearing reading for this item (missing, "
        "unavailable or insufficient evidence); the state is unknown, not ended.",
    )
