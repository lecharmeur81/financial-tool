"""Historical Similarity Engine (Phase 15): a rule-based, explainable nearest-neighbour search
over the current market's 9-feature state (institutional flows, whale flows, retail activity,
liquidity, funding, open interest, volatility, market structure, macro) against sampled historical
dates, each read from the same already-published domain scores/readings used by
``cfi.regime`` (Phase 14) and ``cfi.divergence`` (Phase 13).

Evidence category (R2): the similarity score is a Statistical Signal (L3) — "a metric evaluated
against its own history or another metric" — a documented distance computed over already-published
Calculated Metrics. It is NOT a Regime Classification, and the regime label attached to each
historical analogue is only a citation of that analogue's own already-computed Phase 14
classification, not a new one performed here.

Ingests nothing of its own (no ``sources.py``, no ``jobs.py``, no worker/schedule changes, no new
provider settings) — pure computation, same posture as ``cfi.divergence`` and ``cfi.regime``.

Look-ahead-bias discipline (R4, this phase's explicit instruction) is structural, not a runtime
check bolted on afterward:
* Every historical candidate's own feature snapshot is gathered with ``as_of = knowledge_time =
  candidate_date`` (never the query's own, later ``as_of``) — the same convention
  ``cfi.regime.service.RegimeService._classify_at`` already established.
* A historical analogue's 7/30/90-day forward return and its maximum-drawdown window are only
  displayed once that many days have genuinely elapsed by the *query's* ``as_of`` — never
  fabricated or estimated ahead of that (``cfi.similarity.outcomes``).
* No predicted future return is ever produced. Only actual historical outcomes of past analogues,
  and the distribution/range across them — never a single forecast number.
"""

from __future__ import annotations
