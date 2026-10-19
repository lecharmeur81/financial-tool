"""`cfi.alerts.lifecycle.decide`: deduplication, cooldown, and re-arm (Phase 23 spec
"Deduplication / Cooldown") — pure and database-free by construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cfi.alerts.lifecycle import (
    OPEN_STATUSES,
    Candidate,
    ExistingAlert,
    decide,
    user_transition,
    user_transition_sources,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def test_first_observation_creates() -> None:
    assert decide(None, Candidate("accumulation"), now=NOW, cooldown_seconds=3600) == "create"


def test_unchanged_condition_is_not_repeated() -> None:
    existing = ExistingAlert(observed_value="accumulation", timestamp=NOW - timedelta(minutes=5))
    action = decide(existing, Candidate("accumulation"), now=NOW, cooldown_seconds=3600)
    assert action == "skip_unchanged"


def test_changed_condition_within_cooldown_is_suppressed() -> None:
    existing = ExistingAlert(observed_value="accumulation", timestamp=NOW - timedelta(minutes=30))
    action = decide(existing, Candidate("distribution"), now=NOW, cooldown_seconds=3600)
    assert action == "skip_cooldown"


def test_changed_condition_exactly_at_the_cooldown_boundary_rearms() -> None:
    """The boundary itself (elapsed == cooldown) already counts as elapsed — `decide` tests
    ``elapsed < cooldown_seconds`` for suppression, so exactly-equal elapsed re-arms."""
    existing = ExistingAlert(observed_value="accumulation", timestamp=NOW - timedelta(hours=1))
    action = decide(existing, Candidate("distribution"), now=NOW, cooldown_seconds=3600)
    assert action == "rearm"


def test_changed_condition_one_second_before_the_cooldown_boundary_is_suppressed() -> None:
    existing = ExistingAlert(
        observed_value="accumulation", timestamp=NOW - timedelta(hours=1) + timedelta(seconds=1)
    )
    action = decide(existing, Candidate("distribution"), now=NOW, cooldown_seconds=3600)
    assert action == "skip_cooldown"


def test_changed_condition_just_past_cooldown_rearms() -> None:
    existing = ExistingAlert(
        observed_value="accumulation", timestamp=NOW - timedelta(hours=1, seconds=1)
    )
    action = decide(existing, Candidate("distribution"), now=NOW, cooldown_seconds=3600)
    assert action == "rearm"


def test_changed_condition_well_past_cooldown_rearms() -> None:
    existing = ExistingAlert(observed_value="accumulation", timestamp=NOW - timedelta(days=1))
    action = decide(existing, Candidate("distribution"), now=NOW, cooldown_seconds=3600)
    assert action == "rearm"


# ------------------------------------------------------------------ user transitions (Phase 52)
@pytest.mark.parametrize(
    ("current", "target", "verdict"),
    [
        ("active", "acknowledged", "apply"),
        ("active", "resolved", "apply"),
        ("acknowledged", "resolved", "apply"),
        # Idempotent repeats change nothing.
        ("acknowledged", "acknowledged", "noop"),
        ("resolved", "resolved", "noop"),
        # Terminal alerts are never reopened or re-stamped.
        ("resolved", "acknowledged", "reject"),
        ("expired", "acknowledged", "reject"),
        ("expired", "resolved", "reject"),
        # Targets a user cannot set, and unknown statuses.
        ("active", "active", "reject"),
        ("acknowledged", "active", "reject"),
        ("active", "expired", "reject"),
        ("active", "bogus", "reject"),
        ("bogus", "resolved", "reject"),
        ("bogus", "acknowledged", "reject"),
    ],
)
def test_user_transition_table(current: str, target: str, verdict: str) -> None:
    assert user_transition(current, target) == verdict


def test_user_transition_sources_are_exactly_the_open_statuses_that_may_move() -> None:
    assert user_transition_sources("acknowledged") == ("active",)
    assert user_transition_sources("resolved") == ("active", "acknowledged")
    assert user_transition_sources("active") == ()
    assert user_transition_sources("expired") == ()
    assert OPEN_STATUSES == ("active", "acknowledged")


def test_no_terminal_status_is_a_source_of_any_applied_transition() -> None:
    for target in ("acknowledged", "resolved"):
        for terminal in ("resolved", "expired"):
            assert user_transition(terminal, target) in ("noop", "reject")
            assert terminal not in user_transition_sources(target)
