"""`cfi.journal.universe` — fixed vocabulary and lifecycle rules (Phase 25 spec "Status": "Use
clear states"), plus the "Invalid state transitions" testing category, plus a source-level guard
mirroring Phase 24's "No real-order execution" check: no autonomous decision-making, trading
advice, or real execution pathway anywhere in ``cfi.journal`` (Phase 25 "Important constraints" /
"Do NOT add autonomous AI decision-making")."""

from __future__ import annotations

import pkgutil
from importlib import import_module
from pathlib import Path

from cfi.journal.universe import STATUS_VALUES, VALID_TRANSITIONS


def test_status_values_are_exactly_open_resolved_invalidated_cancelled() -> None:
    assert set(STATUS_VALUES) == {"open", "resolved", "invalidated", "cancelled"}


def test_open_may_transition_to_any_terminal_state() -> None:
    assert set(VALID_TRANSITIONS["open"]) == {"resolved", "invalidated", "cancelled"}


def test_resolved_invalidated_and_cancelled_are_terminal() -> None:
    assert VALID_TRANSITIONS["resolved"] == ()
    assert VALID_TRANSITIONS["invalidated"] == ()
    assert VALID_TRANSITIONS["cancelled"] == ()


def test_no_state_transitions_to_itself() -> None:
    """A decision can never be resolved/invalidated/cancelled twice ("Prevent invalid
    transitions" — same discipline Phase 24 established for paper trades)."""
    for status, targets in VALID_TRANSITIONS.items():
        assert status not in targets


def test_every_status_value_has_a_transition_entry() -> None:
    assert set(VALID_TRANSITIONS) == set(STATUS_VALUES)


# ------------------------------------------------------------------ "no autonomous decision-making
# / no real execution pathway" (Phase 25 "Important constraints"). A source-level guard, not just
# a design intention: every module in ``cfi.journal`` is scanned for tokens that would indicate an
# automatic trading-advice or real-execution pathway crept in.

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
    "should_buy",
    "should_sell",
    "recommended_action",
    "best_strategy",
)


def test_journal_package_contains_no_execution_or_advice_pathway() -> None:
    import cfi.journal as journal_pkg

    package_dir = Path(journal_pkg.__file__).parent
    offenders: list[str] = []
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module = import_module(f"cfi.journal.{module_info.name}")
        source_path = Path(module.__file__ or "")
        text = source_path.read_text().lower()
        for token in _FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{module_info.name}: {token!r}")
    assert offenders == []


# ------------------------------------------------------------------ "Hindsight protection"
# (Phase 25 spec): a source-level guard that the repository's post-creation write methods never
# reference the decision-time-only columns. This is the same invariant `cfi.journal.repository`'s
# own module docstring claims; this test keeps that claim honest as the file evolves.

_DECISION_TIME_ONLY_COLUMNS = (
    "decision_time",
    "asset",
    "decision_type",
    "thesis",
    "expected_scenario",
    "alternative_scenario",
    "time_horizon",
    "entry_price",
    "observed_price_at_decision",
    "invalidation_condition",
    "key_risks",
    "confidence",
    "decision_snapshot_id",
    "market_brief_id",
    "relevant_alert_ids",
    "market_regime_label",
)

_POST_CREATION_WRITE_METHODS = (
    "update_notes",
    "record_outcome",
    "cancel",
    "link_paper_trade",
    "unlink_paper_trade",
)


def test_post_creation_writes_never_touch_decision_time_columns() -> None:
    import ast

    import cfi.journal.repository as repo_module

    source_path = Path(repo_module.__file__ or "")
    tree = ast.parse(source_path.read_text())

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in _POST_CREATION_WRITE_METHODS:
            body_source = ast.unparse(node)
            for column in _DECISION_TIME_ONLY_COLUMNS:
                # `.values(column=...)` keyword usage is what would re-write that column;
                # a bare mention (e.g. in a docstring) is not what this guard checks for.
                if f"{column}=" in body_source:
                    offenders.append(f"{node.name} assigns to {column!r}")
    assert offenders == []
