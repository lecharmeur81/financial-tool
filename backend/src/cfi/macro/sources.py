"""Which provider supplies which macro dataset, how often, and how far back (Phase 11).

One provider (FRED) supplies every dataset. All macro work runs on the ``backfill`` queue (like
SoSoValue, Phase 6): it is not latency-sensitive (macro series update at most daily, most far less
often) and benefits from deep history, so it never competes with the fast/recent queues market data
uses. FRED needs a free API key (``CFI_PROVIDER_FRED_API_KEY``); when it is not configured, jobs
are skipped, not failed (mirrors ``cfi.institutional.sources.credential_configured``).
"""

from __future__ import annotations

import os
from datetime import timedelta

from cfi.domain.enums import AuthType
from cfi.ingestion.scheduled import ScheduledSource
from cfi.macro.universe import (
    CPI,
    DXY_BROAD_PROXY,
    FED_BALANCE_SHEET,
    FED_FUNDS_EFFECTIVE,
    FED_FUNDS_TARGET_LOWER,
    FED_FUNDS_TARGET_UPPER,
    M2_MONTHLY,
    M2_WEEKLY,
    NASDAQ_COMPOSITE,
    OIL_WTI,
    PCE_PRICE_INDEX,
    REVERSE_REPO,
    SP500,
    TREASURY_GENERAL_ACCOUNT,
    UNEMPLOYMENT_RATE,
    US_SUBJECT,
    UST_YIELD_2Y,
    UST_YIELD_10Y,
    VIX,
    all_datasets,
)
from cfi.providers import fred
from cfi.providers.base import ProviderAdapter

MacroSource = ScheduledSource

DAY = timedelta(days=1)
FIVE_YEARS = timedelta(days=365 * 5)
TEN_YEARS = timedelta(days=365 * 10)

_DAILY_KW = {
    "align": DAY,
    "recent": timedelta(days=10),
    "history": FIVE_YEARS,
    "chunk": timedelta(days=365),
}
_WEEKLY_KW = {
    "align": timedelta(days=7),
    "recent": timedelta(days=28),
    "history": FIVE_YEARS,
    "chunk": timedelta(days=365),
}
_MONTHLY_KW = {
    "align": timedelta(days=30),
    "recent": timedelta(days=100),
    "history": TEN_YEARS,
    "chunk": timedelta(days=365 * 2),
}
_EVENT_KW = {
    "align": DAY,
    "recent": timedelta(days=21),
    "history": TEN_YEARS,
    "chunk": timedelta(days=365 * 2),
}


def _sources() -> tuple[MacroSource, ...]:
    daily = (
        DXY_BROAD_PROXY,
        UST_YIELD_2Y,
        UST_YIELD_10Y,
        FED_FUNDS_EFFECTIVE,
        VIX,
        SP500,
        NASDAQ_COMPOSITE,
        OIL_WTI,
        REVERSE_REPO,
    )
    weekly = (FED_BALANCE_SHEET, TREASURY_GENERAL_ACCOUNT, M2_WEEKLY)
    monthly = (CPI, PCE_PRICE_INDEX, UNEMPLOYMENT_RATE, M2_MONTHLY)
    event = (FED_FUNDS_TARGET_UPPER, FED_FUNDS_TARGET_LOWER)
    out: list[MacroSource] = []
    out.extend(
        MacroSource(fred.PROVIDER_ID, d, US_SUBJECT, 6 * 3600, "backfill", **_DAILY_KW)
        for d in daily
    )
    out.extend(
        MacroSource(fred.PROVIDER_ID, d, US_SUBJECT, 12 * 3600, "backfill", **_WEEKLY_KW)
        for d in weekly
    )
    out.extend(
        MacroSource(fred.PROVIDER_ID, d, US_SUBJECT, 24 * 3600, "backfill", **_MONTHLY_KW)
        for d in monthly
    )
    out.extend(
        MacroSource(fred.PROVIDER_ID, d, US_SUBJECT, 12 * 3600, "backfill", **_EVENT_KW)
        for d in event
    )
    assert len(out) == len(all_datasets())  # noqa: S101 — every dataset is scheduled exactly once
    return tuple(out)


SOURCES: tuple[MacroSource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {fred.PROVIDER_ID: fred.FRED()}
PRIORITY: dict[str, int] = {fred.PROVIDER_ID: 10}
ATTRIBUTION: dict[str, dict[str, str]] = {fred.PROVIDER_ID: fred.ATTRIBUTION}


def credential_configured(provider_id: str, environ: dict[str, str] | None = None) -> bool:
    """Whether the provider can be called: keyless, optional key, or its key variable is set.
    Only the *presence* of the variable is checked; its value is never read into a response
    (mirrors ``cfi.institutional.sources.credential_configured``)."""
    auth = ADAPTERS[provider_id].capabilities.auth
    if auth.type is AuthType.NONE or auth.optional:
        return True
    env = os.environ if environ is None else environ
    return bool(env.get(auth.env_var))


def sources_for(provider_ids: list[str]) -> list[MacroSource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown macro provider(s) {', '.join(unknown)} (known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> MacroSource:
    for item in SOURCES:
        if (item.provider_id, item.dataset.dataset_id, item.subject) == (
            provider_id,
            dataset_id,
            subject,
        ):
            return item
    raise KeyError((provider_id, dataset_id, subject))
