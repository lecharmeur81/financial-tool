"""Which providers supply which derivatives datasets, how often, and how far back.

Request budget: Binance about 9 requests an hour (2 hourly statistics × 4 perpetuals, funding
every 4 h), OKX about 13 an hour plus liquidation pages (one page per 100 orders), Deribit about
3 an hour — far below every documented limit. History loads (one chunk per run) add a few
hundred requests once.

History reach is what the free endpoints keep: Binance hourly statistics and OKX hourly open
interest / account ratios about one month (29 and 28 days are loaded), funding one year (Binance)
and three months (OKX), DVOL one year. Deribit snapshots and OKX liquidations have no history:
they accumulate from the first run.
"""

from __future__ import annotations

from datetime import timedelta

from cfi.derivatives.universe import HOUR, OPTION_ASSETS, PERP_ASSETS, dataset
from cfi.ingestion.scheduled import ScheduledSource
from cfi.providers import binance_futures, deribit, okx_derivatives
from cfi.providers.base import ProviderAdapter

DerivativesSource = ScheduledSource
DAY = timedelta(days=1)


def _sources() -> tuple[DerivativesSource, ...]:
    out: list[DerivativesSource] = []
    for asset in PERP_ASSETS:
        for provider, history in (
            (binance_futures.PROVIDER_ID, timedelta(days=29)),
            (okx_derivatives.PROVIDER_ID, timedelta(days=28)),
        ):
            for metric in ("open_interest", "long_short_account_ratio"):
                out.append(
                    DerivativesSource(
                        provider,
                        dataset(metric, asset),
                        asset,
                        3600,
                        "ingest",
                        recent=timedelta(hours=6),
                        align=HOUR,
                        history=history,
                        chunk=timedelta(days=10),
                        max_catch_up=timedelta(days=2),
                    )
                )
        for provider, history, chunk in (
            (binance_futures.PROVIDER_ID, timedelta(days=365), timedelta(days=300)),
            (okx_derivatives.PROVIDER_ID, timedelta(days=90), timedelta(days=30)),
        ):
            out.append(
                DerivativesSource(
                    provider,
                    dataset("funding_rate", asset),
                    asset,
                    4 * 3600,
                    "ingest",
                    recent=timedelta(days=3),
                    history=history,
                    chunk=chunk,
                )
            )
        out.append(
            DerivativesSource(
                okx_derivatives.PROVIDER_ID,
                dataset("liquidations", asset),
                asset,
                3600,
                "ingest",
                recent=timedelta(hours=3),
                align=HOUR,
                max_catch_up=timedelta(hours=12),
            )
        )
    for asset in OPTION_ASSETS:
        out.append(
            DerivativesSource(
                deribit.PROVIDER_ID,
                dataset("futures_curve", asset),
                asset,
                3600,
                "ingest",
                recent=timedelta(minutes=1),
            )
        )
        out.append(
            DerivativesSource(
                deribit.PROVIDER_ID,
                dataset("option_chain", asset),
                asset,
                4 * 3600,
                "backfill",
                recent=timedelta(minutes=1),
            )
        )
        out.append(
            DerivativesSource(
                deribit.PROVIDER_ID,
                dataset("volatility_index", asset),
                asset,
                3600,
                "ingest",
                recent=timedelta(hours=6),
                align=HOUR,
                history=timedelta(days=365),
                chunk=timedelta(days=40),
                max_catch_up=timedelta(days=2),
            )
        )
    return tuple(out)


SOURCES: tuple[DerivativesSource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {
    binance_futures.PROVIDER_ID: binance_futures.BinanceFutures(),
    okx_derivatives.PROVIDER_ID: okx_derivatives.OkxDerivatives(),
    deribit.PROVIDER_ID: deribit.Deribit(),
}
PRIORITY: dict[str, int] = {
    binance_futures.PROVIDER_ID: 10,
    okx_derivatives.PROVIDER_ID: 10,
    deribit.PROVIDER_ID: 10,
}
ATTRIBUTION: dict[str, dict[str, str]] = {
    binance_futures.PROVIDER_ID: binance_futures.ATTRIBUTION,
    okx_derivatives.PROVIDER_ID: okx_derivatives.ATTRIBUTION,
    deribit.PROVIDER_ID: deribit.ATTRIBUTION,
}


def sources_for(provider_ids: list[str]) -> list[DerivativesSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown derivatives provider(s) {', '.join(unknown)} "
            f"(known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> DerivativesSource:
    for item in SOURCES:
        if (item.provider_id, item.dataset.dataset_id, item.subject) == (
            provider_id,
            dataset_id,
            subject,
        ):
            return item
    raise KeyError((provider_id, dataset_id, subject))


def providers_for(dataset_id: str, subject: str) -> list[str]:
    return [
        s.provider_id
        for s in SOURCES
        if s.dataset.dataset_id == dataset_id and s.subject == subject
    ]
