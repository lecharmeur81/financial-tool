"""Celery beat schedule for market, institutional, whale and derivatives data (pure; no
connections).

Queues by workload (ADR-0023): ``ingest_fast`` (minute bars, last trade), ``ingest`` (everything
else recent), ``backfill`` (history, low priority). Each scheduled run expires after one interval,
so a slow queue never piles up duplicate runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cfi.derivatives.sources import sources_for as derivative_sources_for
from cfi.domain.datasets import DatasetSpec
from cfi.institutional.sources import sources_for
from cfi.liquidity.sources import sources_for as liquidity_sources_for
from cfi.market.sources import ADAPTERS, datasets_for
from cfi.whales.sources import sources_for as whale_sources_for

# Seconds between scheduled runs, per dataset period (or metric for event series).
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 120,
    "15m": 300,
    "1h": 300,
    "4h": 900,
    "1d": 1800,
    "spot_price": 30,
    "market_cap": 300,
    "market_cap_1d": 6 * 3600,
}
BACKFILL_INTERVAL_SECONDS = 60
FAST_QUEUE_KEYS = {"1m", "spot_price"}


@dataclass(frozen=True, slots=True)
class ScheduledIngestion:
    provider_id: str
    dataset_id: str
    interval_seconds: int
    queue: str


def _key(dataset: DatasetSpec) -> str:
    if dataset.period == "event":
        return dataset.metric
    if dataset.metric == "market_cap":
        return "market_cap_1d"
    return dataset.period


def scheduled_ingestions(provider_ids: list[str]) -> list[ScheduledIngestion]:
    out = []
    for provider_id in provider_ids:
        if provider_id not in ADAPTERS:
            raise ValueError(
                f"unknown market provider {provider_id!r} (known: {', '.join(sorted(ADAPTERS))})"
            )
        for dataset in datasets_for(provider_id):
            key = _key(dataset)
            out.append(
                ScheduledIngestion(
                    provider_id=provider_id,
                    dataset_id=dataset.dataset_id,
                    interval_seconds=INTERVAL_SECONDS[key],
                    queue="ingest_fast" if key in FAST_QUEUE_KEYS else "ingest",
                )
            )
    return out


def institutional_entries(provider_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One entry per (provider, dataset). Institutional data changes at most daily, so intervals
    are hours; runs are idempotent (re-reading a window only adds new days or revisions)."""
    return {
        f"institutional:{item.provider_id}:{item.dataset.dataset_id}": {
            "task": "institutional.ingest",
            "schedule": float(item.interval_seconds),
            "args": (item.provider_id, item.dataset.dataset_id),
            "options": {"queue": item.queue, "expires": item.interval_seconds},
        }
        for item in sources_for(provider_ids)
    }


def whale_entries(provider_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One entry per (provider, dataset, subject); intervals are hours (daily data, rich lists)
    or 3 hours (large transfers). Runs are idempotent."""
    return {
        f"whales:{item.provider_id}:{item.dataset.dataset_id}:{item.subject}": {
            "task": "whales.ingest",
            "schedule": float(item.interval_seconds),
            "args": (item.provider_id, item.dataset.dataset_id, item.subject),
            "options": {"queue": item.queue, "expires": item.interval_seconds},
        }
        for item in whale_sources_for(provider_ids)
    }


def derivative_entries(provider_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One entry per (provider, dataset, subject); hourly (open interest, ratios, liquidations,
    DVOL, futures curve) or every 4 hours (funding, option chain). Runs are idempotent."""
    return {
        f"derivatives:{item.provider_id}:{item.dataset.dataset_id}:{item.subject}": {
            "task": "derivatives.ingest",
            "schedule": float(item.interval_seconds),
            "args": (item.provider_id, item.dataset.dataset_id, item.subject),
            "options": {"queue": item.queue, "expires": item.interval_seconds},
        }
        for item in derivative_sources_for(provider_ids)
    }


def liquidity_entries(provider_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One entry per (provider, dataset, subject); every 6 hours (the data itself changes at
    most daily — see ``cfi.liquidity.sources``). Runs are idempotent."""
    return {
        f"liquidity:{item.provider_id}:{item.dataset.dataset_id}:{item.subject}": {
            "task": "liquidity.ingest",
            "schedule": float(item.interval_seconds),
            "args": (item.provider_id, item.dataset.dataset_id, item.subject),
            "options": {"queue": item.queue, "expires": item.interval_seconds},
        }
        for item in liquidity_sources_for(provider_ids)
    }


def beat_schedule(
    provider_ids: list[str],
    institutional_provider_ids: list[str] | None = None,
    whale_provider_ids: list[str] | None = None,
    derivative_provider_ids: list[str] | None = None,
    liquidity_provider_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    schedule: dict[str, dict[str, Any]] = institutional_entries(institutional_provider_ids or [])
    schedule.update(whale_entries(whale_provider_ids or []))
    schedule.update(derivative_entries(derivative_provider_ids or []))
    schedule.update(liquidity_entries(liquidity_provider_ids or []))
    for item in scheduled_ingestions(provider_ids):
        schedule[f"latest:{item.provider_id}:{item.dataset_id}"] = {
            "task": "market.ingest_latest",
            "schedule": float(item.interval_seconds),
            "args": (item.provider_id, item.dataset_id),
            "options": {"queue": item.queue, "expires": item.interval_seconds},
        }
    if provider_ids:
        schedule["backfill:round"] = {
            "task": "market.backfill_round",
            "schedule": float(BACKFILL_INTERVAL_SECONDS),
            "options": {"queue": "backfill", "expires": BACKFILL_INTERVAL_SECONDS},
        }
    return schedule
