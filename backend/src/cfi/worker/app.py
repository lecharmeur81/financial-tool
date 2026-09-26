"""Celery application: ``celery -A cfi.worker.app worker|beat``.

Task rules (ADR-0023): idempotent (the engine de-duplicates), acknowledged after completion,
explicit time limits, one task at a time per process, results not stored (``ops.job_run`` is the
job history of record).
"""

from __future__ import annotations

import time
from typing import Any

from celery import Celery, signals

from cfi.core.config import get_settings
from cfi.core.logging import configure_logging, get_logger
from cfi.derivatives.jobs import ingest_source as ingest_derivative_source
from cfi.derivatives.sources import source as derivative_source
from cfi.derivatives.sources import sources_for as derivative_sources_for
from cfi.institutional.jobs import ingest_source
from cfi.institutional.sources import credential_configured, source, sources_for
from cfi.liquidity.jobs import ingest_source as ingest_liquidity_source
from cfi.liquidity.sources import source as liquidity_source
from cfi.liquidity.sources import sources_for as liquidity_sources_for
from cfi.market.jobs import backfill_days, backfill_step, ingest_latest
from cfi.market.sources import ADAPTERS, datasets_for
from cfi.market.universe import ASSET_SYMBOLS, dataset_by_id
from cfi.retail.jobs import ingest_source as ingest_retail_source
from cfi.retail.sources import source as retail_source
from cfi.retail.sources import sources_for as retail_sources_for
from cfi.whales.jobs import ingest_source as ingest_whale_source
from cfi.whales.sources import source as whale_source
from cfi.whales.sources import sources_for as whale_sources_for
from cfi.worker.runtime import WorkerRuntime
from cfi.worker.schedule import beat_schedule

log = get_logger(__name__)
settings = get_settings()

app = Celery("cfi")
app.conf.update(
    broker_url=settings.redis_url.get_secret_value(),
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    timezone="UTC",
    enable_utc=True,
    task_default_queue="ingest",
    beat_schedule=beat_schedule(
        settings.market_provider_ids,
        settings.institutional_provider_ids,
        settings.whale_provider_ids,
        settings.derivative_provider_ids,
        settings.liquidity_provider_ids,
        settings.retail_provider_ids,
    ),
)

BACKFILL_BUDGET_SECONDS = 45.0
_runtime: WorkerRuntime | None = None


@signals.setup_logging.connect
def _setup_logging(**_: Any) -> None:
    configure_logging(settings.log_level, settings.log_format)


def runtime() -> WorkerRuntime:
    global _runtime  # one runtime per worker process
    if _runtime is None:
        _runtime = WorkerRuntime(settings)
    return _runtime


@app.task(name="market.ingest_latest", time_limit=280, soft_time_limit=240)
def ingest_latest_task(provider_id: str, dataset_id: str) -> dict[str, Any]:
    if provider_id not in settings.market_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        results = await ingest_latest(ctx, ADAPTERS[provider_id], dataset_by_id(dataset_id))
        return {"runs": [(r.subject, r.status, r.inserted, r.missing) for r in results]}

    return rt.run(go())


@signals.beat_init.connect
def _kick_institutional(**_: Any) -> None:
    """Beat's first run of an interval entry comes one interval after start (hours for
    institutional, whale and derivatives data), so each of those jobs is also queued once when
    beat starts."""
    for item in sources_for(settings.institutional_provider_ids):
        app.send_task(
            "institutional.ingest",
            args=(item.provider_id, item.dataset.dataset_id),
            queue=item.queue,
            expires=item.interval_seconds,
        )
    for w in whale_sources_for(settings.whale_provider_ids):
        app.send_task(
            "whales.ingest",
            args=(w.provider_id, w.dataset.dataset_id, w.subject),
            queue=w.queue,
            expires=w.interval_seconds,
        )
    for d in derivative_sources_for(settings.derivative_provider_ids):
        app.send_task(
            "derivatives.ingest",
            args=(d.provider_id, d.dataset.dataset_id, d.subject),
            queue=d.queue,
            expires=d.interval_seconds,
        )
    for liq in liquidity_sources_for(settings.liquidity_provider_ids):
        app.send_task(
            "liquidity.ingest",
            args=(liq.provider_id, liq.dataset.dataset_id, liq.subject),
            queue=liq.queue,
            expires=liq.interval_seconds,
        )
    for ret in retail_sources_for(settings.retail_provider_ids):
        app.send_task(
            "retail.ingest",
            args=(ret.provider_id, ret.dataset.dataset_id, ret.subject),
            queue=ret.queue,
            expires=ret.interval_seconds,
        )


@app.task(name="institutional.ingest", time_limit=3600, soft_time_limit=3500)
def institutional_ingest_task(provider_id: str, dataset_id: str) -> dict[str, Any]:
    """One institutional dataset from one provider, every configured subject. Skipped (not
    failed) when the provider is disabled or its API key is not configured."""
    if provider_id not in settings.institutional_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    if not credential_configured(provider_id):
        log.warning("institutional_skipped_no_credential", provider=provider_id)
        return {"skipped": f"provider {provider_id} has no API key configured"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        results = await ingest_source(ctx, source(provider_id, dataset_id))
        return {"runs": [(r.subject, r.status, r.inserted, r.revisions) for r in results]}

    return rt.run(go())


@app.task(name="whales.ingest", time_limit=1800, soft_time_limit=1700)
def whale_ingest_task(provider_id: str, dataset_id: str, subject: str) -> dict[str, Any]:
    """One whale dataset from one provider for one asset: the recent window, then one history
    chunk while history is incomplete. Skipped (not failed) when the provider is disabled."""
    if provider_id not in settings.whale_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        results = await ingest_whale_source(ctx, whale_source(provider_id, dataset_id, subject))
        return {"runs": [(r.job_type, r.status, r.inserted, r.revisions) for r in results]}

    return rt.run(go())


@app.task(name="derivatives.ingest", time_limit=1800, soft_time_limit=1700)
def derivative_ingest_task(provider_id: str, dataset_id: str, subject: str) -> dict[str, Any]:
    """One derivatives dataset from one provider for one asset: the recent window (or a venue
    snapshot), then one history chunk while history is incomplete. Skipped (not failed) when the
    provider is disabled."""
    if provider_id not in settings.derivative_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        item = derivative_source(provider_id, dataset_id, subject)
        results = await ingest_derivative_source(ctx, item)
        return {"runs": [(r.job_type, r.status, r.inserted, r.revisions) for r in results]}

    return rt.run(go())


@app.task(name="liquidity.ingest", time_limit=1800, soft_time_limit=1700)
def liquidity_ingest_task(provider_id: str, dataset_id: str, subject: str) -> dict[str, Any]:
    """One liquidity dataset from one provider for one subject: the recent window, then one
    history chunk while history is incomplete. Skipped (not failed) when the provider is
    disabled."""
    if provider_id not in settings.liquidity_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        item = liquidity_source(provider_id, dataset_id, subject)
        results = await ingest_liquidity_source(ctx, item)
        return {"runs": [(r.job_type, r.status, r.inserted, r.revisions) for r in results]}

    return rt.run(go())


@app.task(name="retail.ingest", time_limit=1800, soft_time_limit=1700)
def retail_ingest_task(provider_id: str, dataset_id: str, subject: str) -> dict[str, Any]:
    """One retail dataset from one provider for one subject: the recent window, then one history
    chunk while history is incomplete (trending has none — see retail/sources.py). Skipped (not
    failed) when the provider is disabled."""
    if provider_id not in settings.retail_provider_ids:
        return {"skipped": f"provider {provider_id} is disabled"}
    rt = runtime()

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        item = retail_source(provider_id, dataset_id, subject)
        results = await ingest_retail_source(ctx, item)
        return {"runs": [(r.job_type, r.status, r.inserted, r.revisions) for r in results]}

    return rt.run(go())


@app.task(name="market.backfill_round", time_limit=110, soft_time_limit=90)
def backfill_round_task() -> dict[str, Any]:
    """Advance history backfill within a time budget, series by series in a fixed order.
    Completed series are skipped quickly, so later series start once earlier ones finish;
    a failed chunk moves on to the next series and is retried in the next round."""
    rt = runtime()
    overrides = settings.market_backfill_overrides

    async def go() -> dict[str, Any]:
        ctx = await rt.context()
        deadline = time.monotonic() + BACKFILL_BUDGET_SECONDS
        steps = 0
        for provider_id in settings.market_provider_ids:
            adapter = ADAPTERS[provider_id]
            for dataset in datasets_for(provider_id):
                if dataset.period_length is None:
                    continue
                depth = backfill_days(dataset, overrides)
                for subject in ASSET_SYMBOLS:
                    while time.monotonic() < deadline:
                        result = await backfill_step(
                            ctx, adapter, dataset, subject, depth_days=depth
                        )
                        if result is None or result.status == "failed":
                            break
                        steps += 1
                    if time.monotonic() >= deadline:
                        return {"steps": steps, "budget_exhausted": True}
        return {"steps": steps, "budget_exhausted": False}

    return rt.run(go())
