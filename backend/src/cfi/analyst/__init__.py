"""Claude AI Analyst (Phase 21): an evidence-grounded L5 interpretation layer over the platform's
already-computed L1-L4 intelligence (market data, institutional/whale/retail activity, derivatives,
liquidity, macro, market structure, divergence, regime, historical similarity, anomalies, capital
rotation).

Claude is the analyst, not the database (CLAUDE.md R6): every call is grounded in an immutable
``cfi.analyst.snapshot.Snapshot`` built entirely from existing, already-tested domain services —
this package adds no new data ingestion and performs no calculations of its own. Claude may only
cite values already present in that snapshot, each traceable to a stable field ID; a deterministic,
non-AI validator (``cfi.analyst.validator``) checks every response against the snapshot before it is
ever stored or served, rejecting invented numbers, missing evidence sections, unsupported bullish/
bearish/certainty language, or an unlabelled inferred rotation presented as an observed fact.
"""
