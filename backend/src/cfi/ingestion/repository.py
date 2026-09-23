"""Ingestion persistence (PostgreSQL + TimescaleDB). The only module that writes ingestion tables.

Logging tables (job runs, request attempts, payload index, quality findings) are written in their
own short transactions so that a failed ingestion still leaves a complete record of what happened.
Observations for one page are written in a single transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t
from cfi.domain.datasets import DatasetSpec
from cfi.domain.observation import CanonicalObservation
from cfi.ingestion.archive import ArchivedPayload
from cfi.ingestion.detection import QualityFinding
from cfi.providers.base import FetchWindow, ProviderCapabilities, RawResponse
from cfi.providers.http import RequestAttempt


class IngestionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ registry

    async def sync_provider(self, caps: ProviderCapabilities, now: datetime) -> None:
        values = {
            "provider_id": caps.provider_id,
            "display_name": caps.display_name,
            "base_url": caps.base_url,
            "auth_type": str(caps.auth.type),
            "original_source": caps.original_source,
            "terms_verified": caps.terms_verified,
            "notes": caps.notes,
            "updated_at": now,
        }
        stmt = insert(t.provider).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["provider_id"], set_=values)
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def sync_dataset(self, spec: DatasetSpec, now: datetime) -> None:
        values = {
            "dataset_id": spec.dataset_id,
            "metric": spec.metric,
            "unit": spec.unit,
            "period": spec.period,
            "availability_rule": spec.availability.as_dict(),
            "freshness_limit_seconds": int(spec.freshness_limit.total_seconds()),
            "conflict_tolerance": spec.conflict_tolerance,
            "revisable": spec.revisable,
            "expect_continuous": spec.expect_continuous,
            "description": spec.description,
            "updated_at": now,
        }
        stmt = insert(t.dataset).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["dataset_id"], set_=values)
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def link(self, dataset_id: str, provider_id: str, priority: int) -> None:
        values = {
            "dataset_id": dataset_id,
            "provider_id": provider_id,
            "priority": priority,
            "enabled": True,
        }
        stmt = insert(t.dataset_provider).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["dataset_id", "provider_id"], set_={"priority": priority}
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ job runs

    async def start_job(
        self,
        dataset_id: str,
        provider_id: str,
        window: FetchWindow,
        started_at: datetime,
        code_version: str,
    ) -> int:
        stmt = (
            insert(t.job_run)
            .values(
                job_type="ingest",
                dataset_id=dataset_id,
                provider_id=provider_id,
                window_start=window.start,
                window_end=window.end,
                status="running",
                started_at=started_at,
                pages=0,
                records_received=0,
                inserted=0,
                duplicates=0,
                revisions=0,
                missing=0,
                conflicts=0,
                rejected=0,
                code_version=code_version,
            )
            .returning(t.job_run.c.job_run_id)
        )
        async with self.engine.begin() as conn:
            return int((await conn.execute(stmt)).scalar_one())

    async def finish_job(self, job_run_id: int, **fields: Any) -> None:
        stmt = update(t.job_run).where(t.job_run.c.job_run_id == job_run_id).values(**fields)
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ requests & payloads

    async def record_request(self, attempt: RequestAttempt) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(t.provider_request).values(**asdict(attempt)))

    async def insert_payload(
        self, raw: RawResponse, archived: ArchivedPayload, dataset_id: str, job_run_id: int
    ) -> int:
        stmt = (
            insert(t.payload)
            .values(
                provider_id=raw.provider_id,
                dataset_id=dataset_id,
                job_run_id=job_run_id,
                endpoint=raw.endpoint,
                request_params=dict(raw.request_params),
                http_status=raw.status_code,
                content_type=raw.content_type,
                received_at=raw.received_at,
                content_hash=archived.content_hash,
                archive_uri=archived.uri,
                bytes=archived.bytes,
            )
            .returning(t.payload.c.payload_id)
        )
        async with self.engine.begin() as conn:
            return int((await conn.execute(stmt)).scalar_one())

    async def mark_payload(
        self, payload_id: int, received_at: datetime, ok: bool, error: str | None
    ) -> None:
        stmt = (
            update(t.payload)
            .where(t.payload.c.payload_id == payload_id, t.payload.c.received_at == received_at)
            .values(schema_ok=ok, schema_error=error)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ series & observations

    async def series_id(self, obs: CanonicalObservation) -> int:
        identity = {
            "dataset_id": obs.dataset_id,
            "subject_ref": obs.subject_ref,
            "venue": obs.venue,
            "period": obs.period,
        }
        async with self.engine.begin() as conn:
            await conn.execute(
                insert(t.series)
                .values(
                    **identity,
                    metric=obs.metric,
                    asset=obs.asset,
                    unit=obs.unit,
                    created_at=func.now(),
                )
                .on_conflict_do_nothing(constraint="series_identity")
            )
            venue_match = (
                t.series.c.venue.is_(None) if obs.venue is None else t.series.c.venue == obs.venue
            )
            row = (
                await conn.execute(
                    select(t.series.c.series_id, t.series.c.unit).where(
                        t.series.c.dataset_id == obs.dataset_id,
                        t.series.c.subject_ref == obs.subject_ref,
                        t.series.c.period == obs.period,
                        venue_match,
                    )
                )
            ).one()
        if row.unit != obs.unit:
            raise ValueError(f"series {row.series_id} is stored in {row.unit!r}, got {obs.unit!r}")
        return int(row.series_id)

    async def latest_for_provider(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, tuple[int, Decimal | None]]:
        """Latest stored revision (and its value) per event time, for one provider."""
        if not event_times:
            return {}
        o = t.observation
        stmt = (
            select(o.c.event_time, o.c.revision, o.c.value)
            .distinct(o.c.event_time)
            .where(
                o.c.series_id == series_id,
                o.c.source_provider == provider_id,
                o.c.event_time.in_(list(event_times)),
            )
            .order_by(o.c.event_time, o.c.revision.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {r.event_time: (int(r.revision), r.value) for r in rows}

    async def latest_from_others(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, list[tuple[str, Decimal | None]]]:
        """Latest revision per (event time, other provider)."""
        if not event_times:
            return {}
        o = t.observation
        stmt = (
            select(o.c.event_time, o.c.source_provider, o.c.value)
            .distinct(o.c.event_time, o.c.source_provider)
            .where(
                o.c.series_id == series_id,
                o.c.source_provider != provider_id,
                o.c.event_time.in_(list(event_times)),
            )
            .order_by(o.c.event_time, o.c.source_provider, o.c.revision.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        out: dict[datetime, list[tuple[str, Decimal | None]]] = {}
        for r in rows:
            out.setdefault(r.event_time, []).append((r.source_provider, r.value))
        return out

    async def insert_observations(self, rows: Sequence[tuple[int, CanonicalObservation]]) -> int:
        if not rows:
            return 0
        values = [
            {
                "series_id": series_id,
                "event_time": o.event_time,
                "available_at": o.available_at,
                "available_at_estimated": o.available_at_estimated,
                "ingested_at": o.ingested_at,
                "value": o.value,
                "source_provider": o.source_provider,
                "original_source": o.original_source,
                "raw_ref": o.raw_ref,
                "revision": o.revision,
                "pit_reliability": str(o.pit_reliability),
                "quality_status": str(o.quality_status),
                "quality_note": o.quality_note,
                "confidence": o.confidence,
                "transformations": list(o.transformations),
            }
            for series_id, o in rows
        ]
        async with self.engine.begin() as conn:
            await conn.execute(insert(t.observation), values)
        return len(values)

    async def latest_event_time(self, series_id: int, provider_id: str) -> datetime | None:
        o = t.observation
        stmt = select(func.max(o.c.event_time)).where(
            o.c.series_id == series_id,
            o.c.source_provider == provider_id,
            o.c.value.is_not(None),
        )
        async with self.engine.connect() as conn:
            value: datetime | None = (await conn.execute(stmt)).scalar()
        return value

    # ------------------------------------------------------------------ quality findings

    async def record_findings(self, findings: Sequence[QualityFinding]) -> None:
        if not findings:
            return
        values = [
            {
                "dataset_id": f.dataset_id,
                "series_id": f.series_id,
                "provider_id": f.provider_id,
                "job_run_id": f.job_run_id,
                "check_name": str(f.check_name),
                "status": f.status,
                "details": f.details,
                "checked_at": f.checked_at,
            }
            for f in findings
        ]
        async with self.engine.begin() as conn:
            await conn.execute(insert(t.quality_check_result), values)

    # ------------------------------------------------------------------ read models (API)

    async def provider_health(self, since: datetime) -> list[dict[str, Any]]:
        stmt = text(
            """
            SELECT p.provider_id, p.display_name,
                   COALESCE(s.requests, 0) AS requests,
                   COALESCE(s.successes, 0) AS successes,
                   s.last_success_at, s.last_failure_at, s.last_error,
                   (SELECT count(*) FROM ops.provider_request r2
                     WHERE r2.provider_id = p.provider_id AND r2.outcome <> 'success'
                       AND r2.started_at > COALESCE(
                           (SELECT max(r3.started_at) FROM ops.provider_request r3
                             WHERE r3.provider_id = p.provider_id AND r3.outcome = 'success'),
                           '-infinity'::timestamptz)) AS consecutive_failures,
                   (SELECT j.status FROM ops.job_run j WHERE j.provider_id = p.provider_id
                     ORDER BY j.started_at DESC, j.job_run_id DESC LIMIT 1) AS last_job_status
              FROM ops.provider p
              LEFT JOIN LATERAL (
                   SELECT count(*) AS requests,
                          count(*) FILTER (WHERE r.outcome = 'success') AS successes,
                          max(r.started_at) FILTER (WHERE r.outcome = 'success') AS last_success_at,
                          max(r.started_at) FILTER (WHERE r.outcome <> 'success')
                              AS last_failure_at,
                          (array_agg(r.outcome || COALESCE(' (HTTP ' || r.http_status || ')', '')
                                     ORDER BY r.started_at DESC)
                               FILTER (WHERE r.outcome <> 'success'))[1] AS last_error
                     FROM ops.provider_request r
                    WHERE r.provider_id = p.provider_id AND r.started_at >= :since
              ) s ON true
             ORDER BY p.provider_id
            """
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt, {"since": since})).mappings().all()
        return [dict(r) for r in rows]

    async def recent_jobs(self, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(t.job_run)
            .order_by(t.job_run.c.started_at.desc(), t.job_run.c.job_run_id.desc())
            .limit(limit)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class RepositoryRecorder:
    """RequestRecorder that persists every HTTP attempt to ``ops.provider_request``."""

    def __init__(self, repo: IngestionRepository) -> None:
        self.repo = repo

    async def record(self, attempt: RequestAttempt) -> None:
        await self.repo.record_request(attempt)
