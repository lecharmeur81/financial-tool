"""The shared, read-only step: one stored snapshot payload to ``investment_decision.v0``.

Extracted unchanged from ``GET /api/v1/advisor/brief`` (Phase 53) so that the portfolio exposure
view (Phase 54) briefs several assets from one snapshot without a second copy of the pipeline. It
is a pure function of its arguments: no database, no network, no clock, no Claude."""

from __future__ import annotations

from typing import Any

from cfi.decision.identity import SnapshotRef
from cfi.intelligence import (
    build_confirmation,
    build_investment_decision,
    build_opportunities,
    build_ranking,
    build_risk_invalidation,
    build_risk_view,
    build_unified_snapshot,
)

__all__ = ["build_investment_decision_for"]


def build_investment_decision_for(
    payload: dict[str, Any], snapshot_ref: SnapshotRef
) -> dict[str, Any]:
    """``investment_decision.v0`` for every asset in ``payload`` (the asset-independent part)."""
    unified = build_unified_snapshot(payload, snapshot_ref=snapshot_ref)
    opportunities = build_opportunities(unified, build_confirmation(unified))
    ranking = build_ranking(opportunities)
    risk_view = build_risk_view(payload, snapshot_ref=snapshot_ref)
    risk = build_risk_invalidation(opportunities, ranking, risk_view)
    return build_investment_decision(opportunities, ranking, risk, risk_view)
