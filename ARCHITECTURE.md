# ARCHITECTURE.md

**Status:** Draft v0.1 (Phase 0). Principles in §1–§10 are the intended contract.
Technology choices in §11 are **proposed** and must be confirmed in Phase 1/2 (see `DECISIONS.md`).
Nothing described here is implemented yet.

---

## 1. Purpose and design principles

The platform answers: **Where is money moving, who is moving it, and how is that behavior changing?**

Design principles:

1. **Evidence before interpretation.** Data flows one way through strict layers (§2).
2. **The database and statistical engine are the source of truth.** Claude interprets; it never supplies data.
3. **Point-in-time correctness.** Every value knows *when it happened* and *when we could have known it*.
4. **Missing data is visible.** Gaps, staleness, and revisions are recorded and shown, never hidden.
5. **Every number is traceable.** Any value on screen can be followed back to raw provider payloads and the code version that transformed it.
6. **No single-provider dependency** where an abstraction reasonably prevents it.
7. **Confidence, not certainty.** Signals, regimes, and interpretations carry confidence and caveats.
8. **Simple first.** One database, one language for the core, batch before streaming. Add complexity only when a measured need appears.

---

## 2. The layer model

```
┌──────────────────────────────────────────────────────────────────────────┐
│ L0  RAW              Provider payloads exactly as received (immutable)   │
├──────────────────────────────────────────────────────────────────────────┤
│ L1  OBSERVED DATA    Normalised observations, canonical units & symbols  │
├──────────────────────────────────────────────────────────────────────────┤
│ L2  METRICS          Deterministic calculations over observations        │
├──────────────────────────────────────────────────────────────────────────┤
│ L3  SIGNALS          Statistical evaluation of metrics vs. history        │
├──────────────────────────────────────────────────────────────────────────┤
│ L4  REGIME           Classification of market state, with confidence      │
├──────────────────────────────────────────────────────────────────────────┤
│ L5  AI INTERPRETATION  Claude's explanation of L1–L4 (labelled as such)   │
├──────────────────────────────────────────────────────────────────────────┤
│ L6  USER DECISION    The human's decision, rationale, and outcome         │
└──────────────────────────────────────────────────────────────────────────┘
```

### Layer contract

| Layer | Written by | Reads from | Mutability | Must record |
|---|---|---|---|---|
| L0 Raw | Ingestion adapters | External providers | Append-only, never edited | provider, endpoint, request params, received_at, payload hash |
| L1 Observed | Normalisers | L0 | Append-only; revisions are new rows | event_time, available_at, ingested_at, source, quality status, raw reference |
| L2 Metrics | Metric engine | L1 (and other L2) | Recomputable; versioned by metric version | metric_id + version, inputs, as_of, quality status |
| L3 Signals | Signal engine | L2 | Recomputable; versioned | method, lookback window, statistic, threshold, confidence |
| L4 Regime | Regime engine | L3 (+ L2) | Recomputable; versioned | regime label, component signals, confidence, model version |
| L5 AI | Claude Analyst | L1–L4 **snapshot only** | Append-only | model ID, prompt version, input snapshot ID, output, validation result |
| L6 Decision | User | Everything | Append-only journal | decision, rationale, snapshot viewed, timestamp, later outcome |

**Rules**

- A layer never writes into a layer to its left.
- L5 never writes to L1–L4. If Claude's output contains a number, it must match a value in the input snapshot or the output is rejected (§8).
- L2–L4 are **derived** and can be rebuilt from L1 for any `as_of` time. If they cannot be rebuilt, that is a bug.
- Supporting analyses (anomalies, similarity, rotation, backtests) are L3/L4-level consumers: they read metrics/signals and write their own versioned results.
- **Hypothesis** is a sixth evidence category (CLAUDE.md R2): an untested proposed explanation. It is not a data layer; it is a label on L5 output (AI-proposed) or L6 entries (user-proposed), and is always stored and displayed separately from interpretation.

---

## 3. Component overview

```
 External providers (exchanges, on-chain, ETF, options, macro, sentiment)
        │
        ▼
 ┌───────────────────┐   ┌──────────────────┐
 │ Provider adapters │──▶│ Raw store (L0)   │
 │ (one per source)  │   └──────────────────┘
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐   ┌──────────────────┐
 │ Normalisers +     │──▶│ Observation      │
 │ quality checks    │   │ store (L1)       │
 └───────────────────┘   └────────┬─────────┘
                                  ▼
                      ┌─────────────────────┐
                      │ Metric engine (L2)  │
                      └──────────┬──────────┘
                                 ▼
                      ┌─────────────────────┐
                      │ Signal engine (L3)  │── divergence · anomaly · rotation
                      └──────────┬──────────┘
                                 ▼
                      ┌─────────────────────┐
                      │ Regime engine (L4)  │── historical similarity · backtesting
                      └──────────┬──────────┘
                                 ▼
                      ┌─────────────────────┐
                      │ Snapshot builder    │  (frozen, point-in-time evidence pack)
                      └──────────┬──────────┘
                                 ▼
                      ┌─────────────────────┐
                      │ Claude Analyst (L5) │── output validator
                      └──────────┬──────────┘
                                 ▼
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   API / Dashboard         Daily brief · Alerts    Paper trading · Decision journal (L6)
```

### Components

| Component | Responsibility | Phase |
|---|---|---|
| Provider adapters | Fetch from one provider; handle auth, rate limits, retries, pagination; write L0 | 3 (framework), 4–10 (sources) |
| Scheduler | Run ingestion and computation jobs on a schedule; record job runs | 2/3 |
| Normalisers | Map provider payloads to canonical observations, units, symbols | 3–10 |
| Data quality | Freshness, completeness, range, cross-source consistency checks | 3 onward |
| Metric engine | Pure functions `f(observations, as_of) → metric`, registered with IDs and versions | 4–11 |
| Signal engine | Z-scores, percentiles, regime-relative thresholds, divergence tests | 12 |
| Regime engine | Combine signals into a labelled market state with confidence | 13 |
| Similarity engine | Find historical periods whose feature vectors resemble the present | 14 |
| Backtester | Point-in-time, walk-forward evaluation of signals and scenarios | 15 |
| Red-team harness | Adversarial checks: leakage, overfitting, multiple testing, regime drift | 16 |
| Anomaly engine | Flag statistically unusual observations/metrics, incl. data-error candidates | 17 |
| Rotation engine | Relative flows between BTC / ETH / alts / stablecoins / sectors | 18 |
| Snapshot builder | Freeze all evidence for a given `as_of` into an immutable, ID'd pack | 19 |
| Claude Analyst | Turn a snapshot into a labelled interpretation; validated before storage | 19 |
| Daily intelligence | Scheduled snapshot + interpretation + delivery | 20 |
| Alerts | Rule-based triggers on signals/regimes; never on AI text alone | 21 |
| Paper trading | Simulated positions from user-chosen scenarios | 22 |
| Decision journal | Record what the user decided, why, with the snapshot they saw | 23 |
| API + Dashboard | Read-only presentation of every layer with drill-down lineage | 24 |

---

## 4. Time model (point-in-time correctness)

Every observation carries three timestamps (all UTC):

| Field | Meaning | Example |
|---|---|---|
| `event_time` | When the thing happened / the period it describes | ETF flow for trading day 2026-03-02 |
| `available_at` | The earliest time the value was publicly knowable | Issuer publishes it the next morning |
| `ingested_at` | When *we* received it | Our job ran at 09:14 UTC |

**Point-in-time query rule:** a computation "as of" time *T* may use only rows with `available_at <= T`,
and for revised values, only the latest revision with `available_at <= T`.

Why this matters:
- ETF flows, 13F filings, macro releases, and some on-chain aggregates are **published with a lag** and sometimes **revised**.
- Wallet/entity labels **change over time**. A wallet labelled "exchange" today may not have been known as one in 2021.
- Using today's knowledge to compute yesterday's signal creates look-ahead bias, which silently inflates backtests.

When a provider does not give a publication time, `available_at` is set by an explicit, documented
**availability rule** per dataset (e.g. `event_time + 1 day`) and flagged as `available_at_estimated = true`.
For data we started collecting ourselves, `ingested_at` is the conservative bound.

---

## 5. Provider abstraction

- Each provider has **one adapter** implementing a common interface (fetch, paginate, rate-limit, map to canonical).
- Every adapter must handle (CLAUDE.md R8): authentication · rate limits · retries · exponential backoff · timeouts ·
  malformed responses · provider outages · stale data · duplicate data · missing data · schema changes.
  Schema changes are detected by validating each payload against the expected schema; a mismatch is stored in L0,
  marked `provider_error`, and alerted — never coerced silently.
- Duplicate deliveries are made harmless by idempotent writes keyed on (dataset, entity, event_time, provider, revision).
- Each **dataset** (e.g. "perpetual funding rate", "spot ETF daily net flow") declares a list of eligible providers with priority.
- Provider-specific symbols, units, and field names never leak beyond the normaliser.
- Adapters record provider **licence/terms constraints** (redistribution, storage, rate limits) in configuration.
- If the primary provider fails or diverges, the system either falls back (and marks the source) or marks the value `missing` — it never silently blends providers.
- Cross-provider disagreement above a tolerance is itself a data-quality signal.

Rule of thumb: abstract where two or more realistic providers exist for a dataset. Do not build abstraction
for a dataset with exactly one source; wrap it simply and document the dependency in `DECISIONS.md`.

---

## 6. Data quality and missing data

Every observation and metric has a `quality_status`:

`ok` · `missing` · `stale` · `partial` · `estimated` · `revised` · `suspect` · `conflicting` · `provider_error`

- Missing values are never filled with zero. Forward-fill or interpolation is allowed only when the metric
  definition in `DATA_DICTIONARY.md` explicitly permits it, and the result is flagged `estimated`.
- Metrics inherit the worst quality status of their required inputs.
- The dashboard and the AI snapshot always show quality status next to the value.
- Coverage (what % of the expected points exist) is tracked per dataset per day.

---

## 7. Lineage and reproducibility

- Every L2–L4 row records: definition ID + version, input references (or input query + as_of), code version (Git commit), parameters.
- Recomputing any metric for any past `as_of` must reproduce the stored value (or explain the difference, e.g. a revision became available).
- Snapshots given to Claude are stored immutably with an ID, so any interpretation can be audited later against exactly what Claude saw.

---

## 8. AI Analyst guardrails (Claude inside the product)

1. **Input:** an immutable snapshot (L1–L4 values, quality flags, caveats, historical comparisons). Nothing else — no free web browsing for data.
2. **Output contract:** structured (e.g. JSON) with exactly these sections, in order (CLAUDE.md R6):
   Summary · Evidence · Contradicting Evidence · Market Regime · Key Changes · Risks · Scenarios · Invalidation Conditions · Data Quality.
   Each statement inside is tagged with its evidence category (R2); hypotheses are tagged `hypothesis`.
   - When required data is missing, the affected section states **"Insufficient data."** rather than inferring.
   - When sources disagree, the output names the sources and their values in Contradicting Evidence and Data Quality.
3. **Citation rule:** every number in the output must reference a snapshot field ID.
4. **Validator:** a deterministic post-check extracts every number/claim reference and verifies it against the snapshot. Failures are rejected or flagged; they are never silently shown.
5. **Labelling:** AI output is always displayed as *interpretation*, visually distinct from observed data.
6. **No advice:** output describes scenarios and evidence; it does not instruct the user to buy or sell.
7. **Versioning:** model ID and prompt version are stored with every output.

---

## 9. Entity classification ("who is moving it")

"Institutional", "whale", "retail", "exchange", "fund", "miner", "market maker" are **claims**, and every claim needs evidence.

Each classification records:
- the entity/address/flow being classified;
- the label;
- the **evidence class**:
  - `direct` — the source itself identifies the actor (e.g. ETF issuer flow reports, regulatory filings, exchange-published data);
  - `attributed` — a third-party label (e.g. an on-chain analytics provider's cluster label), with the provider named;
  - `inferred` — a heuristic proxy (e.g. transfer size bands, venue mix, premium between venues);
- confidence, the rule or source that produced it, and `valid_from` / `valid_to`.

The UI must distinguish "ETF inflow (direct)" from "large-wallet accumulation (inferred)".
A large transfer is **not** an institution by default; a small transfer is **not** retail by default.

---

## 10. Backtesting integrity

- Backtests run only through the point-in-time query layer (§4). There is no other data path.
- Walk-forward / out-of-sample splits are the default; in-sample-only results are labelled as such.
- Explicitly modelled (CLAUDE.md R4): fees · slippage · liquidity (position size vs. available depth/volume) · execution assumptions
  (fill price, delay, venue) · turnover · position sizing · funding costs · data latency · missing data · unavailable historical data
  (a signal is not evaluated before all its inputs existed).
- Survivorship and selection bias: the asset/venue universe at each historical date is the universe that existed *then*,
  including delisted assets and defunct exchanges where data exists.
- Every backtest records how many variants were tried (to account for multiple testing).
- Results are reported with dispersion and drawdowns, never as a single headline number, and never as proof of future performance.

---

## 11. Proposed technology (NOT yet accepted — see DECISIONS.md ADR-0008)

| Concern | Proposal | Reason |
|---|---|---|
| Core language | Python 3.12+ | Strongest ecosystem for data, statistics, and backtesting |
| Database | PostgreSQL + TimescaleDB extension | One database for relational metadata and time-series; SQL for point-in-time queries |
| Data processing | Polars and/or pandas, NumPy, SciPy, statsmodels | Standard, well-tested statistical tooling |
| Validation / schemas | Pydantic | Typed provider payloads and canonical models |
| Migrations | Alembic (with SQLAlchemy) | Versioned schema changes |
| Jobs | Simple scheduler first (e.g. APScheduler), orchestrator later only if needed | Simplicity |
| API | FastAPI | Typed, lightweight |
| Dashboard | Decide in Phase 24 (options: React/Next.js; Streamlit for internal prototypes) | Defer until data layer exists |
| AI | Anthropic API (Claude), structured output + validator | Phase 19 |
| Runtime | Docker Compose for local dev (Docker Desktop + WSL2 on Windows) | Reproducible environment |
| Quality | pytest, ruff, mypy, pre-commit | Tests, lint, types |
| Secrets | `.env` locally (git-ignored); secret manager in production | Never in Git |

---

## 12. Proposed repository layout (NOT yet created)

```
FINANCIAL TOOL/
├── CLAUDE.md, README.md, ARCHITECTURE.md, DATA_DICTIONARY.md,
│   DECISIONS.md, PROGRESS.md, TODO.md
├── src/cfi/
│   ├── core/            # config, time utilities, logging, errors
│   ├── providers/       # one adapter per provider
│   ├── ingestion/       # jobs, scheduling, raw storage
│   ├── normalize/       # provider → canonical observations
│   ├── quality/         # data-quality checks
│   ├── metrics/         # L2 metric registry and definitions
│   ├── signals/         # L3 statistics, divergence
│   ├── regime/          # L4 regime classification
│   ├── analysis/        # similarity, anomaly, rotation
│   ├── backtest/        # point-in-time backtester
│   ├── ai/              # snapshot builder, Claude analyst, validator
│   ├── api/             # FastAPI app
│   └── journal/         # decisions, paper trading
├── migrations/
├── tests/               # unit, integration, point-in-time leakage tests
├── docs/                # extended docs, ADRs if DECISIONS.md grows too large
└── docker/
```

---

## 13. Deployment stages

1. **Local research** — batch jobs on the development machine, daily/hourly granularity.
2. **Production (batch)** — hosted database and scheduler, daily intelligence, alerts.
3. **Real-time intelligence** — streaming sources (websockets) only for datasets where latency matters (liquidations, funding, order book). Added last, and only where batch is demonstrably insufficient.
