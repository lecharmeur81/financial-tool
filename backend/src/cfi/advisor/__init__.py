"""Advisor Brief (Phase 53, ADR-0093): a deterministic evidence pack for one asset.

Pure composition of two existing, already-tested contracts built from ONE stored snapshot: the
Decision Center view (``decision_view.v0``) and the investment decision
(``investment_decision.v0``).
It adds no score, stance, threshold or rule; it relabels, groups and links what those contracts
already say. See ``brief``."""

from cfi.advisor.brief import (
    CONTRACT_VERSION,
    NOT_CLAIMED,
    AdvisorInputError,
    build_advisor_brief,
)

__all__ = ["CONTRACT_VERSION", "NOT_CLAIMED", "AdvisorInputError", "build_advisor_brief"]
