# ARCHITECTURE.md

**Status:** v1.0 — Phase 2 architecture review. **Design only; nothing is implemented.**
Every major decision below references an Architecture Decision Record (ADR) in `DECISIONS.md`, which gives the
decision, reason, alternatives considered, trade-offs, and future implications.
Decisions marked **Proposed** need the user's approval before implementation — see the
**Architecture Approval Checklist** in `TODO.md`.

Governing rules: `CLAUDE.md` Part B (R1–R13). Field and table definitions: `DATA_DICTIONARY.md`.

---

## Contents

1. Purpose and principles
2. System context and containers
3. Layer model and evidence hierarchy
4. Technology stack
5. Architecture review (30 areas)
   - 5.1 Database architecture · 5.2 Time-series strategy · 5.3 Data ingestion · 5.4 Provider abstraction
   - 5.5 API · 5.6 Background jobs · 5.7 Caching · 5.8 Authentication · 5.9 Authorization · 5.10 Security
   - 5.11 Observability · 5.12 Logging · 5.13 Error handling · 5.14 Data quality · 5.15 Historical data
   - 5.16 Backtesting · 5.17 AI architecture · 5.18 AI grounding · 5.19 Alerts · 5.20 Scalability
   - 5.21 Cost control · 5.22 Provider outages · 5.23 Rate limits · 5.24 Time zones · 5.25 Look-ahead bias
   - 5.26 Survivorship bias · 5.27 Data leakage · 5.28 Reproducibility · 5.29 Versioning · 5.30 Disaster recovery
6. Entity classification
7. User layer: decision journal and paper trading
8. Repository layout
9. Deployment topology
10. Component-to-phase map
11. Architectural risks

---

## 1. Purpose and principles

The platform answers: **Where is money moving, who is moving it, and how is that behavior changing?**
It is decision-support software, not a prediction oracle (R1).

1. **Evidence before interpretation.** Data flows one way through strict layers (§3).
2. **The database and statistical engine are the source of truth.** Claude interprets; it never supplies data (R6).
3. **Point-in-time correctness.** Every value knows when it happened, when it was knowable, and when we learned it (§5.25).
4. **Missing, stale, and conflicting data are visible**, never hidden or silently repaired (R3).
5. **Every number is traceable** to raw provider payloads and to the code version that produced it (§5.28).
6. **No single-provider dependency** where an adapter reasonably prevents it (R8).
7. **Confidence, not certainty** at every derived layer.
8. **Simple first.** One primary database, one backend language, batch before streaming (R13).

---

## 2. System context and containers

```
                    ┌──────────────────────────────────────────────────────────────┐
  External          │ Exchanges · On-chain providers · ETF issuers/aggregators ·   │
  providers         │ Options venues · Stablecoin sources · Macro · Sentiment      │
                    └───────────────┬──────────────────────────────────────────────┘
                                    │ HTTPS (pull, batch)        │ WebSocket (later, real-time)
                                    ▼                            ▼
┌──────────────────────────────────────────────┐   ┌──────────────────────────────┐
│ WORKERS (Python, Celery)                     │   │ STREAM COLLECTORS (later)    │
│  ingest · backfill · compute · ai · alerts   │   │ long-running, per venue      │
└───────┬───────────────┬──────────────────────┘   └──────────────┬───────────────┘
        │               │ jobs / rate-limit / cache               │ Redis Streams
        │               ▼                                         ▼
        │        ┌─────────────┐                          ┌───────────────┐
        │        │   REDIS     │◀─────────────────────────│ stream writer │
        │        │ broker·cache│                          └───────┬───────┘
        │        │ limits·pubsub│                                 │
        │        └──────┬──────┘                                  │
        ▼               │                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ POSTGRESQL + TIMESCALEDB  (source of truth)                                       │
│  schemas: ref · raw · obs · calc · sig · regime · ai · usr · ops                  │
└───────────────▲──────────────────────────────────────────────────────────────────┘
                │                                       ┌──────────────────────────┐
                │                                       │ RAW PAYLOAD ARCHIVE      │
                │                                       │ filesystem (dev) /       │
                │                                       │ S3-compatible (prod)     │
                │                                       └──────────────────────────┘
┌───────────────┴──────────────────────┐        ┌───────────────────────────────┐
│ API (Python, FastAPI)  /api/v1       │◀──────▶│ ANTHROPIC CLAUDE API          │
│ sole gateway to data; auth; SSE      │  (via  │ (called only by ai workers)   │
└───────────────▲──────────────────────┘ workers)└───────────────────────────────┘
                │ HTTPS (REST + SSE), session cookie
┌───────────────┴──────────────────────┐
│ FRONTEND (Next.js, React, TypeScript)│
│ presentation only; no DB access      │
└──────────────────────────────────────┘
```

**Container responsibilities**

| Container | Responsibility | Must not |
|---|---|---|
| Frontend (Next.js) | Render dashboards, charts, forms; call the API | Hold business logic, connect to the database, call Claude, hold secrets beyond its own session |
| API (FastAPI) | Authenticate, authorize, serve read models, accept user-layer writes, stream updates | Run long computations or provider calls inline |
| Workers (Celery) | Ingestion, backfill, metric/signal/regime computation, AI jobs, alert evaluation | Write outside the schemas their DB role allows (§5.9) |
| Stream collectors (later) | Hold venue WebSocket connections; push events to Redis Streams | Compute metrics |
| PostgreSQL + TimescaleDB | System of record for all layers | — |
| Raw payload archive | Immutable provider payloads (L0 bodies) | Be modified after write |
| Redis | Broker, cache, shared rate-limit state, pub/sub, streams | Be a source of truth (it is disposable) |

Decisions: ADR-0014 (stack), ADR-0015 (service boundaries).

---

## 3. Layer model and evidence hierarchy

```
L0 RAW → L1 OBSERVED → L2 METRICS → L3 SIGNALS → L4 REGIME → L5 AI INTERPRETATION / HYPOTHESIS → L6 USER DECISION
```

| Layer | Evidence category (R2) | DB schema | Written by (DB role) | Mutability |
|---|---|---|---|---|
| L0 Raw | (source material) | `raw` + archive | `cfi_ingest` | Append-only, immutable |
| L1 Observed | Observed Data | `obs` | `cfi_ingest` | Append-only; revisions are new rows |
| L2 Metrics | Calculated Metric | `calc` | `cfi_compute` | Recomputable; versioned definitions |
| L3 Signals | Statistical Signal | `sig` | `cfi_compute` | Recomputable; versioned |
| L4 Regime | Regime Classification | `regime` | `cfi_compute` | Recomputable; versioned models |
| L5 AI | AI Interpretation, Hypothesis | `ai` | `cfi_compute` (snapshots), `cfi_ai` (outputs) | Append-only |
| L6 User | User Decision (and user hypotheses) | `usr` | `cfi_api` | Append-only journal; paper trades |
| Reference | — | `ref` | `cfi_ingest` (+ admin) | Bitemporal (valid time + record time) |
| Operations | — | `ops` | all services (own rows) | Append-mostly |

**Rules**
- A layer reads only from layers to its left and never writes to them — enforced by **database roles**, not only by code (§5.9, ADR-0027).
- L2–L4 are derivable from L1 for any `as_of`; if not, that is a bug.
- AI output never enters L1–L4. Numbers in AI output must match snapshot values (§5.18).
- Hypotheses (AI- or user-proposed) are stored with category `hypothesis` and are never shown as interpretation or fact.

---

## 4. Technology stack

| Concern | Choice | Status | ADR |
|---|---|---|---|
| Frontend | Next.js (App Router), React, TypeScript (strict) | Proposed | 0014, 0015 |
| Charts | TradingView Lightweight Charts (price/time-series) + Apache ECharts (analytics) | Proposed | 0043 |
| Backend | Python 3.12+, FastAPI, Pydantic v2 | Proposed | 0014 |
| Data access | SQLAlchemy 2.x (Core for time-series, ORM for user/ref), psycopg 3, Alembic migrations | Proposed | 0014 |
| Numerics | NumPy, pandas and/or Polars, SciPy, statsmodels | Proposed | 0014 |
| Database | PostgreSQL + TimescaleDB (self-hosted) | Proposed | 0016 |
| Raw archive | Local filesystem (dev) → S3-compatible object storage (prod) | Proposed | 0019 |
| Queue / scheduler | Celery with Redis broker; Celery beat for schedules | Proposed | 0023 |
| Cache / limits / pub-sub | Redis (or wire-compatible Valkey) | Proposed | 0024 |
| AI | Anthropic Claude API, structured JSON output, server-side only | Proposed | 0034 |
| Containers | Docker, Docker Compose (dev and first production) | Proposed | 0014 |
| Python tooling | uv (dependencies/lockfile), ruff, mypy, pytest | Proposed | 0014 |
| Frontend tooling | pnpm, ESLint, TypeScript strict, Vitest; Playwright for end-to-end later | Proposed | 0014 |
| Observability | Structured JSON logs, OpenTelemetry, Prometheus + Grafana | Proposed | 0029 |

---

## 5. Architecture review

Each subsection states the design. Rationale, alternatives, trade-offs, and future implications are in the referenced ADR.

### 5.1 Database architecture — ADR-0016, ADR-0017

- **One primary database:** PostgreSQL with the TimescaleDB extension holds every layer. Relational metadata
  (reference data, users, journal, configuration) and time-series live together, so point-in-time joins are plain SQL.
- **Schemas per layer** (`ref`, `raw`, `obs`, `calc`, `sig`, `regime`, `ai`, `usr`, `ops`) make the layer rule visible and enforceable with grants.
- **Series registry.** Every observed time series is registered once in `obs.series` (metric, subject, venue, period, unit).
  Data rows reference `series_id`, keeping rows narrow and making "what is this number" a single lookup.
- **Hybrid storage model** (ADR-0017):
  - **Typed hypertables** for high-volume, multi-field market data: `obs.market_bar` (OHLCV), `obs.funding_rate`,
    `obs.open_interest`, `obs.liquidation_event`, `obs.orderbook_depth`, `obs.option_quote`, `obs.onchain_transfer`.
  - **Generic scalar hypertable** `obs.observation` for lower-volume single-value series: ETF flows and holdings,
    stablecoin supply, exchange reserves, macro releases, sentiment indices, on-chain aggregates.
  - Every L1 table carries the same **provenance columns** (DATA_DICTIONARY §2): `event_time`, `available_at`,
    `ingested_at`, `source_provider`, `original_source`, `revision`, `quality_status`, `quality_note`, `confidence`, `raw_ref`.
- **Multiple providers side by side.** The same series can hold values from several providers
  (unique key includes `source_provider`). A **selection view** picks the preferred provider per point in time according to the
  dataset's priority list and records which one was used; conflicts are flagged, not blended (R3).
- **Keys.** Time-series rows: natural composite keys (`series_id`, `event_time`, `source_provider`, `revision`) — required
  because TimescaleDB unique constraints must include the time column. Entities: `bigint` identities; externally exposed IDs for
  user-layer objects use UUIDs.
- **Numeric types.** Exact `NUMERIC` by default (ADR-0010); a benchmark in the infrastructure phase decides whether
  high-volume families switch to `double precision` with the exact string kept in L0 (ADR-0044).
- **Migrations** with Alembic only; additive by default; destructive steps need explicit approval (R10).
- **Implemented:** `obs.series`, `obs.observation` (Phase 4), `obs.market_bar` (Phase 5, 30-day chunks, no compression
  yet), `obs.institutional_flow` (Phase 6, 180-day chunks; ETF flows and treasury flows/holdings with entity type and
  evidence class — `inferred` rejected by a database check), `obs.large_transfer` (Phase 7, 30-day chunks; one series
  per transfer), `ref.entity` and `ref.entity_label` (Phase 7, address labels with R5 rules as database checks),
  `obs.derivative_quote` (Phase 8, 7-day chunks; one series per futures / perpetual / option instrument, venue
  snapshots). The other typed tables and the `selected_observation` view are still planned.

### 5.2 Time-series strategy — ADR-0020

- **Hypertables** partitioned on the table's time column (`event_time` for L1; `as_of` for L2–L4). Chunk intervals sized per
  family by expected volume (e.g. 1 day for 1-minute bars, 1 month for daily series) and tuned after measurement.
- **Compression (columnstore)** for chunks older than a family-specific age (e.g. 7 days for minute data), segmented by `series_id`.
  Late-arriving revisions into compressed chunks are supported but slower; revisable families compress later.
- **Continuous aggregates** (e.g. 1m → 1h → 1d bars) **only for non-revisable families** (exchange candles, trades).
  A continuous aggregate groups by event time and cannot respect `available_at` or revision vintages, so revisable
  datasets (ETF flows, macro, on-chain aggregates) are aggregated by the point-in-time engine instead.
- **Retention tiers** (need approval, see checklist): full resolution kept for a defined window, then only rollups;
  L0 raw bodies for high-frequency endpoints kept for a defined window; **no deletion of L1 low-frequency data**.
  Retention never runs on data referenced by a stored snapshot, backtest, or journal entry without migrating the reference.
- **Point-in-time indexes:** (`series_id`, `available_at`) in addition to (`series_id`, `event_time`) on revisable tables.

### 5.3 Data ingestion architecture — ADR-0021, ADR-0009

Pipeline for every ingestion job (pull, batch):

```
schedule/trigger → rate-limit token → fetch (adapter) → write L0 (archive + raw.payload row)
   → validate against expected schema → normalise to canonical (units, symbols, UTC)
   → quality checks → idempotent upsert into L1 → record job_run + coverage
   → publish "dataset_updated(series, time range)" → downstream compute jobs
```

- **Dataset registry** (`ops.dataset`, `ops.dataset_provider`): for each dataset — eligible providers with priority,
  schedule, freshness limit, availability rule (how to set `available_at`), history start date, conflict tolerance, retention.
- **Idempotency:** re-running any job for the same window produces no duplicates (upsert on natural key);
  a changed value for an existing key becomes a new `revision`, never an overwrite.
- **Job types:** `ingest` (scheduled, recent window), `backfill` (history, low priority, resumable with checkpoints),
  `reconcile` (re-fetch recent windows to catch late corrections), `gap_fill` (triggered by gap detection).
- **High-frequency ingestion** (1-minute and faster) is supported in batch by fetching windows; true streaming comes later
  through stream collectors → Redis Streams → batched writer (§5.20). The L1 schema is identical for both paths.
- **Batch first, real-time last** (ADR-0009).

**Implemented in Phase 4** (`backend/src/cfi/ingestion/`, ADR-0046): `IngestionEngine.ingest(dataset, adapter, client, window)`
runs the pipeline above for one dataset/provider/window. Not yet implemented: scheduling and `dataset_updated` events
(arrive with the Celery workers), `backfill`/`reconcile`/`gap_fill` job types, coverage table, per-dataset retention.
Detection rules as built:

| Situation | What the engine does |
|---|---|
| Same key, same value (again or twice in one response) | Counted as a duplicate; not stored again |
| Same key, different value, same provider | Stored as a new `revision`; finding `revision` (`unexpected` if the dataset is not revisable) |
| Same key, different values *within one response* | First kept, other rejected; finding `inconsistent_duplicate_in_response` |
| Provider sends `null` | Stored as `missing` with a note; finding `missing_value` |
| Expected point not delivered (continuous datasets) | Explicit `missing` row; finding `completeness_gap`; a later value becomes revision 1 |
| Newest value older than the freshness limit, or no data | Finding `freshness` = `stale`; `job_run.stale = true` |
| Two providers differ beyond the dataset tolerance | Incoming row stored as `conflicting` (note names the other provider and value); both kept; finding `cross_provider_conflict` |
| Record cannot be normalised (unknown symbol, bad value, unfinished bar) | Rejected, reason recorded; job status `partial` |
| Payload not JSON / schema changed | Payload archived and flagged `schema_ok = false`; job `failed` with `schema_mismatch` |
| Timeout, 5xx, 429 | Retried with backoff (429/503 honour `Retry-After`); every attempt logged; job `failed` if retries run out |

**Implemented in Phase 5** (ADR-0047): scheduling with Celery (`backend/src/cfi/worker/`), `ingest` and `backfill`
job types, bar record family (`obs.market_bar`), per-subject job runs, `ops.backfill_state` checkpoints. Market-data
behaviour as built:

**Implemented in Phase 6** (ADR-0048): third record family (`CanonicalFlow` → `obs.institutional_flow`), adapter hook
`parse_page(spec, raw)` so a listing page can pass names to the pages that follow it in the same job, availability rule
`next_us_trading_day` with `known_when_received`, US trading calendar (`cfi/core/calendars.py`), per-dataset
`check_freshness` (off for sporadic events), Celery task `institutional.ingest` (SoSoValue on the `backfill` queue,
CoinGecko holdings on `ingest`; queued once when beat starts).

**Implemented in Phase 7** (ADR-0049): fourth record family (`CanonicalTransfer` → `obs.large_transfer`), address
checksum validation (`cfi/core/addresses.py`), Coin Metrics Community and Blockchair adapters, Celery task
`whales.ingest` (one run = the recent window plus one history chunk while history is incomplete; Blockchair on the
`backfill` queue so one process owns its daily request budget), address labels imported from versioned CSV files
(`cfi/whales/seed_labels`, idempotent, never overwritten).

**Implemented in Phase 8** (ADR-0050): fifth record family (`CanonicalQuote` → `obs.derivative_quote`), Binance
USDⓈ-M, OKX derivatives and Deribit adapters, the shared scheduled-source runner `cfi/ingestion/scheduled.py` (used by
whales and derivatives: recent window aligned to complete periods, catch-up after downtime, one history chunk per run),
Celery task `derivatives.ingest` (the option chain on the `backfill` queue). OKX liquidation orders are aggregated into
hourly totals inside the adapter across pages (`RequestSpec.state`); incompletely read hours become missing points.

| Situation | What happens |
|---|---|
| Current, unfinished bar (or CoinGecko's running value) | Skipped and counted (`job_run.skipped`); fetched again once final (period end + 60 s) |
| Coinbase publishes no candle for a minute | Explicit `missing` bar with the note that it may mean zero trades |
| High below low, non-positive price, negative volume | Stored unchanged as `suspect` with the reason; finding `consistency` |
| Worker stopped for a while | Next latest run starts after the newest stored bar (up to 1,000 bars back) |
| History | Backfill walks back in request-sized chunks to the configured depth; stops after 3 empty chunks (provider history start, e.g. Kraken's 720-bar limit, or an instrument's listing); a failed chunk is retried, never skipped |
| Provider unreachable (e.g. ISP block) | Runs fail with the error; circuit breaker pauses calls; the dashboard shows the failure |
| HTTP 418/429 with a long `Retry-After` | Not retried early; circuit held open for the requested time |

### 5.4 Provider abstraction — ADR-0022

**Implemented in Phase 4:** `ProviderAdapter` (`first_request` / `next_request` / `parse` / `normalise`) in
`cfi/providers/base.py`; shared `ProviderHttpClient` with auth (header, query or bearer; secret read from an environment
variable and redacted), timeouts, retries with exponential backoff and jitter, token-bucket rate limiter, circuit
breaker, and per-attempt records (`ops.provider_request`) in `cfi/providers/http.py`. Rate limiter and circuit breaker are
in-process until workers share them via Redis. Mock providers for tests only: `cfi/providers/mock.py`.


- **One adapter per provider** implementing a small interface: `fetch(dataset, window) → RawResponse`,
  `parse(RawResponse) → list[ProviderRecord]`, `normalise(ProviderRecord) → CanonicalRecord`, plus declared
  capabilities (datasets, history depth, granularity, auth type, rate limits) and terms (storage/redistribution).
- A shared **HTTP client layer** gives every adapter the same timeouts, retries with exponential backoff and jitter,
  rate-limit tokens, circuit breaker, request ledger (for cost), and payload archiving — adapters contain only
  provider-specific mapping. This covers every failure mode in R8.
- **Anti-corruption boundary:** provider symbols, field names, units, and time conventions stop at `normalise()`.
  Canonical models are the only types the rest of the system sees (R8).
- **Symbol mapping** via `ref.asset_symbol_map` / `ref.instrument_map` (bitemporal) — never string matching at runtime.
- **Selection and fallback:** described in §5.22. A fallback is recorded in `source_provider`; values are never blended.
- **Single-source datasets** get a simple adapter and a documented dependency ADR — no speculative abstraction (R13).

### 5.5 API architecture — ADR-0025

- **REST over HTTPS, versioned** at `/api/v1`. OpenAPI generated by FastAPI; the frontend's TypeScript client is generated
  from it, so both sides share one contract.
- **Resource groups:** `reference`, `series` (observations), `metrics`, `signals`, `regimes`, `divergences`, `similarity`,
  `backtests`, `anomalies`, `rotations`, `snapshots`, `interpretations`, `alerts`, `journal`, `paper`, `quality`,
  `providers/health`, `lineage`, `auth`, `admin`.
- **Evidence envelope** on every data response: `evidence_category`, `as_of`, `knowledge_time`, `quality_status`
  (and coverage), `sources` (provider + original source), `definition_version`, and a `lineage` link. The UI cannot
  render a value without knowing what kind of value it is (R2).
- **Point-in-time parameter:** every read endpoint accepts `as_of` (default: now) so any dashboard can be viewed
  "as it would have looked" at a past time. **Phase 18 correction (ADR-0060):** `knowledge_time` now defaults to
  `as_of` — not independently to `now()` — whenever `as_of` is supplied and `knowledge_time` is not, closing a
  revision/leakage gap (`ingested_at <= knowledge_time`) that a caller supplying only `as_of` used to defeat
  silently. Both values are capped at the real `now()`, including an explicitly supplied one (R3). All ten
  point-in-time routes now share this single resolution function (`cfi.api.params.resolve_query_times`)
  instead of each carrying its own copy.
- **Read-only for L0–L5.** Writes only for user-layer objects (journal, paper trading, alert rules, settings) and admin operations.
  Recomputations and AI analyses are **requested** via the API and executed by workers (returns a job ID).
- **Live updates:** Server-Sent Events first (one-way, simple, works through proxies); WebSockets only if two-way need appears.
- **Errors** use RFC 9457 "problem details" JSON with a stable `error_code` (§5.13).
- **Pagination:** cursor-based on time; mandatory time bounds and server-side row limits to prevent unbounded queries.
- **Implemented in Phase 5:** `GET /api/v1/market/catalog`, `/market/bars` (asset, timeframe, venue, limit ≤ 1,500,
  start, end, `as_of`), `/market/overview` — evidence envelope with source, units, derivation, quality (missing /
  not-loaded / suspect / conflicting / revised), freshness and last ingestion run. The OpenAPI-generated TypeScript
  client is not built yet (types are hand-written in `frontend/src/lib/market.ts`).
- **Implemented in Phase 6:** `GET /api/v1/institutional/catalog`, `/overview`, `/etf-flows` (asset, interval
  1d/1w/1mo, start, end), `/etf-funds`, `/treasury`, `/score` — all take `as_of` (cut-off on `available_at`) and
  `knowledge_time` (cut-off on `ingested_at`). Every metric carries source, timestamp, unit, calculation, freshness and
  data quality, its evidence category and evidence class. Types hand-written in `frontend/src/lib/institutional.ts`.
- **Implemented in Phase 7:** `GET /api/v1/whales/catalog`, `/overview`, `/flows`, `/holders`, `/transfers`,
  `/addresses/{chain}/{address}`, `/entities`, `/score` (with contradiction indicators) — same `as_of` /
  `knowledge_time` cut-offs; labels count only from their `available_at` and within `valid_from`/`valid_to`. Every
  address carries its classification with evidence, source and confidence. Types in `frontend/src/lib/whales.ts`.
- **Implemented in Phase 8:** `GET /api/v1/derivatives/catalog`, `/overview`, `/asset` (score with components,
  conditions, open interest, leverage, funding, basis, liquidations, options, positioning, price context, data
  quality), `/history` (hourly series for charts) — same `as_of` / `knowledge_time` cut-offs. Types in
  `frontend/src/lib/derivatives.ts`.

### 5.6 Background jobs — ADR-0023

- **Celery** workers with **Redis as broker**; **Celery beat** for schedules (schedule definitions in code/config, versioned).
- **Queues by workload** so slow work never starves urgent work:
  `ingest_fast` (minute-level), `ingest` (hourly/daily), `backfill` (low priority), `compute`, `ai`, `alerts`, `maintenance`.
- **Task rules:** idempotent; late acknowledgement (a task is acknowledged after it finishes, so a crashed worker's task is
  redelivered); explicit time limits; retries only for transient errors; a dead-letter record for exhausted retries.
- **Postgres `ops.job_run` is the job history of record** (start, end, status, rows, error, code version) — not the broker.
- **Dependency chaining:** `dataset_updated` events trigger the minimal downstream recomputation (metrics → signals →
  regime → alert evaluation), debounced so a burst of updates causes one recomputation.
- Celery does not support Windows as a worker platform; workers run in Linux containers (Docker) — also on the Windows dev machine.
- **Implemented in Phase 5:** services `worker` (queues `ingest_fast`, `ingest`), `worker-backfill` (queue `backfill`)
  and `beat`; schedules in `cfi/worker/schedule.py` (1m bars and last trade every 30–60 s, other timeframes every
  2–30 min, market caps every 5 min / 6 h, backfill round every 60 s). Dependency chaining (`dataset_updated`) and the
  `compute`/`ai`/`alerts`/`maintenance` queues are not built yet.

### 5.7 Caching — ADR-0024

- **Redis is never a source of truth.** Every cached item can be rebuilt from Postgres; a cache failure degrades speed, not correctness.
- **What is cached:** API read responses for heavy queries; reference data; latest dashboard tiles; provider-health summaries.
- **Invalidation by data version**, not only time: each series/metric has a version counter bumped on write; cache keys include
  the version, so updates invalidate naturally. Short TTLs as a safety net.
- **Historical point-in-time queries** (fixed past `as_of` and fixed `knowledge_time`) are immutable and cache well.
- **Cached payloads carry their `as_of`**, so staleness stays visible (R3).
- Not cached: AI generations (they are stored records), auth decisions, anything user-private beyond the session.
- Next.js data caching is disabled for live data routes to avoid serving stale market data from the frontend layer.

### 5.8 Authentication — ADR-0026

- **FastAPI owns authentication.** Users in `usr.app_user`; passwords hashed with **Argon2id**; **TOTP two-factor mandatory** for owner/admin.
- **Server-side sessions** (session ID in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie; session record in Redis with Postgres audit),
  so sessions can be revoked instantly. CSRF protection on state-changing requests.
- Next.js and the API are served under the same site (reverse proxy), so the cookie works for both without exposing tokens to JavaScript.
- **Machine access** (scripts, notebooks): personal API tokens, hashed at rest, scoped, expiring.
- **Single user first**, but the model supports multiple users. OIDC login (Google, etc.) can be added later without redesign.

### 5.9 Authorization — ADR-0027

- **Application roles:** `owner` (everything incl. admin and secrets rotation), `analyst` (read all data, run analyses, own journal
  and paper accounts, alert rules), `viewer` (read dashboards only). Checked in API dependencies, per endpoint.
- **Ownership:** user-layer rows carry `user_id`; users see and modify only their own journal, paper accounts, and alert rules.
- **Database roles enforce the layer rule** (defence in depth):

| DB role | Can write | Can read |
|---|---|---|
| `cfi_ingest` | `raw`, `obs`, `ref`, own `ops` rows | `ref`, `ops` |
| `cfi_compute` | `calc`, `sig`, `regime`, `ai.snapshot` (snapshot builder), own `ops` rows | `ref`, `obs`, `calc`, `sig`, `regime` |
| `cfi_ai` | `ai.interpretation`, `ai.usage`, own `ops` rows | `ai.snapshot`, `ref` — nothing else, so Claude's worker cannot see un-snapshotted data |
| `cfi_alerts` | `usr.alert_event`, own `ops` rows | `ref`, `calc`, `sig`, `regime`, `usr.alert_rule`, `ops` quality results |
| `cfi_api` | `usr`, request records in `ops` | all schemas (read) |
| `cfi_readonly` | — | all except secrets/auth tables (for research notebooks) |
| `cfi_migrator` | schema changes (migrations only) | — |

  A bug in AI code therefore *cannot* write a metric, and a bug in the API *cannot* alter observed data.

### 5.10 Security — ADR-0028

- **Secrets:** never in code or Git (R9). `.env` locally (git-ignored), `.env.example` with placeholders; Docker secrets or a cloud secret
  manager in production. Secrets never logged; log scrubbing for known key patterns.
- **Exchange credentials:** read-only keys only. The platform **never** stores keys with trading or withdrawal permission — paper trading
  needs none (§6).
- **Network:** only the reverse proxy is exposed; Postgres and Redis bind to the internal network with passwords; TLS everywhere outside the host.
- **Web:** strict CORS (same site), CSRF tokens, Content-Security-Policy, secure cookies, input validation (Pydantic), parameterised SQL only.
- **Prompt-injection defence:** ingested text (social posts, news titles, provider free text) is **data** — delimited, length-limited,
  never placed in Claude's instructions, and never able to trigger actions; Claude has no tools that act on the world (§5.17).
- **Supply chain:** lockfiles (uv, pnpm), pinned container image digests, dependency vulnerability scanning in CI, minimal non-root containers.
- **Audit log** (`ops.audit_log`, append-only): logins, role changes, alert-rule changes, admin actions, data corrections, AI budget changes.
- **Backups encrypted** at rest and in transit (§5.30).

### 5.11 Observability — ADR-0029

Three signals, all tagged with service, job, dataset, and provider:
- **Metrics** (Prometheus): request latency/errors, queue depth and task duration, ingestion lag per dataset, **data freshness**
  (age of latest point vs. freshness limit), coverage %, provider error rates and circuit state, AI tokens/cost and validation-failure rate,
  DB size and compression ratio.
- **Traces** (OpenTelemetry): API request → DB; job → provider call → DB; AI job → Claude call → validator.
- **Logs:** §5.12.
- **Dashboards (Grafana):** System health · Data freshness & quality · Provider health · AI usage & validation · Cost.
- **Health endpoints:** `/health/live` (process up), `/health/ready` (DB, Redis reachable). Data health is separate and shown to the user.
- A lighter start is possible (logs + DB health tables only); see checklist.

### 5.12 Logging — ADR-0029

- **Structured JSON logs** to stdout (container-native), one event per line.
- **Correlation IDs** on every line: `request_id`, `job_id`, `task_id`, `snapshot_id`, `provider`, `dataset`.
- **Levels:** `ERROR` (needs attention), `WARNING` (degraded: fallback used, stale data, retry), `INFO` (lifecycle), `DEBUG` (off in production).
- **Never logged:** secrets, tokens, passwords, full raw payloads (those go to the L0 archive), personal data beyond user ID.
- **Retention:** short (e.g. 14–30 days) for application logs; the audit log and `ops.job_run` are kept in the database long-term.

### 5.13 Error handling — ADR-0030

- **Error taxonomy** (typed exceptions):
  `ProviderTransientError` (timeouts, 5xx, 429) → retry with backoff ·
  `ProviderPermanentError` (auth failure, 4xx, discontinued endpoint) → no retry, alert ·
  `SchemaMismatchError` (payload shape changed) → store L0, mark `provider_error`, alert, stop that dataset ·
  `DataValidationError` (values out of range) → keep row as `suspect` ·
  `InsufficientDataError` (computation lacks inputs) → result `missing`, not an exception to the user ·
  `ComputationError` (bug) → fail job loudly ·
  `AIValidationError` (unsupported numbers/claims) → reject or flag output (§5.18).
- **Never swallow errors** (R3/R7). Every failure lands in `ops.job_run` with its error and shows in observability.
- **Partial failure is explicit:** if 5 of 6 venues succeed, the aggregate is computed with `partial` quality and the missing venue named.
- **API errors:** problem-details JSON with `error_code`, human message, and correlation ID; no stack traces to clients.

### 5.14 Data quality — ADR-0031

- **Checks per dataset** declared in the registry, executed after each ingest:
  freshness · completeness/coverage · range and unit sanity · monotonicity where applicable · duplicate detection ·
  cross-provider consistency (tolerance per dataset) · schema conformity · continuity (unexpected gaps).
- **Results stored** in `ops.quality_check_result` (history kept) and **propagated**: L1 rows get `quality_status`; L2–L4 inherit the worst
  status of required inputs; snapshots, dashboards, and alerts show it.
- **Quality statuses:** `ok` · `missing` · `stale` · `partial` · `estimated` · `revised` · `suspect` · `conflicting` · `provider_error`.
- **Filling** only where a metric definition explicitly permits it; result flagged `estimated`.
- **Data-quality alerts** (stale feed, conflict, schema change) are first-class alerts (§5.19).
- A **Data Quality dashboard** shows coverage and freshness per dataset, so the user always sees how strong the foundation is.

### 5.15 Historical data — ADR-0032

- **History start per dataset** recorded in the registry (when data truly begins); signals are not evaluated before all inputs exist (R4).
- **Point-in-time reliability** tag per row (`pit_reliability`):
  - `native` — we recorded it live; `available_at` and vintage are real.
  - `vendor_pit` — provider supplies historical vintages/publication times.
  - `backfilled_latest` — historical values as they look *today* (may include later revisions or re-labelling).
  Backtests declare which reliability levels they accept and report it; `backfilled_latest` data is flagged as a look-ahead risk.
- **Own vintages:** for sources that overwrite history (web pages, holdings files), we keep every version we fetched (L0 archive + revisions).
- **Backfill jobs** are resumable, rate-limit aware, low priority, and write `job_run` checkpoints.
- **Research exports:** point-in-time extracts to Parquet for notebooks (DuckDB/Polars), always generated through the point-in-time loader.

### 5.16 Backtesting architecture — ADR-0033

```
Experiment spec (versioned) ─▶ Point-in-time loader ─▶ Feature builder (as_of-aligned)
      │                              ▲ only data door              │
      ▼                              │                             ▼
Walk-forward splitter ─▶ Signal/strategy evaluation ─▶ Execution & cost model ─▶ Results + report
      │                                                                              │
      └────────────── Experiment registry (params, code SHA, data knowledge_time, trials count) ◀┘
```

- **Point-in-time loader is the only data path** into research and backtests: every read is `as_of`-bound on `available_at`,
  optionally also `knowledge_time`-bound (§5.25), with revision and label vintages respected.
- **Two engines sharing one cost model:**
  - *Vectorised research engine* for fast signal evaluation (hit rates, forward-return distributions, information coefficients).
  - *Event-driven simulator* for strategies and paper trading, modelling order timing, fills, and position state.
- **Cost and constraint model (R4):** fees (venue fee schedules) · slippage (function of size vs. liquidity/depth) · liquidity caps ·
  execution assumptions (signal time → earliest executable time → fill price) · funding payments for perpetuals · turnover · position sizing ·
  missing-data handling (no trade when inputs missing) · data latency.
- **Validation defaults:** walk-forward / out-of-sample; purged and embargoed splits where labels overlap; multiple-testing accounting via the
  registry's trial count; results reported as distributions with drawdowns and turnover, never one headline number (R4).
- **Universe as-of:** asset/instrument/venue universes are taken as they existed at each date (§5.26).
- Backtests run as `backfill`/`compute` queue jobs and store results in `sig`-adjacent research tables; they never change live signals.

### 5.17 AI architecture — ADR-0034, realized in Phase 21 (ADR-0068)

```
API POST /analyst/analyze                              Celery "ai" queue, task analyst.analyze
  → ai.interpretation row inserted, status=queued        ── analysis_id returned immediately
                                                               │
                                                               ▼
  Snapshot builder (cfi.analyst.snapshot): calls all 14 tools once (cfi.analyst.tools — each a
  thin, read-only wrapper over an existing, already-tested domain service; no raw DB access)
  → flattened field_id → SnapshotField map → immutable ai.snapshot row (JSON, sha256 hash)
  → Prompt assembly (cfi.analyst.prompts): versioned system prompt + task + delimited snapshot
    JSON + user question
  → Budget check (ai.usage summed for the current calendar month against
    Settings.ai_monthly_budget_usd) — refuses explicitly (AIBudgetExceededError) before any call
  → Claude API (cfi.analyst.client.ClaudeClient, over cfi.providers.http.ProviderHttpClient —
    the same auth/timeout/retry/backoff/rate-limit/circuit-breaker machinery every ingestion
    adapter gets, R8)
  → Deterministic validator (cfi.analyst.validator; no model call) → pass: store ai.interpretation
    (completed) · fail: retry once with the validator's own errors appended to the prompt → still
    failing: store as failed with the validator's errors, nothing silently reinterpreted
  → GET /analyst/{analysis_id} (status/response/errors; labelled as AI Interpretation, L5)
```

- **Claude is called only by the `ai` Celery queue's `analyst.analyze` task**, never by the frontend
  or synchronously inside an API request; the API key is read from the environment server-side only
  (R9) and the API process never imports the Celery application that would need it
  (`cfi.worker.client` is a separate, minimal task producer — ADR-0068).
- **Structured output** with the twelve required sections (Summary, Evidence, Contradicting
  Evidence, Market Regime, Key Changes, Capital/Participant Behavior, Derivatives & Liquidity
  Context, Historical Context, Risks/Uncertainties, Scenarios, Invalidation Conditions, Data
  Quality — CLAUDE.md R6's nine plus three added in the Phase 21 spec); every evidence statement
  cites the snapshot `field_id`(s) it relies on. Section order is enforced **by construction**:
  `cfi.analyst.schema.AnalystResponse`'s Pydantic field order is the one true order, not a
  property of the incoming JSON (ADR-0068).
- **Model is a configuration value** (`Settings.anthropic_model`, currently `claude-sonnet-5`),
  never hard-coded; model, prompt version, and snapshot version are stored with every
  `ai.interpretation` row.
- **Cost controls:** a monthly budget ceiling (`Settings.ai_monthly_budget_usd`, TODO.md B3)
  enforced by summing `ai.usage.cost_usd` for the current month before every call — refuses
  explicitly, never silently skips; usage (tokens, latency, estimated cost) recorded per attempt.
- **No action tools.** The 14 analyst tools (`cfi.analyst.universe.TOOLS`) are read-only wrappers
  over existing domain services (institutional, whale, retail, derivatives, liquidity, macro,
  market structure, divergence, regime, similarity, anomaly, rotation, plus market data and a
  cross-tool data-quality summary) — Claude never queries the database directly, writes data,
  triggers alerts, or places trades.
- **Evaluation harness (R12):** the deterministic validator's own unit tests exercise every
  grounding-failure scenario (invented numbers, unsupported directional verdicts, an inferred
  rotation stated as fact, a historical-similarity guarantee, missing "Insufficient data."/"Sources
  conflict." disclosures) against synthetic snapshots — no live model calls required to regression-
  test grounding.

### 5.18 AI grounding — ADR-0034, realized in Phase 21 (ADR-0068)

- **Snapshot = the complete evidence Claude may use** (`cfi.analyst.snapshot.Snapshot`). Every tool
  result is flattened into a stable dotted **field_id** → `SnapshotField(display, value, unit,
  evidence_category, quality_status, source)`; a numeric leaf's `display` string is the exact text
  Claude must copy verbatim when citing it (never recomputed or rounded by the model).
- **Explicit absences:** a tool that raises a well-understood `CFIError` comes back `"status":
  "unavailable"` with its `error_code`/`detail` preserved, never hidden; `check_data_quality`
  (the 14th tool) rolls every tool's status up into one `data_quality_state`
  (`ok`/`degraded`/`insufficient`) and a `has_conflicts` flag, both carried into the prompt and
  the stored `ai.interpretation` row.
- **No arithmetic by Claude.** The system prompt instructs Claude to copy numbers exactly as they
  appear in cited `display` values; the deterministic validator (`cfi.analyst.validator.validate`)
  then re-extracts every numeric token from the response and checks it against the snapshot,
  independent of what Claude claims to have done.
- **Validator checks (no model call, pure string/number comparison):** all twelve sections present
  (enforced by the Pydantic schema itself, `extra="forbid"`) · every numeric token in a grounded
  section maps to one of its cited `field_id`s' exact `display` value · every cited `field_id`
  exists in the snapshot · prose sections get a whole-snapshot numeric backstop sweep ·
  `"Insufficient data."` is required verbatim when `data_quality_state == "insufficient"` ·
  `"Sources conflict."` is required verbatim when `has_conflicts` · banned-language patterns catch
  bullish/bearish verdicts, trading directives, manufactured certainty, "capital moved from X to Y"
  stated as fact (not hedged), and historical-similarity-as-guarantee phrasing. On failure, Claude
  is retried exactly once with the validator's own errors appended to the prompt; a second failure
  is stored as `failed` with those errors — never silently reinterpreted or partially accepted.
- **Auditability:** every `ai.interpretation` row carries its `snapshot_id` (linking to the
  immutable, hashed `ai.snapshot.payload` Claude actually saw), `prompt_version`, `model`,
  `tools_called`, `validation_status`/`validation_errors`, `attempt_count`, `data_quality_state`,
  and, on failure, `error`; each Claude call attempt is its own `ai.usage` row (tokens, latency,
  estimated cost). No free-form conversational memory is kept — only these structured, queryable
  records (Phase 21 spec, Section 13).
- **Display:** AI text is visually distinct from data; each cited number links back to its snapshot
  `field_id` and from there to the underlying tool result.

### 5.19 Alert architecture — ADR-0035

- **Rule-based alerts on L1–L4 and data-quality events only** — never on AI text (R6).
- **Rule types:** threshold, crossing, percentile/z-score extreme, change-over-window, divergence (institutional vs. retail composites),
  regime change, data quality (stale, conflict, schema change, provider outage).
- **Evaluation** in the `alerts` queue after the relevant computation completes (event-driven), plus a periodic sweep for time-based rules.
- **Noise control:** hysteresis (separate trigger and reset levels), cooldowns, deduplication, grouping, and minimum-quality requirements —
  if inputs are stale or missing, the alert reports a *data* problem instead of firing a *market* alert.
- **Alert record** (`usr.alert_event`) stores the rule version, triggering values with IDs, quality, and a snapshot reference.
- **Channels:** in-app first; email and a messaging channel (e.g. Telegram) via a notification adapter — choice needs approval.
- Optional: an AI explanation may be attached **after** an alert fires, labelled as interpretation; it never decides whether to fire.

### 5.20 Scalability — ADR-0037

- **Scale up before out.** One well-sized Postgres node with compression handles large volumes; illustration: 1-minute bars for
  500 series ≈ 720,000 rows/day ≈ 263 million rows/year (compression makes this manageable; to be benchmarked).
- **Scale out by role:** add Celery workers per queue; separate `ingest_fast` workers from heavy `compute`/`backfill`.
- **Read replica** for API and research reads when needed; heavy research moves to Parquet exports.
- **Real-time path (later):** stream collectors → Redis Streams → batched writer to Postgres → incremental metric updates → pub/sub → SSE.
  Kafka/Redpanda only if Redis Streams becomes a measured bottleneck.
- **Stateless API and workers**, so horizontal scaling needs no redesign.

### 5.21 Cost control — ADR-0038

- **Data providers:** budget per provider; `ops.request_ledger` records every request (endpoint, weight, cost class) so spend is visible
  before invoices; free/public sources first; paid sources added per dataset with a written justification.
- **Claude:** per-day/month ceilings enforced in code; model tiering; prompt caching; batch processing for non-urgent work; token usage dashboard.
- **Storage:** compression, retention tiers, raw-archive lifecycle rules (move old L0 to cheaper storage class).
- **Compute:** debounced recomputation; backfills off-peak; no polling faster than a dataset's real update frequency.
- **Infrastructure:** single-host Docker Compose until load justifies more.

### 5.22 Provider outages — ADR-0022

- **Circuit breaker per provider/endpoint** (closed → open after repeated failures → half-open probe). State in Redis, events in `ops.provider_health_event`.
- **Fallback policy per dataset:** if the primary is down/stale and a secondary is eligible, fetch from the secondary; rows record the actual
  `source_provider`; the UI and snapshots show "fallback provider in use". If no eligible fallback, values become `missing`/`stale` — never guessed.
- **Staleness propagates** to metrics, signals, regime confidence, alerts (data alert instead of market alert), and AI snapshots.
- **Recovery:** gap detection schedules `gap_fill` jobs when the provider returns; reconciliation compares fallback and primary values for the outage window.
- **Provider scorecard** (uptime, latency, conflict rate) informs future provider choices.

### 5.23 Rate limits — ADR-0022

- **Central token buckets in Redis** per provider, API key, and endpoint weight, shared by all workers (no worker can exceed limits alone).
- **Honour provider signals:** `Retry-After`, remaining-quota and weight headers adjust the bucket dynamically.
- **Priority:** `ingest_fast` > `ingest` > `reconcile` > `backfill`; backfills yield when budget is tight.
- **Capacity planning:** the dataset registry's schedules are checked against each provider's limits before activation.
- **Backoff:** exponential with jitter; 429s counted in provider health.

### 5.24 Time zones — ADR-0039

- **Store and compute in UTC** with timezone-aware types (`timestamptz`); naive datetimes are rejected at the boundary.
- **Convert at the edges only:** provider-local times → UTC at normalisation; UTC → the user's display time zone in the UI
  (default `Asia/Manila`, configurable).
- **Calendars:** crypto days are UTC days (00:00–24:00 UTC; weekly bars start Monday 00:00 UTC). US-listed products (ETFs), equities,
  and macro releases use an exchange/release calendar with daylight-saving transitions handled (US Eastern → UTC).
- **Bar semantics:** `event_time` = bar open; `available_at` ≥ bar close (+ publication latency). Each dataset documents its convention.

### 5.25 Look-ahead bias — ADR-0018, ADR-0040

- **Two time axes for knowledge** (bitemporal):
  - `available_at` — when the value was *publicly knowable* → used by backtests and historical signals.
  - `ingested_at` — when *our system* knew it → used to reproduce exactly what the system showed at a past moment (`knowledge_time`).
- **Every engine function takes `as_of` explicitly;** there is no "latest" default inside computation code.
- **Revisions and label changes** are new rows/versions; the loader returns the latest version with `available_at ≤ as_of`.
- **Bar-close rule:** a bar is not usable until its close time plus latency.
- **Availability rules:** when a source gives no publication time, the dataset's documented rule sets a conservative `available_at`
  (e.g. ETF daily flow → next US business day, morning ET) and the row is flagged `available_at_estimated = true`.
- **Automated leakage tests:** "future poison" tests insert sentinel values after `as_of` and assert results are unchanged; tests assert no
  engine query lacks an `as_of` bound.

### 5.26 Survivorship bias — ADR-0040

- **Master data keeps the dead:** assets, instruments, venues, and ETFs have listing/launch and delisting/closure dates and status history;
  delisted and failed ones stay in the database with their data.
- **Universes are defined as-of:** "top N by market cap", "all perps on venue X", "all spot ETFs" are evaluated with membership at each date.
- **Events retained:** collapses, depegs, and delistings are data, not noise to clean away.
- Where history for dead assets is unavailable, the gap is recorded and backtest reports state the survivorship limitation.

### 5.27 Data leakage — ADR-0040

Beyond look-ahead:
- **Normalisation leakage:** z-scores/percentiles use rolling or expanding windows ending at `as_of`, never full-sample statistics.
- **Model-selection leakage:** parameters are chosen on training windows only; the test window is untouched; trial counts recorded.
- **Label overlap:** purged/embargoed splits when forward-return labels overlap.
- **Regime leakage:** regime models used historically must be *filtered* (information up to `as_of`), not *smoothed* with future data.
- **Entity-label leakage:** wallet labels applied historically only within their `valid_from`/`valid_to` and `available_at`.
- **Similarity leakage:** historical analogue search excludes periods whose outcome window overlaps the query period.

### 5.28 Reproducibility — ADR-0041

Every derived result (metric, signal, regime, snapshot, AI output, backtest) records:
- definition/model/prompt **version**, **parameters**, **code version** (Git SHA and container image digest),
- **data coordinates**: `as_of` and `knowledge_time` (and for backtests, accepted `pit_reliability` levels),
- **input fingerprint** (hash of the input set) and random seeds where applicable.

A **recompute-and-compare** maintenance job periodically recomputes a sample of historical results and reports differences (expected ones
explained by late data or revisions; unexpected ones are bugs). Dependency lockfiles and pinned images make environments reproducible.

### 5.29 Versioning — ADR-0041

| Thing | Scheme |
|---|---|
| API | URL major version (`/api/v1`); additive changes within a version; breaking changes → `/v2` with overlap period |
| Database schema | Alembic revisions; additive-first; destructive changes only with approval (R10) |
| Metric / signal / regime definitions | `name.vN`; a formula change creates a new version; old versions and their values are retained |
| Prompts and AI output schema | `prompt_id.vN`, `schema.vN`; stored with each interpretation |
| Provider payload schemas | expected schema per adapter version; mismatch → alert (§5.13) |
| Datasets (vintages) | revisions and `ingested_at` |
| Application releases | Semantic versioning; Git tags; changelog in `PROGRESS.md` |

### 5.30 Disaster recovery — ADR-0042

- **Postgres:** continuous WAL archiving + scheduled full backups with a mature tool (pgBackRest or WAL-G) to off-site, encrypted object
  storage → point-in-time recovery. Development: nightly logical dump is sufficient.
- **Raw archive:** replicated/versioned object storage — together with L0 metadata it allows **rebuilding L1 and everything above** if needed.
- **Redis:** disposable; rebuilt from Postgres (sessions may be lost → users log in again).
- **Configuration and infrastructure** as code in Git; secrets recoverable from the secret manager.
- **Targets (need approval):** proposed production **RPO ≤ 15 minutes**, **RTO ≤ 4 hours**.
- **Restore drills** on a schedule (e.g. quarterly), recorded in `PROGRESS.md`; an untested backup is not a backup.
- **Provider-side loss:** because we keep our own copies and vintages, a provider deleting history does not delete ours.

---

## 6. Entity classification ("who is moving it") — ADR-0006

"Institutional", "ETF", "exchange", "market maker", "hedge fund", "government", "whale", "retail" are **claims** that need evidence (R5).

- Labels live in `ref.entity_label` and are **bitemporal**: `valid_from`/`valid_to` (when the label is true in the world) and
  `available_at`/`recorded_at` (when the label became knowable / when we stored it). Historical analysis uses only labels knowable at `as_of`.
- Each label records `evidence_class` — `direct` (the source identifies the actor: issuer reports, filings, exchange-published data),
  `attributed` (a named third party's label, provider recorded), or `inferred` (heuristic, e.g. size band, venue mix, cross-venue premium) —
  plus `confidence` and the rule or source that produced it.
- Composites such as "institutional flow" and "retail activity" record the evidence mix of their inputs, and the UI shows it
  (e.g. "ETF inflow — direct" vs. "large-wallet accumulation — inferred").
- Large ≠ institutional. Small ≠ retail. Unlabelled entities are `unknown`.
- **Implemented in Phase 7** (ADR-0049) for on-chain addresses: classes `exchange`, `institution`, `fund`,
  `market_maker`, `protocol`, `miner`, `government`, `other` (each needs a named entity and a direct or attributed
  label) and `unknown_large_holder` (inferred from size only, no entity). Database checks make an inferred
  institution, fund or market maker impossible to store. Precedence: direct > attributed > confidence > newest;
  disagreeing labels are shown as conflicts.

---

## 7. User layer: decision journal and paper trading — ADR-0036

- **Decision journal (L6):** append-only entries linking the decision, rationale, the `snapshot_id` and `interpretation_id` viewed,
  the user's own hypotheses (tagged `hypothesis`), planned invalidation conditions, and a later outcome review. Edits create new versions.
- **Paper trading:** simulated accounts, orders, fills, positions, and PnL using the **same execution and cost model** as backtesting (§5.16),
  with fills priced from point-in-time market data plus latency and slippage. Every paper order can link to a journal entry.
- **No live execution:** the platform holds no trading-enabled keys and has no order-routing component (ADR-0007).

---

## 8. Repository layout — ADR-0015, ADR-0045

```
FINANCIAL TOOL/
├── CLAUDE.md  README.md  ARCHITECTURE.md  DATA_DICTIONARY.md  DECISIONS.md  PROGRESS.md  TODO.md
├── compose.yaml  .env.example  .github/workflows/ci.yml          (created in Phase 3)
├── backend/                                                        (created in Phase 3; Dockerfile here)
│   ├── Dockerfile  pyproject.toml  uv.lock  alembic.ini
│   ├── src/cfi/
│   │   ├── core/          # config, time (UTC, calendars), errors, logging, ids
│   │   ├── domain/        # canonical models (no provider code)
│   │   ├── db/            # engine, schemas, point-in-time loader, repositories
│   │   ├── providers/     # http client layer, rate limits, circuit breaker; adapters/<provider>/
│   │   ├── ingestion/     # dataset registry, pipeline, backfill, reconcile
│   │   ├── quality/       # checks, propagation
│   │   ├── metrics/  signals/  regime/  analysis/   # L2–L4 and similarity/anomaly/rotation/divergence
│   │   ├── backtest/      # experiments, splitters, cost model, engines
│   │   ├── ai/            # snapshot builder, prompts/, client, validator, evals/
│   │   ├── alerts/  journal/  paper/
│   │   ├── api/           # FastAPI app, routers, auth, schemas
│   │   └── workers/       # Celery app, queues, schedules
│   ├── migrations/        # Alembic
│   └── tests/             # unit/ integration/ db/ api/ quant/ (historical fixtures) leakage/ ai_eval/
├── frontend/                                                       (created in Phase 3; Dockerfile here)
│   ├── Dockerfile  package.json  pnpm-lock.yaml
│   └── src/ (app/, components/, charts/, lib/api-client/ generated)
├── infra/                 # not yet created — observability config, production deployment (later)
└── docs/                  # extended docs if needed
```

---

## 9. Deployment topology — ADR-0014, ADR-0037

**Development (Windows + Docker Desktop with WSL2):** one Compose project (`compose.yaml`, implemented in Phase 3):
`db` (timescale/timescaledb:2.30.1-pg17) · `redis` (redis:8.8-alpine) · `migrate` (Alembic, runs once) · `api` · `frontend`.
Planned later: `worker` (one per queue group) · `beat` · optional `prometheus`/`grafana`.
Named Docker volumes for data (not bind-mounted from `E:`). Images are built from source (no bind mounts in Phase 3);
for hot reload, run the API or frontend locally with uv/pnpm against the Compose database and Redis.
Note: bind mounts from Windows drives into Linux containers are slow; placing the working copy inside the WSL2 filesystem is faster — needs a decision.

**First production (later phase):** a single Linux host (VPS) running the same Compose project behind a reverse proxy with TLS,
off-site backups, and monitoring. Managed Postgres/Timescale is an alternative. Container orchestration (Kubernetes) only if load demands it.
The hosting location must allow access to the chosen exchange APIs (jurisdiction restrictions vary by provider and must be verified).

---

## 10. Component-to-phase map

Phases 0–5 are defined by the user's guide; later phase numbers in `CLAUDE.md` §C3 are provisional until the user issues each phase.

| Component | Planned phase (provisional) |
|---|---|
| Infrastructure (Compose, DB, migrations baseline, CI, tooling) | 3 — done |
| Ingestion engine, provider client layer, dataset registry, quality detection | 4 — done |
| Market data: OHLCV, last trade, market cap, workers, market API, Market page | 5 — done |
| Institutional capital: ETF flows (BTC, ETH, SOL, XRP), treasuries, Institutional Flow Score, Flows page | 6 — done |
| Whale intelligence: exchange flows, top holders, large transfers, coin age, entity labels, Whale Flow Score, Whales page | 7 — done |
| Derivatives, liquidity, retail, macro, market-structure datasets and metrics | 8+ (to be issued) |
| Divergence, regime, similarity, backtesting, red-team, anomaly, rotation | 12–18 |
| AI analyst (snapshot, prompts, validator, evals) | 19 |
| Daily intelligence, alerts, paper trading, decision journal | 20–23 |
| Executive dashboard (frontend) | 24 |
| Security + AI + stress testing | 25 |
| Production, real-time intelligence | 26–27 |

---

## 11. Architectural risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | Look-ahead via backfilled/revised data | Inflated backtests, false confidence | Bitemporal model, `pit_reliability`, leakage tests (§5.25) |
| 2 | "Institutional" labels are mostly inference | Misleading conclusions | `evidence_class` + confidence everywhere; UI separates direct from inferred (R5) |
| 3 | Paid data costs and restrictive terms | Budget overrun; unusable data | Provider budgets, request ledger, terms recorded before ingestion |
| 4 | Exchange API geo-restrictions | Missing datasets depending on host location | Several providers per dataset; failures visible in provider health and on the Market page; `CFI_MARKET_PROVIDERS` to disable blocked ones. Known: Binance, OKX, Bybit, Kraken blocked by Philippine ISPs (2024–2025) |
| 5 | Short crypto history (few cycles) | Overfit regimes/similarity | Walk-forward, trial counting, Phase 16 red-team |
| 6 | AI hallucinated numbers | Wrong decisions | Snapshot grounding + deterministic validator + eval harness |
| 7 | TimescaleDB licence (TSL) limits | Cannot offer the DB itself as a service | Our use (own application) is permitted; revisit if the business model changes |
| 8 | Scope size (28 phases) vs. one developer | Stalled project | Batch-first, vertical slices, strict phase gates |
| 9 | Windows development friction (Celery unsupported natively, slow bind mounts, path with space) | Slow/fragile dev loop | Everything in Linux containers; consider WSL2 working copy |
| 10 | Single Postgres node as single point of failure | Downtime/data loss | Backups + PITR, restore drills, replica later |
