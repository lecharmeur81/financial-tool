"""End-to-end ingestion against real PostgreSQL + TimescaleDB, using mock providers.

Covers: successful ingestion (with full provenance), timeout, retry, rate limit, malformed response,
duplicate records, missing values, stale values, conflicting provider values, revisions, rejected
records, provider health and the API read models.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.domain.datasets import DatasetSpec
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.providers.base import FetchWindow, ProviderAdapter
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from cfi.providers.mock import (
    MOCK_DATASET,
    Fail,
    MockPoint,
    MockProviderA,
    MockProviderB,
    MockServerA,
    MockServerB,
    RawBody,
    Timeout,
    _MockServer,
)
from tests.integration.conftest import requires_services
from tests.support import T0, FakeClock, WallClock

pytestmark = [pytest.mark.integration, requires_services]

HOUR = timedelta(hours=1)
WINDOW = FetchWindow(T0, T0 + 6 * HOUR)
PRICES = [Decimal("63000.50") + i for i in range(6)]
API_KEY = "test-only-key"


def points(values: Sequence[Decimal | None] = PRICES) -> list[MockPoint]:
    return [MockPoint(T0 + i * HOUR, v) for i, v in enumerate(values)]


@dataclass
class Harness:
    engine: IngestionEngine
    repo: IngestionRepository
    db: AsyncEngine
    wall: WallClock
    clock: FakeClock
    archive_root: Path

    async def run(
        self,
        adapter: ProviderAdapter,
        server: _MockServer,
        *,
        dataset: DatasetSpec = MOCK_DATASET,
        window: FetchWindow = WINDOW,
        retry: RetryPolicy | None = None,
    ) -> IngestionResult:
        await self.engine.register(dataset, adapter)
        client = ProviderHttpClient(
            adapter.capabilities,
            transport=server.transport(),
            retry=retry or RetryPolicy(max_attempts=3, base_delay=0.5, jitter=0),
            recorder=RepositoryRecorder(self.repo),
            environ={MockProviderB.API_KEY_ENV: API_KEY},
            sleep=self.clock.sleep,
            clock=self.clock,
        )
        async with client:
            return await self.engine.ingest(dataset, adapter, client, window)

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


@pytest.fixture
def harness(db: AsyncEngine, test_settings: Settings) -> Harness:
    repo = IngestionRepository(db)
    wall = WallClock(T0 + 6 * HOUR + timedelta(minutes=5))  # all six bars closed, data fresh
    root = test_settings.raw_archive_dir
    return Harness(
        IngestionEngine(repo, FileSystemArchive(root), clock=wall),
        repo,
        db,
        wall,
        FakeClock(),
        root,
    )


OBS_SQL = """
    SELECT s.metric, s.asset, s.unit, s.subject_ref, o.* FROM obs.observation o
    JOIN obs.series s USING (series_id) WHERE o.source_provider = :p
    ORDER BY o.event_time, o.revision
"""


# --------------------------------------------------------------------------- success & provenance


async def test_successful_ingestion_with_full_provenance(harness: Harness) -> None:
    result = await harness.run(MockProviderA(), MockServerA(points(), page_size=2))

    assert result.status == "succeeded"
    assert (result.pages, result.records_received, result.inserted) == (3, 6, 6)
    assert (result.duplicates, result.missing, result.conflicts, result.rejected) == (0, 0, 0, 0)
    assert result.stale is False

    rows = await harness.rows(OBS_SQL, p="mock_a")
    assert [r["value"] for r in rows] == PRICES
    first = rows[0]
    assert first["metric"] == "close_price"  # what was measured
    assert first["event_time"] == T0  # when it occurred (UTC)
    assert first["ingested_at"] == harness.wall.current  # when it was ingested
    assert first["available_at"] == T0 + HOUR + timedelta(minutes=1)  # when it was knowable
    assert first["available_at_estimated"] is True
    assert first["original_source"] == "mock_exchange_a"  # where it came from
    assert first["source_provider"] == "mock_a"  # which provider supplied it
    assert first["unit"] == "usd"  # unit
    assert first["asset"] == "BTC"  # asset
    assert (first["quality_status"], first["pit_reliability"]) == ("ok", "native")  # reliability
    assert first["transformations"] == ["event_time: epoch milliseconds -> UTC"]  # transformed

    payloads = await harness.rows("SELECT * FROM raw.payload ORDER BY payload_id")
    assert len(payloads) == 3
    assert all(p["schema_ok"] for p in payloads)
    assert first["raw_ref"] == payloads[0]["payload_id"]
    archived = FileSystemArchive(harness.archive_root).load(payloads[0]["archive_uri"])
    assert b'"data"' in archived  # the exact provider bytes are kept

    job = (await harness.rows("SELECT * FROM ops.job_run"))[0]
    assert (job["status"], job["inserted"], job["pages"]) == ("succeeded", 6, 3)
    requests = await harness.rows("SELECT outcome FROM ops.provider_request")
    assert [r["outcome"] for r in requests] == ["success"] * 3


async def test_second_provider_normalises_to_the_same_series(harness: Harness) -> None:
    await harness.run(MockProviderA(), MockServerA(points()))
    result = await harness.run(MockProviderB(), MockServerB(points(), api_key=API_KEY))
    assert result.status == "succeeded"
    assert result.conflicts == 0
    series = await harness.rows("SELECT count(*) AS n FROM obs.series")
    assert series[0]["n"] == 1  # different formats, one canonical series
    b_rows = await harness.rows(OBS_SQL, p="mock_b")
    assert [r["value"] for r in b_rows] == PRICES  # cents converted to USD
    assert any("cents" in t for t in b_rows[0]["transformations"])


# --------------------------------------------------------------------------- failures


async def test_timeout_fails_the_job_and_is_tracked(harness: Harness) -> None:
    server = MockServerA(points()).then(Timeout(), Timeout(), Timeout())
    result = await harness.run(MockProviderA(), server)

    assert result.status == "failed"
    assert result.error_code == "provider_transient_error"
    assert result.inserted == 0
    requests = await harness.rows("SELECT outcome, job_run_id FROM ops.provider_request")
    assert [r["outcome"] for r in requests] == ["timeout"] * 3
    assert all(r["job_run_id"] == result.job_run_id for r in requests)
    assert harness.clock.slept == [0.5, 1.0]
    health = await harness.repo.provider_health(T0 - timedelta(days=365))
    assert health[0]["consecutive_failures"] == 3
    assert health[0]["last_error"] == "timeout"
    assert health[0]["last_job_status"] == "failed"


async def test_retry_then_success(harness: Harness) -> None:
    server = MockServerA(points(), page_size=10).then(Fail(503), Fail(500))
    result = await harness.run(MockProviderA(), server)
    assert result.status == "succeeded"
    assert result.inserted == 6
    outcomes = await harness.rows("SELECT outcome FROM ops.provider_request ORDER BY request_id")
    assert [r["outcome"] for r in outcomes] == ["server_error", "server_error", "success"]


async def test_rate_limit_is_respected(harness: Harness) -> None:
    server = MockServerA(points(), page_size=10).then(Fail(429, {"Retry-After": "5"}))
    result = await harness.run(MockProviderA(), server)
    assert result.status == "succeeded"
    assert 5.0 in harness.clock.slept
    outcomes = await harness.rows("SELECT outcome FROM ops.provider_request ORDER BY request_id")
    assert [r["outcome"] for r in outcomes] == ["rate_limited", "success"]


async def test_malformed_response_is_stored_flagged_and_stops_the_job(harness: Harness) -> None:
    result = await harness.run(MockProviderA(), MockServerA(points()).then(RawBody(b"{not json")))

    assert result.status == "failed"
    assert result.error_code == "schema_mismatch"
    assert result.inserted == 0
    payload = (await harness.rows("SELECT * FROM raw.payload"))[0]
    assert payload["schema_ok"] is False
    assert "not valid JSON" in payload["schema_error"]
    assert FileSystemArchive(harness.archive_root).load(payload["archive_uri"]) == b"{not json"
    checks = await harness.rows("SELECT check_name, status FROM ops.quality_check_result")
    assert {"check_name": "schema", "status": "failed"} in checks


async def test_rejected_record_is_reported_and_others_kept(harness: Harness) -> None:
    body = (
        b'{"data": [{"t": 1788220800000, "symbol": "BTCUSD", "close": "1"},'
        b' {"t": 1788224400000, "symbol": "DOGEUSD", "close": "2"}], "next_cursor": null}'
    )
    window = FetchWindow(T0, T0 + 2 * HOUR)
    result = await harness.run(MockProviderA(), MockServerA([]).then(RawBody(body)), window=window)
    assert result.status == "partial"
    assert (result.inserted, result.rejected) == (2, 1)  # 1 value + 1 explicit gap row
    finding = next(f for f in result.findings if f.check_name == "rejected_record")
    assert "unknown symbol" in finding.details["reason"]


# --------------------------------------------------------------------------- data-quality detection


async def test_duplicate_records_are_detected_not_stored_twice(harness: Harness) -> None:
    first = await harness.run(MockProviderA(), MockServerA(points()))
    second = await harness.run(MockProviderA(), MockServerA(points()))
    assert first.inserted == 6
    assert (second.inserted, second.duplicates) == (0, 6)
    count = await harness.rows("SELECT count(*) AS n FROM obs.observation")
    assert count[0]["n"] == 6

    # the same point twice in one response
    repeated = [*points(), MockPoint(T0, PRICES[0])]
    third = await harness.run(MockProviderA("mock_c"), MockServerA(repeated, page_size=10))
    assert third.inserted == 6
    assert third.duplicates == 1


async def test_missing_values_and_gaps_are_explicit(harness: Harness) -> None:
    values: list[Decimal | None] = list(PRICES)
    values[2] = None  # provider sends null
    served = [p for p in points(values) if p.time != T0 + 4 * HOUR]  # provider omits 04:00
    result = await harness.run(MockProviderA(), MockServerA(served))

    assert result.status == "succeeded"
    assert result.missing == 2
    rows = await harness.rows(OBS_SQL, p="mock_a")
    by_hour = {r["event_time"].hour: r for r in rows}
    assert len(rows) == 6
    assert by_hour[2]["value"] is None
    assert by_hour[2]["quality_status"] == "missing"
    assert by_hour[2]["quality_note"] == "provider returned null for this point"
    assert by_hour[4]["value"] is None
    assert by_hour[4]["quality_status"] == "missing"
    assert by_hour[4]["quality_note"] == "expected point not delivered by provider"
    names = {f.check_name for f in result.findings}
    assert {"missing_value", "completeness_gap"} <= names


async def test_late_value_fills_a_gap_as_a_revision(harness: Harness) -> None:
    served = [p for p in points() if p.time != T0 + 4 * HOUR]
    await harness.run(MockProviderA(), MockServerA(served))
    again = await harness.run(MockProviderA(), MockServerA(points()))
    assert (again.revisions, again.inserted) == (1, 1)
    rows = await harness.rows(OBS_SQL + "", p="mock_a")
    four = [r for r in rows if r["event_time"].hour == 4]
    assert [(r["revision"], r["value"]) for r in four] == [(0, None), (1, PRICES[4])]


async def test_stale_data_is_reported(harness: Harness) -> None:
    harness.wall.advance(timedelta(hours=10))  # newest point is now ~16 h old; limit is 3 h
    result = await harness.run(MockProviderA(), MockServerA(points()))
    assert result.status == "succeeded"
    assert result.stale is True
    fresh = next(f for f in result.findings if f.check_name == "freshness")
    assert fresh.status == "stale"
    assert fresh.details["freshness_limit_seconds"] == 3 * 3600
    job = (await harness.rows("SELECT stale FROM ops.job_run"))[0]
    assert job["stale"] is True


async def test_empty_response_is_reported_as_stale(harness: Harness) -> None:
    result = await harness.run(MockProviderA(), MockServerA([]))
    assert result.stale is True
    assert result.inserted == 0


async def test_conflicting_provider_values_are_flagged_and_both_kept(harness: Harness) -> None:
    await harness.run(MockProviderA(), MockServerA(points()))
    other = list(PRICES)
    other[1] = PRICES[1] * Decimal("1.02")  # 2 % off: beyond the 0.5 % tolerance
    other[3] = PRICES[3] * Decimal("1.001")  # 0.1 % off: within tolerance
    result = await harness.run(MockProviderB(), MockServerB(points(other), api_key=API_KEY))

    assert result.status == "succeeded"
    assert result.conflicts == 1
    b_rows = {r["event_time"].hour: r for r in await harness.rows(OBS_SQL, p="mock_b")}
    assert b_rows[1]["quality_status"] == "conflicting"
    assert "mock_a=63001.50" in b_rows[1]["quality_note"]
    assert b_rows[3]["quality_status"] == "ok"
    a_rows = {r["event_time"].hour: r for r in await harness.rows(OBS_SQL, p="mock_a")}
    assert a_rows[1]["value"] == PRICES[1]  # original provider's value untouched
    conflict = next(f for f in result.findings if f.check_name == "cross_provider_conflict")
    assert conflict.details["others"][0]["provider"] == "mock_a"


async def test_changed_value_becomes_a_new_revision(harness: Harness) -> None:
    await harness.run(MockProviderA(), MockServerA(points()))
    changed = list(PRICES)
    changed[0] = Decimal("1")
    result = await harness.run(MockProviderA(), MockServerA(points(changed)))
    assert (result.revisions, result.inserted, result.duplicates) == (1, 1, 5)
    revision = next(f for f in result.findings if f.check_name == "revision")
    assert revision.status == "unexpected"  # this dataset is not revisable
    rows = await harness.rows(OBS_SQL, p="mock_a")
    zero = [r for r in rows if r["event_time"] == T0]
    assert [(r["revision"], r["value"]) for r in zero] == [(0, PRICES[0]), (1, Decimal("1"))]


# --------------------------------------------------------------------------- API read models


async def test_provider_health_and_runs_api(harness: Harness, test_settings: Settings) -> None:
    await harness.run(MockProviderA(), MockServerA(points()))
    await harness.run(MockProviderA(), MockServerA(points()).then(Timeout(), Timeout(), Timeout()))
    with TestClient(create_app(test_settings)) as client:
        health = client.get("/api/v1/providers/health", params={"hours": 24 * 30}).json()
        runs = client.get("/api/v1/ingestion/runs").json()
    provider = health["providers"][0]
    assert provider["provider_id"] == "mock_a"
    assert provider["consecutive_failures"] == 3
    assert provider["last_job_status"] == "failed"
    assert [r["status"] for r in runs] == ["failed", "succeeded"]
    assert runs[0]["error_code"] == "provider_transient_error"
