"""Which providers supply which institutional datasets, for which subjects, and how often.

Only adapters verified against official documentation appear here. Mock providers are never
registered in the application (R3).

All SoSoValue work runs on the ``backfill`` queue: one worker process then owns the provider's
20-requests-per-minute budget (rate limiters are per process — ADR-0046), and the slow listing
sweeps never delay market data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import AuthType
from cfi.institutional.universe import (
    ETF_ASSETS,
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_HOLDING_ASSETS,
    TREASURY_HOLDINGS_COMPANIES,
    TREASURY_PURCHASE_ASSETS,
    TREASURY_PURCHASE_BTC,
)
from cfi.providers import coingecko, sosovalue
from cfi.providers.base import ProviderAdapter


@dataclass(frozen=True, slots=True)
class InstitutionalSource:
    provider_id: str
    dataset: DatasetSpec
    subjects: tuple[str, ...]
    interval_seconds: int
    queue: str
    # How far back each run asks (the provider may return less; documented per adapter).
    lookback_days: int


SOURCES: tuple[InstitutionalSource, ...] = (
    InstitutionalSource(
        sosovalue.PROVIDER_ID, ETF_FLOW_US_SPOT, ETF_ASSETS, 2 * 3600, "backfill", 31
    ),
    InstitutionalSource(
        sosovalue.PROVIDER_ID, ETF_FUND_FLOW_US_SPOT, ETF_ASSETS, 6 * 3600, "backfill", 31
    ),
    InstitutionalSource(
        sosovalue.PROVIDER_ID,
        TREASURY_PURCHASE_BTC,
        TREASURY_PURCHASE_ASSETS,
        12 * 3600,
        "backfill",
        3650,
    ),
    InstitutionalSource(
        coingecko.PROVIDER_ID,
        TREASURY_HOLDINGS_COMPANIES,
        TREASURY_HOLDING_ASSETS,
        6 * 3600,
        "ingest",
        1,
    ),
)

ADAPTERS: dict[str, ProviderAdapter] = {
    sosovalue.PROVIDER_ID: sosovalue.SoSoValue(),
    coingecko.PROVIDER_ID: coingecko.CoinGecko(),
}

PRIORITY: dict[str, int] = {sosovalue.PROVIDER_ID: 10, coingecko.PROVIDER_ID: 10}

ATTRIBUTION: dict[str, dict[str, str]] = {
    sosovalue.PROVIDER_ID: sosovalue.ATTRIBUTION,
    coingecko.PROVIDER_ID: coingecko.ATTRIBUTION,
}


def sources_for(provider_ids: list[str]) -> list[InstitutionalSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown institutional provider(s) {', '.join(unknown)} "
            f"(known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str) -> InstitutionalSource:
    for item in SOURCES:
        if item.provider_id == provider_id and item.dataset.dataset_id == dataset_id:
            return item
    raise KeyError((provider_id, dataset_id))


def credential_configured(provider_id: str, environ: dict[str, str] | None = None) -> bool:
    """Whether the provider can be called: keyless, optional key, or its key variable is set.
    Only the *presence* of the variable is checked; its value is never read into a response."""
    auth = ADAPTERS[provider_id].capabilities.auth
    if auth.type is AuthType.NONE or auth.optional:
        return True
    env = os.environ if environ is None else environ
    return bool(env.get(auth.env_var))
