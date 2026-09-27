"""Constants for the Historical Similarity Engine (Phase 15). See ADR-0058 for rationale."""

from __future__ import annotations

BENCHMARK_ASSET = "BTC"

# Candidate search window (ADR-0058, mirroring the documented performance trade-off already
# established for cfi.regime.history.historical_examples, Phase 14/ADR-0057): sampling every date
# in the lookback window would require one full 9-feature snapshot (7 domain service calls) per
# day, which is not needed for finding a handful of good analogues. A weekly sample over 2 years
# is a deliberate, documented cost/precision trade-off, not a silent shortcut.
LOOKBACK_DAYS = 730
STEP_DAYS = 7

# A candidate must be at least this many days before the query's own as_of to count as genuinely
# "historical" rather than effectively today.
MIN_CANDIDATE_AGE_DAYS = 14

# Selected analogues must be at least this many days apart from each other, so the top results are
# not five consecutive weeks of the same episode (greedy de-duplication by recency, highest
# similarity first).
MIN_GAP_DAYS = 30

# Detailed rows returned (date, similarity score, regime, forward returns, drawdown, volatility).
TOP_N_ANALOGUES = 5

# The broader, still-deduplicated set of analogues whose forward returns feed the *distribution*
# section (a superset of the detailed rows) — capped for cost, and never used to produce a single
# predicted number, only a range.
MAX_DISTRIBUTION_SAMPLE = 15
MIN_DISTRIBUTION_SAMPLE = 3

# A candidate is compared only if at least this fraction of the total feature weight is available
# on BOTH the query date and the candidate date (mirrors cfi.regime's min_available_weight
# convention).
MIN_AVAILABLE_WEIGHT = "0.5"

FORWARD_RETURN_HORIZONS_DAYS: tuple[int, ...] = (7, 30, 90)
DRAWDOWN_WINDOW_DAYS = 90

NOT_TRACKED: tuple[str, ...] = (
    "Feature normalization uses fixed, documented bounds decided once for this parameter version "
    "(not fitted to any date's data) so that no candidate's similarity score can ever be "
    "influenced by data outside its own point-in-time snapshot — see cfi.similarity.parameters.",
    "Only BTC is compared (the platform's established benchmark asset) — no per-asset similarity "
    "search.",
    "No predicted future return is produced. 7/30/90-day forward returns and maximum drawdown are "
    "reported only for historical analogues, and only once genuinely knowable as of the query's "
    "own as_of — never for the current (query) date itself.",
)
