"""Versioned vocabulary of the Cross-Domain Confirmation Engine (Phase 45; ADR-0082).

Everything the confirmation rules depend on lives here as data, so a rule never hides a constant:

* ``EVIDENCE_FAMILIES`` (``evidence_families.v0``): which family each directional domain belongs to,
  by **data lineage**. Domains in one family count once per asset and direction. This is a
  practical lineage safeguard, **not** proof of statistical independence.
* ``CONFIRMATION_PARAMS_V0`` (``confirmation_params.v0``): experimental engineering parameters,
  not validated predictors and not guarantees of future returns. The decision engine's own
  parameters are not reused here because the eligibility rules differ (stricter: stale, partial
  and not-assessed readings do not vote), and none of them is altered.
* ``LIMITATIONS``: known cross-family relationships and scope limits, stated rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from cfi.decision.universe import KEY_CONFIRMATION_DOMAINS

__all__ = [
    "CONFIRMATION_PARAMS_V0",
    "EVIDENCE_FAMILIES",
    "EVIDENCE_FAMILIES_VERSION",
    "KEY_CONFIRMATION_DOMAINS",
    "LIMITATIONS",
    "ConfirmationParameters",
    "EvidenceFamily",
]

EVIDENCE_FAMILIES_VERSION: Final = "evidence_families.v0"
PARAMETER_VERSION: Final = "confirmation_params.v0"


@dataclass(frozen=True, slots=True)
class EvidenceFamily:
    family_id: str
    lineage: str  # the data lineage the family rests on (default providers)


# Directional domain -> family. A directional domain with no entry here is excluded from the
# vote (``no_family_mapping``), never counted; a test pins that every defined directional domain
# is mapped.
EVIDENCE_FAMILIES: Final = MappingProxyType(
    {
        "institutional": EvidenceFamily(
            "institutional_flows", "US spot ETF flows (SoSoValue), with CoinGecko prices"
        ),
        "whale": EvidenceFamily(
            "onchain_large_holders",
            "on-chain large transfers and holders (Blockchair, Coin Metrics)",
        ),
        "liquidity": EvidenceFamily("stablecoin_liquidity", "stablecoin supply (DefiLlama)"),
        "macro": EvidenceFamily("macro_backdrop", "US macro series (FRED)"),
        "market_structure": EvidenceFamily(
            "price_structure", "market-wide price and volume structure (CoinGecko)"
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ConfirmationParameters:
    version: str = PARAMETER_VERSION
    min_families: int = 2  # distinct eligible families on one side to confirm
    require_key_layer: bool = True  # one eligible asset-specific confirmer from the key layer
    coverage_floor: tuple[int, int] = (1, 2)  # eligible / expected below 1/2 -> insufficient


CONFIRMATION_PARAMS_V0: Final = ConfirmationParameters()

LIMITATIONS: Final = (
    (
        "independence_by_lineage_only",
        "Family de-duplication is a data-lineage safeguard, not proof of statistical independence.",
    ),
    (
        "price_lineage_overlap",
        "Institutional flows and market structure both use CoinGecko price data; the relationship "
        "is recorded, not modelled.",
    ),
    (
        "economic_overlap_not_modelled",
        "Liquidity, macro and market structure can respond to common conditions; no correlation "
        "or causation is claimed or measured.",
    ),
    (
        "market_wide_evidence_shared",
        "Liquidity, macro and market structure are market-wide (market structure is "
        "BTC-benchmarked); they are shown in every asset block as shared, not as independent "
        "observations of that asset.",
    ),
    (
        "experimental_parameters",
        "Thresholds are experimental engineering parameters, not validated predictors or "
        "guarantees of future returns.",
    ),
)
