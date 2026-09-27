# RED_TEAM_REPORT.md

**Phase 17 — Quantitative Red-Team Review.** Independent adversarial review of the platform's
quantitative methodology, conducted 2026-09-27. Scope: market data, institutional flows, whale
classification, retail proxies, derivatives, liquidity, macro, market structure, regime engine,
divergence engine, historical similarity engine, backtesting engine.

**Posture:** this review tries to prove the methodology wrong, not confirm it's right. No code was
modified. Every finding below is anchored to an exact file:line and was independently verified by
reading the cited code (not merely inferred from documentation) before being included here. Findings
that were investigated and found NOT to be problems are recorded too, at the end, because a red-team
review that only reports bad news is not trustworthy — the negative findings are as much a claim
about the codebase as the positive ones, and are made with the same evidentiary bar.

**Severity scale:** CRITICAL (silently produces wrong numbers that look valid, platform-wide or in a
core primitive) · HIGH (a specific engine's output is materially unrealistic or biased) · MEDIUM (a
real methodological weakness, bounded in scope or already partially mitigated) · LOW (a documented
trade-off worth tightening, not a defect).

---

## Summary table

| # | Finding | Domain | Severity |
|---|---|---|---|
| 1 | `knowledge_time` silently defaults to "now", defeating the revision/leakage gate | Platform-wide (every domain except raw OHLCV bars) | CRITICAL |
| 2 | FRED macro series carry no point-in-time vintage — always the latest revision | Macro → Regime/Similarity/Backtest | HIGH |
| 3 | Stop-loss/take-profit fills skip slippage and ignore opening gaps | Backtesting engine | HIGH |
| 4 | Regime/Market-Structure classification has no hysteresis — hard-cutoff flip-flopping | Regime engine, Market Structure Score | HIGH |
| 5 | Cost model applies flat slippage regardless of trade size vs. liquidity cap | Backtesting engine | MEDIUM |
| 6 | Altcoin relative-strength (20% of Market Structure Score) has no minimum-asset-count floor | Market Structure Score | MEDIUM |
| 7 | Retail Speculation Score reuses the same series as Derivatives Health Score | Retail / Derivatives | MEDIUM |
| 8 | Liquidity Score measures stablecoin supply growth, not liquidity or peg stability | Liquidity | MEDIUM |
| 9 | Derivatives liquidation-stress component is single-venue (OKX only) | Derivatives | MEDIUM |
| 10 | Similarity candidate sampling is locked to one weekday per query | Historical Similarity | MEDIUM |
| 11 | Backtest position sizing uses day D's close; the order fills at D+1's open | Backtesting engine | MEDIUM |
| 12 | Backtest test suite verifies status/counts, not exact prices/fees/Sharpe values | Backtesting engine (tests) | MEDIUM |
| 13 | Large-transfer size classification uses the latest balance snapshot, not the transfer-date balance | Whale intelligence | LOW |
| 14 | Silent warmup shortfall: no flag if fewer than `WARMUP_DAYS` bars exist before `start` | Backtesting engine | LOW |
| 15 | Fixed 4-asset universe with no first-class "delisted/discontinued" state | Market data | LOW |

---

## Findings

### 1. `knowledge_time` silently defaults to "now", defeating the revision/leakage gate

**Problem.** Every domain API route (`institutional`, `whales`, `retail`, `derivatives`, `liquidity`,
`macro`, `market_structure`, `regime`, `similarity`, `divergence`) defines its own `_times()` helper
that resolves `as_of` and `knowledge_time` **independently**:

```python
# backend/src/cfi/api/routes/market_structure.py:57-61 (identical pattern in the other 9 route files)
def _times(as_of: datetime | None, knowledge_time: datetime | None) -> tuple[datetime, datetime]:
    now = utc_now()
    a = aware(as_of, "as_of")
    k = aware(knowledge_time, "knowledge_time")
    return (now if a is None else min(a, now)), (now if k is None else min(k, now))
```

If a caller supplies only `as_of` (the natural single-parameter way to ask "what did this look like
on date X") and omits `knowledge_time`, `knowledge_time` resolves to `utc_now()`. That value is then
passed straight into every domain query's revision gate, e.g.:

```python
# backend/src/cfi/market_structure/queries.py:44-46
AND o.event_time >= :start AND o.event_time < :end
AND o.available_at <= :as_of AND o.ingested_at <= :kt
```
(the identical `available_at <= :as_of AND ingested_at <= :kt` shape recurs at
`institutional/queries.py:51,80,107,129`, `whales/queries.py:48,69,89,120`,
`retail/queries.py:53,84,112`, `derivatives/queries.py:51,74,89,118`, `liquidity/queries.py:43`).

With `kt = now()`, `ingested_at <= :kt` is true for every row ever stored — the clause becomes a
no-op. Only `available_at <= :as_of` still restricts anything, which means: a value that was
**revised** after `as_of` but whose (possibly estimated) `available_at` still reads as before
`as_of` will be visible to the query, exactly the "future revisions leaking into historical
decisions" pattern R4 explicitly names. Raw OHLCV price bars are NOT affected — `MarketQueries.bars()`
(`market/queries.py:45-68`) takes a single `as_of` and uses it for both `available_at` and
`ingested_at`, which is the correct pattern; this bug is specific to every "observation" series
(institutional flows, whale/on-chain flows, retail proxies, derivatives, liquidity, macro,
market-structure's TOTAL-cap series, and — through those — regime/similarity/divergence outputs
built from them).

**Why it matters.** This is the single highest-leverage vector for silent look-ahead bias in the
whole platform, because it requires no attacker and no unusual usage — it fires on the single most
natural way to call any of these ten endpoints ("give me the state as of date X"). It is currently
masked in every internal, already-composed call path (see the "checked, correct" section below,
item C1) because those call sites always pass `knowledge_time=as_of` explicitly — but that is a
convention enforced by careful call-site discipline, not by the type system or a default, and one
new call site (a future direct API integration, a script, a person testing the API, a future
backtest built directly against the HTTP surface rather than through `cfi.divergence.adapters`) is
one missed keyword argument away from silently reintroducing look-ahead bias.

**Evidence.** `market_structure.py:57-61`, `macro.py:53`, `institutional.py:347-350`,
`whales.py:58`, `retail.py:55`, `derivatives.py:51`, `liquidity.py:54`, `regime.py:47`,
`similarity.py:47`, `divergence.py:62` (all ten route files share this exact `_times` body, verified
directly, not just grepped by name) paired with the query-level `ingested_at <= :kt` gate confirmed
in each domain's `queries.py` as listed above.

**Recommended correction.** Make `knowledge_time` default to `as_of`, not to `now()`, whenever
`as_of` is explicitly supplied and `knowledge_time` is not (`k = a if (a is not None and k is None)
else (now if k is None else min(k, now))`, or simply require `knowledge_time` to be supplied whenever
`as_of` is in the past, erroring otherwise) — matching the discipline every internal call site
already follows by convention. Consider centralizing `_times()` into one shared helper
(`cfi.api.params`) instead of ten independent copies, since a shared correction here fixes all ten
routes as one edit and prevents future skew between them (they are already textually identical,
which is itself a sign this should not be ten separate functions).

**Test required.** An integration test per affected domain (or one shared parametrized test) that:
(a) stores an initial value for date D with `available_at`/`ingested_at` at D; (b) stores a revised
value for the same `event_time`/subject at a later `revision`, with `ingested_at` well after D;
(c) calls the API/service with `as_of=D` and `knowledge_time` **omitted**; (d) asserts the revised
value is NOT returned (only the original, D-dated revision is) — this test should currently FAIL,
proving the gap, and should pass once the default is corrected.

---

### 2. FRED macro series carry no point-in-time vintage — always the latest revision

**Problem.** The FRED provider adapter leaves `realtime_start`/`realtime_end` at their API defaults,
so every value ingested is FRED's **current, most-revised** figure for a given date, never the value
as it was first published:

```python
# backend/src/cfi/providers/fred.py:23-27
- ``realtime_start`` / ``realtime_end`` (default: today) select which *vintage* of each value to
  return; left at their defaults here, so every value returned is FRED's **current** (most
  revised) figure for that date, not the value as first published — see
  ``cfi.macro.universe``'s "Point-in-time integrity" note for why this is an accepted limitation,
  not a bug;
```
This is explicitly disclosed as an "accepted limitation," and the module's own `notes` field repeats
it (`fred.py:82-84`). It is not hidden. But disclosure does not change what the data actually does:
CPI, PCE, unemployment, and the balance-sheet/TGA/reverse-repo series feeding
`macro_environment_score`'s `net_liquidity_trend` component (weight 0.15, per the retail/derivatives
red-team pass) are all subject to routine revision (initial vs. final GDP/CPI prints, seasonal
re-benchmarking of the Fed's own balance-sheet series, etc.), and every one of them is stored and
served as if the final, revised number were knowable on the original date.

**Why it matters.** Any historical computation that uses macro data — the Macro Environment Score
directly, and, through `cfi.similarity.snapshot.gather_snapshot`/`cfi.regime.snapshot`, every
regime classification, similarity analogue, and (were a `DomainScoreSignal` on a macro feature ever
backtested) the Backtesting Engine itself — sees a macro reading that could not actually have been
known at that historical date. This is precisely R4's "future revisions leaking into historical
signals," and it is the one place in the platform where the point-in-time architecture's own
`available_at`/`ingested_at` machinery cannot rescue the result, because FRED's API itself does not
tell this system when a given number was first published versus later revised — the system would
need to *track* vintages (FRED's own "ALFRED" real-time dataset) to close this gap, which is a
larger, disclosed, deferred piece of work (ADR-0054), not a quick fix.

**Evidence.** `backend/src/cfi/providers/fred.py:23-27,78-85`; `backend/src/cfi/macro/universe.py`'s
"Point-in-time integrity" docstring note (referenced from fred.py, not independently re-quoted here);
DECISIONS.md ADR-0054 ("conservative documented release-schedule delays for revised series, not full
ALFRED vintage tracking").

**Recommended correction.** Either (a) integrate FRED's ALFRED vintage endpoints
(`realtime_start`/`realtime_end` per-observation, which FRED does support) so `available_at` reflects
the actual first-publication date of each vintage, not just the release-schedule delay estimate
currently used — this is the complete fix; or (b), as a cheaper interim step, add an explicit,
loud caveat to every score/output that consumes macro data (`macro_environment_score`, and anything
built on top of it in regime/similarity/backtest) stating that macro inputs reflect today's revised
values, not the historical vintage — upgrading this from a docstring-only disclosure to a
runtime-visible `quality_note` or `evidence` flag on the affected outputs.

**Test required.** Once vintage tracking exists: seed two vintages of the same FRED observation
(an initial release and a later revision with a different `realtime_start`), query at an `as_of`
between the two, and assert the ORIGINAL vintage is returned. Until then, a documentation/regression
test that asserts `macro_environment_score`'s response schema exposes a machine-readable
vintage-risk flag (once (b) above is implemented) so downstream consumers can programmatically
discount or exclude this component from historical backtests.

---

### 3. Stop-loss/take-profit fills skip slippage and ignore opening gaps

**Problem.** In the backtesting engine's intrabar stop check, both the stop-loss and take-profit
fill at the *exact* theoretical stop level, with no slippage applied and no check for whether the
bar's own open already gapped through that level:

```python
# backend/src/cfi/backtest/engine.py:232-251
if strategy.stops.stop_loss_pct is not None:
    sl = position.entry_price * (1 - strategy.stops.stop_loss_pct / 100)
    if today.low <= sl:
        stop_price, reason = sl, "stop_loss"
...
if stop_price is not None:
    equity += position.size_base * (stop_price - position.last_mark_price)
    fee = cost_module.apply_fee(position.size_base * stop_price, params)
    equity -= fee
    trades.append(_close_trade(position, stop_price, fee, reason, today.time))
```
Compare this to the two other exit paths in the same file, both of which DO apply slippage:
```python
# line 223 (signal/time exit, at today's open)
exit_price = cost_module.slipped_price(today.open, direction="sell", params=params)
# line 302 (forced end-of-backtest close)
exit_price = cost_module.slipped_price(final.close, direction="sell", params=params)
```
No test exercises this path at all — neither `test_backtest_engine.py` nor any unit test asserts a
stop-loss or take-profit fires, despite `EXAMPLE_STRATEGIES["sma_trend_follow_v1"]` defining both
(`strategy.py:96,112`).

**Why it matters.** This asymmetrically flatters exactly the trades most likely to be executed under
market stress — a stop firing during a fast, thin-liquidity move is the single scenario where real
slippage is worst, and (if the bar gapped through the stop level, which is routine in 24/7 crypto
markets, e.g. a weekend gap or a flash crash) a real fill would be materially worse than the stop
price itself. Modeling every stop as a costless, no-slippage, exact-level fill systematically
overstates the performance of any strategy that relies on stops for risk control — which is most of
them, since `StopConditions` is a first-class field on every `StrategyDefinition`.

**Severity: HIGH.** This is not a hypothetical edge case; it is the default behavior of the one
code path specifically designed to protect capital, and it is completely untested.

**Recommended correction.** (a) Apply `cost_module.slipped_price(stop_price, direction="sell",
params=params)` to both the stop-loss and take-profit fill, matching every other exit path. (b) Check
`today.open` against the stop level before assuming an intrabar fill at the exact level: if
`today.open` has already gapped through `sl` (i.e. `today.open <= sl` for a stop-loss, or
`today.open >= tp` for a take-profit), fill at the (slipped) open instead of the theoretical stop
level, since that is the worst price a real order would have achieved.

**Test required.** A synthetic-bar unit/integration test with: (1) a bar whose low pierces the
stop-loss level but whose open is still above it — assert the fill price equals the slipped stop
level, not the raw stop level; (2) a bar whose OPEN already gaps below the stop-loss level — assert
the fill price equals the slipped open, which should be worse (lower) than the stop level; (3) the
symmetric two cases for take-profit.

---

### 4. Regime/Market-Structure classification has no hysteresis — hard-cutoff flip-flopping

**Problem.** Every threshold in the regime classifier and the market-structure score is a strict
step function with no dead-zone or persistence rule:

```python
# backend/src/cfi/regime/classifier.py:109-118 (_evaluate_condition) — strict gte/lte/between
# backend/src/cfi/regime/parameters.py:98 — e.g. whale_score >= 15
# backend/src/cfi/regime/classifier.py:186-188 — classify()'s own is_ambiguous = margin < tie_margin (0.08)
#                                                  and top_qualifies = top.confidence >= min_confidence_assign (0.55)
```
A metric oscillating at, say, 14.99 ↔ 15.01, or a regime-confidence margin oscillating at
0.079 ↔ 0.081, flips a condition — and potentially which regime wins — with no smoothing across
time. Each `as_of` is classified from scratch with no memory of the prior day's label
(`classifier.py`, `history.py`, `service.py` — none carry state between calls). The Market Structure
Score's own bands (`score_parameters.py:61-67`) have the identical property (verified in the
separate agent pass on that module).

**Why it matters.** "Regime instability" and "unstable thresholds" are named directly in this
review's own scope. A regime label (or a market-structure band label) that flips daily around a
boundary is worse than useless for a human decision-maker trying to read a *stable* market state —
it manufactures the appearance of a regime change where the underlying score barely moved, which is
exactly the kind of spurious signal the platform's stated purpose ("detect accumulation/distribution,
detect... changes") is supposed to avoid producing. It also directly threatens the reliability of
`cfi.regime.history`'s "regime duration" and "historical examples" features, which depend on
consecutive same-label days.

**Evidence.** `classifier.py:109-118,149,186-188`; `parameters.py:98,125,420-484` (7 regime
definitions, hard-banded); `market_structure/score_parameters.py:61-67`; ADR-0057 (confirms
thresholds are "chosen by design," never claims stability was tested).

**Recommended correction.** Add either (a) a dead-zone/hysteresis band around each threshold (e.g.
"enter Accumulation at score >= 15, only exit back to Neutral at score < 10," an asymmetric
enter/exit band), or (b) a minimum-persistence rule (a regime only changes label after N consecutive
days of a different classification), or (c) at minimum, surface each condition's *distance* to its
threshold (not just true/false) so a consumer can distinguish "barely qualifies" from "solidly
qualifies" even without changing the classification logic itself.

**Test required.** A synthetic time series that oscillates a single input metric across a threshold
by a small, realistic amount (e.g. ±2% day to day around the boundary) and asserts the number of
label changes over N days stays below some sanity bound once hysteresis is added — currently this
test would show the label changing on nearly every oscillation, which is itself the proof of the bug
before any fix, and should be written first as a red (failing-expectation) baseline.

---

### 5. Cost model applies flat slippage regardless of trade size vs. liquidity cap

**Problem.** `slipped_price()` applies a constant proportional adjustment independent of how large
the trade is relative to the liquidity constraint the same module enforces:

```python
# backend/src/cfi/backtest/costs.py:49-56
def slipped_price(price: Decimal, *, direction: str, params: CostParameterSet) -> Decimal:
    adjustment = price * params.slippage_bps / Decimal(10_000)
    ...
```
A trade sized at 0.1% of the liquidity cap and a trade sized right at the 5%-of-volume cap
(`max_participation_pct`, `costs.py:29`) incur the identical 5 bps of slippage.

**Why it matters.** Real market impact is convex in participation rate — the larger a trade is
relative to available liquidity, the worse the realized price, non-linearly. Modeling slippage as
flat understates costs precisely for the largest, most market-moving trades this engine itself
permits (anything up to the participation cap), which biases backtested performance upward for
strategies that size aggressively. The docstring already flags the *values* as "not fitted," but this
is a *structural* gap (missing convexity), not a calibration one.

**Evidence.** `costs.py:25-31,44-56,59-67` (the whole cost module, read in full — no
size-dependent term exists anywhere in it).

**Recommended correction.** Make `slipped_price` (or a new function) take the trade's notional as a
fraction of the day's liquidity cap and scale the slippage accordingly (even a simple linear or
square-root-of-participation term, e.g. `slippage_bps * (1 + k * participation_fraction)`, would be
a meaningful improvement over a flat constant) — versioned the same way `CostParameterSet` already
is, so this remains a documented, adjustable assumption rather than a hidden constant.

**Test required.** Two backtests differing only in position size (e.g. `fixed_fraction=0.1` vs.
`fixed_fraction=0.9` of equity, same strategy/window), asserting the larger-sized run pays a strictly
higher effective slippage rate (realized fill price vs. quoted price, as a percentage) than the
smaller one — this test should currently FAIL (both would show identical bps), proving the gap.

---

### 6. Altcoin relative-strength (20% of Market Structure Score) has no minimum-asset-count floor

**Problem.** The altcoin relative-strength component averages whichever of ETH/SOL/XRP happen to
have sufficient history, and is only marked unavailable when NONE do:

```python
# backend/src/cfi/market_structure/score.py:223-238 (per the domain red-team pass)
# averages "whichever of the supplied altcoin readings are available"; "unavailable" only when none are
```
`weight_altcoin_relative_strength = 0.20` (`score_parameters.py:53`) is applied to this average
regardless of whether it was built from three assets or one, and `relative_strength()`
(`metrics.py:458-488`) applies no liquidity/quality filter of its own.

**Why it matters.** If two of the three altcoins temporarily lack sufficient history (a data gap, a
new venue integration not yet backfilled, etc.), a full fifth of the headline Market Structure Score
becomes driven entirely by whichever single asset remains — with no down-weighting for the reduced
sample breadth and no indication to the reader that "altcoin relative strength" today means "one
coin's relative strength."

**Evidence.** `market_structure/score.py:223-238`; `market_structure/score_parameters.py:53`;
`market_structure/metrics.py:458-488` (all verified in the market-structure/regime/divergence red-team
pass).

**Recommended correction.** Either (a) require a minimum count (e.g. at least 2 of 3 altcoins) before
reporting this component as `"ok"`, falling back to `"insufficient_data"` otherwise (matching the
platform's own `MIN_COVERAGE`-style convention used elsewhere, e.g. `whales/score.py:181-187`,
`institutional/score.py:213-219`); or (b) down-weight the component's contribution proportionally to
how many of the three assets are actually available.

**Test required.** A synthetic case with only 1 of 3 altcoins having sufficient history: assert the
component is reported `"insufficient_data"` (or its weight is reduced) rather than `"ok"` with a
full 0.20 weight from a single asset.

---

### 7. Retail Speculation Score reuses the same series as Derivatives Health Score

**Problem.** `retail_speculation_score` gives combined weight 0.80 (0.40 + 0.40) to
`funding_rate` and `long_short_account_ratio`, both sourced from Binance derivatives data
(`retail/universe.py:9-24`, `retail/score.py`) — the exact same `deriv.funding_rate` series that
also drives 0.25 of the Derivatives Health Score (`derivatives/score.py:189-210`). The code is
explicit that "neither field is retail-exclusive" (`retail/universe.py:14-18`) and stamps every
value `measurement_class="proxy"` (`retail/metrics.py:7-12,25-26`) — this is disclosed, not hidden.
Binance's long/short ratio is an **account-count** ratio, not position-size-weighted, so it is
biased toward many small accounts but is not filtered by account type at all: an institutional
prop desk's account counts exactly the same as a single retail account in this ratio.

**Why it matters.** Two headline scores that are supposed to represent different participant classes
(retail speculation vs. overall derivatives-market stress) partially derive from the identical
underlying number. A capital-flow-divergence narrative built on "retail is over-leveraged while
derivatives health looks fine" (or vice versa) could be comparing a metric against a rescaled
version of itself rather than two independent signals — a false-correlation risk baked into the
platform's own cross-domain comparison feature (the Divergence Engine's "10 standardized
comparisons").

**Evidence.** `retail/universe.py:9-24`, `retail/score.py` (weight 0.40 each per
DATA_DICTIONARY.md:634-636), `retail/metrics.py:7-12,25-26`, `derivatives/score.py:189-210` (weight
0.25).

**Recommended correction.** Either find a genuinely retail-exclusive proxy (e.g. a
position-size-weighted or account-tier-segmented long/short ratio, if any provider publishes one),
or, short of that, add an explicit "shares an input with Derivatives Health Score" cross-reference
note to both scores' API responses and to any Divergence Engine comparison that pairs them, so a
consumer reading a "retail vs. derivatives" divergence knows the two are not fully independent.

**Test required.** A test on the Divergence Engine's comparison catalog asserting that any comparison
pairing Retail Speculation against Derivatives Health surfaces a disclosed shared-input note (once
added) — or, absent a code fix, a documentation-only follow-up (flagged here since this finding's
correction may be primarily documentation/labeling rather than code).

---

### 8. Liquidity Score measures stablecoin supply growth, not liquidity or peg stability

**Problem.** The Liquidity Score is built entirely from stablecoin supply-growth figures
(`usdt_growth_7d`, `usdc_growth_7d`, `total_growth_7d`, `growth_acceleration` —
`liquidity/score.py:7-13`), with no stablecoin price or peg-stability signal tracked anywhere in the
module (confirmed: no "peg"/"depeg" reference anywhere in `backend/src/cfi/liquidity/`).

**Why it matters.** A large stablecoin mint can occur for reasons that have nothing to do with
tradeable market liquidity — reserve backstopping during a depeg event, an issuer's internal
treasury operation, a mint later burned without ever reaching an exchange. The current score would
read any of these as "strong liquidity expansion," which is precisely the "false correlation between
a proxy and what it's assumed to measure" failure mode this review was asked to find. This is a
more severe instance of the same proxy-validity risk as finding #7, but here there is no disclosure
at all — unlike the retail-score module (which stamps `measurement_class="proxy"`), nothing in
`liquidity/score.py` or DATA_DICTIONARY.md's Liquidity Score entry caveats that supply growth is not
the same thing as usable market depth.

**Evidence.** `liquidity/score.py:7-13`; DATA_DICTIONARY.md:540-542; absence confirmed by search
(no peg/depeg handling anywhere under `backend/src/cfi/liquidity/`).

**Recommended correction.** At minimum, add an explicit caveat (matching the retail module's own
`measurement_class="proxy"` convention) to the Liquidity Score's definition and API response,
stating plainly that it measures stablecoin *supply* growth, not price stability or realized market
depth. If a stablecoin price-tracking data source is available (most major stablecoins publish spot
prices on the same venues already integrated), consider adding a peg-deviation check as an input or
at least a flag that suppresses/discounts the score during a detected depeg event.

**Test required.** A test asserting the Liquidity Score's API response or catalog entry exposes a
machine-readable caveat/measurement-class field (once added) distinguishing "supply growth" from
"liquidity" in the same way the retail score already does.

---

### 9. Derivatives liquidation-stress component is single-venue (OKX only)

**Problem.** The liquidation component of Derivatives Health Score (weight 0.20,
`derivatives/score.py`) uses OKX exclusively for both the liquidation totals and the open-interest
denominator (`derivatives/metrics.py:523-577`, `derivatives/score.py:105,273-300`) — "one venue
only," per the component's own definition text.

**Why it matters.** A single venue's outage, API issue, or venue-specific liquidation cascade (which
can be driven by that venue's own idiosyncratic leverage/liquidation-engine settings, not the broader
market) fully determines a fifth of the Derivatives Health Score, with no cross-venue smoothing or
outlier robustness anywhere in `compute()` (`score.py:325-374` is a straight weighted average with no
winsorizing). This contrasts with the funding-rate component of the same score, which correctly
OI-weights across every venue with available data (`derivatives/metrics.py:350-382`) — the platform
clearly knows how to do multi-venue aggregation robustly elsewhere; this component just doesn't.

**Evidence.** `derivatives/metrics.py:350-382` (correct multi-venue funding aggregation, for
contrast) vs. `derivatives/metrics.py:523-577` and `derivatives/score.py:105,273-300,325-374`
(single-venue liquidations, unweighted final aggregation).

**Recommended correction.** Extend liquidation tracking to every venue this platform already ingests
derivatives data from (Binance, Bybit, OKX, Deribit, per the provider list), and OI-weight the
liquidation-stress reading the same way funding already is — or, if multi-venue liquidation data is
not readily available from every provider, explicitly down-weight or flag this component's
confidence when only one venue is contributing, rather than treating it as equally reliable as the
multi-venue components it sits alongside in the same weighted average.

**Test required.** Feed the score computation two scenarios with identical aggregate liquidation
volume: (a) spread proportionally across 3 venues, (b) concentrated entirely in 1 venue. Assert the
score/confidence for scenario (b) is flagged or discounted relative to (a) once the fix is in —
currently both would score identically since only OKX is read at all.

---

### 10. Similarity candidate sampling is locked to one weekday per query

**Problem.** `candidate_dates()` samples backward from the query's own `as_of` in fixed
`step_days=7` increments (`similarity/search.py:32-43`), so every candidate in a single query falls
on the same day-of-week as `as_of` itself.

**Why it matters.** A short, sharp historical episode (a 2-3 day de-leveraging spike, a flash crash)
that happens not to land on the sampling grid's specific weekday is structurally invisible to the
search, while a similar-magnitude episode that happens to align with the grid is captured — a
selection-bias artifact distinct from (and not covered by) the cost/precision trade-off ADR-0058
already documents. This is not merely a "sparser sampling" concern (which IS documented); it is a
specific, undocumented **systematic exclusion pattern** correlated with calendar alignment rather
than event significance.

**Evidence.** `similarity/search.py:32-43`; DECISIONS.md ADR-0058 (documents the weekly-vs-daily
cost/precision trade-off but not the fixed-weekday artifact specifically). Note: this review's
similarity pass found the core similarity SCORE, normalization, and forward-return/drawdown gating
to be genuinely look-ahead-free (see negative findings below) — this sampling-grid issue is the one
real gap found in an otherwise carefully-built module.

**Recommended correction.** Either offset the sampling grid's phase per query (e.g. anchor to a fixed
calendar reference rather than `as_of` itself, so different queries don't all share one weekday), or
sample candidates on a rotating/staggered schedule across multiple weekday phases and merge/de-duplicate
the results, preserving the same total number of domain-service calls per query if cost parity
matters.

**Test required.** Construct a synthetic short spike event on a date that falls on a different
weekday than the current sampling grid's phase; assert it is NOT found as a candidate today, and IS
found once the phase-offset or multi-phase fix is applied.

---

### 11. Backtest position sizing uses day D's close; the order fills at D+1's open

**Problem.** `_sized_notional()` is called with `price=today.close` (`engine.py:291`) while deciding
tomorrow's order, and the resulting **base-asset quantity** (`notional / today.close`, `engine.py:297`)
is fixed at that point — but the order actually executes next iteration at
`slipped_price(today.open, ...)` of the *following* bar (`engine.py:209`), a different day's price.

**Why it matters.** If BTC moves significantly overnight (routine in a 24/7 market), the realized
notional, leverage, and exposure at the moment of execution can differ materially from what was
targeted when `risk_limits`/`liquidity_cap` were checked against the stale close price. This is a
known, common convention in event-driven backtesting (decide from the last known price, execute at
the next tradeable price) and is disclosed as the deliberate "execution lag" in the module's own
docstring — but the specific consequence (a fixed BTC quantity, not a fixed target notional, crossing
the gap) is not discussed or tested anywhere, and means the leverage/exposure caps are only
approximately respected at execution, not exactly.

**Evidence.** `engine.py:265-297` (signal decided and sized from `bars_through_today`/`today.close`)
vs. `engine.py:207-221` (execution at the NEXT bar's slipped open).

**Recommended correction.** Either (a) accept this as a documented modeling approximation (it is
defensible, and matches standard practice), explicitly noting in `Assumptions` that sizing is
computed against the decision day's close while execution occurs at the next day's open, so realized
exposure can deviate from the targeted exposure by the overnight gap; or (b), for a tighter model,
re-check (and if necessary re-cap) the position size against the actual execution-day open price at
the moment of fill, before finalizing `size_base`.

**Test required.** A synthetic case with a large, known overnight gap between a decision day's close
and the next day's open; assert (for option (a)) that `Assumptions` surfaces this as a named,
quantifiable risk, or (for option (b)) that the realized notional after execution never exceeds the
risk limit computed against the actual fill price, even when the gap is large enough that sizing
against the close alone would have breached it.

---

### 12. Backtest test suite verifies status/counts, not exact prices/fees/Sharpe values

**Problem.** Across `test_backtest_engine.py` (integration) and `test_backtest_metrics.py` (unit):
- Every integration assertion is on `status`, `num_trades >= 1`, `len(equity_curve) > 0`, or
  equality-between-two-runs (reproducibility/leakage) — none assert an exact trade entry/exit price,
  fee amount, or P&L value for the fully deterministic synthetic price path, despite it being
  hand-computable.
- Sharpe and Sortino are only ever tested for `is None` / presence (`test_backtest_metrics.py`) —
  no test checks either value against an independently, by-hand-computed expected number.
- No test in either suite exercises `strategy.stops` (stop-loss/take-profit) at all, despite
  `sma_trend_follow_v1` defining both.

**Why it matters.** A systematic pricing bug — including finding #3 above, which the existing suite
did not catch — would pass every currently-existing test. Status/count-level assertions prove the
engine *runs* and produces *some* trades; they do not prove the trades are *priced correctly*. Given
this is the platform's core research/validation tool, silent numeric errors here are the highest-cost
kind of bug to leave undetected.

**Evidence.** Direct reading of `backend/tests/integration/test_backtest_engine.py` and
`backend/tests/unit/test_backtest_metrics.py` (all assertions inventoried during this review).

**Recommended correction.** Add at least one fully hand-verified test: a short, small synthetic bar
sequence (a handful of days) with a strategy and cost parameters simple enough to compute the
expected entry price, fee, exit price, fee, P&L, and resulting Sharpe/Sortino by hand (or with an
independent script, not the engine itself), and assert the engine's output matches those exact
numbers to the Decimal. Add a second test that specifically triggers a stop-loss and a third that
triggers a take-profit, each asserting the exact fill price (which will also serve as the regression
test for finding #3's fix).

**Test required.** As described above — this finding's own correction *is* the required test.

---

### 13. Large-transfer size classification uses the latest balance snapshot, not the transfer-date balance

**Problem.** Historical large-transfer classification looks up each transfer's sender/recipient
address against the *latest* top-holder balance snapshot, not a snapshot as of the transfer's own
date:

```python
# backend/src/cfi/whales/service.py:626-643 (per the institutional/whale red-team pass)
latest_balances = snapshots[-1].balances  # used for every row in the start..end window
```
This is disclosed in DATA_DICTIONARY.md ("classified at read time … labels, else size from the
latest snapshot"), and — importantly — it can only ever produce the `UNKNOWN_LARGE` /
`UNLABELLED` classification, never "institution" or "whale" as a hard label (R5's evidence-hierarchy
guardrails, verified independently in this review, block that entirely). So this is bounded, not a
labeling-integrity violation.

**Why it matters.** An address that only accumulated a large balance *after* a given historical
transfer can be retroactively classified as an "unknown large holder" for that earlier transfer (or
the reverse: an address that has since drawn down below the threshold loses a classification it
arguably deserved at the time). This is a mild, size-only form of look-ahead — the transfer's
classification can change depending on when you ask, purely due to *today's* balance, not the
balance that existed when the transfer happened.

**Evidence.** `whales/service.py:626-643`; DATA_DICTIONARY.md's large-transfer classification note
(confirmed disclosed, not hidden).

**Severity: LOW** — bounded to a size-inference convenience label, never an evidenced institution/
whale claim, and already disclosed. Included because it is a genuine, verifiable instance of "use of
future information" even though its blast radius is small.

**Recommended correction.** If per-date historical balance snapshots exist (or can be
reconstructed from the same on-chain data already ingested), classify each transfer against the
balance snapshot nearest to its own `event_time`, not the latest one.

**Test required.** A synthetic case: address X has a small balance at transfer time T1, later grows
past the large-holder threshold by T2 (today). Assert a query for T1's transfers classifies X based
on its balance *at* T1, not its current (T2) balance.

---

### 14. Silent warmup shortfall: no flag if fewer than `WARMUP_DAYS` bars exist before `start`

**Problem.** `WARMUP_DAYS=220` (`backtest/universe.py:9`) is used only to widen the bar-fetch window
(`_fetch_bars`, `engine.py:84`: `start - timedelta(days=WARMUP_DAYS)`) — there is no check anywhere
that the fetch actually returned that many bars before `start_idx`. If real historical data has a
gap shortening the available pre-`start` warmup window, SMA200/RSI silently compute over fewer bars
than the strategy assumes, with no warning surfaced (unlike the trailing-volume case in
`_trailing_avg_volume`, which correctly returns `None` and a warning when insufficient — `engine.py:
97-102,133-136`).

**Why it matters.** A strategy relying on an SMA(200) crossover could unknowingly be evaluated
against an SMA computed from, say, 90 days of history because of an upstream data gap, producing a
materially different (and silently wrong) signal reading with no indication in `warnings` that
anything was short.

**Evidence.** `engine.py:74-86` (`_fetch_bars`, no post-fetch bar-count check against
`WARMUP_DAYS`); contrast with `engine.py:96-102,130-136` (`_trailing_avg_volume`/liquidity cap,
which DOES warn on insufficient data).

**Recommended correction.** After fetching, check how many bars exist before `start_idx` and, if
fewer than `WARMUP_DAYS` (or than the specific signal's own required lookback, e.g. 200 for SMA200),
append a warning to `BacktestResult.warnings` naming the shortfall — mirroring the existing
liquidity-warning convention exactly.

**Test required.** Seed a synthetic bar series with fewer than `WARMUP_DAYS` days of history before
`start`; assert `warnings` contains an entry describing the shortfall once implemented (currently it
would not).

---

### 15. Fixed 4-asset universe with no first-class "delisted/discontinued" state

**Problem.** `ASSET_SYMBOLS` (BTC/ETH/SOL/XRP, `market/universe.py:22-28`) and the 5-venue `VENUES`
dict (`market/sources.py:39-90`) are static, hardcoded tuples with no representation for "this asset
was delisted from this venue" or "this venue permanently stopped publishing" as a state distinct from
"temporarily stale." `jobs.py:79-84` iterates the fixed asset list unconditionally.

**Why it matters.** This is low-severity **today**, because the platform only tracks a small, still-
live set of major assets/venues — there is no current instance of survivorship bias actually
occurring. But it means the data model has no mechanism to prevent it once the tracked universe
grows: any future cross-sectional history feature (e.g. "which of the top-20 2021 alts are still
relevant") would need this distinction built in from the start, and retrofitting it later is harder
than designing for it now.

**Evidence.** `market/universe.py:22-28`; `market/sources.py:39-90`; `market/jobs.py:79-84`; the
absence of any "delisted"/"discontinued" enum value anywhere in `cfi.domain.enums` (checked during
the market-data pass).

**Recommended correction.** No immediate code change needed given the current single-benchmark,
4-asset scope (this mirrors the Backtesting Engine's own documented long-only/single-asset v1 scope
decision, ADR-0059). When/if a multi-asset universe is added (already flagged in TODO.md as future
work), add an explicit `valid_from`/`valid_to`-style membership record per asset-venue pair, mirroring
the pattern `ref.entity_label` already uses successfully for whale/institution labels.

**Test required.** Deferred until a multi-asset universe exists — not actionable against the current
single-benchmark scope.

---

## Checked and found correct (negative findings)

These were investigated with the same rigor as the findings above and are recorded because a
red-team review is only useful if its silence about an area is also evidence, not just an omission.

- **C1. Every internal domain-composition call path passes `knowledge_time=as_of` explicitly.**
  `cfi.similarity.snapshot.gather_snapshot`, `cfi.regime.snapshot`, and `cfi.divergence.adapters`'s
  own composition methods all pass an explicit `knowledge_time` equal to their own `as_of` (never
  relying on a route-level default) — this is why finding #1 has not yet manifested in the regime,
  similarity, or backtesting engines' actual outputs, even though the underlying route-level default
  is unsafe for any *other* caller.
- **C2. `AvailabilityRule`/`available_at` computation is correct.** `available_at = event_time (bar
  close) + period + delay`, with a hard `NotYetFinalError` guard against storing an unfinished bar
  as final (`domain/datasets.py:102-119`). No place was found using a bar's *open* time as if it were
  its availability time.
- **C3. Missing data is consistently a first-class state, never a fabricated zero or silent
  interpolation**, across market data, market structure, institutional, whale, retail, derivatives,
  liquidity, and macro (`quality_status="missing"`, `MIN_COVERAGE`/`min_available_weight` gates
  excluding rather than zero-filling incomplete components, verified independently in every domain
  pass).
- **C4. R5's "large ≠ institutional" rule is enforced redundantly at three layers** (application code
  raising `LabelError`, an import-time rejection of conflicting entity definitions, and a database
  CHECK constraint) — no code path can store or emit "institution"/"whale" as a category derived
  purely from transfer/balance size.
- **C5. The evidence hierarchy (evidence_class/confidence/valid_from/valid_to) is fully modeled** for
  whale/institutional labels, with documented precedence rules and disagreements surfaced as
  conflicts rather than silently resolved.
- **C6. No look-ahead bias in score normalization anywhere outside macro's FRED-vintage gap (finding
  #2).** Every score (institutional, whale, derivatives health, liquidity, retail, macro
  environment, market structure, similarity's 9 features) uses fixed, documented reference
  scales/clamp bounds — never a percentile/z-score computed against a historical window that could
  include future-relative-to-`as_of` data. (Retail's Activity Score is the one place percentile-rank
  normalization is used at all, and it is correctly restricted to `start <= p.time < as_of`.)
- **C7. Regime "duration"/"historical examples" (`cfi.regime.history`) contain no look-ahead** — both
  walk strictly backward from `as_of`, never using information from after it to determine where a
  regime run "truly" started.
- **C8. The Divergence Engine does not assert false causation.** Every "possible rotation" edge is
  explicitly hedged ("consistent with, but not proof of," `evidence_class="inferred"` always), and
  the evidence-generation code (`cfi.divergence.metrics.evidence`) is genuinely deterministic —
  template strings driven by already-computed numeric thresholds, no language model invoked, no
  hidden randomness.
- **C9. The Historical Similarity Engine's core score, its normalization, and its forward-return/
  max-drawdown knowability gating are all genuinely look-ahead-free**, verified at two independent
  layers (an explicit `not_yet_known` status check AND a database-level `available_at <= as_of`
  guard on the underlying bar fetch) — the only real gap found in this engine is the sampling-grid
  artifact (finding #10).
- **C10. No provider-blending/silent-substitution risk in market data.** Each venue is its own
  series; conflicting values across providers are stored as separate rows, never averaged or
  silently preferred, matching R3's "never silently substitute one provider for another."

---

## Priority order for a follow-up correction pass

If corrections are undertaken in a later phase, the highest-leverage order (impact × how many
downstream outputs each finding touches) is: **#1 → #3 → #2 → #4 → #12 → #5/#6/#9 → #7/#8/#9(dup
removed)/#11/#13/#14/#15.** #1 is listed first because it is a one-line-class fix (correcting one
shared default) that closes the platform's single widest look-ahead-bias exposure; #3 and #12 are
listed early because they are specific to the just-built, not-yet-relied-upon Backtesting Engine and
are cheap to fix and test before that engine is used for any real strategy evaluation.

No code was modified as part of this review, per instruction. Stopping here.
