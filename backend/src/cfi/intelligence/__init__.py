"""Unified Intelligence Snapshot (Phase 44; ADR-0081).

A pure, read-only projection of one stored ``ai.snapshot`` payload. See ``unified_snapshot``."""

from cfi.intelligence.confirmation import (
    ConfirmationInputError,
    build_confirmation,
)
from cfi.intelligence.opportunity import OpportunityInputError, build_opportunities
from cfi.intelligence.ranking import RankingInputError, build_ranking
from cfi.intelligence.risk import RiskInputError, build_risk_invalidation
from cfi.intelligence.risk_view import build_risk_view
from cfi.intelligence.unified_snapshot import (
    CONTRACT_VERSION,
    build_unified_snapshot,
)

__all__ = [
    "CONTRACT_VERSION",
    "ConfirmationInputError",
    "OpportunityInputError",
    "RankingInputError",
    "RiskInputError",
    "build_confirmation",
    "build_opportunities",
    "build_ranking",
    "build_risk_invalidation",
    "build_risk_view",
    "build_unified_snapshot",
]
