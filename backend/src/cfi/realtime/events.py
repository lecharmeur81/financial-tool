"""Pure helpers for turning one ``cfi.alerts.service.CandidateDecision`` into the extra fields an
intelligence event stores that an alert row alone does not (Phase 35). No I/O, no database — same
discipline as ``cfi.alerts.rules``/``cfi.alerts.lifecycle`` (R13: testable without a reachable
database)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from cfi.alerts.service import CandidateDecision


def detection_method_for(alert_type: str) -> str:
    """Which deterministic engine/rule produced this candidate — ``cfi.alerts.rules`` already
    names one evaluator function per alert type 1:1, so the method name is derived from that
    existing mapping rather than a second, parallel one (R13)."""
    return f"cfi.alerts.rules.evaluate_{alert_type}"


def change_magnitude(previous_value: str | None, current_value: str) -> Decimal | None:
    """The numeric difference between the previous and current observed value, when both happen
    to be parseable as numbers. Most domains report categorical band labels (e.g.
    ``"notable_high"``), for which this is correctly ``None`` ("where applicable" — the schema
    never fabricates a magnitude for a non-numeric transition, R3)."""
    if previous_value is None:
        return None
    try:
        return Decimal(current_value) - Decimal(previous_value)
    except (InvalidOperation, ValueError):
        return None


def correlation_key_for(snapshot_id: int) -> str:
    """Every event produced by the same evaluation cycle was read from the same evidence
    snapshot, so grouping by ``snapshot_id`` is a simple, deterministic stand-in for "these
    readings co-occurred" (the spec's own "simple correlation/group identifier... is sufficient
    for this phase" — no graph database, no bespoke time-window heuristic)."""
    return f"snapshot:{snapshot_id}"


def is_meaningful_decision(decision: CandidateDecision) -> bool:
    """Only a ``create``/``rearm`` decision is a meaningful state transition worth an event —
    ``skip_unchanged``/``skip_cooldown`` are exactly the noise
    ``cfi.alerts.lifecycle.decide`` already filters out (never re-detected here, R13)."""
    return decision.action in ("create", "rearm")
