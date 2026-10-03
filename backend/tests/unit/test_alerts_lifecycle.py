"""`cfi.alerts.lifecycle.decide`: deduplication, cooldown, and re-arm (Phase 23 spec
"Deduplication / Cooldown") — pure and database-free by construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cfi.alerts.lifecycle import Candidate, ExistingAlert, decide

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
