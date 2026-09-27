"""``_balances_as_of`` (RED_TEAM_REPORT.md finding #13 / ADR-0064): a transfer must be classified
using the balance snapshot in effect AT THE TRANSFER'S OWN TIME, never the latest snapshot
regardless of when the transfer happened. Synthetic case from the report: address X has a small
balance at T1, later grows past the large-holder threshold by T2 (today) — a query for T1's
transfers must classify X on its T1 balance, not its T2 balance, and the reverse must also hold
for an address that has since drawn down."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.whales import score as ws
from cfi.whales.service import _balances_as_of

T1 = datetime(2026, 9, 1, tzinfo=UTC)
T2 = datetime(2026, 9, 10, tzinfo=UTC)
X = "addr_x"


def _snapshot(t: datetime, balance: str) -> ws.Snapshot:
    return ws.Snapshot(time=t, balances={X: Decimal(balance)}, classes={})


def test_a_transfer_at_t1_uses_the_t1_balance_not_a_later_larger_one() -> None:
    """X had a small balance at T1 and only grew large by T2: a T1 query must not borrow T2's
    balance."""
    snapshots = [_snapshot(T1, "10"), _snapshot(T2, "50000")]
    assert _balances_as_of(snapshots, T1)[X] == Decimal("10")


def test_a_transfer_at_t2_uses_the_t2_balance_not_the_earlier_smaller_one() -> None:
    snapshots = [_snapshot(T1, "10"), _snapshot(T2, "50000")]
    assert _balances_as_of(snapshots, T2)[X] == Decimal("50000")


def test_a_transfer_between_two_snapshots_uses_the_earlier_one_still_in_effect() -> None:
    mid = datetime(2026, 9, 5, tzinfo=UTC)
    snapshots = [_snapshot(T1, "10"), _snapshot(T2, "50000")]
    assert _balances_as_of(snapshots, mid)[X] == Decimal("10")


def test_a_transfer_predating_every_snapshot_gets_no_borrowed_future_balance() -> None:
    before = datetime(2026, 8, 1, tzinfo=UTC)
    snapshots = [_snapshot(T1, "10"), _snapshot(T2, "50000")]
    assert _balances_as_of(snapshots, before) == {}


def test_an_address_that_has_since_drawn_down_still_gets_its_larger_historical_balance() -> None:
    """The reverse case: an address that WAS large at T1 but has since drawn down by T2 must not
    lose the classification it held at T1 just because a later, smaller snapshot exists at query
    time for some other transfer."""
    snapshots = [_snapshot(T1, "50000"), _snapshot(T2, "10")]
    assert _balances_as_of(snapshots, T1)[X] == Decimal("50000")
    assert _balances_as_of(snapshots, T2)[X] == Decimal("10")


def test_no_snapshots_at_all_returns_an_empty_map() -> None:
    assert _balances_as_of([], T1) == {}
