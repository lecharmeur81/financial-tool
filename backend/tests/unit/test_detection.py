"""Duplicate, revision, conflict, gap and staleness detection (pure functions)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.detection import (
    Classification,
    classify,
    conflict_note,
    expected_points,
    find_conflicts,
    find_gaps,
    is_stale,
    relative_difference,
    split_batch,
)
from cfi.providers.base import RawResponse
from tests.support import T0

BASE = CanonicalObservation(
    dataset_id="d",
    metric="m",
    asset="BTC",
    subject_ref="BTC-USD",
    period="1h",
    unit="usd",
    event_time=T0,
    available_at=T0,
    available_at_estimated=True,
    ingested_at=T0,
    value=Decimal("100"),
    source_provider="p",
    original_source="s",
    quality_status=QualityStatus.OK,
    pit_reliability=PitReliability.NATIVE,
)


def test_batch_duplicates_and_inconsistent_repeats() -> None:
    later = replace(BASE, event_time=T0 + timedelta(hours=1))
    split = split_batch([BASE, BASE, later, replace(later, value=Decimal("101"))])
    assert split.unique == [BASE, later]
    assert split.duplicates == [BASE]
    assert split.inconsistent == [(later, replace(later, value=Decimal("101")))]


def test_classification_against_stored_value() -> None:
    assert classify(BASE, None) == (Classification.NEW, 0)
    assert classify(BASE, (0, Decimal("100"))) == (Classification.DUPLICATE, 0)
    assert classify(BASE, (2, Decimal("99"))) == (Classification.REVISION, 3)
    missing = replace(BASE, value=None, quality_status=QualityStatus.MISSING, quality_note="n")
    assert classify(missing, (0, None)) == (Classification.DUPLICATE, 0)
    assert classify(BASE, (0, None)) == (Classification.REVISION, 1)  # late value fills a gap


def test_conflicts_respect_tolerance() -> None:
    tol = Decimal("0.005")
    others = [("a", Decimal("100.4")), ("b", Decimal("102")), ("c", None)]
    conflicts = find_conflicts(Decimal("100"), others, tol)
    assert [c.other_provider for c in conflicts] == ["b"]
    assert conflicts[0].relative_difference == pytest.approx(Decimal("0.0196"), abs=Decimal("1e-4"))
    assert "b=102" in conflict_note(conflicts, tol)
    assert find_conflicts(None, others, tol) == []
    assert relative_difference(Decimal(0), Decimal(0)) == 0


def test_expected_points_and_gaps() -> None:
    hour = timedelta(hours=1)
    expected = expected_points(T0, T0 + 4 * hour, hour, not_after=T0 + 3 * hour)
    assert expected == [T0, T0 + hour, T0 + 2 * hour]  # the 03:00 bar has not closed yet
    assert find_gaps(expected, [T0, T0 + 2 * hour]) == [T0 + hour]
    shifted = expected_points(
        T0 + timedelta(minutes=30), T0 + 3 * hour, hour, not_after=T0 + 9 * hour
    )
    assert shifted == [T0 + hour, T0 + 2 * hour]  # aligned to the hour grid


def test_staleness() -> None:
    limit = timedelta(hours=3)
    assert is_stale(None, limit, T0)
    assert not is_stale(T0, limit, T0 + timedelta(hours=2))
    assert is_stale(T0, limit, T0 + timedelta(hours=4))


def test_archive_stores_once_and_refuses_path_escape(tmp_path: Path) -> None:
    archive = FileSystemArchive(tmp_path)
    raw = RawResponse("p", "/x", {}, T0, 200, "application/json", b'{"a": 1}')
    first = archive.store(raw)
    second = archive.store(raw)
    assert first == second
    assert archive.load(first.uri) == b'{"a": 1}'
    assert len(list(tmp_path.rglob("*.bin"))) == 1
    with pytest.raises(ValueError, match="escapes"):
        archive.load("file:../../etc/passwd")
