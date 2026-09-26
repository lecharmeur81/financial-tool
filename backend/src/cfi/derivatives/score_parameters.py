"""Versioned parameter sets for the Derivatives Health Score (Phase 8 addendum).

The score's weights, reference scales, band boundaries and minimum-available-weight are
judgment parameters (R2: Calculated Metric, not fitted to data) — chosen by design, not
statistically validated. They previously lived as module-level constants inside ``score.py``.
This module externalises them into a small, versioned, immutable registry so that:

* the scoring engine (``score.py``) loads parameters through one function, :func:`parameters`,
  instead of hard-coding numbers;
* a future change publishes a **new** version id here rather than editing an existing one, so
  every score ever computed remains reproducible against the exact parameters that produced it
  (R3 — never silently change the meaning of a past value);
* red-team / backtesting work (Phases 15-16) can load an old or alternate parameter set by id
  without touching the scoring engine.

This is a plain Python module, not a database table, because there is exactly one active
version at a time and nothing here is edited at runtime — a deliberate choice against
over-engineering a config subsystem nothing yet needs. ``parameters()`` is the interface the
rest of the code depends on; promoting this registry into a database table later (if multiple
versions ever need to be compared live) would not require changing any caller.

**Do not edit the values of an existing entry once it has been used to compute a score that
someone has seen.** Add a new ``ParameterSet`` under a new version id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParameterSet:
    """One complete, named set of Derivatives Health Score parameters.

    Weights are expected to sum to 1 (checked by tests, not enforced at construction — this
    stays a plain data container). Every "scale" is the metric value at which that component's
    stress reaches 1 (see ``score.py``'s module docstring for the stress formula).
    """

    version: str
    weight_funding: Decimal
    weight_basis: Decimal
    weight_leverage: Decimal
    weight_liquidations: Decimal
    weight_volatility: Decimal
    funding_scale: Decimal  # |annualised 7-day funding|, ratio
    basis_band: tuple[Decimal, Decimal]  # ordinary annualised basis range (stress 0 inside)
    basis_scale: Decimal  # distance beyond basis_band at which stress reaches 1
    leverage_scale: Decimal  # |7-day relative leverage change|
    liquidation_scale: Decimal  # 24h liquidated (coins) ÷ open interest (coins)
    dvol_scales: dict[str, tuple[Decimal, Decimal]]  # per-asset (calm, stressed) DVOL level
    min_available_weight: Decimal  # below this available weight, score is "Insufficient data"
    bands: tuple[tuple[Decimal | None, str], ...]  # (lower bound or None, label); highest first


DERIVATIVES_HEALTH_V1 = ParameterSet(
    version="derivatives_health_v1",
    weight_funding=Decimal("0.25"),
    weight_basis=Decimal("0.15"),
    weight_leverage=Decimal("0.20"),
    weight_liquidations=Decimal("0.20"),
    weight_volatility=Decimal("0.20"),
    funding_scale=Decimal("0.30"),
    basis_band=(Decimal(0), Decimal("0.10")),
    basis_scale=Decimal("0.15"),
    leverage_scale=Decimal("0.20"),
    liquidation_scale=Decimal("0.01"),
    dvol_scales={
        "BTC": (Decimal("0.30"), Decimal("0.80")),
        "ETH": (Decimal("0.40"), Decimal("1.00")),
    },
    min_available_weight=Decimal("0.5"),
    bands=(
        (Decimal(75), "low stress"),
        (Decimal(50), "moderate stress"),
        (Decimal(25), "elevated stress"),
        (None, "high stress"),
    ),
)

#: Every parameter set ever published, keyed by version id. Append-only: never replace an
#: existing entry's values (see module docstring).
PARAMETER_SETS: dict[str, ParameterSet] = {DERIVATIVES_HEALTH_V1.version: DERIVATIVES_HEALTH_V1}

#: The version the scoring engine uses when none is specified.
CURRENT_VERSION = DERIVATIVES_HEALTH_V1.version


def parameters(version: str | None = None) -> ParameterSet:
    """Look up a named parameter set (defaults to :data:`CURRENT_VERSION`).

    An unknown version id is a hard error rather than a silent fallback (R3): a caller asking
    for a specific historical version must get that version or an explicit failure, never a
    substitute it did not ask for.
    """
    key = version or CURRENT_VERSION
    if key not in PARAMETER_SETS:
        raise KeyError(f"Unknown Derivatives Health Score parameter version: {key!r}")
    return PARAMETER_SETS[key]
