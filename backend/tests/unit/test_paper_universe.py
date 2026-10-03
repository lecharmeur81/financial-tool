"""`cfi.paper.universe` — fixed vocabulary and lifecycle rules (Phase 24 spec "Trade lifecycle":
"Use clear states... Prevent invalid transitions") plus the "No real-order execution" testing
category: a source-level guard that no exchange/order/credential code has crept into the
``cfi.paper`` package."""

from __future__ import annotations

import pkgutil
from importlib import import_module
from pathlib import Path

from cfi.paper.universe import DIRECTION_VALUES, STATUS_VALUES, VALID_TRANSITIONS


def test_status_values_are_exactly_open_closed_cancelled() -> None:
    assert set(STATUS_VALUES) == {"open", "closed", "cancelled"}


def test_direction_values_are_exactly_long_short() -> None:
    assert set(DIRECTION_VALUES) == {"long", "short"}


def test_open_may_transition_to_closed_or_cancelled() -> None:
    assert set(VALID_TRANSITIONS["open"]) == {"closed", "cancelled"}


def test_closed_and_cancelled_are_terminal() -> None:
    assert VALID_TRANSITIONS["closed"] == ()
    assert VALID_TRANSITIONS["cancelled"] == ()


def test_no_state_transitions_to_itself() -> None:
    """A trade can never be closed/cancelled twice ("Prevent invalid transitions")."""
    for status, targets in VALID_TRANSITIONS.items():
        assert status not in targets


# ------------------------------------------------------------------ "No real-order execution"
# (Phase 24 spec "Testing"). A source-level guard, not just a design intention: every module in
# ``cfi.paper`` is scanned for tokens that would indicate a real exchange/order/credential
# pathway crept in (Phase 24 "Important constraints" / "Security / safety").

_FORBIDDEN_TOKENS = (
    "api_key",
    "apikey",
    "secret_key",
    "private_key",
    "place_order",
    "submit_order",
    "cancel_order",
    "create_order",
    "exchange_client",
    "ccxt",
    "binance.client",
)


def test_paper_package_contains_no_real_execution_pathway() -> None:
    import cfi.paper as paper_pkg

    package_dir = Path(paper_pkg.__file__).parent
    offenders: list[str] = []
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module = import_module(f"cfi.paper.{module_info.name}")
        source_path = Path(module.__file__ or "")
        text = source_path.read_text().lower()
        for token in _FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{module_info.name}: {token!r}")
    assert offenders == []
