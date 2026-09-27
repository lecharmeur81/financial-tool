"""Unit tests for cfi.backtest.splits — time-only in-sample/validation/out-of-sample partitioning
and walk-forward windows. No parameter search happens here (this phase's explicit instruction);
these are pure date-range partitions."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from cfi.backtest.splits import three_way_split, walk_forward_windows

START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2030, 1, 1, tzinfo=UTC)  # exactly 3653 days


def test_three_way_split_windows_are_contiguous_and_cover_the_full_range() -> None:
    in_sample, validation, out_of_sample = three_way_split(
        start=START, end=END, in_sample_pct=60, validation_pct=20
    )
    assert in_sample.start == START
    assert in_sample.end == validation.start
    assert validation.end == out_of_sample.start
    assert out_of_sample.end == END
    assert in_sample.label == "in_sample"
    assert validation.label == "validation"
    assert out_of_sample.label == "out_of_sample"


def test_three_way_split_rejects_percentages_leaving_no_room_for_out_of_sample() -> None:
    with pytest.raises(ValueError, match="out_of_sample"):
        three_way_split(start=START, end=END, in_sample_pct=70, validation_pct=30)


def test_three_way_split_rejects_out_of_range_percentages() -> None:
    with pytest.raises(ValueError, match="in_sample_pct and validation_pct"):
        three_way_split(start=START, end=END, in_sample_pct=0, validation_pct=20)
    with pytest.raises(ValueError, match="in_sample_pct and validation_pct"):
        three_way_split(start=START, end=END, in_sample_pct=60, validation_pct=100)


def test_three_way_split_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        three_way_split(start=END, end=START, in_sample_pct=60, validation_pct=20)


def test_walk_forward_windows_are_non_overlapping_by_default() -> None:
    pairs = walk_forward_windows(start=START, end=END, train_days=365, test_days=90)
    assert len(pairs) > 1
    for train, test in pairs:
        assert train.end == test.start
        assert (test.end - test.start).days == 90
        assert (train.end - train.start).days == 365
    # consecutive TEST windows are contiguous and non-overlapping (the default step == test_days
    # advances each fold's train_start by test_days, which lines up each new test window exactly
    # where the previous one ended, even though train windows themselves overlap).
    for (_, test_a), (_, test_b) in pairwise(pairs):
        assert test_a.end == test_b.start


def test_walk_forward_windows_stops_once_a_test_window_would_exceed_end() -> None:
    pairs = walk_forward_windows(start=START, end=END, train_days=365, test_days=90)
    for _, test in pairs:
        assert test.end <= END


def test_walk_forward_windows_rejects_non_positive_arguments() -> None:
    with pytest.raises(ValueError, match="train_days and test_days"):
        walk_forward_windows(start=START, end=END, train_days=0, test_days=90)
    with pytest.raises(ValueError, match="train_days and test_days"):
        walk_forward_windows(start=START, end=END, train_days=90, test_days=-1)
    with pytest.raises(ValueError, match="step_days"):
        walk_forward_windows(start=START, end=END, train_days=90, test_days=90, step_days=0)
