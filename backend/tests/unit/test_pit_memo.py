"""``cfi.core.pit_memo``: reuse only for identical keys inside one scope; never across scopes,
never outside a scope, never for exceptions; stored values are isolated copies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from cfi.core.pit_memo import pit_read, pit_read_scope

T0 = datetime(2026, 9, 28, 12, 0, 0, 123456, tzinfo=UTC)
ENGINE = object()


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self) -> dict[str, Any]:
        self.calls += 1
        return {"n": self.calls, "nested": {"x": [1, 2]}}


async def _read(c: _Counter, *, name: str = "r", engine: object = ENGINE, **kw: Any) -> Any:
    args = kw.get("args", ("BTC", T0, T0))
    return await pit_read(name, engine, *args, call=c.read)


async def test_outside_a_scope_every_call_reads() -> None:
    c = _Counter()
    await _read(c)
    await _read(c)
    assert c.calls == 2


async def test_identical_inputs_inside_a_scope_reuse() -> None:
    c = _Counter()
    with pit_read_scope() as stats:
        a = await _read(c)
        b = await _read(c)
    assert c.calls == 1
    assert a == b
    assert (stats.hits, stats.misses) == (1, 1)


@pytest.mark.parametrize(
    "args",
    [
        ("ETH", T0, T0),  # asset
        ("BTC", T0 + timedelta(microseconds=1), T0),  # as_of differs by 1 microsecond
        ("BTC", T0, T0 + timedelta(microseconds=1)),  # knowledge_time (revision cutoff) differs
        ("BTC", T0 + timedelta(days=1), T0),  # same calendar date NOT required to match: other day
        ("BTC", T0.replace(hour=0, minute=0, second=0, microsecond=0), T0),  # same date, other time
        ("BTC", T0.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None), T0),  # naive
    ],
)
async def test_different_inputs_never_reuse(args: tuple[Any, ...]) -> None:
    c = _Counter()
    with pit_read_scope() as stats:
        await _read(c)
        await _read(c, args=args)
    assert c.calls == 2
    assert stats.hits == 0


async def test_same_instant_in_other_timezone_is_a_conservative_miss() -> None:
    c = _Counter()
    with pit_read_scope():
        await _read(c)
        await _read(c, args=("BTC", T0.astimezone(timezone(timedelta(hours=8))), T0))
    assert c.calls == 2  # never reuse on a looser equality than identical representation


async def test_other_read_name_or_engine_never_reuses() -> None:
    c = _Counter()
    with pit_read_scope():
        await _read(c)
        await _read(c, name="other")
        await _read(c, engine=object())
    assert c.calls == 3


async def test_scopes_do_not_share_and_exit_discards() -> None:
    c = _Counter()
    with pit_read_scope():
        await _read(c)
    with pit_read_scope():
        await _read(c)
    assert c.calls == 2


async def test_exceptions_are_not_cached() -> None:
    state = {"n": 0}

    async def flaky() -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    with pit_read_scope() as stats:
        with pytest.raises(RuntimeError):
            await pit_read("r", ENGINE, T0, call=flaky)
        assert await pit_read("r", ENGINE, T0, call=flaky) == "ok"
        assert await pit_read("r", ENGINE, T0, call=flaky) == "ok"
    assert state["n"] == 2
    assert (stats.hits, stats.misses) == (1, 1)


async def test_returned_values_are_isolated_copies() -> None:
    c = _Counter()
    with pit_read_scope():
        first = await _read(c)
        first["nested"]["x"].append(99)  # mutating the first result...
        second = await _read(c)
        second["nested"]["x"].append(7)
        third = await _read(c)
    assert third["nested"]["x"] == [1, 2]  # ...never leaks into later reads


async def test_entry_cap_keeps_reading_correctly() -> None:
    c = _Counter()
    with pit_read_scope(max_entries=1) as stats:
        await _read(c, args=("BTC", T0, T0))
        await _read(c, args=("ETH", T0, T0))  # over the cap: read, not stored
        await _read(c, args=("ETH", T0, T0))  # so read again, never wrong
        await _read(c, args=("BTC", T0, T0))  # stored entry still reused
    assert c.calls == 3
    assert stats.uncached == 2


def test_default_cap_covers_one_evaluations_historical_builds() -> None:
    from cfi.core.pit_memo import DEFAULT_MAX_ENTRIES

    # ~300 distinct historical snapshot builds x 7 reads; below this, reuse would silently stop
    # part-way through the evaluation (a 512 cap filled during the 120-day regime walk).
    assert DEFAULT_MAX_ENTRIES >= 300 * 7
