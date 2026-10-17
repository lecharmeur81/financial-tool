"""Per-evaluation memo for point-in-time (PIT) domain reads.

``cfi.regime.snapshot.gather_snapshot`` and ``cfi.similarity.snapshot.gather_snapshot`` make the
same seven domain-service reads with the same arguments. Within one analyst snapshot build the two
engines walk overlapping historical dates, so the same ``(read, asset, as_of, knowledge_time)`` can
be requested twice.

Why reuse is safe (Phase 51):

* The key contains the exact ``as_of`` and ``knowledge_time`` instants (full ISO-8601 including
  microseconds and offset) — nothing is rounded to a day, so two calls only share a result when
  their inputs are identical.
* Every domain service filters ``available_at <= as_of`` and ``ingested_at <= knowledge_time``;
  ``ingested_at`` is the ingestion clock, so rows written after ``knowledge_time`` are invisible
  to both calls. Identical inputs therefore read identical rows.
* The memo only lives inside an explicit :func:`pit_read_scope` (one ``build_snapshot`` call) and
  is discarded on exit; it is never shared across evaluations, so there is no stale-data reuse
  and a later evaluation (different ``as_of``/``knowledge_time``, or newly ingested revisions)
  always re-reads.
* The engine identity is part of the key, so different databases never share entries.
* Outside a scope :func:`pit_read` calls straight through, so behaviour is unchanged.
* Stored and returned values are deep copies, so a consumer mutating a result cannot affect
  another consumer. Exceptions are never cached (the next call retries).

Revision windows (Phase 51, step 2)
-----------------------------------

:func:`pit_revision_window` lets a point-in-time *query method* reuse one wide read of a series'
revisions for many ``(start, end, as_of, knowledge_time)`` requests inside the same scope. It is
only ever used inside a scope and the window dies with it. A request is answered from the window
only when that provably gives the rows the production SQL would return; otherwise the caller's
existing SQL runs (``direct``):

* The window loads **every revision** with ``available_at <= cutoff`` and ``ingested_at <= cutoff``
  for a contiguous ``event_time`` range, using the same series predicates as the production query.
  A request with ``as_of <= cutoff`` and ``knowledge_time <= cutoff`` sees a subset of those rows;
  Python then re-applies the production predicates (``event_time >= start``, ``event_time < end``,
  ``available_at <= as_of``, ``ingested_at <= knowledge_time``) and keeps the highest ``revision``
  per ``event_time`` (``DISTINCT ON (event_time) ... ORDER BY event_time, revision DESC``).
* ``cutoff`` is fixed when the window is created and is at most ``now - LATE_ARRIVAL_MARGIN``.
  ``ingested_at`` is the ingestion clock, so a row stored after the window was loaded has
  ``ingested_at > cutoff`` and is invisible to every request the window serves, exactly as under
  SQL. Requests with a later ``as_of``/``knowledge_time`` (including "now") use SQL.
* If two visible rows share an ``event_time`` and the top ``revision`` (different providers or
  series), SQL's pick is unspecified, so the request uses SQL.
* A request outside the loaded ``event_time`` range extends the window (never a gap); naive
  datetimes, an exhausted row budget, or any doubt use SQL.
* The window key contains the engine identity and the query's series parameters; windows live in
  the scope's memo only. Returned rows are fresh dicts (list-valued columns are copied).

Not covered: an in-place UPDATE of an already stored row (e.g. a quality flag) while a scope is
open is not seen by the window. Scopes last one alert evaluation.

Window counters (``PitMemoStats``)
----------------------------------

These describe revision-window traffic only; reads that do not go through
:func:`pit_revision_window` are not counted in them.

* ``window_hits``: requests answered from a window. A request whose own window load filled or
  extended the window and was then answered from it also counts, so hits are not "pure cache
  hits" (hits per load shows how many requests each SQL read served).
* ``window_loads``: SQL reads made to fill or extend a window (a load that then fails the row
  budget still counts).
* ``window_fallbacks``: requests that used the normal SQL path (``direct``) instead. This
  combines every cause (naive datetimes or an empty range, ``as_of``/``knowledge_time`` later
  than the cutoff, a disabled window or exhausted row budget, a visible revision tie) and does not
  identify which one applied.

Zero fallbacks is expected for the seeded historical benchmark, whose anchor lies well in the
past. It is not a universal production requirement: live reads near the present (later than
``now - LATE_ARRIVAL_MARGIN``) correctly fall back to SQL and are counted as fallbacks.

This is a leaf module: it imports nothing from ``cfi``.
"""

from __future__ import annotations

import asyncio
import copy
from bisect import bisect_left
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

# One alert evaluation builds at most ~300 distinct historical snapshots (regime duration walk,
# regime examples, similarity candidates) x 7 reads = ~2100 entries; the cap must exceed that or
# reuse silently stops part-way (e.g. at 512 the 120-day regime walk alone would fill it before the
# similarity candidates that overlap it). The scope is discarded after each snapshot build, so
# the memory is held only for the duration of one evaluation.
DEFAULT_MAX_ENTRIES = 2304


@dataclass(slots=True)
class PitMemoStats:
    """Counters for one scope: ``misses`` are real reads, ``hits`` are reuses."""

    hits: int = 0
    misses: int = 0
    uncached: int = 0  # misses not stored because the entry cap was reached
    hits_by_name: dict[str, int] = field(default_factory=dict)
    misses_by_name: dict[str, int] = field(default_factory=dict)
    window_hits: int = 0  # requests answered from a revision window
    window_loads: int = 0  # SQL reads that filled or extended a revision window
    window_fallbacks: int = 0  # requests that used the existing SQL instead


class _Memo:
    __slots__ = ("entries", "max_entries", "stats", "window_rows", "windows")

    def __init__(self, max_entries: int) -> None:
        self.entries: dict[tuple[Any, ...], Any] = {}
        self.max_entries = max_entries
        self.stats = PitMemoStats()
        self.windows: dict[tuple[Any, ...], _Window] = {}
        self.window_rows = 0


_scope: ContextVar[_Memo | None] = ContextVar("cfi_pit_memo", default=None)


def _norm(value: object) -> object:
    """Hashable, exact representation of one key part. Datetimes keep every component
    (microseconds, tzinfo offset); naive and aware values never compare equal."""
    if isinstance(value, datetime):
        return ("dt", value.isoformat())
    if isinstance(value, date):
        return ("d", value.isoformat())
    return (type(value).__name__, value)


@contextmanager
def pit_read_scope(max_entries: int = DEFAULT_MAX_ENTRIES) -> Iterator[PitMemoStats]:
    """Open a fresh memo for the duration of the ``with`` block (nested scopes are independent)."""
    memo = _Memo(max_entries)
    token = _scope.set(memo)
    try:
        yield memo.stats
    finally:
        _scope.reset(token)


async def pit_read[T](
    name: str, engine: object, *args: object, call: Callable[[], Awaitable[T]]
) -> T:
    """Return ``await call()``, reusing a prior result with an identical key inside the scope."""
    memo = _scope.get()
    if memo is None:
        return await call()
    key = (name, id(engine), *(_norm(a) for a in args))
    if key in memo.entries:
        memo.stats.hits += 1
        memo.stats.hits_by_name[name] = memo.stats.hits_by_name.get(name, 0) + 1
        return copy.deepcopy(memo.entries[key])  # type: ignore[no-any-return]
    value = await call()
    memo.stats.misses += 1
    memo.stats.misses_by_name[name] = memo.stats.misses_by_name.get(name, 0) + 1
    if len(memo.entries) < memo.max_entries:
        memo.entries[key] = copy.deepcopy(value)
    else:
        memo.stats.uncached += 1
    return value


# ---------------------------------------------------------------------------- revision windows

LATE_ARRIVAL_MARGIN = timedelta(minutes=5)  # cutoff = now - margin (clock-skew allowance)
WINDOW_EXTEND_PAD = timedelta(days=120)  # extra event_time span loaded when a window is extended
MAX_WINDOW_ROWS = 400_000  # revision rows held per scope; beyond this the SQL path is used

#: ``load(start, end, cutoff)``: every revision with ``start <= event_time < end``,
#: ``available_at <= cutoff`` and ``ingested_at <= cutoff`` (same series predicates as the direct
#: query), each row a dict with at least ``event_time``, ``available_at``, ``ingested_at`` and
#: ``revision``, and the same keys in the same order as the direct query returns.
RevisionLoader = Callable[[datetime, datetime, datetime], Awaitable[list[dict[str, Any]]]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _Window:
    __slots__ = ("cutoff", "disabled", "hi", "keys", "lo", "lock", "rows", "strings", "times")

    def __init__(self, cutoff: datetime) -> None:
        self.cutoff = cutoff
        self.disabled = False
        self.lo: datetime | None = None  # loaded event_time range is [lo, hi)
        self.hi: datetime | None = None
        self.keys: tuple[str, ...] | None = None
        # (event_time, available_at, ingested_at, revision, values) sorted by event_time
        self.rows: list[tuple[Any, ...]] = []
        self.times: list[datetime] = []
        self.strings: dict[str, str] = {}
        self.lock = asyncio.Lock()


def _aware(*values: datetime) -> bool:
    return all(v.tzinfo is not None and v.utcoffset() is not None for v in values)


def _compact(win: _Window, rows: Sequence[dict[str, Any]]) -> list[tuple[Any, ...]] | None:
    """Rows as tuples sharing repeated strings; ``None`` if the column set is inconsistent."""
    out: list[tuple[Any, ...]] = []
    for r in rows:
        keys = tuple(r)
        if win.keys is None:
            win.keys = keys
        elif keys != win.keys:
            return None
        values = tuple(win.strings.setdefault(v, v) if type(v) is str else v for v in r.values())
        out.append((r["event_time"], r["available_at"], r["ingested_at"], r["revision"], values))
    out.sort(key=lambda t: t[0])
    return out


async def _extend(
    memo: _Memo, win: _Window, start: datetime, end: datetime, load: RevisionLoader
) -> bool:
    """Make ``[start, end)`` part of the loaded range. ``False`` means: use the SQL path."""
    if win.lo is None or win.hi is None:
        pieces = [(start, end, False)]
    else:
        pieces = []
        if start < win.lo:
            pieces.append((start - WINDOW_EXTEND_PAD, win.lo, True))
        if end > win.hi:
            pieces.append((win.hi, end + WINDOW_EXTEND_PAD, False))
    for lo, hi, before in pieces:
        loaded = await load(lo, hi, win.cutoff)
        memo.stats.window_loads += 1
        compact = _compact(win, loaded)
        if compact is None or memo.window_rows + len(compact) > MAX_WINDOW_ROWS:
            memo.window_rows -= len(win.rows)
            win.rows, win.times, win.disabled = [], [], True
            return False
        memo.window_rows += len(compact)
        if win.lo is None or win.hi is None:
            win.lo, win.hi, win.rows = lo, hi, compact
        elif before:
            win.lo, win.rows = lo, compact + win.rows
        else:
            win.hi, win.rows = hi, win.rows + compact
        win.times = [r[0] for r in win.rows]
    return True


def _select(
    win: _Window,
    start: datetime,
    end: datetime,
    as_of: datetime,
    knowledge_time: datetime,
    copy_idx: tuple[int, ...],
) -> list[dict[str, Any]] | None:
    """The rows ``DISTINCT ON (event_time) ... ORDER BY event_time, revision DESC`` returns, or
    ``None`` when SQL's choice is unspecified (a visible revision tie)."""
    if win.keys is None:  # the loaded range holds no rows at all
        return []
    times, rows = win.times, win.rows
    i, j = bisect_left(times, start), bisect_left(times, end)
    out: list[dict[str, Any]] = []
    while i < j:
        event_time = times[i]
        best: tuple[Any, ...] | None = None
        tie = False
        while i < j and times[i] == event_time:
            row = rows[i]
            i += 1
            if row[1] <= as_of and row[2] <= knowledge_time:
                if best is None or row[3] > best[3]:
                    best, tie = row, False
                elif row[3] == best[3]:
                    tie = True
        if tie:
            return None
        if best is not None:
            values = list(best[4])
            for k in copy_idx:
                if isinstance(values[k], list):
                    values[k] = list(values[k])
            out.append(dict(zip(win.keys, values, strict=True)))
    return out


async def pit_revision_window(
    family: Sequence[object],
    engine: object,
    *,
    start: datetime,
    end: datetime,
    as_of: datetime,
    knowledge_time: datetime,
    load: RevisionLoader,
    direct: Callable[[], Awaitable[list[dict[str, Any]]]],
    copy_columns: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The rows ``direct()`` would return, served from the scope's revision window when that is
    provably identical (see the module docstring), otherwise from ``direct()`` itself.

    ``family`` must identify the query *and every parameter that selects the series* (anything
    other than ``start``/``end``/``as_of``/``knowledge_time``). Outside a scope this is exactly
    ``await direct()``."""
    memo = _scope.get()
    if memo is None:
        return await direct()
    key = ("revision_window", id(engine), tuple(_norm(p) for p in family))
    win = memo.windows.get(key)
    limit = win.cutoff if win is not None else _utc_now() - LATE_ARRIVAL_MARGIN
    if (
        not _aware(start, end, as_of, knowledge_time)
        or start >= end
        or as_of > limit
        or knowledge_time > limit
        or (win is not None and win.disabled)
    ):
        memo.stats.window_fallbacks += 1
        return await direct()
    if win is None:
        win = memo.windows[key] = _Window(limit)
    async with win.lock:
        if win.disabled or not await _extend(memo, win, start, end, load):
            memo.stats.window_fallbacks += 1
            return await direct()
        keys = win.keys or ()
        copy_idx = tuple(keys.index(c) for c in copy_columns if c in keys)
        selected = _select(win, start, end, as_of, knowledge_time, copy_idx)
    if selected is None:
        memo.stats.window_fallbacks += 1
        return await direct()
    memo.stats.window_hits += 1
    return selected
