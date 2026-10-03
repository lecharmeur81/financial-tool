"""Decision review and basic statistics (Phase 25 spec "Decision review" / "API": "Review
historical decisions" / "Basic decision statistics") — pure functions over already-persisted
rows, computed live rather than a separately maintained counter (R3, same posture as
``cfi.paper.stats.performance_stats``).

Both are **descriptive only**. Neither module ranks decision types, scores a "best" thesis, or
produces anything resembling a recommendation — the spec is explicit: "These are descriptive
statistics, not recommendations... Do not produce a 'best strategy' or rank the user's
decisions." What is *not* computed here is as deliberate as what is."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionStats:
    total_decisions: int
    open_decisions: int
    resolved_decisions: int
    invalidated_decisions: int
    cancelled_decisions: int
    thesis_supported_count: int
    thesis_contradicted_count: int
    invalidation_occurred_count: int
    average_time_to_resolution_hours: Decimal | None


@dataclass(frozen=True, slots=True)
class DecisionReview:
    decisions_by_type: dict[str, int]
    decisions_by_regime: dict[str, int]
    decisions_by_invalidation_condition: dict[str, int]
    decisions_by_outcome: dict[str, int]


def decision_stats(rows: list[dict[str, Any]]) -> DecisionStats:
    counts = Counter(r["status"] for r in rows)
    resolved = [r for r in rows if r["status"] in ("resolved", "invalidated")]

    durations: list[Decimal] = []
    for r in resolved:
        if r.get("decision_time") and r.get("outcome_timestamp"):
            decision_time: datetime = r["decision_time"]
            outcome_timestamp: datetime = r["outcome_timestamp"]
            hours = Decimal(str((outcome_timestamp - decision_time).total_seconds() / 3600))
            durations.append(hours)
    average_hours = sum(durations, Decimal(0)) / len(durations) if durations else None

    return DecisionStats(
        total_decisions=len(rows),
        open_decisions=counts.get("open", 0),
        resolved_decisions=counts.get("resolved", 0),
        invalidated_decisions=counts.get("invalidated", 0),
        cancelled_decisions=counts.get("cancelled", 0),
        thesis_supported_count=sum(1 for r in rows if r.get("thesis_supported") is True),
        thesis_contradicted_count=sum(1 for r in rows if r.get("thesis_contradicted") is True),
        invalidation_occurred_count=sum(1 for r in rows if r.get("invalidation_occurred") is True),
        average_time_to_resolution_hours=average_hours,
    )


def decision_review(rows: list[dict[str, Any]]) -> DecisionReview:
    """Exact-match grouping only — free-text fields (``decision_type``,
    ``invalidation_condition``) are grouped by their literal stored string, never clustered or
    semantically matched (no NLP is attempted here or anywhere else in this phase, R3: a
    fabricated grouping would be worse than an honestly narrow one)."""
    by_type = Counter(r["decision_type"] for r in rows if r.get("decision_type"))
    by_regime = Counter(
        r["market_regime_label"] for r in rows if r.get("market_regime_label") is not None
    )
    by_invalidation = Counter(
        r["invalidation_condition"] for r in rows if r.get("invalidation_condition")
    )
    by_outcome = Counter(r["outcome"] for r in rows if r.get("outcome"))
    return DecisionReview(
        decisions_by_type=dict(by_type),
        decisions_by_regime=dict(by_regime),
        decisions_by_invalidation_condition=dict(by_invalidation),
        decisions_by_outcome=dict(by_outcome),
    )
