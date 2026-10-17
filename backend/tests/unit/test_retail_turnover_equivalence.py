"""The indexed ``DerivativesProxySeries`` must equal the scan-based ``derivatives_proxy`` exactly.

``RetailService._turnover_history`` used to call ``derivatives_proxy`` once per hourly poll time,
and each call rescanned every point of every series (``latest``): cost ~ polls x points, i.e.
quadratic in the history length. It now indexes the series once. These tests pin that the answers
are identical - including missing values, unsorted input, duplicate timestamps, boundary
instants and the freshness cutoff - and measure the work done at several history sizes with
deterministic data (elapsed wall-clock time and the number of points examined).
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.retail import metrics as m

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
TOL = m.DERIVATIVES_LATEST_TOLERANCE
ASSETS = ("BTC", "ETH", "SOL", "XRP")


class CountingSeq(Sequence[m.Point]):
    """A list that counts every element handed out when it is iterated."""

    def __init__(self, items: list[m.Point]) -> None:
        self.items = items
        self.examined = 0

    def __iter__(self) -> Iterator[m.Point]:
        for item in self.items:
            self.examined += 1
            yield item

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        return self.items[index]


def reference_turnover_history(
    funding: Mapping[str, Sequence[m.Point]],
    ratio: Mapping[str, Sequence[m.Point]],
    span: timedelta,
    before: datetime,
) -> list[Decimal]:
    """The implementation before the change (RetailService._turnover_history), verbatim."""
    candidate_times = sorted({p.time for pts in ratio.values() for p in pts if p.time < before})
    history: list[Decimal] = []
    cutoff = before - span
    for t in candidate_times:
        if t < cutoff:
            continue
        proxy = m.derivatives_proxy(funding, ratio, t)
        if proxy.status == "ok" and proxy.account_ratio_avg is not None:
            history.append(abs(proxy.account_ratio_avg - 1))
    return history


def indexed_turnover_history(
    funding: Mapping[str, Sequence[m.Point]],
    ratio: Mapping[str, Sequence[m.Point]],
    span: timedelta,
    before: datetime,
) -> list[Decimal]:
    """The same loop with the indexed series (mirrors RetailService._turnover_history)."""
    candidate_times = sorted({p.time for pts in ratio.values() for p in pts if p.time < before})
    history: list[Decimal] = []
    cutoff = before - span
    series = m.DerivativesProxySeries(funding, ratio)
    for t in candidate_times:
        if t < cutoff:
            continue
        proxy = series.at(t)
        if proxy.status == "ok" and proxy.account_ratio_avg is not None:
            history.append(abs(proxy.account_ratio_avg - 1))
    return history


def make_series(
    hours: int, seed: int, *, gaps: bool = True, noise: bool = True
) -> tuple[dict[str, list[m.Point]], dict[str, list[m.Point]]]:
    """Deterministic hourly funding/ratio series for four assets, ending just before ``NOW``.

    With ``noise`` the data is deliberately awkward: missing values, a gap longer than the
    tolerance, duplicate timestamps with different values, shuffled order, an asset with funding
    only and one with ratio only."""
    rng = random.Random(seed)  # noqa: S311 — deterministic test data
    funding: dict[str, list[m.Point]] = {}
    ratio: dict[str, list[m.Point]] = {}
    for n, asset in enumerate(ASSETS):
        f: list[m.Point] = []
        r: list[m.Point] = []
        for i in range(hours):
            t = NOW - HOUR * (hours - i)
            if gaps and hours > 40 and 20 <= i % 97 < 30 and n % 2 == 0:
                continue  # a 10 h hole: longer than the 6 h tolerance
            fv = None if noise and rng.random() < 0.07 else Decimal(rng.randint(-30, 30)) / 100000
            rv = None if noise and rng.random() < 0.07 else Decimal(rng.randint(60, 160)) / 100
            f.append(m.Point(t, fv))
            r.append(m.Point(t, rv))
            if noise and rng.random() < 0.03:  # duplicate timestamp, different value
                f.append(m.Point(t, Decimal(rng.randint(-30, 30)) / 100000))
                r.append(m.Point(t, Decimal(rng.randint(60, 160)) / 100))
        if noise:
            rng.shuffle(f)
            rng.shuffle(r)
        funding[asset] = f
        ratio[asset] = r
    if noise:
        del ratio["SOL"]  # funding only
        del funding["XRP"]  # ratio only
    return funding, ratio


def test_latest_index_matches_latest_at_every_boundary() -> None:
    rng = random.Random(7)  # noqa: S311 — deterministic test data
    base = NOW - timedelta(hours=30)
    points = [
        m.Point(base + timedelta(minutes=30 * rng.randint(0, 60)), Decimal(rng.randint(1, 9)))
        for _ in range(40)
    ] + [m.Point(base + HOUR * 5, None), m.Point(base + HOUR * 5, Decimal(3))]
    rng.shuffle(points)
    index = m.LatestIndex(points)
    # every half hour from before the first point to after the last, plus exact tolerance edges
    probes = [base - HOUR + timedelta(minutes=30 * k) for k in range(0, 110)]
    probes += [p.time + TOL for p in points] + [p.time + TOL + timedelta(seconds=1) for p in points]
    for as_of in probes:
        assert index.at(as_of, TOL) is m.latest(points, as_of, TOL), as_of


def test_latest_index_duplicate_timestamp_picks_the_same_point_as_latest() -> None:
    t = NOW - HOUR
    first, second = m.Point(t, Decimal(1)), m.Point(t, Decimal(2))
    for order in ([first, second], [second, first]):
        assert m.LatestIndex(order).at(NOW, TOL) is m.latest(order, NOW, TOL)


def test_latest_index_empty_and_all_missing() -> None:
    assert m.LatestIndex([]).at(NOW, TOL) is None
    assert m.LatestIndex([m.Point(NOW - HOUR, None)]).at(NOW, TOL) is None
    assert m.LatestIndex([m.Point(NOW + HOUR, Decimal(1))]).at(NOW, TOL) is None


@pytest.mark.parametrize("noise", [False, True])
@pytest.mark.parametrize("hours", [0, 1, 7, 60, 400])
def test_proxy_series_equals_derivatives_proxy_at_every_poll(hours: int, noise: bool) -> None:
    funding, ratio = make_series(hours, seed=hours + 1, noise=noise)
    series = m.DerivativesProxySeries(funding, ratio)
    times = {p.time for pts in (*funding.values(), *ratio.values()) for p in pts}
    probes = sorted(times | {NOW, NOW - TOL, NOW - TOL - timedelta(seconds=1)})
    probes += [t + TOL for t in list(times)[:50]] + [
        t + TOL + timedelta(seconds=1) for t in list(times)[:50]
    ]
    for as_of in probes:
        assert series.at(as_of) == m.derivatives_proxy(funding, ratio, as_of), as_of


@pytest.mark.parametrize("noise", [False, True])
@pytest.mark.parametrize("hours", [0, 1, 25, 300, 900])
def test_turnover_history_is_identical(hours: int, noise: bool) -> None:
    funding, ratio = make_series(hours, seed=100 + hours, noise=noise)
    for span in (timedelta(days=180), timedelta(days=3), timedelta(hours=5)):
        expected = reference_turnover_history(funding, ratio, span, NOW)
        assert indexed_turnover_history(funding, ratio, span, NOW) == expected


def test_work_and_elapsed_time_by_history_size(capsys: pytest.CaptureFixture[str]) -> None:
    """Deterministic data at several sizes: points examined and wall-clock time, both versions."""
    rows = []
    for hours in (100, 200, 400, 800):
        funding, ratio = make_series(hours, seed=5, noise=False, gaps=False)
        counted_f = {a: CountingSeq(list(p)) for a, p in funding.items()}
        counted_r = {a: CountingSeq(list(p)) for a, p in ratio.items()}
        t0 = time.perf_counter()
        expected = reference_turnover_history(counted_f, counted_r, timedelta(days=180), NOW)
        ref_s = time.perf_counter() - t0
        examined = sum(c.examined for c in (*counted_f.values(), *counted_r.values()))
        t0 = time.perf_counter()
        got = indexed_turnover_history(funding, ratio, timedelta(days=180), NOW)
        new_s = time.perf_counter() - t0
        assert got == expected
        rows.append((hours, examined, ref_s, new_s))
    # The scanned work grows with the square of the history; doubling it roughly quadruples it.
    assert rows[-1][1] / rows[-2][1] > 3.5
    with capsys.disabled():
        print("\nhourly points | points examined (before) | seconds before | seconds after")
        for hours, examined, ref_s, new_s in rows:
            print(f"{hours:13d} | {examined:24d} | {ref_s:14.4f} | {new_s:13.4f}")
