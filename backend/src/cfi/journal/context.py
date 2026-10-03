"""Pure extraction helpers over an already-built ``cfi.analyst.snapshot.Snapshot`` (Phase 25 spec
"Decision-time context" / review by market regime) — no I/O, no new tool call, no new adapter
call: everything read here was already fetched once when the snapshot itself was built
(``cfi.analyst.snapshot.build_snapshot``, reused unchanged from Phase 21).

Deliberately narrow: a journal entry's one true evidence record is the snapshot itself
(``decision_snapshot_id``), reproducible from ``ai.snapshot.payload``. These two values are
denormalized, queryable copies of facts the snapshot already contains, kept only because SQL
cannot group by a jsonb path as cheaply as by a plain column — never a second source of truth
(the snapshot is still what `decision_snapshot_id` is for)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.analyst.snapshot import Snapshot


def regime_label(snapshot: Snapshot) -> str | None:
    """The current regime's label, if the regime engine could classify one (``None`` on
    ``insufficient_data`` or an ``unavailable`` tool — missing is first-class, R3)."""
    result = snapshot.raw.get("get_market_regime")
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    label = data.get("label")
    return label if isinstance(label, str) else None


def observed_price(snapshot: Snapshot, asset: str) -> Decimal | None:
    """The same observed closing price ``get_market_data`` already captured in this snapshot for
    ``asset`` (``None`` if ``asset`` is untracked or the value is itself unavailable) — reused
    verbatim, never refetched."""
    result = snapshot.raw.get("get_market_data")
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    assets: Any = data.get("assets")
    if not isinstance(assets, dict) or asset not in assets:
        return None
    price_field = assets[asset].get("price_close")
    if not isinstance(price_field, dict):
        return None
    value = price_field.get("value")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
