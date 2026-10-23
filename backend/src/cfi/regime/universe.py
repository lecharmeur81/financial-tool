"""Market Regime Engine parameters (Phase 14).

No ingestion (see ``cfi/regime/__init__.py``). ``BENCHMARK_ASSET`` matches
``cfi.market_structure.universe.BENCHMARK_ASSET`` — every per-asset reading used by the
classifier (trend, RSI, volatility percentile, institutional/whale/derivatives-health scores) is
read for this one asset, the same "one benchmark" precedent as Phase 12/13, rather than blending
signals across assets.
"""

from __future__ import annotations

from decimal import Decimal

BENCHMARK_ASSET = "BTC"

#: The seven regimes the user asked for. "mixed_unclear" is never itself matched against
#: conditions (see ``cfi.regime.parameters``) — it is the explicit fallback when no regime's
#: conditions are sufficiently and unambiguously satisfied.
REGIME_IDS: tuple[str, ...] = (
    "accumulation",
    "recovery",
    "expansion",
    "euphoria",
    "distribution",
    "capitulation",
    "mixed_unclear",
)

#: Below this available (non-"unavailable") condition weight, a regime cannot be evaluated at all
#: ("insufficient_data" — never scored, never silently treated as unmatched).
MIN_AVAILABLE_WEIGHT_DEFAULT = Decimal("0.5")

#: A regime must reach at least this confidence to be assigned outright.
MIN_CONFIDENCE_ASSIGN_DEFAULT = Decimal("0.55")

#: If the best and second-best regime's confidence are within this margin of each other, the
#: classification is "mixed_unclear" rather than picking one arbitrarily.
TIE_MARGIN_DEFAULT = Decimal("0.08")

#: Regime duration ("how long has this regime held") is found by walking backward from ``as_of``,
#: one day at a time, re-classifying each day, until the label changes or this cap is reached.
#: Capped conservatively — each day re-runs the full classification (nine domain calls) — a
#: documented performance trade-off (ADR-0057), not a silently narrowed one (R3).
MAX_DURATION_LOOKBACK_DAYS = 120

#: Historical examples of the same regime are found by *sampling* (not walking every day) further
#: back than the current streak, at this step size, over this total lookback — a coarser,
#: deliberately cheaper method than the duration walk above (documented trade-off, ADR-0057).
HISTORICAL_LOOKBACK_DAYS = 365
HISTORICAL_STEP_DAYS = 7

#: A sampled run must span at least this many consecutive samples to count as a historical
#: episode (avoids reporting a single noisy weekly sample as a whole "episode").
MIN_EPISODE_SAMPLES = 2
# Interactive requests (GET /regime/current) classify the independent historical samples with at
# most this many in flight. Kept below the default DB pool size (5) so one request cannot starve it.
# Offline read-only probes on the live DB: 3 and 4 were indistinguishable within run-to-run noise
# (3: 7.31 s, 7.72 s; 4: 7.44 s, 6.88 s), so the lower database load wins.
INTERACTIVE_HISTORICAL_CONCURRENCY = 3

MAX_HISTORICAL_EXAMPLES = 3

#: Sourcing/scope gaps, restated here for the user's review (R3 — never silently narrowed).
NOT_TRACKED: tuple[str, ...] = (
    "Regime conditions are evaluated only for BENCHMARK_ASSET (BTC) — the same 'one benchmark' "
    "convention as Phases 12/13. A regime here describes BTC's own market structure/flow "
    "conditions, not necessarily every altcoin's.",
    "None of the seven underlying domain scores has a persisted, ranged history of its own (the "
    "Market Structure Score gap already documented in Phase 12/13). Regime duration and "
    "historical examples are computed by re-running the classifier at past as_of values, not by "
    "reading a stored regime history table — there is no such table.",
    "The seven regime definitions (condition sets, weights, thresholds) are v1 judgment "
    "parameters, chosen by design and anchored to each domain score's own already-published "
    "bands where possible — not fitted to data, not empirically validated (same posture as "
    "every other score in this platform).",
)
