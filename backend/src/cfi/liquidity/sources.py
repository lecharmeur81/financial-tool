"""Which provider supplies liquidity / stablecoin data, how often, and how far back (Phase 9).

DefiLlama is the sole provider (``cfi.providers.defillama``); its stablecoin-supply dataset
(``SUPPLY``) is the sole liquidity dataset, tracked for three subjects: USDT, USDC, TOTAL. Every
call to DefiLlama's chart endpoint returns its **entire** history in one response (see
``providers/defillama.py``'s module docstring), so this source is scheduled at a low frequency —
the underlying data itself only changes once a day, and polling more often buys nothing.

History reach: DefiLlama's stablecoin charts start November 2017. History is loaded back that
far, one chunk per run (``cfi.ingestion.scheduled``) — not to spare DefiLlama's request budget
(a single call already returns everything), but so a first start doesn't insert several years of
daily rows in one job run.
"""

from __future__ import annotations

from datetime import timedelta

from cfi.ingestion.scheduled import ScheduledSource
from cfi.liquidity.universe import DAY, SUBJECTS, SUPPLY
from cfi.providers import defillama
from cfi.providers.base import ProviderAdapter

LiquiditySource = ScheduledSource

# DefiLlama's stablecoin charts start November 2017 (~9.3 years back from Phase 9); a generous
# round depth, not an exact day count — history_step stops once it reaches the provider's start.
HISTORY_DEPTH = timedelta(days=3400)
HISTORY_CHUNK = timedelta(days=180)


def _sources() -> tuple[LiquiditySource, ...]:
    return tuple(
        LiquiditySource(
            defillama.PROVIDER_ID,
            SUPPLY,
            subject,
            6 * 3600,
            "ingest",
            recent=timedelta(days=3),
            align=DAY,
            history=HISTORY_DEPTH,
            chunk=HISTORY_CHUNK,
            max_catch_up=timedelta(days=7),
        )
        for subject in SUBJECTS
    )


SOURCES: tuple[LiquiditySource, ...] = _sources()

ADAPTERS: dict[str, ProviderAdapter] = {defillama.PROVIDER_ID: defillama.DefiLlama()}
PRIORITY: dict[str, int] = {defillama.PROVIDER_ID: 10}
ATTRIBUTION: dict[str, dict[str, str]] = {defillama.PROVIDER_ID: defillama.ATTRIBUTION}


def sources_for(provider_ids: list[str]) -> list[LiquiditySource]:
    unknown = [p for p in provider_ids if p not in ADAPTERS]
    if unknown:
        raise ValueError(
            f"unknown liquidity provider(s) {', '.join(unknown)} "
            f"(known: {', '.join(sorted(ADAPTERS))})"
        )
    return [s for s in SOURCES if s.provider_id in provider_ids]


def source(provider_id: str, dataset_id: str, subject: str) -> LiquiditySource:
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
