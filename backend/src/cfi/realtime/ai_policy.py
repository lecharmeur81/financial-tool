"""The AI-trigger policy (Phase 35): which intelligence events, if any, are worth asking Claude
about. Pure and database-free (R13, same discipline as ``cfi.alerts.rules``) — the one, separate
"has it been too soon since the last request" check that genuinely needs the database (how
recently an AI request was last made) lives in ``cfi.realtime.service``, not here."""

from __future__ import annotations

from cfi.alerts.service import CandidateDecision
from cfi.realtime.events import is_meaningful_decision
from cfi.realtime.universe import AI_TRIGGER_SEVERITIES

# The same "no usable reading" vocabulary ``cfi.alerts.rules`` already uses (R13: reuse, not a
# second status vocabulary) — an event built from a component that did not actually run cleanly
# is not "sufficiently data-rich" enough to spend a Claude call on.
_UNUSABLE_STATUSES = frozenset({"insufficient_data", "unavailable", "not_applicable"})


def significant_decisions(decisions: tuple[CandidateDecision, ...]) -> list[CandidateDecision]:
    """Which of this cycle's create/rearm decisions are significant enough to even be considered
    for AI analysis: sufficiently severe (``AI_TRIGGER_SEVERITIES``) and sufficiently data-rich
    (the triggering component itself reported ``ok``, never a stand-in for missing data, R3)."""
    return [
        d
        for d in decisions
        if is_meaningful_decision(d)
        and d.candidate.severity in AI_TRIGGER_SEVERITIES
        and d.candidate.component_status not in _UNUSABLE_STATUSES
    ]


def question_for(decision: CandidateDecision) -> str:
    """A short, grounded question for the Claude Analyst to answer about one significant
    transition — reuses the candidate's own already-disclosed trigger condition and values
    (never a second description of the same fact, R13); the Analyst's existing tools/snapshot
    pipeline (Phase 21, unchanged) is what actually answers it."""
    c = decision.candidate
    previous = decision.previous_observed_value
    was_clause = f" (was {previous!r})" if previous else ""
    return (
        f"{c.trigger_condition}. Observed value is now {c.observed_value!r}{was_clause}."
        " What does the available evidence say about this change?"
    )
