"""In-sample / validation / out-of-sample partitioning and walk-forward windows (Phase 16).

No optimizer lives here or anywhere in this package (see ``cfi.backtest`` module docstring and this
phase's explicit instruction). These functions only cut a date range into named windows for the
USER to run the SAME, already-fixed ``StrategyDefinition`` over and compare — they never search
across windows for a better parameter set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Window:
    label: str  # "in_sample" | "validation" | "out_of_sample" | "walk_forward_train_N" | ...
    start: datetime
    end: datetime  # exclusive


def three_way_split(
    *, start: datetime, end: datetime, in_sample_pct: int, validation_pct: int
) -> tuple[Window, Window, Window]:
    """Split ``[start, end)`` into in-sample / validation / out-of-sample windows by the given
    percentages of the total span (the remainder goes to out-of-sample). Purely a partition — the
    caller decides what, if anything, to do differently between windows."""
    if not (0 < in_sample_pct < 100) or not (0 < validation_pct < 100):
        raise ValueError("in_sample_pct and validation_pct must each be between 0 and 100")
    if in_sample_pct + validation_pct >= 100:
        raise ValueError("in_sample_pct + validation_pct must leave room for out_of_sample")
    total_days = (end - start).days
    if total_days <= 0:
        raise ValueError("end must be after start")
    in_sample_end = start + timedelta(days=total_days * in_sample_pct // 100)
    validation_end = start + timedelta(days=total_days * (in_sample_pct + validation_pct) // 100)
    return (
        Window("in_sample", start, in_sample_end),
        Window("validation", in_sample_end, validation_end),
        Window("out_of_sample", validation_end, end),
    )


def walk_forward_windows(
    *, start: datetime, end: datetime, train_days: int, test_days: int, step_days: int | None = None
) -> list[tuple[Window, Window]]:
    """Rolling (train, test) window pairs: train ``train_days`` ending at a point, test the
    ``test_days`` immediately after it, then step forward by ``step_days`` (default: ``test_days``,
    i.e. non-overlapping test windows) and repeat until the test window would run past ``end``."""
    if train_days <= 0 or test_days <= 0:
        raise ValueError("train_days and test_days must be positive")
    step = step_days if step_days is not None else test_days
    if step <= 0:
        raise ValueError("step_days must be positive")

    pairs: list[tuple[Window, Window]] = []
    train_start = start
    fold = 0
    while True:
        train_end = train_start + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        if test_end > end:
            break
        pairs.append(
            (
                Window(f"walk_forward_train_{fold}", train_start, train_end),
                Window(f"walk_forward_test_{fold}", train_end, test_end),
            )
        )
        train_start = train_start + timedelta(days=step)
        fold += 1
    return pairs
