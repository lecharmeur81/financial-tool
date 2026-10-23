"""Precomputed default Historical Similarity response (Redis, never a source of truth — ADR-0024).

The default ``GET /api/v1/similarity/current`` (no ``as_of``, no ``knowledge_time``) costs roughly
25 s to compute (about 103 historical candidate snapshots), far beyond the 8 s frontend timeout. A
scheduled worker task (``similarity.refresh``) computes exactly that default response with the
unchanged ``SimilarityService.current`` and stores it here; the route serves it instead of
recomputing.

Safeguards (each covered by a unit test):

- the stored entry carries the exact ``as_of`` / ``knowledge_time`` it was computed for and the
  time it was stored; an entry older than ``MAX_AGE_SECONDS`` (measured from its ``as_of``, the
  conservative end) is never served as current;
- a missing, expired, malformed or unreadable entry is a controlled 503, never a silent live
  recomputation (a 25 s request) and never stale data presented as current;
- a refresh that fails or is cut short writes nothing, so the previous entry is left untouched and
  simply ages out; a lock prevents overlapping refreshes;
- ``freshness`` states the age of *this result only*. It is not evidence that the market data the
  result was computed from is current.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from fastapi.encoders import jsonable_encoder

from cfi.api.params import resolve_query_times
from cfi.core.errors import ServiceUnavailableError
from cfi.core.logging import get_logger
from cfi.core.pit_memo import pit_read_scope
from cfi.core.time import utc_now

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)

CACHE_KEY = "cfi:similarity:current:v1"
LOCK_KEY = "cfi:similarity:refresh:lock"
SCHEMA_VERSION = 1
# A served result is never older than this (measured from its ``as_of``).
MAX_AGE_SECONDS = 900
# Refresh well inside the maximum age so a valid entry always exists while the next one (about
# 25 s of work) is being computed; a 900 s refresh would leave a gap on every cycle.
REFRESH_INTERVAL_SECONDS = 600
# Longer than the task's own time limit; released early by its owner, expires if the worker dies.
LOCK_TTL_SECONDS = 150
# An entry stamped further in the future than this is treated as malformed (clock fault).
_CLOCK_SKEW = timedelta(seconds=60)

FRESHNESS_NOTE = (
    "Age of this similarity result only. It does not establish that the underlying market, flow "
    "or macro data used to compute it is current; check the data-quality views for that."
)

_RELEASE_IF_OWNER_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)

Compute = Callable[[datetime, datetime], Awaitable[dict[str, Any]]]


def _unavailable(reason: str) -> ServiceUnavailableError:
    return ServiceUnavailableError(
        f"The precomputed Historical Similarity result is not available ({reason}). "
        "It is refreshed by a background job; retry shortly, or pass an explicit as_of for a "
        "slower live computation."
    )


def build_entry(
    payload: dict[str, Any], *, as_of: datetime, knowledge_time: datetime, computed_at: datetime
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "knowledge_time": knowledge_time.isoformat(),
        "computed_at": computed_at.isoformat(),
        "payload": jsonable_encoder(payload),
    }


def _aware(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed


def serve_entry(raw: str | None, *, now: datetime) -> dict[str, Any]:
    """The cached response with its ``freshness`` block, or ``ServiceUnavailableError``."""
    if raw is None:
        raise _unavailable("no result has been computed yet")
    try:
        entry = json.loads(raw)
        if not isinstance(entry, dict) or entry.get("version") != SCHEMA_VERSION:
            raise ValueError("unexpected entry shape or version")
        as_of = _aware(entry.get("as_of"))
        knowledge_time = _aware(entry.get("knowledge_time"))
        computed_at = _aware(entry.get("computed_at"))
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        if as_of != knowledge_time or payload.get("as_of") != as_of.isoformat():
            raise ValueError("entry is not the default now/now view")
        if computed_at < as_of or computed_at > now + _CLOCK_SKEW:
            raise ValueError("inconsistent timestamps")
    except (ValueError, TypeError) as exc:
        log.warning("similarity_precompute_malformed", error=str(exc))
        raise _unavailable("the stored entry is malformed") from exc

    age = (now - as_of).total_seconds()
    if age > MAX_AGE_SECONDS:
        log.warning("similarity_precompute_expired", age_seconds=round(age))
        raise _unavailable(f"the latest result is {round(age)} s old, over {MAX_AGE_SECONDS} s")
    return {
        **payload,
        "freshness": {
            "source": "precomputed",
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "computed_at": computed_at.isoformat(),
            "age_seconds": max(0, round(age)),
            "max_age_seconds": MAX_AGE_SECONDS,
            "note": FRESHNESS_NOTE,
        },
    }


async def read_current(redis: Redis | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Serve the precomputed default response (see :func:`serve_entry`)."""
    if redis is None:
        raise _unavailable("the cache is not configured")
    try:
        raw = await redis.get(CACHE_KEY)
    except Exception as exc:
        log.warning("similarity_precompute_read_failed", exc_info=True)
        raise _unavailable("the cache could not be read") from exc
    return serve_entry(raw, now=utc_now() if now is None else now)


async def _release(redis: Redis, token: str) -> None:
    try:
        await cast("Awaitable[Any]", redis.eval(_RELEASE_IF_OWNER_LUA, 1, LOCK_KEY, token))
    except Exception:
        log.warning("similarity_precompute_lock_release_failed", exc_info=True)


async def refresh_current(redis: Redis, compute: Compute) -> dict[str, Any]:
    """Compute the default response and store it. Writes only after a complete, successful
    computation; any failure propagates and leaves the existing entry untouched."""
    token = uuid.uuid4().hex
    if not await redis.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL_SECONDS):
        return {"skipped": "another refresh is already running"}
    try:
        as_of, knowledge_time = resolve_query_times(None, None)
        with pit_read_scope():
            payload = await compute(as_of, knowledge_time)
        entry = build_entry(
            payload, as_of=as_of, knowledge_time=knowledge_time, computed_at=utc_now()
        )
        await redis.set(CACHE_KEY, json.dumps(entry), ex=MAX_AGE_SECONDS)
        return {
            "stored": True,
            "as_of": entry["as_of"],
            "status": payload.get("status"),
            "computed_at": entry["computed_at"],
        }
    finally:
        await _release(redis, token)
