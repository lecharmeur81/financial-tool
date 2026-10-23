"""Precomputed default Similarity response: storage, freshness, failures, route, schedule."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfi.api.app import create_app
from cfi.api.routes import similarity as route
from cfi.core import pit_memo
from cfi.core.config import Settings
from cfi.core.errors import ServiceUnavailableError
from cfi.similarity import precompute as pc
from cfi.worker.schedule import beat_schedule

NOW = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)


class FakeRedis:
    """The few Redis calls used, with SET NX / EX semantics (no clock: expiry is not simulated)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets: list[tuple[str, dict[str, Any]]] = []
        self.fail_get = False

    async def get(self, key: str) -> str | None:
        if self.fail_get:
            raise ConnectionError("down")
        return self.data.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        self.sets.append((key, {"nx": nx, "ex": ex}))
        return True

    async def eval(self, _script: str, _n: int, key: str, token: str) -> int:
        if self.data.get(key) == token:
            del self.data[key]
            return 1
        return 0


def _entry(**over: Any) -> str:
    as_of = over.pop("as_of", NOW - timedelta(seconds=30))
    entry = pc.build_entry(
        over.pop("payload", {"status": "ok", "as_of": as_of.isoformat(), "analogues": []}),
        as_of=as_of,
        knowledge_time=over.pop("knowledge_time", as_of),
        computed_at=over.pop("computed_at", as_of + timedelta(seconds=25)),
    )
    entry.update(over)
    return json.dumps(entry)


# ------------------------------------------------------------------ serving / freshness


def test_a_fresh_entry_is_served_with_its_age_and_the_payload_unchanged() -> None:
    out = pc.serve_entry(_entry(), now=NOW)
    assert out["status"] == "ok"
    fr = out["freshness"]
    assert fr["source"] == "precomputed"
    assert fr["age_seconds"] == 30
    assert fr["max_age_seconds"] == 900
    assert fr["as_of"] == fr["knowledge_time"] == (NOW - timedelta(seconds=30)).isoformat()
    assert "underlying" in fr["note"]
    out.pop("freshness")
    assert out == {
        "status": "ok",
        "as_of": (NOW - timedelta(seconds=30)).isoformat(),
        "analogues": [],
    }


def test_an_entry_exactly_at_the_maximum_age_is_served_and_one_second_older_is_not() -> None:
    pc.serve_entry(_entry(as_of=NOW - timedelta(seconds=900)), now=NOW)
    with pytest.raises(ServiceUnavailableError, match="over 900"):
        pc.serve_entry(_entry(as_of=NOW - timedelta(seconds=901)), now=NOW)


def test_a_missing_entry_is_a_controlled_error() -> None:
    with pytest.raises(ServiceUnavailableError, match="no result"):
        pc.serve_entry(None, now=NOW)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"version": 99}),
        _entry(version=2),
        _entry(payload="x"),
        json.dumps({**json.loads(_entry()), "as_of": "2026-10-22T23:59:30"}),  # naive
        _entry(knowledge_time=NOW - timedelta(days=1)),  # not the default now/now view
        _entry(computed_at=NOW + timedelta(hours=1)),  # from the future
        _entry(computed_at=NOW - timedelta(hours=1)),  # computed before its own as_of
        _entry(payload={"status": "ok", "as_of": "something-else"}),
    ],
)
def test_a_malformed_entry_is_never_served(raw: str) -> None:
    with pytest.raises(ServiceUnavailableError, match="malformed"):
        pc.serve_entry(raw, now=NOW)


async def test_read_current_handles_missing_redis_and_read_errors() -> None:
    with pytest.raises(ServiceUnavailableError, match="not configured"):
        await pc.read_current(None)
    r = FakeRedis()
    r.fail_get = True
    with pytest.raises(ServiceUnavailableError, match="could not be read"):
        await pc.read_current(r)  # type: ignore[arg-type]


# ------------------------------------------------------------------ refresh


async def test_refresh_stores_the_exact_view_once_and_releases_the_lock() -> None:
    r = FakeRedis()
    seen: dict[str, Any] = {}

    async def compute(a: datetime, k: datetime) -> dict[str, Any]:
        seen["scope"] = pit_memo._scope.get() is not None
        seen["pair"] = (a, k)
        return {"status": "ok", "as_of": a.isoformat(), "knowledge_time": k.isoformat()}

    result = await pc.refresh_current(r, compute)  # type: ignore[arg-type]
    assert result["stored"] is True
    assert seen["scope"] is True  # computed inside one request-style PIT memo
    assert seen["pair"][0] == seen["pair"][1]  # the default view: as_of == knowledge_time
    stored = json.loads(r.data[pc.CACHE_KEY])
    assert stored["as_of"] == seen["pair"][0].isoformat()
    assert stored["knowledge_time"] == seen["pair"][1].isoformat()
    assert (pc.CACHE_KEY, {"nx": False, "ex": 900}) in r.sets  # Redis drops it at the max age
    assert pc.LOCK_KEY not in r.data
    assert pit_memo._scope.get() is None
    # what was stored is servable and equals the computed payload
    served = await pc.read_current(r)  # type: ignore[arg-type]
    assert served["status"] == "ok"
    assert served["freshness"]["age_seconds"] <= 5


async def test_a_failed_refresh_keeps_the_previous_entry_and_releases_the_lock() -> None:
    r = FakeRedis()
    r.data[pc.CACHE_KEY] = "previous"

    async def boom(_a: datetime, _k: datetime) -> dict[str, Any]:
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await pc.refresh_current(r, boom)  # type: ignore[arg-type]
    assert r.data[pc.CACHE_KEY] == "previous"
    assert pc.LOCK_KEY not in r.data


async def test_overlapping_refresh_is_skipped_and_leaves_the_lock_to_its_owner() -> None:
    r = FakeRedis()
    r.data[pc.LOCK_KEY] = "someone-else"
    called = False

    async def compute(_a: datetime, _k: datetime) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    result = await pc.refresh_current(r, compute)  # type: ignore[arg-type]
    assert "skipped" in result
    assert called is False
    assert r.data[pc.LOCK_KEY] == "someone-else"
    assert pc.CACHE_KEY not in r.data


async def test_the_refresh_interval_leaves_a_valid_entry_during_the_next_computation() -> None:
    # computation ~25 s must fit between the refresh interval and the maximum age
    assert pc.REFRESH_INTERVAL_SECONDS + 120 < pc.MAX_AGE_SECONDS  # task time limit is 120 s


# ------------------------------------------------------------------ route


def _client(monkeypatch: Any, redis: Any, service: type | None = None) -> TestClient:
    if service is not None:
        monkeypatch.setattr(route, "SimilarityService", service)
    settings = Settings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://u:not-a-real-password@db:5432/x"),
        redis_url=SecretStr("redis://:not-a-real-password@redis:6379/0"),
    )
    app = create_app(settings, health_checks={})
    app.state.engine = object()
    app.state.redis = redis
    return TestClient(app, raise_server_exceptions=False)


class _NeverCalled:
    def __init__(self, engine: Any) -> None:
        raise AssertionError("the default view must never compute live")


def test_default_request_is_served_from_the_cache_without_touching_the_service(
    monkeypatch: Any,
) -> None:
    r = FakeRedis()
    now = datetime.now(UTC)
    r.data[pc.CACHE_KEY] = _entry(as_of=now - timedelta(seconds=20))
    r.data[pc.CACHE_KEY] = _entry(
        as_of=now - timedelta(seconds=20),
        computed_at=now - timedelta(seconds=1),
    )
    with _client(monkeypatch, r, _NeverCalled) as client:
        response = client.get("/api/v1/similarity/current")
    assert response.status_code == 200
    assert response.json()["freshness"]["source"] == "precomputed"


def test_default_request_without_a_valid_entry_is_a_503_not_a_live_computation(
    monkeypatch: Any,
) -> None:
    with _client(monkeypatch, FakeRedis(), _NeverCalled) as client:
        response = client.get("/api/v1/similarity/current")
    assert response.status_code == 503


@pytest.mark.parametrize(
    "params",
    [
        {"as_of": "2026-01-01T00:00:00+00:00"},
        {"knowledge_time": "2026-01-01T00:00:00+00:00"},
    ],
)
def test_explicit_parameters_never_receive_the_cached_default(
    monkeypatch: Any, params: dict[str, str]
) -> None:
    r = FakeRedis()
    now = datetime.now(UTC)
    r.data[pc.CACHE_KEY] = _entry(as_of=now, computed_at=now)
    seen: dict[str, Any] = {}

    class Live:
        def __init__(self, engine: Any) -> None:
            pass

        async def current(self, *, as_of: Any, knowledge_time: Any) -> dict[str, Any]:
            seen["called"] = True
            return {"live": True}

    with _client(monkeypatch, r, Live) as client:
        response = client.get("/api/v1/similarity/current", params=params)
    assert response.status_code == 200
    assert response.json() == {"live": True}
    assert seen["called"] is True


# ------------------------------------------------------------------ schedule / task


def test_the_refresh_is_scheduled_on_the_alerts_queue_inside_the_maximum_age() -> None:
    entry = beat_schedule([])["similarity:refresh"]
    assert entry["task"] == "similarity.refresh"
    assert entry["schedule"] == 600.0 < pc.MAX_AGE_SECONDS
    assert entry["options"] == {"queue": "alerts", "expires": 600}


def test_the_worker_registers_the_refresh_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setenv("CFI_DATABASE_URL", "postgresql+psycopg://u:not-a-real-password@localhost/x")
    monkeypatch.setenv("CFI_REDIS_URL", "redis://:not-a-real-password@localhost:6379/0")
    sys.modules.pop("cfi.worker.app", None)
    try:
        import cfi.worker.app as worker_app

        assert "similarity.refresh" in worker_app.app.tasks
        assert "similarity:refresh" in worker_app.app.conf.beat_schedule
    finally:
        sys.modules.pop("cfi.worker.app", None)
