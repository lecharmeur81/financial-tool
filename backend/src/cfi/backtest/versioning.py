"""Reproducibility record (Phase 16): every backtest run stores exactly what the user's spec
requires — strategy version, parameter version, dataset version, code version, timestamp, and
assumptions — so a later reader can tell precisely what produced a given result, without re-running
it, and can judge whether it is still reproducible (e.g. if the code version has since changed).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


def code_version() -> str:
    """The installed ``cfi`` package version (``pyproject.toml``'s ``[project].version``) — the
    closest honest, non-fabricated stand-in for a git commit hash available from inside the
    running process itself."""
    try:
        return importlib.metadata.version("cfi")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover — always installed in dev
        return "unknown"


def dataset_version(
    *,
    asset: str,
    start: datetime,
    end: datetime,
    as_of: datetime,
    knowledge_time: datetime,
    provider_id: str,
) -> str:
    """A deterministic fingerprint of exactly which slice of price history a run used — the same
    inputs always produce the same fingerprint, so two runs can be compared for whether they used
    the same data, without storing the bars themselves a second time (they are already stored, in
    full, in ``obs.market_bar``)."""
    key = "|".join(
        (
            asset,
            start.isoformat(),
            end.isoformat(),
            as_of.isoformat(),
            knowledge_time.isoformat(),
            provider_id,
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RunVersions:
    strategy_id: str
    strategy_version: str
    parameter_version: str  # the cost model version used
    dataset_version: str
    code_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Assumptions:
    """Every documented modeling assumption behind a run's numbers — restated in full on every
    result so nothing is implicit (R1: never present uncertain inference as fact)."""

    asset: str
    start: datetime
    end: datetime
    as_of: datetime
    knowledge_time: datetime
    initial_capital: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    max_participation_pct: Decimal
    risk_free_rate_annual: Decimal
    execution_lag: str = (
        "signal-driven entries/exits execute at the FOLLOWING bar's open, never the deciding "
        "bar's own close; stop-loss/take-profit trigger intrabar against that day's own high/low "
        "and fill at the stop/take-profit level — UNLESS that day's own open already gapped "
        "through the level, in which case the fill is at that (slipped) open instead, since that "
        "is the worst price a real order could have achieved that day (ADR-0061, finding #3)"
    )
    liquidity_sizing_note: str = (
        "position size is capped using the TRAILING average volume through the decision day, "
        "never the execution bar's own (not yet known) volume"
    )
    sizing_price_gap_note: str = (
        "position size (a fixed base-asset quantity) is computed from the decision day's CLOSE, "
        "but the order fills at the FOLLOWING day's open — a different price. Realized notional, "
        "leverage and exposure at the moment of execution can therefore differ from what was "
        "targeted when risk_limits/liquidity_cap were checked, by the size of the overnight gap. "
        "This is a documented modeling approximation (standard event-driven-backtest practice), "
        "not a re-checked-at-fill guarantee (RED_TEAM_REPORT.md finding #11)"
    )
    slippage_participation_note: str = (
        "slippage scales with this trade's notional as a fraction of the day's liquidity cap "
        "(participation_fraction, clamped to [0, 1]) when the cost model's "
        "participation_impact_coefficient is non-zero; cost_model_v1 is flat (coefficient 0) for "
        "backward reproducibility, cost_model_v2 (the current default) is convex "
        "(RED_TEAM_REPORT.md finding #5)"
    )
    extra: dict[str, Any] = field(default_factory=dict)
