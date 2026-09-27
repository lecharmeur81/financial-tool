"""Unit tests for cfi.api.params.resolve_query_times.

RED_TEAM_REPORT.md finding #1 (CRITICAL, Phase 17): every point-in-time route resolved
``knowledge_time`` independently of ``as_of``, so a caller who supplied only ``as_of`` silently
got ``knowledge_time = now()`` — turning the ``ingested_at <= knowledge_time`` revision/leakage
gate into a no-op. ADR-0060 (Phase 18) fixes this by making ``knowledge_time`` default to
``as_of`` whenever ``as_of`` is explicitly supplied and ``knowledge_time`` is not.

These tests pin down the corrected resolution rule directly against the shared helper, since all
ten domain routes now delegate to it (see ``test_market_structure_api.py`` for an end-to-end
integration proof that a revision is not leaked once this default is corrected).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cfi.api.params import resolve_query_times
from cfi.core.errors import DataValidationError


def test_both_omitted_default_to_now() -> None:
    before = datetime.now(tz=UTC)
    a, k = resolve_query_times(None, None)
    after = datetime.now(tz=UTC)
    assert before <= a <= after
    assert before <= k <= after
    assert a == k


def test_as_of_only_makes_knowledge_time_default_to_as_of_not_now() -> None:
    """The core Phase 17 finding: as_of in the past must not silently pull in "now" data."""
    as_of = datetime(2024, 1, 1, tzinfo=UTC)
    a, k = resolve_query_times(as_of, None)
    assert a == as_of
    assert k == as_of  # NOT utc_now() — this is the fix
    assert k != datetime.now(tz=UTC)


def test_explicit_knowledge_time_is_honored_even_when_before_as_of() -> None:
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    knowledge_time = datetime(2024, 1, 1, tzinfo=UTC)
    a, k = resolve_query_times(as_of, knowledge_time)
    assert a == as_of
    assert k == knowledge_time


def test_explicit_knowledge_time_after_as_of_is_honored() -> None:
    """A caller may legitimately ask 'what does today's system know about that past date' —
    this is a real use case (e.g. re-running an old as_of with today's fully-settled data) and
    must remain possible; the fix only changes the *default*, not what an explicit value can do.
    """
    as_of = datetime(2024, 1, 1, tzinfo=UTC)
    knowledge_time = datetime(2024, 6, 1, tzinfo=UTC)
    a, k = resolve_query_times(as_of, knowledge_time)
    assert a == as_of
    assert k == knowledge_time


def test_knowledge_time_only_defaults_as_of_to_now() -> None:
    knowledge_time = datetime(2024, 1, 1, tzinfo=UTC)
    before = datetime.now(tz=UTC)
    a, k = resolve_query_times(None, knowledge_time)
    after = datetime.now(tz=UTC)
    assert before <= a <= after
    assert k == knowledge_time


def test_future_values_are_capped_at_now() -> None:
    future = datetime.now(tz=UTC) + timedelta(days=365)
    a, k = resolve_query_times(future, future)
    now = datetime.now(tz=UTC)
    assert a <= now
    assert k <= now


def test_naive_datetimes_are_rejected() -> None:
    naive = datetime(2024, 1, 1)  # noqa: DTZ001 - deliberately naive, testing rejection
    with pytest.raises(DataValidationError):
        resolve_query_times(naive, None)
    with pytest.raises(DataValidationError):
        resolve_query_times(datetime(2024, 1, 1, tzinfo=UTC), naive)
