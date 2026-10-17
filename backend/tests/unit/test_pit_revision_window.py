"""``pit_revision_window``: serving point-in-time revision queries from a per-scope window.

``Store`` is an in-memory table. ``Store.direct`` implements the production SQL semantics
(``event_time >= start AND event_time < end AND available_at <= as_of AND ingested_at <= kt``,
then ``DISTINCT ON (event_time) ... ORDER BY event_time, revision DESC``); ``Store.load`` the
window's loader (same range, ``available_at <= cutoff AND ingested_at <= cutoff``, every revision).
Every result of the window is compared with ``Store.direct``. A visible revision tie is the one case
where SQL's pick is unspecified; there the window must hand the request to ``direct``.
These tests do not exercise the SQL text itself (see test_pit_window_queries.py for the wiring).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from cfi.core import pit_memo
from cfi.core.pit_memo import pit_read_scope, pit_revision_window

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
LIMIT = NOW - pit_memo.LATE_ARRIVAL_MARGIN
BASE = datetime(2026, 6, 1, tzinfo=UTC)
US = timedelta(microseconds=1)
H = timedelta(hours=1)
D = timedelta(days=1)


def make_row(
    event_time: datetime,
    revision: int,
    available_at: datetime,
    ingested_at: datetime,
    value: int | None = 1,
    provider: str = "p1",
) -> dict[str, Any]:
    return {
        "event_time": event_time,
        "value": value,
        "revision": revision,
        "available_at": available_at,
        "ingested_at": ingested_at,
        "source_provider": provider,
        "tags": ["x"],
    }


@dataclass
class Store:
    rows: list[dict[str, Any]] = field(default_factory=list)
    loads: list[tuple[datetime, datetime, datetime]] = field(default_factory=list)
    directs: int = 0

    def visible(self, start: datetime, end: datetime, as_of: datetime, kt: datetime) -> Any:
        return [
            r
            for r in self.rows
            if start <= r["event_time"] < end
            and r["available_at"] <= as_of
            and r["ingested_at"] <= kt
        ]

    def reference(
        self, start: datetime, end: datetime, as_of: datetime, kt: datetime
    ) -> tuple[list[dict[str, Any]], bool]:
        """(rows SQL returns, whether any event_time had a visible top-revision tie)."""
        by_time: dict[datetime, list[dict[str, Any]]] = {}
        for r in self.visible(start, end, as_of, kt):
            by_time.setdefault(r["event_time"], []).append(r)
        out, ambiguous = [], False
        for t in sorted(by_time):
            top = max(r["revision"] for r in by_time[t])
            winners = [r for r in by_time[t] if r["revision"] == top]
            ambiguous |= len(winners) > 1
            out.append(dict(winners[0], tags=list(winners[0]["tags"])))
        return out, ambiguous

    async def load(self, start: datetime, end: datetime, cutoff: datetime) -> list[dict[str, Any]]:
        self.loads.append((start, end, cutoff))
        rows = self.visible(start, end, cutoff, cutoff)
        rows = sorted(rows, key=lambda r: (r["event_time"], -r["revision"]))
        return [dict(r, tags=list(r["tags"])) for r in rows]

    async def direct(
        self, start: datetime, end: datetime, as_of: datetime, kt: datetime
    ) -> list[dict[str, Any]]:
        self.directs += 1
        return self.reference(start, end, as_of, kt)[0]

    async def read(
        self,
        start: datetime,
        end: datetime,
        as_of: datetime,
        kt: datetime,
        *,
        engine: object | None = None,
        family: tuple[object, ...] = ("t",),
    ) -> list[dict[str, Any]]:
        return await pit_revision_window(
            family,
            engine if engine is not None else ENGINE,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=kt,
            load=self.load,
            direct=lambda: self.direct(start, end, as_of, kt),
            copy_columns=("tags",),
        )


ENGINE = object()


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pit_memo, "_utc_now", lambda: NOW)


def random_store(rng: random.Random) -> Store:
    store = Store()
    for n in range(400):
        event = BASE + n * H
        for revision in range(rng.choice([1, 1, 2, 3, 4])):
            ingested = event + timedelta(minutes=rng.randint(0, 60 * 30)) + revision * H
            available = event + timedelta(minutes=rng.randint(0, 60 * 10))
            value = None if rng.random() < 0.08 else rng.randint(1, 9)
            store.rows.append(make_row(event, revision, available, ingested, value))
            if rng.random() < 0.03:  # same event + revision from another provider => tie
                store.rows.append(make_row(event, revision, available, ingested, 7, "p2"))
    rng.shuffle(store.rows)
    return store


@pytest.mark.parametrize("seed", range(25))
async def test_randomized_requests_equal_the_sql_semantics(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture data
    store = random_store(rng)
    with pit_read_scope() as stats:
        for _ in range(60):
            start = BASE + timedelta(minutes=rng.randint(-3000, 14000))
            end = start + timedelta(minutes=rng.randint(60, 60 * 24 * 12))
            as_of = BASE + timedelta(minutes=rng.randint(0, 60 * 24 * 40))
            kt = (
                as_of
                if rng.random() < 0.5
                else BASE + timedelta(minutes=rng.randint(0, 60 * 24 * 40))
            )
            expected, _ambiguous = store.reference(start, end, as_of, kt)
            before = store.directs
            got = await store.read(start, end, as_of, kt)
            assert got == expected
            assert list(map(list, got)) == list(map(list, expected))  # same keys, same order
            if _ambiguous:
                assert store.directs == before + 1  # a tie is never guessed
    assert stats.window_hits > 0
    assert stats.window_loads >= 1


@pytest.mark.parametrize("d_avail", [-US, timedelta(0), US])
@pytest.mark.parametrize("d_ingest", [-US, timedelta(0), US])
async def test_available_at_and_ingested_at_boundaries(
    d_avail: timedelta, d_ingest: timedelta
) -> None:
    event = BASE + D
    avail, ingested = event + H, event + 2 * H
    store = Store([make_row(event, 0, avail, ingested)])
    with pit_read_scope():
        got = await store.read(event, event + D, avail + d_avail, ingested + d_ingest)
    expected = d_avail >= timedelta(0) and d_ingest >= timedelta(0)
    assert [r["revision"] for r in got] == ([0] if expected else [])
    assert got == store.reference(event, event + D, avail + d_avail, ingested + d_ingest)[0]


async def test_event_time_range_is_start_inclusive_end_exclusive() -> None:
    store = Store([make_row(BASE + n * D, 0, BASE, BASE) for n in range(5)])
    with pit_read_scope():
        got = await store.read(BASE + D, BASE + 3 * D, LIMIT, LIMIT)
    assert [r["event_time"] for r in got] == [BASE + D, BASE + 2 * D]


async def test_historical_supersession_and_late_arriving_revisions() -> None:
    event = BASE + D
    store = Store(
        [
            make_row(event, 0, event, event + H, value=1),
            make_row(event, 1, event, event + 3 * H, value=2),
        ]
    )
    with pit_read_scope():
        r = (event, event + D)
        assert (await store.read(*r, event + 2 * H, event + 2 * H))[0]["value"] == 1
        assert (await store.read(*r, event + 4 * H, event + 4 * H))[0]["value"] == 2
        # knowledge_time earlier than the supersession: the old revision (as_of may be later)
        assert (await store.read(*r, event + 4 * H, event + 2 * H))[0]["value"] == 1

        # a revision ingested AFTER the window was loaded (ingested_at > cutoff)
        store.rows.append(make_row(event, 2, event, NOW, value=3))
        for as_of, kt in ((event + 4 * H, event + 4 * H), (LIMIT - H, LIMIT - H), (LIMIT, LIMIT)):
            got = await store.read(*r, as_of, kt)
            assert got == store.reference(*r, as_of, kt)[0]
            assert got[0]["value"] == 2  # not visible, exactly as under SQL
        # a request that could see it is not served from the window
        before = store.directs
        got = await store.read(*r, NOW, NOW)
        assert store.directs == before + 1
        assert got[0]["value"] == 3


async def test_revision_tie_falls_back_to_sql_only_when_both_rows_are_visible() -> None:
    event = BASE + D
    store = Store(
        [
            make_row(event, 1, event, event + H, value=1, provider="a"),
            make_row(event, 1, event, event + 5 * H, value=2, provider="b"),
        ]
    )
    with pit_read_scope() as stats:
        r = (event, event + D)
        one = await store.read(*r, event + 2 * H, event + 2 * H)  # only "a" visible
        assert (store.directs, one[0]["value"]) == (0, 1)
        both = await store.read(*r, event + 6 * H, event + 6 * H)  # tie
        assert store.directs == 1
        assert both == store.reference(*r, event + 6 * H, event + 6 * H)[0]
    assert stats.window_fallbacks == 1


async def test_requests_the_window_cannot_vouch_for_use_sql() -> None:
    store = Store([make_row(BASE + n * D, 0, BASE, BASE) for n in range(5)])
    naive = datetime(2026, 6, 1)  # noqa: DTZ001 - deliberately naive
    with pit_read_scope() as stats:
        await store.read(BASE, BASE + 5 * D, NOW, NOW)  # as_of/kt later than the cutoff limit
        await store.read(BASE, BASE + 5 * D, LIMIT, NOW)  # knowledge_time later than the limit
        await store.read(BASE, BASE + 5 * D, LIMIT + US, LIMIT)  # one microsecond past it
        calls = []

        async def naive_direct() -> list[dict[str, Any]]:
            calls.append(1)
            return []

        assert (
            await pit_revision_window(  # naive datetimes
                ("t",),
                ENGINE,
                start=naive,
                end=naive + 5 * D,
                as_of=LIMIT,
                knowledge_time=LIMIT,
                load=store.load,
                direct=naive_direct,
            )
            == []
        )
        assert calls == [1]
        store.directs += 1  # keep the tally below simple
        await store.read(BASE + D, BASE + D, LIMIT, LIMIT)  # empty range
        assert store.loads == []
        assert store.directs == 5
        await store.read(BASE, BASE + 5 * D, LIMIT, LIMIT)  # exactly at the limit: served
        assert len(store.loads) == 1
    assert stats.window_fallbacks == 5


async def test_later_requests_cannot_exceed_the_cutoff_the_window_was_loaded_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store([make_row(BASE, 0, BASE, BASE)])
    with pit_read_scope():
        await store.read(BASE, BASE + D, LIMIT, LIMIT)  # window cutoff = LIMIT
        monkeypatch.setattr(pit_memo, "_utc_now", lambda: NOW + 3 * H)  # time passes
        store.rows.append(make_row(BASE, 1, BASE, NOW + H, value=9))  # stored after the load
        got = await store.read(BASE, BASE + D, NOW + H, NOW + H)  # above the window cutoff
        assert got == store.reference(BASE, BASE + D, NOW + H, NOW + H)[0]
        assert got[0]["revision"] == 1
        assert store.directs == 1


async def test_window_extends_contiguously_in_both_directions() -> None:
    store = Store([make_row(BASE + n * D, 0, BASE, BASE, value=n) for n in range(400)])
    with pit_read_scope():
        for lo, hi in ((200, 210), (50, 60), (300, 310), (0, 400), (20, 30), (10, 395)):
            start, end = BASE + lo * D, BASE + hi * D
            got = await store.read(start, end, LIMIT, LIMIT)
            assert got == store.reference(start, end, LIMIT, LIMIT)[0]
            assert len(got) == hi - lo
        # (50,60) was before the loaded range, (300,310) after; neither re-read what was loaded
        loaded = sorted(store.loads)
        for (_, hi_a, _), (lo_b, _, _) in pairwise(loaded):
            assert hi_a <= lo_b  # no range loaded twice
    assert store.directs == 0


async def test_empty_ranges_and_missing_values_and_ordering() -> None:
    store = Store(
        [
            make_row(BASE + 2 * D, 0, BASE, BASE, value=None),
            make_row(BASE + D, 0, BASE, BASE, value=5),
            make_row(BASE + 3 * D, 0, BASE, BASE, value=None),
        ]
    )
    with pit_read_scope():
        empty = await store.read(BASE + 10 * D, BASE + 11 * D, LIMIT, LIMIT)
        assert empty == []
        got = await store.read(BASE, BASE + 5 * D, LIMIT, LIMIT)
    assert [r["value"] for r in got] == [5, None, None]
    assert [r["event_time"] for r in got] == sorted(r["event_time"] for r in got)


async def test_isolation_between_engines_scopes_and_outside_a_scope() -> None:
    store = Store([make_row(BASE, 0, BASE, BASE)])
    other_engine = object()
    args = (BASE, BASE + D, LIMIT, LIMIT)
    with pit_read_scope():
        await store.read(*args)
        await store.read(*args)
        assert len(store.loads) == 1  # reused within the scope
        await store.read(*args, engine=other_engine)
        assert len(store.loads) == 2  # another engine never shares
        await store.read(*args, family=("other",))
        assert len(store.loads) == 3  # another family never shares
        with pit_read_scope():
            await store.read(*args)
            assert len(store.loads) == 4  # a nested scope is independent
        await store.read(*args)
        assert len(store.loads) == 4  # and does not disturb the outer one
    with pit_read_scope():
        await store.read(*args)
    assert len(store.loads) == 5  # a new scope starts empty
    before = store.directs
    await store.read(*args)  # no scope: straight through
    assert (store.directs, len(store.loads)) == (before + 1, 5)


async def test_returned_rows_are_private_copies() -> None:
    store = Store([make_row(BASE, 0, BASE, BASE)])
    with pit_read_scope():
        first = await store.read(BASE, BASE + D, LIMIT, LIMIT)
        first[0]["value"] = 999
        first[0]["tags"].append("mutated")
        first.append({})
        second = await store.read(BASE, BASE + D, LIMIT, LIMIT)
    assert second == [make_row(BASE, 0, BASE, BASE)]


async def test_row_budget_falls_back_to_sql_and_stops_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pit_memo, "MAX_WINDOW_ROWS", 5)
    store = Store([make_row(BASE + n * D, 0, BASE, BASE) for n in range(20)])
    with pit_read_scope() as stats:
        for _ in range(3):
            got = await store.read(BASE, BASE + 20 * D, LIMIT, LIMIT)
            assert got == store.reference(BASE, BASE + 20 * D, LIMIT, LIMIT)[0]
    assert len(store.loads) == 1  # tried once, then disabled
    assert store.directs == 3
    assert stats.window_hits == 0


async def test_concurrent_requests_do_not_duplicate_rows() -> None:
    store = Store([make_row(BASE + n * D, 0, BASE, BASE, value=n) for n in range(60)])
    ranges = [(0, 10), (5, 25), (30, 40), (0, 60), (50, 60), (12, 14)]
    with pit_read_scope():
        results = await asyncio.gather(
            *(store.read(BASE + a * D, BASE + b * D, LIMIT, LIMIT) for a, b in ranges)
        )
    for (a, b), got in zip(ranges, results, strict=True):
        assert [r["value"] for r in got] == list(range(a, b))
