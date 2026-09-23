"""Ingestion engine (ADR-0021): one pipeline for every dataset and provider.

    job_run start
      → for each page:  HTTP (auth, rate limit, retries, backoff, timeout, circuit breaker)
                        → archive raw payload (L0) → validate schema → normalise records
                        → batch de-duplication → compare with stored data (duplicate / revision)
                        → cross-provider conflict check → insert observations (L1)
      → completeness (explicit missing rows for expected-but-absent points)
      → freshness (stale check)
      → quality findings + job_run finish

Nothing is silently dropped or repaired: every skipped, rejected, missing, stale or conflicting
item is counted on the job run and recorded as a quality finding.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from cfi import __version__
from cfi.core.errors import (
    CFIError,
    DataValidationError,
    ProviderNotConfiguredError,
    SchemaMismatchError,
)
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.ingestion.archive import RawArchive
from cfi.ingestion.detection import (
    CheckName,
    Classification,
    QualityFinding,
    classify,
    conflict_note,
    expected_points,
    find_conflicts,
    find_gaps,
    is_stale,
    split_batch,
)
from cfi.ingestion.repository import IngestionRepository
from cfi.providers.base import FetchWindow, NormaliseContext, ProviderAdapter, RequestSpec
from cfi.providers.http import ProviderHttpClient

log = get_logger(__name__)

SeriesKey = tuple[str, str, str | None, str]


@dataclass(slots=True)
class IngestionResult:
    job_run_id: int
    dataset_id: str
    provider_id: str
    status: str = "running"
    pages: int = 0
    records_received: int = 0
    inserted: int = 0
    duplicates: int = 0
    revisions: int = 0
    missing: int = 0
    conflicts: int = 0
    rejected: int = 0
    stale: bool | None = None
    error_code: str | None = None
    error_detail: str | None = None
    findings: list[QualityFinding] = field(default_factory=list)


class IngestionEngine:
    def __init__(
        self,
        repo: IngestionRepository,
        archive: RawArchive,
        *,
        clock: Callable[[], datetime] = utc_now,
        code_version: str = __version__,
    ) -> None:
        self.repo = repo
        self.archive = archive
        self.clock = clock
        self.code_version = code_version
        self._series_cache: dict[SeriesKey, int] = {}
        self._series_template: dict[int, CanonicalObservation] = {}

    async def register(
        self, dataset: DatasetSpec, adapter: ProviderAdapter, priority: int = 100
    ) -> None:
        """Record the dataset, the provider and their link in the registry tables."""
        now = self.clock()
        await self.repo.sync_dataset(dataset, now)
        await self.repo.sync_provider(adapter.capabilities, now)
        await self.repo.link(dataset.dataset_id, adapter.provider_id, priority)

    async def ingest(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        client: ProviderHttpClient,
        window: FetchWindow,
    ) -> IngestionResult:
        started = self.clock()
        job_id = await self.repo.start_job(
            dataset.dataset_id, adapter.provider_id, window, started, self.code_version
        )
        result = IngestionResult(job_id, dataset.dataset_id, adapter.provider_id)
        logger = log.bind(
            job_run_id=job_id, dataset=dataset.dataset_id, provider=adapter.provider_id
        )
        logger.info(
            "ingestion_started",
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
        )

        try:
            if not adapter.supports(dataset.dataset_id):
                raise ProviderNotConfiguredError(
                    f"Provider '{adapter.provider_id}' does not declare dataset "
                    f"'{dataset.dataset_id}'.",
                    provider_id=adapter.provider_id,
                )
            received: dict[int, set[datetime]] = defaultdict(set)
            await self._fetch_all(dataset, adapter, client, window, result, received)
            await self._completeness(dataset, adapter, window, result, received)
            await self._freshness(dataset, adapter, result, received)
            result.status = "partial" if result.rejected else "succeeded"
        except CFIError as exc:
            result.status = "failed"
            result.error_code = exc.error_code
            result.error_detail = exc.detail
            logger.warning("ingestion_failed", error_code=exc.error_code, detail=exc.detail)
        except Exception as exc:  # a bug: record it, then re-raise loudly
            result.status = "failed"
            result.error_code = "internal_error"
            result.error_detail = type(exc).__name__
            await self._finish(result)
            logger.exception("ingestion_crashed")
            raise

        await self._finish(result)
        logger.info(
            "ingestion_finished",
            status=result.status,
            inserted=result.inserted,
            duplicates=result.duplicates,
            revisions=result.revisions,
            missing=result.missing,
            conflicts=result.conflicts,
            rejected=result.rejected,
            stale=result.stale,
        )
        return result

    # ------------------------------------------------------------------ pipeline steps

    async def _fetch_all(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        client: ProviderHttpClient,
        window: FetchWindow,
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        spec: RequestSpec | None = adapter.first_request(dataset.dataset_id, window)
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        while spec is not None:
            fingerprint = (spec.path, tuple(sorted(spec.params.items())))
            if fingerprint in seen:
                raise SchemaMismatchError(
                    f"Pagination loop detected for '{adapter.provider_id}' (repeated request).",
                    provider_id=adapter.provider_id,
                )
            if result.pages >= adapter.capabilities.max_pages:
                raise SchemaMismatchError(
                    f"Page limit ({adapter.capabilities.max_pages}) exceeded for "
                    f"'{adapter.provider_id}'.",
                    provider_id=adapter.provider_id,
                )
            seen.add(fingerprint)

            raw = await client.send(
                spec, dataset_id=dataset.dataset_id, job_run_id=result.job_run_id
            )
            result.pages += 1
            archived = self.archive.store(raw)
            payload_id = await self.repo.insert_payload(
                raw, archived, dataset.dataset_id, result.job_run_id
            )
            try:
                records = adapter.parse(raw)
                next_spec = adapter.next_request(spec, raw, records)
            except SchemaMismatchError as exc:
                await self.repo.mark_payload(payload_id, raw.received_at, False, exc.detail)
                await self._record(
                    [
                        self._finding(
                            dataset,
                            result,
                            CheckName.SCHEMA,
                            "failed",
                            {"payload_id": payload_id, "error": exc.detail},
                        )
                    ],
                    result,
                )
                raise
            await self.repo.mark_payload(payload_id, raw.received_at, True, None)
            result.records_received += len(records)

            ctx = NormaliseContext(dataset=dataset, ingested_at=self.clock(), raw_ref=payload_id)
            normalised: list[CanonicalObservation] = []
            rejections: list[QualityFinding] = []
            for record in records:
                try:
                    obs = adapter.normalise(record, ctx)
                    if obs.unit != dataset.unit or obs.dataset_id != dataset.dataset_id:
                        raise DataValidationError(
                            f"normalised unit {obs.unit!r} does not match "
                            f"dataset unit {dataset.unit!r}"
                        )
                    normalised.append(obs)
                except (DataValidationError, ValueError) as exc:
                    result.rejected += 1
                    rejections.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.REJECTED,
                            "rejected",
                            {
                                "payload_id": payload_id,
                                "reason": str(exc),
                                "record": {k: str(v) for k, v in record.payload.items()},
                            },
                        )
                    )
            await self._record(rejections, result)
            await self._store_page(dataset, adapter, normalised, result, received)
            spec = next_spec

    async def _store_page(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        observations: Sequence[CanonicalObservation],
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        split = split_batch(observations)
        findings: list[QualityFinding] = []
        result.duplicates += len(split.duplicates)
        for first, other in split.inconsistent:
            result.rejected += 1
            findings.append(
                self._finding(
                    dataset,
                    result,
                    CheckName.INCONSISTENT_BATCH,
                    "rejected",
                    {
                        "event_time": first.event_time.isoformat(),
                        "kept": str(first.value),
                        "rejected": str(other.value),
                    },
                )
            )

        by_series: dict[int, list[CanonicalObservation]] = defaultdict(list)
        for obs in split.unique:
            by_series[await self._series_id(obs)].append(obs)

        rows: list[tuple[int, CanonicalObservation]] = []
        for series_id, group in by_series.items():
            times = [o.event_time for o in group]
            existing = await self.repo.latest_for_provider(series_id, times, adapter.provider_id)
            others = await self.repo.latest_from_others(series_id, times, adapter.provider_id)
            for obs in group:
                received[series_id].add(obs.event_time)
                kind, revision = classify(obs, existing.get(obs.event_time))
                if kind is Classification.DUPLICATE:
                    result.duplicates += 1
                    continue
                if kind is Classification.REVISION:
                    result.revisions += 1
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.REVISION,
                            "expected" if dataset.revisable else "unexpected",
                            {
                                "event_time": obs.event_time.isoformat(),
                                "previous": str(existing[obs.event_time][1]),
                                "new": str(obs.value),
                                "revision": revision,
                            },
                            series_id,
                        )
                    )
                obs = obs.with_revision(revision)
                if obs.value is None:
                    result.missing += 1
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.MISSING_VALUE,
                            "missing",
                            {"event_time": obs.event_time.isoformat(), "note": obs.quality_note},
                            series_id,
                        )
                    )
                conflicts = find_conflicts(
                    obs.value, others.get(obs.event_time, []), dataset.conflict_tolerance
                )
                if conflicts:
                    result.conflicts += 1
                    obs = obs.with_quality(
                        QualityStatus.CONFLICTING,
                        conflict_note(conflicts, dataset.conflict_tolerance),
                    )
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.CONFLICT,
                            "conflicting",
                            {
                                "event_time": obs.event_time.isoformat(),
                                "value": str(obs.value),
                                "others": [
                                    {
                                        "provider": c.other_provider,
                                        "value": str(c.other_value),
                                        "relative_difference": str(c.relative_difference),
                                    }
                                    for c in conflicts
                                ],
                                "tolerance": str(dataset.conflict_tolerance),
                            },
                            series_id,
                        )
                    )
                rows.append((series_id, obs))
        result.inserted += await self.repo.insert_observations(rows)
        await self._record(findings, result)

    async def _completeness(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        window: FetchWindow,
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        """Expected-but-absent points become explicit ``missing`` rows (never interpolated)."""
        period = dataset.period_length
        if not dataset.expect_continuous or period is None or not received:
            return
        now = self.clock()
        expected = expected_points(window.start, window.end, period, not_after=now)
        rows: list[tuple[int, CanonicalObservation]] = []
        findings: list[QualityFinding] = []
        for series_id, present in received.items():
            gaps = find_gaps(expected, present)
            already = await self.repo.latest_for_provider(series_id, gaps, adapter.provider_id)
            gaps = [g for g in gaps if g not in already]
            for gap in gaps:
                base = self._series_template[series_id]
                rows.append(
                    (
                        series_id,
                        CanonicalObservation(
                            dataset_id=dataset.dataset_id,
                            metric=dataset.metric,
                            asset=base.asset,
                            subject_ref=base.subject_ref,
                            venue=base.venue,
                            period=dataset.period,
                            unit=dataset.unit,
                            event_time=gap,
                            available_at=now,
                            available_at_estimated=True,
                            ingested_at=now,
                            value=None,
                            source_provider=adapter.provider_id,
                            original_source=adapter.capabilities.original_source,
                            quality_status=QualityStatus.MISSING,
                            quality_note="expected point not delivered by provider",
                            pit_reliability=PitReliability.NATIVE,
                        ),
                    )
                )
            if gaps:
                result.missing += len(gaps)
                findings.append(
                    self._finding(
                        dataset,
                        result,
                        CheckName.GAP,
                        "missing",
                        {
                            "missing_points": [g.isoformat() for g in gaps],
                            "expected": len(expected),
                        },
                        series_id,
                    )
                )
        result.inserted += await self.repo.insert_observations(rows)
        await self._record(findings, result)

    async def _freshness(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        now = self.clock()
        findings = []
        if not received:
            result.stale = True
            findings.append(
                self._finding(
                    dataset,
                    result,
                    CheckName.FRESHNESS,
                    "stale",
                    {"reason": "provider returned no data for the window"},
                )
            )
        else:
            stale_any = False
            for series_id in received:
                latest = await self.repo.latest_event_time(series_id, adapter.provider_id)
                stale = is_stale(latest, dataset.freshness_limit, now)
                stale_any |= stale
                findings.append(
                    self._finding(
                        dataset,
                        result,
                        CheckName.FRESHNESS,
                        "stale" if stale else "ok",
                        {
                            "latest_event_time": latest.isoformat() if latest else None,
                            "freshness_limit_seconds": int(dataset.freshness_limit.total_seconds()),
                            "checked_against": now.isoformat(),
                        },
                        series_id,
                    )
                )
            result.stale = stale_any
        await self._record(findings, result)

    # ------------------------------------------------------------------ helpers

    async def _series_id(self, obs: CanonicalObservation) -> int:
        key: SeriesKey = (obs.dataset_id, obs.subject_ref, obs.venue, obs.period)
        if key not in self._series_cache:
            self._series_cache[key] = await self.repo.series_id(obs)
            self._series_template[self._series_cache[key]] = obs
        return self._series_cache[key]

    def _finding(
        self,
        dataset: DatasetSpec,
        result: IngestionResult,
        check: CheckName,
        status: str,
        details: dict[str, object],
        series_id: int | None = None,
    ) -> QualityFinding:
        return QualityFinding(
            dataset_id=dataset.dataset_id,
            check_name=check,
            status=status,
            checked_at=self.clock(),
            series_id=series_id,
            provider_id=result.provider_id,
            job_run_id=result.job_run_id,
            details=details,
        )

    async def _record(self, findings: list[QualityFinding], result: IngestionResult) -> None:
        result.findings.extend(findings)
        await self.repo.record_findings(findings)

    async def _finish(self, result: IngestionResult) -> None:
        await self.repo.finish_job(
            result.job_run_id,
            status=result.status,
            finished_at=self.clock(),
            pages=result.pages,
            records_received=result.records_received,
            inserted=result.inserted,
            duplicates=result.duplicates,
            revisions=result.revisions,
            missing=result.missing,
            conflicts=result.conflicts,
            rejected=result.rejected,
            stale=result.stale,
            error_code=result.error_code,
            error_detail=result.error_detail,
        )
