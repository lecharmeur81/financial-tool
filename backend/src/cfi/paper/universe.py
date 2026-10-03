"""Fixed vocabulary for paper trading (Phase 24 spec "Trade lifecycle" / "Core paper-trading
record").

Reuses, unchanged: ``cfi.market.universe.ASSET_SYMBOLS`` (the platform's only tracked assets — a
paper trade may not be opened on an asset the rest of the platform has no price series for) and
``cfi.backtest.costs`` (the versioned fee/slippage model; see that module's own docstring for why
its parameter sets are not duplicated here).
"""

from __future__ import annotations

from cfi.backtest.costs import CURRENT_VERSION as DEFAULT_COST_MODEL_VERSION
from cfi.market.universe import ASSET_SYMBOLS

__all__ = [
    "ASSET_SYMBOLS",
    "DEFAULT_COST_MODEL_VERSION",
    "DIRECTION_VALUES",
    "PAPER_TRADE_SCHEMA_VERSION",
    "RELEVANT_ALERTS_LIMIT",
    "STATUS_VALUES",
    "VALID_TRANSITIONS",
]

PAPER_TRADE_SCHEMA_VERSION = "paper_trade.v1"

# ("Trade lifecycle": "Use clear states such as OPEN, CLOSED, CANCELLED. Only implement
# additional states if required by the existing architecture." — no additional state is
# required, so these three are exhaustive.)
STATUS_VALUES: tuple[str, ...] = ("open", "closed", "cancelled")

DIRECTION_VALUES: tuple[str, ...] = ("long", "short")

# The only transitions this service will execute ("Prevent invalid transitions"): a trade may be
# closed or cancelled exactly once, from ``open``, and never re-opened, re-closed, or
# re-cancelled afterward (every other combination — closing a cancelled trade, cancelling a
# closed trade, closing/cancelling a trade twice — is rejected).
VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("closed", "cancelled"),
    "closed": (),
    "cancelled": (),
}

# How many currently-active alerts ("Integration with existing intelligence": "Allow each paper
# trade to retain references to the relevant: ... Alert(s)") are captured as contextual evidence
# at decision time. A cap, not a filter by relevance (this phase has no relevance-ranking model
# of its own to invent, R3) — matches the existing ``GET /api/v1/alerts`` endpoint's own default
# page size (``cfi.api.routes.alerts.list_alerts``).
RELEVANT_ALERTS_LIMIT = 50
