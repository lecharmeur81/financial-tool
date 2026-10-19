"""Deduplication / cooldown / re-arm decision (Phase 23 spec "Deduplication / Cooldown").

Pure and database-free by construction: it takes the last stored alert for a dedup key (if any)
and a freshly evaluated candidate, and returns what should happen — never touching the database
itself (``cfi.alerts.repository.AlertRepository`` executes the decision). This is what makes
dedup/cooldown/re-arm behavior testable without a reachable database (none exists anywhere this
phase has been built, same as every prior phase)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Action = Literal["create", "skip_unchanged", "skip_cooldown", "rearm"]


@dataclass(frozen=True, slots=True)
class ExistingAlert:
    """The minimal shape of the most recent non-terminal (``active``/``acknowledged``) alert
    previously stored for one dedup key — read by the repository, decided on here."""

    observed_value: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class Candidate:
    """The minimal shape of a freshly evaluated alert candidate needed to decide its fate."""

    observed_value: str


def decide(
    existing: ExistingAlert | None,
    candidate: Candidate,
    *,
    now: datetime,
    cooldown_seconds: float,
) -> Action:
    """Decide what to do with ``candidate`` given the dedup key's most recent non-terminal alert.

    - No prior alert for this key at all -> ``create`` (first observation establishes the record).
    - A prior alert exists and its observed value is identical -> ``skip_unchanged`` ("do not
      repeatedly generate the same alert while the underlying condition remains unchanged").
    - A prior alert exists, the value differs (the condition has moved to a new state), but the
      cooldown window since that alert has not yet elapsed -> ``skip_cooldown`` (alert-spam
      protection).
    - A prior alert exists, the value differs, and the cooldown window has elapsed -> ``rearm``
      (the caller creates a new alert and marks the prior one superseded)."""
    if existing is None:
        return "create"
    if existing.observed_value == candidate.observed_value:
        return "skip_unchanged"
    elapsed = (now - existing.timestamp).total_seconds()
    if elapsed < cooldown_seconds:
        return "skip_cooldown"
    return "rearm"


# ---------------------------------------------------------------------------------------------
# User-driven status transitions (Phase 52). Pure, like ``decide``.
#
#   active ──acknowledge──▶ acknowledged ──resolve──▶ resolved      (terminal)
#      └────────────────────resolve──────────────────▶ resolved
#   expired (set only by a re-arm supersede) is terminal.
#
# A request for the status an alert already has is a no-op (idempotent: no timestamp is rewritten,
# R10 audit history). A terminal alert is never reopened or re-stamped. ``insufficient_evidence``
# and every other evaluation outcome stay outside this table: it only judges what a *user* may do.
OPEN_STATUSES: tuple[str, ...] = ("active", "acknowledged")

TransitionVerdict = Literal["apply", "noop", "reject"]

_USER_TARGET_SOURCES: dict[str, tuple[str, ...]] = {
    "acknowledged": ("active",),
    "resolved": ("active", "acknowledged"),
}


def user_transition_sources(target: str) -> tuple[str, ...]:
    """Statuses from which a user may move an alert to ``target`` (empty if not user-settable)."""
    return _USER_TARGET_SOURCES.get(target, ())


def user_transition(current: str, target: str) -> TransitionVerdict:
    """``apply`` a permitted change, ``noop`` if the alert already has ``target`` (idempotent),
    ``reject`` anything else (terminal source, unknown status, or a target a user cannot set)."""
    if target not in _USER_TARGET_SOURCES:
        return "reject"
    if current == target:
        return "noop"
    return "apply" if current in _USER_TARGET_SOURCES[target] else "reject"
