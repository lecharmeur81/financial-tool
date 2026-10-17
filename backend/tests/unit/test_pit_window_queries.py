"""The five query methods that use ``pit_revision_window``, driven through a fake ``_all``.

``fake_all`` interprets the parameters of the two SQL shapes each method issues: the production
query (``as_of`` / ``kt`` parameters, ``DISTINCT ON`` semantics) and the window loader (``cutoff``
parameter, every revision). For each method the result inside a ``pit_read_scope`` must equal the
result outside one (the untouched SQL path) for randomized requests, with fewer reads. This proves
the wiring (series parameters, family keys, copied columns, cut-offs), not the SQL text; the
SQL text keeps the production predicates and is covered by the disposable-database tests.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from cfi.core import pit_memo
from cfi.core.pit_memo import pit_read_scope
from cfi.macro import queries as macro_queries
from cfi.macro.queries import MacroQueries
from cfi.market import queries as market_queries
from cfi.market.queries import MarketQueries
from cfi.market_structure import queries as ms_queries
from cfi.market_structure.queries import MarketStructureQueries
from cfi.retail import queries as retail_queries
from cfi.retail.queries import RetailQueries

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
BASE = datetime(2026, 6, 1, tzinfo=UTC)
LIMIT = NOW - pit_memo.LATE_ARRIVAL_MARGIN


def columns(spec: str) -> list[str]:
    return [c.strip().removeprefix("o.") for c in spec.split(",")]


OBS_FULL = columns(macro_queries.OBS_COLUMNS)
SERIES = [  # (series_id, dataset_id, asset, venue)
    (1, "ds.a", "BTC", "binance"),
    (2, "ds.a", "BTC", "okx"),  # same asset, other venue: only the unfiltered queries see it
    (3, "ds.a", "ETH", "binance"),
    (4, "ds.b", "BTC", "binance"),
]


def build_rows(seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture data
    rows: list[dict[str, Any]] = []
    for sid, *_ in SERIES:
        for n in range(240):
            event = BASE + n * timedelta(hours=6)
            if sid == 2 and rng.random() < 0.7:
                continue
            for revision in range(rng.choice([1, 1, 2, 3])):
                avail = event + timedelta(minutes=rng.randint(0, 600))
                ingested = (
                    event + timedelta(minutes=rng.randint(0, 1800)) + revision * timedelta(hours=2)
                )
                missing = rng.random() < 0.08
                rows.append(
                    {
                        "series_id": sid,
                        "event_time": event,
                        "value": None if missing else Decimal(rng.randint(1, 999)) / 10,
                        "quality_status": "missing" if missing else "ok",
                        "quality_note": None,
                        "revision": revision + (5 if sid == 2 else 0),  # never ties
                        "pit_reliability": "point_in_time",
                        "available_at": avail,
                        "available_at_estimated": False,
                        "ingested_at": ingested,
                        "source_provider": rng.choice(["fred", "x"]),
                        "original_source": "orig",
                        # bar columns
                        "open": Decimal(1),
                        "high": Decimal(2),
                        "low": Decimal(1),
                        "close": Decimal(2),
                        "volume_base": Decimal(5),
                        "volume_quote": Decimal(6),
                        "trade_count": 7,
                        "transformations": ["t1"],
                    }
                )
    rng.shuffle(rows)
    return rows


class FakeDb:
    def __init__(self, rows: list[dict[str, Any]], cols: list[str], bars: bool) -> None:
        self.rows, self.cols, self.bars = rows, cols, bars
        self.calls = {"direct": 0, "load": 0}

    async def all(self, sql: str, **p: Any) -> list[dict[str, Any]]:
        loader = "cutoff" in p
        self.calls["load" if loader else "direct"] += 1
        if self.bars:
            wanted = {p["sid"]}
            avail_cut, ing_cut = (p["cutoff"],) * 2 if loader else (p["as_of"],) * 2
        else:
            asset = p.get("subject", p.get("asset"))
            wanted = {
                sid
                for sid, ds, a, venue in SERIES
                if ds == p["d"] and a == asset and ("venue" not in p or venue == p["venue"])
            }
            avail_cut, ing_cut = (p["cutoff"],) * 2 if loader else (p["as_of"], p["kt"])
        picked = [
            r
            for r in self.rows
            if r["series_id"] in wanted
            and p["start"] <= r["event_time"] < p["end"]
            and r["available_at"] <= avail_cut
            and r["ingested_at"] <= ing_cut
        ]
        picked.sort(key=lambda r: (r["event_time"], -r["revision"]))
        if not loader:  # DISTINCT ON (event_time) ... ORDER BY event_time, revision DESC
            first_per_event: dict[datetime, dict[str, Any]] = {}
            for r in picked:
                first_per_event.setdefault(r["event_time"], r)
            picked = list(first_per_event.values())
        return [
            {c: (list(r[c]) if c == "transformations" else r[c]) for c in self.cols} for r in picked
        ]


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pit_memo, "_utc_now", lambda: NOW)


Case = tuple[
    Any, list[str], bool, Callable[[Any, datetime, datetime, datetime, datetime], Awaitable[Any]]
]


def _cases() -> dict[str, Case]:
    def obs(subject: str = "BTC") -> Callable[..., Awaitable[Any]]:
        async def call(
            q: Any, start: datetime, end: datetime, as_of: datetime, kt: datetime
        ) -> Any:
            return await q.observations(
                "ds.a", subject=subject, start=start, end=end, as_of=as_of, knowledge_time=kt
            )

        return call

    async def deriv(q: Any, start: datetime, end: datetime, as_of: datetime, kt: datetime) -> Any:
        return await q.derivatives_observations(
            "ds.a", asset="BTC", start=start, end=end, as_of=as_of, knowledge_time=kt
        )

    async def bars(q: Any, start: datetime, end: datetime, as_of: datetime, kt: datetime) -> Any:
        return await q.bars(1, "prov", start, end, as_of)

    retail_cols = columns(retail_queries.OBS_COLUMNS)
    return {
        "macro.observations": (MacroQueries, OBS_FULL, False, obs()),
        "market_structure.observations": (
            MarketStructureQueries,
            columns(ms_queries.OBS_COLUMNS),
            False,
            obs("ETH"),
        ),
        "retail.observations": (RetailQueries, retail_cols, False, obs()),
        "retail.derivatives_observations": (RetailQueries, retail_cols, False, deriv),
        "market.bars": (MarketQueries, columns(market_queries.BAR_COLUMNS), True, bars),
    }


@pytest.mark.parametrize("name", list(_cases()))
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_cached_results_equal_direct_results(name: str, seed: int) -> None:
    cls, cols, bars, call = _cases()[name]
    rows = build_rows(seed)
    rng = random.Random(seed * 7919)  # noqa: S311 - deterministic fixture data
    requests = []
    for _ in range(40):
        start = BASE + timedelta(hours=rng.randint(-100, 900))
        end = start + timedelta(hours=rng.randint(24, 24 * 90))
        as_of = BASE + timedelta(hours=rng.randint(0, 24 * 80))
        kt = (
            as_of if bars or rng.random() < 0.5 else BASE + timedelta(hours=rng.randint(0, 24 * 80))
        )
        requests.append((start, end, as_of, kt))
    requests.append((BASE, BASE + 90 * timedelta(days=1), NOW, NOW))  # too recent: SQL path

    plain_db = FakeDb(rows, cols, bars)
    plain = cls(object())
    plain._all = plain_db.all
    expected = [await call(plain, *r) for r in requests]

    fast_db = FakeDb(rows, cols, bars)
    fast = cls(object())
    fast._all = fast_db.all
    with pit_read_scope() as stats:
        got = [await call(fast, *r) for r in requests]

    assert got == expected
    for g, e in zip(got, expected, strict=True):
        assert [list(r) for r in g] == [list(r) for r in e]  # same columns, same order
    assert any(expected), "fixture must return rows"
    assert bars or any(r["value"] is None for g in got for r in g)  # missing values kept
    assert stats.window_hits >= 30
    assert fast_db.calls["load"] < plain_db.calls["direct"] / 2
    assert fast_db.calls["direct"] == 1  # only the too-recent request
    assert plain_db.calls == {"direct": len(requests), "load": 0}


async def test_no_scope_means_no_window_reads() -> None:
    cls, cols, bars, call = _cases()["macro.observations"]
    db = FakeDb(build_rows(1), cols, bars)
    q = cls(object())
    q._all = db.all
    await call(q, BASE, BASE + 30 * timedelta(days=1), LIMIT, LIMIT)
    assert db.calls == {"direct": 1, "load": 0}


async def test_series_parameters_are_part_of_the_window_key() -> None:
    """Different dataset / asset / venue / series / provider never share a window."""
    rows = build_rows(4)
    cols = OBS_FULL
    q = MacroQueries(object())  # type: ignore[arg-type]
    db = FakeDb(rows, cols, False)
    q._all = db.all  # type: ignore[method-assign]
    plain = MacroQueries(object())  # type: ignore[arg-type]
    plain_db = FakeDb(rows, cols, False)
    plain._all = plain_db.all  # type: ignore[method-assign]
    span = (BASE, BASE + 60 * timedelta(days=1), LIMIT, LIMIT)
    with pit_read_scope():
        for ds, subject in (("ds.a", "BTC"), ("ds.a", "ETH"), ("ds.b", "BTC"), ("ds.a", "BTC")):
            kw: dict[str, Any] = {
                "subject": subject,
                "start": span[0],
                "end": span[1],
                "as_of": span[2],
            }
            got = await q.observations(ds, knowledge_time=span[3], **kw)
            assert got == await plain.observations(ds, knowledge_time=span[3], **kw)
    assert db.calls["load"] == 3  # the repeated ("ds.a", "BTC") reused its window
    bar_db = FakeDb(rows, columns(market_queries.BAR_COLUMNS), True)
    bq = MarketQueries(object())  # type: ignore[arg-type]
    bq._all = bar_db.all  # type: ignore[method-assign]
    with pit_read_scope():
        for sid, prov in ((1, "p"), (2, "p"), (1, "q"), (1, "p")):
            await bq.bars(sid, prov, span[0], span[1], span[2])
    assert bar_db.calls["load"] == 3


async def test_two_engines_never_share_rows() -> None:
    rows = build_rows(5)
    dbs = []
    qs = []
    for _ in range(2):
        db = FakeDb(rows, OBS_FULL, False)
        q = MacroQueries(object())  # type: ignore[arg-type]
        q._all = db.all  # type: ignore[method-assign]
        dbs.append(db)
        qs.append(q)
    with pit_read_scope():
        for q in qs:
            for _ in range(3):
                await q.observations(
                    "ds.a",
                    subject="BTC",
                    start=BASE,
                    end=BASE + 30 * timedelta(days=1),
                    as_of=LIMIT,
                    knowledge_time=LIMIT,
                )
    assert [d.calls["load"] for d in dbs] == [1, 1]


async def test_revision_tie_across_series_uses_the_sql_path() -> None:
    event = BASE + timedelta(days=1)
    base = {
        "event_time": event,
        "value": Decimal(1),
        "quality_status": "ok",
        "quality_note": None,
        "revision": 0,
        "pit_reliability": "point_in_time",
        "available_at": event,
        "available_at_estimated": False,
        "ingested_at": event,
        "source_provider": "fred",
        "original_source": "o",
    }
    rows = [dict(base, series_id=1), dict(base, series_id=2, value=Decimal(2))]
    db = FakeDb(rows, OBS_FULL, False)
    q = MacroQueries(object())  # type: ignore[arg-type]
    q._all = db.all  # type: ignore[method-assign]
    with pit_read_scope() as stats:
        got = await q.observations(
            "ds.a",
            subject="BTC",
            start=BASE,
            end=BASE + 5 * timedelta(days=1),
            as_of=LIMIT,
            knowledge_time=LIMIT,
        )
    assert db.calls == {"direct": 1, "load": 1}
    assert stats.window_fallbacks == 1
    assert [r["value"] for r in got] == [Decimal(1)]  # exactly what the direct query returned
