"""Ingestion engine (ADR-0021): one pipeline for every dataset, provider and record family.

    job_run start
      → for each page:  HTTP (auth, rate limit, retries, backoff, timeout, circuit breaker)
                        → archive raw payload (L0) → validate schema → normalise records
                        → consistency checks (suspect) → batch de-duplication
                        → compare with stored data (duplicate / revision)
                        → cross-provider conflict check → insert records (L1)
      → completeness (explicit missing rows for expected-but-absent points)
      → freshness (stale check; ``ingest`` jobs only)
      → quality findings + job_run finish

The same pipeline stores scalar observations (``obs.observation``), OHLCV bars
(``obs.market_bar``), institutional flows (``obs.institutional_flow``), large on-chain transfers
(``obs.large_transfer``) and derivatives quotes (``obs.derivative_quote``); the dataset's ``kind``
selects the store.

Nothing is silently dropped or repaired: every skipped, rejected, missing, suspect, stale or
conflicting item is counted on the job run and (except not-yet-final records, which are simply
fetched again later) recorded as a quality finding.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from cfi import __version__
from cfi.core.errors import (
    CFIError,
    DataValidationError,
    NotYetFinalError,
    ProviderNotConfiguredError,
    SchemaMismatchError,
)
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import ObservedRecord
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
from cfi.ingestion.stores import (
    BarStore,
    FlowStore,
    GapContext,
    ObservationStore,
    QuoteStore,
    RecordStore,
    TransferStore,
)
from cfi.providers.base import FetchWindow, NormaliseContext, ProviderAdapter, RequestSpec
from cfi.providers.http import ProviderHttpClient

log = get_logger(__name__)

SeriesKey = tuple[str, str, str | None, str]
JobType = Literal["ingest", "backfill"]


@dataclass(slots=True)
class IngestionResult:
    job_run_id: int
    dataset_id: str
    provider_id: str
    job_type: JobType = "ingest"
    subject: str | None = None
    status: str = "running"
    pages: int = 0
    records_received: int = 0
    inserted: int = 0
    duplicates: int = 0
    revisions: int = 0
    missing: int = 0
    conflicts: int = 0
    rejected: int = 0
    skipped: int = 0  # not final yet (e.g. the current bar) — fetched again on a later run
    suspect: int = 0
    stale: bool | None = None
    # Range of real (non-missing) values received *inside the requested window*. Some providers
    # return data outside it (e.g. only their most recent N bars); that data is stored but does not
    # count as coverage of the window.
    earliest_received: datetime | None = None
    latest_received: datetime | None = None
    window: FetchWindow | None = None
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
        self._stores: dict[str, RecordStore[ObservedRecord]] = {
            "scalar": ObservationStore(repo.engine),  # type: ignore[dict-item]
            "bar": BarStore(repo.engine),  # type: ignore[dict-item]
            "flow": FlowStore(repo.engine),  # type: ignore[dict-item]
            "transfer": TransferStore(repo.engine),  # type: ignore[dict-item]
            "quote": QuoteStore(repo.engine),  # type: ignore[dict-item]
        }
        self._series_cache: dict[SeriesKey, int] = {}
        self._series_template: dict[int, ObservedRecord] = {}

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
        *,
        job_type: JobType = "ingest",
    ) -> IngestionResult:
        started = self.clock()
        job_id = await self.repo.start_job(
            dataset.dataset_id,
            adapter.provider_id,
            window,
            started,
            self.code_version,
            job_type=job_type,
        )
        result = IngestionResult(
            job_id, dataset.dataset_id, adapter.provider_id, job_type, window.subject
        )
        result.window = window
        logger = log.bind(
            job_run_id=job_id,
            job_type=job_type,
            dataset=dataset.dataset_id,
            provider=adapter.provider_id,
            subject=window.subject,
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
            if job_type == "ingest" and dataset.check_freshness:
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
            skipped=result.skipped,
            suspect=result.suspect,
            stale=result.stale,
        )
        return result

    # ------------------------------------------------------------------ pipeline steps

    def _store(self, dataset: DatasetSpec) -> RecordStore[ObservedRecord]:
        return self._stores[dataset.kind]

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
                records = adapter.parse_page(spec, raw)
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
            normalised: list[ObservedRecord] = []
            findings: list[QualityFinding] = []
            for record in records:
                try:
                    rec = adapter.normalise(record, ctx)
                    if rec.unit != dataset.unit or rec.dataset_id != dataset.dataset_id:
                        raise DataValidationError(
                            f"normalised unit {rec.unit!r} does not match "
                            f"dataset unit {dataset.unit!r}"
                        )
                except NotYetFinalError:
                    result.skipped += 1
                    continue
                except (DataValidationError, ValueError) as exc:
                    result.rejected += 1
                    findings.append(
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
                    continue
                problems = rec.consistency_problems()
                if problems:
                    result.suspect += 1
                    note = "failed consistency check: " + "; ".join(problems)
                    rec = rec.with_quality(QualityStatus.SUSPECT, note)
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.CONSISTENCY,
                            "suspect",
                            {
                                "event_time": rec.event_time.isoformat(),
                                "subject": rec.subject_ref,
                                "value": rec.describe(),
                                "problems": problems,
                            },
                        )
                    )
                normalised.append(rec)
            await self._record(findings, result)
            await self._store_page(dataset, adapter, normalised, result, received)
            spec = next_spec

    async def _store_page(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        records: Sequence[ObservedRecord],
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        store = self._store(dataset)
        split = split_batch(records)
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
                        "kept": first.describe(),
                        "rejected": other.describe(),
                    },
                )
            )

        by_series: dict[int, list[ObservedRecord]] = defaultdict(list)
        for rec in split.unique:
            by_series[await self._series_id(rec)].append(rec)

        rows: list[tuple[int, ObservedRecord]] = []
        for series_id, group in by_series.items():
            times = [r.event_time for r in group]
            existing = await store.latest_for_provider(series_id, times, adapter.provider_id)
            others = await store.latest_from_others(series_id, times, adapter.provider_id)
            for rec in group:
                received[series_id].add(rec.event_time)
                self._track_range(result, rec.event_time, rec.is_missing)
                kind, revision = classify(rec, existing.get(rec.event_time))
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
                                "event_time": rec.event_time.isoformat(),
                                "previous": str(existing[rec.event_time][1]),
                                "new": rec.describe(),
                                "revision": revision,
                            },
                            series_id,
                        )
                    )
                rec = rec.with_revision(revision)
                if rec.is_missing:
                    result.missing += 1
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.MISSING_VALUE,
                            "missing",
                            {"event_time": rec.event_time.isoformat(), "note": rec.quality_note},
                            series_id,
                        )
                    )
                conflicts = find_conflicts(
                    rec.conflict_value, others.get(rec.event_time, []), dataset.conflict_tolerance
                )
                if conflicts:
                    result.conflicts += 1
                    note = conflict_note(conflicts, dataset.conflict_tolerance)
                    if rec.quality_status is QualityStatus.SUSPECT:
                        note = f"{rec.quality_note}; {note}"
                    rec = rec.with_quality(QualityStatus.CONFLICTING, note)
                    findings.append(
                        self._finding(
                            dataset,
                            result,
                            CheckName.CONFLICT,
                            "conflicting",
                            {
                                "event_time": rec.event_time.isoformat(),
                                "value": str(rec.conflict_value),
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
                rows.append((series_id, rec))
        result.inserted += await store.insert(rows)
        await self._record(findings, result)

    async def _completeness(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        window: FetchWindow,
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        """Expected-but-absent points become explicit ``missing`` rows (never interpolated).

        ``ingest`` jobs expect every closed period in the window. ``backfill`` jobs expect points
        only from the first one delivered, because an instrument may not have existed (or been
        listed) earlier in the window — that is not missing data.
        """
        period = dataset.period_length
        if not dataset.expect_continuous or period is None or not received:
            return
        store = self._store(dataset)
        now = self.clock()
        # A period is only "expected" once it could be final: for bars, period end + delay.
        rule = dataset.availability
        final_by = now - rule.delay if rule.kind == "period_end_plus" else now
        rows: list[tuple[int, ObservedRecord]] = []
        findings: list[QualityFinding] = []
        for series_id, present in received.items():
            start = window.start if result.job_type == "ingest" else min(present)
            expected = expected_points(start, window.end, period, not_after=final_by)
            gaps = find_gaps(expected, present)
            already = await store.latest_for_provider(series_id, gaps, adapter.provider_id)
            gaps = [g for g in gaps if g not in already]
            template = self._series_template[series_id]
            context = GapContext(
                provider_id=adapter.provider_id,
                original_source=adapter.capabilities.original_source,
                now=now,
                note=adapter.capabilities.gap_note,
            )
            rows.extend((series_id, store.missing(template, gap, context)) for gap in gaps)
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
                            "note": adapter.capabilities.gap_note,
                        },
                        series_id,
                    )
                )
        result.inserted += await store.insert(rows)
        await self._record(findings, result)

    async def _freshness(
        self,
        dataset: DatasetSpec,
        adapter: ProviderAdapter,
        result: IngestionResult,
        received: dict[int, set[datetime]],
    ) -> None:
        store = self._store(dataset)
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
                latest = await store.latest_event_time(series_id, adapter.provider_id)
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

    @staticmethod
    def _track_range(result: IngestionResult, event_time: datetime, missing: bool) -> None:
        window = result.window
        if missing or (window is not None and not window.start <= event_time < window.end):
            return
        if result.earliest_received is None or event_time < result.earliest_received:
            result.earliest_received = event_time
        if result.latest_received is None or event_time > result.latest_received:
            result.latest_received = event_time

    async def _series_id(self, rec: ObservedRecord) -> int:
        key: SeriesKey = (rec.dataset_id, rec.subject_ref, rec.venue, rec.period)
        if key not in self._series_cache:
            self._series_cache[key] = await self.repo.series_id(rec)
            self._series_template[self._series_cache[key]] = rec
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
            skipped=result.skipped,
            suspect=result.suspect,
            stale=result.stale,
            error_code=result.error_code,
            error_detail=result.error_detail,
        )
