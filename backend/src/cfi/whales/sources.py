"""Which providers supply which whale datasets, how often, and how far back.

Only adapters verified against official documentation appear here; mock providers are never
registered in the application (R3).

Request budget (Blockchair, free tier: 1,440 requests a day, counted in request points): about
8 rich-list points, 4 × 22 aggregation points twice a day, and large-transfer pages (≈ 23 points per
Bitcoin page, ≈ 13 per Ethereum page) every 3 hours — a few hundred points a day, plus a one-off
history load. Coin Metrics allows 10 requests per 6 s; this schedule uses about 40 a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from cfi.domain.datasets import DatasetSpec
from cfi.providers import blockchair, coinmetrics
from cfi.providers.base import ProviderAdapter
from cfi.whales.universe import DORMANCY_ASSETS, WHALE_ASSETS, dataset


@dataclass(frozen=True, slots=True)
class WhaleSource:
    provider_id: str
    dataset: DatasetSpec
    subject: str
    interval_seconds: int
    queue: str
    # Each run re-reads this recent window (new values, revisions, late blocks).
    recent: timedelta
    # Daily datasets: only complete UTC days are requested.
    complete_days_only: bool
    # History loaded once, one chunk per run, back to this depth (0: none).
    history_days: int = 0
    chunk_days: int = 30
    # After downtime, a run reaches back to the newest stored value, at most this far.
    max_catch_up: timedelta = timedelta(0)


def _sources() -> tuple[WhaleSource, ...]:
    out: list[WhaleSource] = []
    for asset in WHALE_ASSETS:
        for metric in coinmetrics.METRIC_IDS:
            out.append(
                WhaleSource(
                    coinmetrics.PROVIDER_ID,
                    dataset(metric, asset),
                    asset,
                    6 * 3600,
                    "ingest",
                    recent=timedelta(days=35),
                    complete_days_only=True,
                    history_days=730,
                    chunk_days=365,
                )
            )
        out.append(
            WhaleSource(
                blockchair.PROVIDER_ID,
                dataset("address_balance", asset),
                asset,
                24 * 3600,
                "backfill",
                recent=timedelta(hours=1),
                complete_days_only=False,
            )
        )
        out.append(
            WhaleSource(
                blockchair.PROVIDER_ID,
                dataset("large_transfer", asset),
                asset,
                3 * 3600,
                "backfill",
                recent=timedelta(hours=6),
                complete_days_only=False,
                history_days=7,
                chunk_days=1,
                max_catch_up=timedelta(days=2),
            )
        )
    for asset in DORMANCY_ASSETS:
        for metric in blockchair.DAILY_METRICS:
            out.append(
                WhaleSource(
                    blockchair.PROVIDER_ID,
                    dataset(metric, asset),
                    asset,
                    12 * 3600,
                    "backfill",
                    recent=timedelta(days=10),
                    complete_days_only=True,
                    history_days=120,
                    chunk_days=30,
                )
            )
    return tuple(out)


SOURCES: tuple[WhaleSource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {
    coinmetrics.PROVIDER_ID: coinmetrics.CoinMetrics(),
    blockchair.PROVIDER_ID: blockchair.Blockchair(),
}
PRIORITY: dict[str, int] = {coinmetrics.PROVIDER_ID: 10, blockchair.PROVIDER_ID: 10}
ATTRIBUTION: dict[str, dict[str, str]] = {
    coinmetrics.PROVIDER_ID: coinmetrics.ATTRIBUTION,
    blockchair.PROVIDER_ID: blockchair.ATTRIBUTION,
}


def sources_for(provider_ids: list[str]) -> list[WhaleSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown whale provider(s) {', '.join(unknown)} (known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> WhaleSource:
    for item in SOURCES:
        if (item.provider_id, item.dataset.dataset_id, item.subject) == (
            provider_id,
            dataset_id,
            subject,
        ):
            return item
    raise KeyError((provider_id, dataset_id, subject))


def provider_for(dataset_id: str) -> str | None:
    return next((s.provider_id for s in SOURCES if s.dataset.dataset_id == dataset_id), None)
