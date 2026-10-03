"""`cfi.journal.stats` — deterministic, DB-free decision review/statistics (Phase 25 spec
"Decision review" / "Basic decision statistics"; "These are descriptive statistics, not
recommendations... Do not produce a 'best strategy' or rank the user's decisions" — enforced by
what this module does not compute, not by a disclaimer string here). Covers the "Historical
review" testing category at the pure-function level."""

from __future__ import annotations

from datetime import UTC, datetime

from cfi.journal.stats import decision_review, decision_stats


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "open",
        "thesis_supported": None,
        "thesis_contradicted": None,
        "invalidation_occurred": None,
        "decision_type": None,
        "market_regime_label": None,
        "invalidation_condition": None,
        "outcome": None,
        "decision_time": None,
        "outcome_timestamp": None,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ decision_stats


def test_no_decisions_at_all() -> None:
    stats = decision_stats([])
    assert stats.total_decisions == 0
    assert stats.open_decisions == 0
    assert stats.resolved_decisions == 0
    assert stats.invalidated_decisions == 0
    assert stats.cancelled_decisions == 0
    assert stats.thesis_supported_count == 0
    assert stats.average_time_to_resolution_hours is None


def test_counts_by_status_split_correctly() -> None:
    rows = [
        _row(status="open"),
        _row(status="open"),
        _row(status="resolved"),
        _row(status="invalidated"),
        _row(status="cancelled"),
    ]
    stats = decision_stats(rows)
    assert stats.total_decisions == 5
    assert stats.open_decisions == 2
    assert stats.resolved_decisions == 1
    assert stats.invalidated_decisions == 1
    assert stats.cancelled_decisions == 1


def test_thesis_supported_and_contradicted_counts_require_exactly_true() -> None:
    rows = [
        _row(thesis_supported=True, thesis_contradicted=False),
        _row(thesis_supported=False, thesis_contradicted=True),
        _row(thesis_supported=None, thesis_contradicted=None),
    ]
    stats = decision_stats(rows)
    assert stats.thesis_supported_count == 1
    assert stats.thesis_contradicted_count == 1


def test_invalidation_occurred_count() -> None:
    rows = [
        _row(invalidation_occurred=True),
        _row(invalidation_occurred=True),
        _row(invalidation_occurred=False),
    ]
    stats = decision_stats(rows)
    assert stats.invalidation_occurred_count == 2


def test_average_time_to_resolution_only_counts_resolved_or_invalidated_with_both_timestamps() -> (
    None
):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)  # 24h later
    rows = [
        _row(status="resolved", decision_time=t0, outcome_timestamp=t1),
        _row(status="open", decision_time=t0, outcome_timestamp=t1),  # excluded: still open
        _row(status="invalidated", decision_time=t0, outcome_timestamp=None),  # excluded: missing
    ]
    stats = decision_stats(rows)
    assert stats.average_time_to_resolution_hours == 24


# ------------------------------------------------------------------ decision_review (descriptive
# only — no field here ranks or scores anything, by construction of the dataclass itself).


def test_decisions_by_type_groups_by_exact_string() -> None:
    rows = [
        _row(decision_type="long_spot"),
        _row(decision_type="long_spot"),
        _row(decision_type="short_perp"),
    ]
    review = decision_review(rows)
    assert review.decisions_by_type == {"long_spot": 2, "short_perp": 1}


def test_decisions_by_type_excludes_missing_values() -> None:
    rows = [_row(decision_type="long_spot"), _row(decision_type=None)]
    review = decision_review(rows)
    assert review.decisions_by_type == {"long_spot": 1}


def test_decisions_by_regime_groups_by_exact_label() -> None:
    rows = [
        _row(market_regime_label="leveraged_expansion"),
        _row(market_regime_label="leveraged_expansion"),
        _row(market_regime_label=None),  # insufficient_data at decision time — excluded, not zero
    ]
    review = decision_review(rows)
    assert review.decisions_by_regime == {"leveraged_expansion": 2}


def test_decisions_by_invalidation_condition_is_a_literal_string_grouping() -> None:
    """No clustering or semantic matching — two differently worded but equivalent conditions are
    two separate groups (documented limitation, R3: an honestly narrow grouping beats a
    fabricated one)."""
    rows = [
        _row(invalidation_condition="BTC closes below 60000"),
        _row(invalidation_condition="btc closes below 60k"),
    ]
    review = decision_review(rows)
    assert review.decisions_by_invalidation_condition == {
        "BTC closes below 60000": 1,
        "btc closes below 60k": 1,
    }


def test_decisions_by_outcome_groups_by_exact_string() -> None:
    rows = [_row(outcome="as_expected"), _row(outcome="not_as_expected"), _row(outcome=None)]
    review = decision_review(rows)
    assert review.decisions_by_outcome == {"as_expected": 1, "not_as_expected": 1}


def test_review_never_contains_a_ranking_or_score_field() -> None:
    """A static guard on the dataclass shape itself: `DecisionReview` must never grow a field
    that ranks, scores, or recommends ("Do not produce a 'best strategy' or rank the user's
    decisions")."""
    from dataclasses import fields

    from cfi.journal.stats import DecisionReview

    forbidden_substrings = ("best", "rank", "score", "recommend")
    for f in fields(DecisionReview):
        lowered = f.name.lower()
        assert not any(token in lowered for token in forbidden_substrings)
