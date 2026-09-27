"""Backtesting Engine (Phase 16): a production-quality research and historical-replay engine for
evaluating rule-based trading strategies against BTC's own already-ingested price history and the
already-published domain scores/signals from earlier phases.

This is decision-support research tooling, not a guaranteed prediction system and not automatic
financial advice (CLAUDE.md A1). A backtest result is a Statistical Signal about how a FIXED,
already-specified strategy would have performed historically under stated assumptions (fees,
slippage, liquidity, execution lag) — never a claim about future performance (R4: "Never use
backtest results as proof of future performance").

Structural anti-look-ahead design (R4, this phase's explicit instruction), not a runtime check
bolted on afterward:
* Every trading decision on day D is computed from price bars and domain-score snapshots covering
  only [..., D] — never day D+1 or later (``cfi.backtest.engine`` slices the in-memory bar array by
  index on every call, the same discipline ``cfi.similarity.outcomes`` already established).
* Execution of a signal-driven entry/exit is deliberately LAGGED to the following bar's open (never
  the same bar's own close) — a standard anti-look-ahead convention: a real trader cannot observe a
  bar's closing price and transact at that same instant.
* Domain-score signals are gathered with ``as_of = knowledge_time = that day`` (never the backtest's
  own later, global ``as_of``) — the same convention ``cfi.regime``/``cfi.similarity`` already use,
  which structurally excludes any later-ingested revision from an earlier day's decision (R3/R4).
* Liquidity sizing uses only the TRAILING average volume through day D — never the execution bar's
  own (not-yet-known) volume.

No parameter optimizer is included anywhere in this package (this phase's explicit instruction: "Do
not optimize parameters against the test set") — ``cfi.backtest.splits`` only partitions a date
range into in-sample/validation/out-of-sample or walk-forward windows for the USER to manually judge
generalization; it never searches for or selects a "best" parameter set.
"""

from __future__ import annotations
