"""Fixed vocabulary for the Decision Journal (Phase 25 spec "Status" / "Hindsight protection").

Reuses, unchanged: ``cfi.market.universe.ASSET_SYMBOLS`` (which journaled assets qualify for an
auto-captured observed price — any other asset/market name is still a valid journal entry, just
without that optional field) and ``cfi.paper.universe.RELEVANT_ALERTS_LIMIT`` (the same cap on how
many currently-active alerts are captured as decision-time context, R13: no second constant for
the same policy).
"""

from __future__ import annotations

from cfi.market.universe import ASSET_SYMBOLS
from cfi.paper.universe import RELEVANT_ALERTS_LIMIT

__all__ = [
    "ASSET_SYMBOLS",
    "DECISION_JOURNAL_SCHEMA_VERSION",
    "RELEVANT_ALERTS_LIMIT",
    "STATUS_VALUES",
    "VALID_TRANSITIONS",
]

DECISION_JOURNAL_SCHEMA_VERSION = "decision_journal.v1"

# ("Trade lifecycle"-equivalent for the journal — "Use clear states"; no additional state is
# required beyond these four.)
STATUS_VALUES: tuple[str, ...] = ("open", "resolved", "invalidated", "cancelled")

# A decision is recorded once and, from the user's point of view, "settles" exactly once: either
# an outcome is recorded (resolved/invalidated — which of the two is the user's own call, not an
# automatic judgment) or the decision is withdrawn before any outcome exists (cancelled). No
# terminal state re-opens — the same "prevent invalid transitions" discipline Phase 24 already
# established for paper trades.
VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("resolved", "invalidated", "cancelled"),
    "resolved": (),
    "invalidated": (),
    "cancelled": (),
}
