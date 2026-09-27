# DECISIONS.md — Architecture Decision Records

Each decision records **context → decision → consequences** (ADR-0001–0013) or
**decision · reason · alternatives · trade-offs · future implications** (ADR-0014 onward). Decisions are never deleted;
a changed decision gets a new ADR that supersedes the old one.

Status values: `Proposed` (awaiting the user's confirmation) · `Accepted` · `Superseded by ADR-xxxx` · `Rejected`.

| ADR | Title | Status | Date |
|---|---|---|---|
| 0001 | Strict one-way layer architecture | Accepted | 2026-09-23 |
| 0002 | Database and statistical engine are the source of truth; AI never supplies data | Accepted | 2026-09-23 |
| 0003 | Point-in-time (bitemporal) data model | Accepted | 2026-09-23 |
| 0004 | Missing data is an explicit state | Accepted | 2026-09-23 |
| 0005 | Provider abstraction per dataset | Accepted | 2026-09-23 |
| 0006 | Entity classification requires evidence class and confidence | Accepted | 2026-09-23 |
| 0007 | Decision-support, not advice or prediction | Accepted | 2026-09-23 |
| 0008 | Core technology stack | Superseded by ADR-0014 | 2026-09-23 |
| 0009 | Batch first, real-time last | **Proposed** | 2026-09-23 |
| 0010 | UTC timestamps and exact decimals in storage | Accepted (precision for high-volume data: see ADR-0044) | 2026-09-23 |
| 0011 | Git workflow and LF line endings | Accepted | 2026-09-23 |
| 0012 | Numbered phases (0–27) instead of letters | Accepted | 2026-09-23 |
| 0013 | Master engineering rules (CLAUDE.md R1–R13) | Accepted | 2026-09-23 |
| 0014 | Technology stack | Accepted | 2026-09-23 |
| 0015 | Service boundaries and monorepo | Accepted | 2026-09-23 |
| 0016 | PostgreSQL + TimescaleDB as the single primary store | Accepted | 2026-09-23 |
| 0017 | Hybrid storage model with a series registry | Accepted | 2026-09-23 |
| 0018 | Bitemporal knowledge model | Accepted | 2026-09-23 |
| 0019 | Raw payload archive in object storage | Accepted | 2026-09-23 |
| 0020 | Time-series strategy | **Proposed** | 2026-09-23 |
| 0021 | Ingestion pipeline and dataset registry | **Proposed** | 2026-09-23 |
| 0022 | Provider adapters, health, fallback, and rate limits | **Proposed** | 2026-09-23 |
| 0023 | Background processing with Celery | Accepted | 2026-09-23 |
| 0024 | Redis role and licence | Accepted | 2026-09-23 |
| 0025 | API design | **Proposed** | 2026-09-23 |
| 0026 | Authentication | Accepted | 2026-09-23 |
| 0027 | Authorization and database-role enforcement | Accepted | 2026-09-23 |
| 0028 | Security baseline | **Proposed** | 2026-09-23 |
| 0029 | Observability and logging | **Proposed** | 2026-09-23 |
| 0030 | Error handling taxonomy | **Proposed** | 2026-09-23 |
| 0031 | Data quality framework | **Proposed** | 2026-09-23 |
| 0032 | Historical data and point-in-time reliability | Accepted | 2026-09-23 |
| 0033 | Backtesting architecture | **Proposed** | 2026-09-23 |
| 0034 | AI architecture and grounding | Accepted | 2026-09-23 |
| 0035 | Alert architecture | **Proposed** | 2026-09-23 |
| 0036 | Decision journal and paper trading | **Proposed** | 2026-09-23 |
| 0037 | Scalability path and real-time processing | **Proposed** | 2026-09-23 |
| 0038 | Cost control | **Proposed** | 2026-09-23 |
| 0039 | Time zones and calendars | **Proposed** | 2026-09-23 |
| 0040 | Bias and leakage controls | **Proposed** | 2026-09-23 |
| 0041 | Reproducibility and versioning | **Proposed** | 2026-09-23 |
| 0042 | Disaster recovery | **Proposed** | 2026-09-23 |
| 0043 | Charting libraries | Accepted | 2026-09-23 |
| 0044 | Numeric precision for high-volume data | Accepted — keep `NUMERIC` (benchmark in Phase 5) | 2026-09-23 |
| 0045 | Phase 3 foundation implementation choices | Accepted | 2026-09-23 |
| 0046 | Phase 4 ingestion engine implementation choices | Accepted | 2026-09-23 |
| 0047 | Phase 5 market-data layer: providers, storage, workers, API, dashboard | Accepted | 2026-09-23 |
| 0048 | Phase 6 institutional capital: sources, storage, aggregation, transparent score | Accepted (amended twice: pacing; `avg_btc_cost`, Farside, HYPE) | 2026-09-24 |
| 0049 | Phase 7 whale intelligence: sources, entity classification, transfers, transparent score | Accepted | 2026-09-24 |
| 0050 | Phase 8 derivatives: sources, quote storage, calculations, Derivatives Health Score | Accepted | 2026-09-26 |

---

## ADR-0001 — Strict one-way layer architecture
**Status:** Accepted (user requirement, Phase 0)

**Context.** Financial dashboards often blur what was observed, what was calculated, and what was opined. That makes errors invisible and interpretations look like facts.

**Decision.** Data flows one way: Observed → Metrics → Signals → Regime → AI Interpretation → User Decision (plus an immutable raw layer beneath Observed). A layer reads only from layers to its left and never writes to them.

**Consequences.** Every derived value is rebuildable and auditable. Slightly more storage and plumbing. Features that "shortcut" layers (e.g. AI writing a metric) are forbidden.

---

## ADR-0002 — Source of truth; AI never supplies data
**Status:** Accepted (user requirement)

**Context.** Language models can produce plausible but false numbers.

**Decision.** The database and statistical engine are the only sources of numbers. Claude receives an immutable snapshot, must cite snapshot field IDs for every number, and its output passes a deterministic validator before storage/display. AI output is always labelled as interpretation.

**Consequences.** Requires a snapshot builder and validator (Phase 19). Claude cannot answer questions whose data is not in the snapshot — it must say the data is missing.

---

## ADR-0003 — Point-in-time (bitemporal) data model
**Status:** Accepted

**Context.** Many sources publish with delay (ETF flows, filings, macro releases) or revise past values; entity labels change over time. Using present knowledge in historical calculations inflates backtests (look-ahead bias).

**Decision.** Every observation stores `event_time`, `available_at`, `ingested_at`, and a `revision` number. All historical computations query with `available_at <= as_of`. Where the source gives no publication time, a documented availability rule sets a conservative `available_at` and flags it as estimated. Entity labels are time-versioned (`valid_from`/`valid_to`).

**Consequences.** More complex queries and storage; needs dedicated leakage tests. In exchange, backtests and historical similarity are honest.

---

## ADR-0004 — Missing data is an explicit state
**Status:** Accepted

**Decision.** Missing values are `NULL` + `quality_status = missing`, never zero. Filling is allowed only when a metric's definition explicitly permits it, and the result is flagged `estimated`. Metrics inherit the worst quality of their inputs. Quality status is shown in the UI and in AI snapshots.

**Consequences.** Some signals will be unavailable on some days; that is correct behaviour.

---

## ADR-0005 — Provider abstraction per dataset
**Status:** Accepted

**Decision.** One adapter per provider behind a common interface; each dataset lists eligible providers with priority. Provider symbols/units never leak past normalisation. No silent blending: a fallback is recorded as a source change. Abstraction is built only where ≥2 realistic providers exist; single-source datasets are wrapped simply and the dependency is documented here.

**Consequences.** Avoids lock-in to one vendor; some duplicated mapping work.

---

## ADR-0006 — Entity classification requires evidence
**Status:** Accepted

**Decision.** Every actor label (institutional, whale, retail, exchange…) records `evidence_class` (`direct` / `attributed` / `inferred`), confidence, rule or source, and validity period. The UI distinguishes direct from inferred evidence.

**Consequences.** "Institutional vs retail" becomes a spectrum of evidence strength rather than a binary claim. Some popular dashboard labels will be shown as low-confidence proxies.

---

## ADR-0007 — Decision-support, not advice or prediction
**Status:** Accepted (user requirement)

**Decision.** The platform presents evidence, divergences, regimes, historical analogues, and scenarios with confidence and invalidation conditions. It does not issue buy/sell instructions or price targets presented as certain. Paper trading is simulation only; no live order execution is in scope.

---

## ADR-0008 — Core technology stack
**Status:** Superseded by ADR-0014 (Phase 2 architecture)

**Proposal.** Python 3.12+; PostgreSQL with TimescaleDB; SQLAlchemy + Alembic; Pydantic; Polars/pandas, NumPy, SciPy, statsmodels; FastAPI; a simple scheduler first; Docker Compose (Docker Desktop + WSL2 on Windows); pytest, ruff, mypy, pre-commit. Dashboard technology deferred to Phase 24.

**Alternatives considered.**
- DuckDB/Parquet only: excellent for research, weaker for a multi-user service with concurrent writes. Could still be used for offline research/backtests.
- ClickHouse: very fast analytics, more operational overhead than needed at this stage.
- Node/TypeScript backend: weaker statistics/backtesting ecosystem.

**Open questions.** Whether Docker Desktop is acceptable on the development machine; hosting target for production.

---

## ADR-0009 — Batch first, real-time last
**Status:** Proposed

**Decision.** Build all phases on scheduled batch ingestion (hourly/daily). Streaming (websocket) ingestion is added only in the final "Real-time intelligence" stage, and only for datasets where latency demonstrably matters (liquidations, funding, order book).

**Consequences.** Faster, simpler development; intraday alerting is limited until the real-time stage.

---

## ADR-0010 — UTC timestamps and exact decimals
**Status:** Accepted

**Decision.** All timestamps are timezone-aware UTC. Prices, sizes, and flows are stored as exact decimals; floats are used only inside statistical computations. Every numeric field has an explicit unit; rates state their period.

---

## ADR-0011 — Git workflow and LF line endings
**Status:** Accepted

**Decision.** `main` is always green; feature work on `phase-<number>/<name>` branches; small commits prefixed with the phase number (e.g. `[P3] add provider interface`) — amended by ADR-0012. `.gitattributes` normalises text files to LF so the repo behaves identically on Windows and Linux. Secrets are never committed (`.env` is git-ignored).

---

## ADR-0012 — Numbered phases instead of letters
**Status:** Accepted (user requirement)

**Context.** Phases were originally labelled A–Z. The user prefers numbers.

**Decision.** Phases are numbered from 0: A→0 (Project foundation), B→1 (Architecture) … Z→25 (Security + AI + stress testing), then 26 (Production) and 27 (Real-time intelligence). Commit prefix is `[P<number>]`; branches are `phase-<number>/<name>`.

**Consequences.** The first commit (`d59cb20`) keeps its original `[A]` label; `[A]` = Phase 0. No other history is affected.

**Amendment (2026-09-23).** At the user's direction, Phase 1 is "Master engineering rules" rather than "Architecture".
The architecture design work is unscheduled until the user places it in the phase plan.
**Amendment 2 (2026-09-23).** The user's guide defines Phase 2 as "Architecture" (ADR-0014 – ADR-0044). Infrastructure is unscheduled;
phase numbers from 3 onward are provisional.

**Amendment 3 (2026-09-27).** The user issued "PHASE 11 — MACRO" directly, so Phase 11 is now "Macroeconomic data
layer" (see ADR-0054), not "Market structure" as the provisional table previously listed at that number. "Market
structure" is unscheduled again until the user places it; phase numbers from 12 onward remain provisional until
each is issued, same as before.

**Amendment 4 (2026-09-27).** The user issued "PHASE 12 — MARKET STRUCTURE" directly, so Phase 12 is now "Market
structure engine" (see ADR-0055). The phases the provisional table previously listed at 12–27 ("Divergence
engine", "Regime engine", and every phase after) each shift down by one, to 13–28; phase numbers from 13 onward
remain provisional until each is issued, same as before.

---

## ADR-0013 — Master engineering rules
**Status:** Accepted (user requirement, Phase 1)

**Context.** The user issued thirteen engineering principles that govern every phase.

**Decision.** They are recorded in `CLAUDE.md` Part B as rules R1–R13 and take precedence over later convenience.
Consequences for existing designs, applied in the same change:
- The evidence hierarchy gains a sixth category, **Hypothesis**, kept separate from AI Interpretation (R2).
- Every observation carries `metric`, `asset`, `original_source` (vs. `source_provider`), and a nullable `confidence` (R3).
- New quality status `conflicting` for cross-provider disagreement; conflicts are shown, not resolved silently (R3).
- The AI output contract is fixed to nine sections, with the literal phrase "Insufficient data." for gaps (R6).
- Adapters must handle the eleven failure modes listed in R8; backtests must model the costs and constraints in R4.

**Consequences.** More fields and tests per feature. The rules are the checklist for reviews and for Phase 16 (quant red-team).

---

# Phase 2 architecture decisions (ADR-0014 – ADR-0044)

Format for each: **Decision · Reason · Alternatives considered · Trade-offs · Future implications.**
"Proposed" = needs the user's approval (see `TODO.md` → Architecture Approval Checklist).

---

## ADR-0014 — Technology stack
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A1). Was: Proposed (stack proposed by the user; supersedes ADR-0008)

**Decision.** Frontend: Next.js (App Router), React, TypeScript (strict). Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, psycopg 3,
Alembic. Numerics: NumPy, pandas and/or Polars, SciPy, statsmodels. Database: PostgreSQL + TimescaleDB. Cache/broker: Redis.
Jobs: Celery. AI: Anthropic Claude API. Containers: Docker + Docker Compose. Tooling: uv, ruff, mypy, pytest; pnpm, ESLint, Vitest.

**Reason.** Python has the strongest statistics/backtesting ecosystem; FastAPI gives typed, documented APIs with little code; Next.js/React/TypeScript
is the most widely supported way to build a rich dashboard; Postgres + Timescale keeps relational and time-series data in one queryable place.

**Alternatives considered.** Node/TypeScript backend (one language, weaker quant ecosystem); Django (heavier, ORM-centric, less suited to
time-series APIs); Streamlit/Dash-only frontend (fast to build, limited for a production multi-page app with auth and live updates).

**Trade-offs.** Two languages (Python + TypeScript) and two toolchains; mitigated by generating the TypeScript API client from OpenAPI.

**Future implications.** Hiring/tooling is mainstream. Heavy research may later add DuckDB/Parquet alongside Postgres without changing the stack.

---

## ADR-0015 — Service boundaries and monorepo
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A2). Was: Proposed

**Decision.** One Git repository with `backend/`, `frontend/`, `infra/`. FastAPI is the **only** gateway to data; Next.js is presentation-only
(no direct DB access, no Claude calls, no business logic). Workers and API share the backend codebase but run as separate processes.

**Reason.** A single owner of data access keeps the layer rules, authorization, and evidence labelling in one place. One repo keeps API contract,
migrations, and UI changes in the same commit.

**Alternatives considered.** Separate repos per service (more overhead, harder atomic changes); Next.js server routes querying Postgres directly
(duplicates logic, bypasses DB-role separation); microservices per domain (premature).

**Trade-offs.** The API becomes a dependency for every screen; an extra network hop compared with direct DB access from Next.js.

**Future implications.** Services can still be split later (e.g. a separate real-time service) because boundaries are clear from day one.

---

## ADR-0016 — PostgreSQL + TimescaleDB as the single primary store
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A3). Was: Proposed

**Decision.** Self-hosted PostgreSQL with the TimescaleDB extension holds all layers, organised into schemas `ref`, `raw`, `obs`, `calc`, `sig`,
`regime`, `ai`, `usr`, `ops`.

**Reason.** Point-in-time queries are joins across reference data, observations, and revisions — easiest in one SQL database. Timescale adds
time partitioning (hypertables), compression, continuous aggregates, and retention policies on top of standard Postgres.

**Alternatives considered.** ClickHouse (very fast analytics, weaker transactional/relational features, more operations); InfluxDB/QuestDB
(time-series focus, weaker relational joins); DuckDB/Parquet only (excellent for research, not a concurrent multi-writer service DB);
plain Postgres with native partitioning (workable, but more manual work for compression/rollups).

**Trade-offs.** Several key Timescale features are under the **Timescale License (TSL)**: free for use in our own application, but it forbids
offering the database itself as a service to third parties. Vertical scaling limits exist for a single node.

**Future implications.** If the product is ever sold as SaaS, our use remains an application built on Timescale (permitted as we understand the licence),
but this must be re-checked with the licence text at that time. A managed Timescale service is an option for production.

---

## ADR-0017 — Hybrid storage model with a series registry
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A4). Was: Proposed

**Decision.** `obs.series` registers every observed series (metric, subject, venue, period, unit). High-volume multi-field data uses **typed
hypertables** (`market_bar`, `funding_rate`, `open_interest`, `liquidation_event`, `orderbook_depth`, `option_quote`, `onchain_transfer`);
lower-volume single-value series use one **generic scalar hypertable** `obs.observation`. All carry the same provenance columns.
Values from multiple providers coexist; a selection view applies provider priority and records the provider used.

**Reason.** Typed tables are compact and fast for OHLCV/options; a generic table avoids dozens of near-identical tables for scalar series.
The registry makes "what is this number" a single lookup and keeps rows narrow.

**Alternatives considered.** One generic entity–attribute–value table for everything (flexible, but poor for multi-field records and very large);
one typed table per dataset (clear, but table sprawl and repeated code); document store/JSONB for L1 (flexible, weak typing and indexing).

**Trade-offs.** Two access patterns to maintain; queries across typed and scalar data need the point-in-time loader to unify them.

**Future implications.** New scalar datasets need no migration (just registry rows); new multi-field families need a new typed table.

---

## ADR-0018 — Bitemporal knowledge model
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A5). Was: Proposed (implements accepted ADR-0003)

**Decision.** Every L1 row has `event_time` (when it happened), `available_at` (when publicly knowable), `ingested_at` (when we stored it), and
`revision`. Reference data and entity labels have valid time and record time. Queries support two cut-offs: `as_of` on `available_at`
(what the world could know) and `knowledge_time` on `ingested_at` (what our system knew).

**Reason.** Backtests need "what could have been known"; audits of past dashboards and AI outputs need "what we actually had".
Without both, revisions and late backfills silently change history.

**Alternatives considered.** Single timestamp (simple, leaks revisions); overwrite-on-revision (loses history); snapshots of whole tables per day
(heavy storage, coarse).

**Trade-offs.** Larger rows and indexes; more complex queries (hidden behind the point-in-time loader); every developer must understand it.

**Future implications.** Enables honest backtests, reproducible AI audits, and "view dashboard as of date X" as a product feature.

---

## ADR-0019 — Raw payload archive in object storage
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A6). Was: Proposed

**Decision.** Every provider response body is written once, compressed, to an archive (local filesystem in development; S3-compatible object
storage with versioning in production), addressed by content hash. `raw.payload` in Postgres indexes it (provider, endpoint, params, received_at,
hash, size, schema check result).

**Reason.** Keeps the database lean while preserving the exact source material for audits, re-parsing after bug fixes, and rebuilding L1.

**Alternatives considered.** JSONB bodies in Postgres (simple, but bloats the primary DB and backups); not storing raw payloads (loses auditability
and recovery); a full data lake from day one (over-engineering).

**Trade-offs.** A second storage system to back up; two-step reads when auditing.

**Future implications.** Lifecycle rules can move old payloads to cheaper storage; the archive doubles as disaster-recovery material.

---

## ADR-0020 — Time-series strategy
**Status:** Proposed (retention periods need approval)

**Decision.** Hypertables on the time column; chunk intervals per family sized by volume; compression for chunks older than a family-specific age,
segmented by `series_id`; continuous aggregates **only for non-revisable families**; retention tiers — full resolution for a defined window,
then rollups; low-frequency L1 data never deleted.

**Reason.** Keeps storage and query cost manageable while protecting point-in-time correctness (continuous aggregates cannot respect
`available_at` or revisions).

**Alternatives considered.** Keep everything at full resolution forever (simple, costly); aggregate everything with continuous aggregates
(fast, leaks revisions); external rollup jobs only (more code).

**Trade-offs.** Writing revisions into compressed chunks is slower; chunk/compression settings need tuning after real measurements.

**Future implications.** Retention choices limit how far back tick-level research can go; they must be decided before large ingestion starts.

---

## ADR-0021 — Ingestion pipeline and dataset registry
**Status:** Proposed

**Decision.** Every ingestion follows: rate-limit token → fetch → archive L0 → schema validation → normalise → quality checks → idempotent upsert
into L1 → job record → `dataset_updated` event. A dataset registry defines providers and priority, schedule, freshness limit, availability rule,
history start, conflict tolerance, and retention. Job types: `ingest`, `backfill`, `reconcile`, `gap_fill`.

**Reason.** One pipeline gives every dataset the same guarantees (R3, R8) and makes adding a dataset mostly configuration.

**Alternatives considered.** Ad-hoc scripts per source (fast to start, inconsistent guarantees); a data-orchestration framework such as Dagster or
Airflow (strong lineage/UI, but heavier operationally and overlapping with Celery).

**Trade-offs.** Up-front framework work in the ingestion phase before the first dataset lands.

**Future implications.** The same pipeline stages serve the future streaming path; an orchestrator can be added later if scheduling complexity grows.

---

## ADR-0022 — Provider adapters, health, fallback, and rate limits
**Status:** Proposed

**Decision.** One adapter per provider (fetch/parse/normalise + declared capabilities and terms) on top of a shared HTTP client layer providing
timeouts, retries with exponential backoff and jitter, Redis-backed token buckets shared across workers, circuit breakers, payload archiving,
and a request ledger. Fallback to a secondary provider is per dataset, explicit, and recorded; never blended.

**Reason.** Centralising resilience means every provider gets all R8 protections without copy-pasted code, and provider code cannot leak into the domain.

**Alternatives considered.** Per-adapter resilience code (duplication, inconsistency); third-party aggregator as the single source (simple, but
single-provider dependency and opaque provenance).

**Trade-offs.** A shared client layer must be flexible enough for REST pagination styles, weights, and auth schemes.

**Future implications.** Provider scorecards (uptime, latency, conflict rate) accumulate from day one and inform paid-provider decisions.

---

## ADR-0023 — Background processing with Celery
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A7); implemented for market data in Phase 5 (ADR-0047). Was: Proposed (Celery named by the user; alternatives listed for approval)

**Decision.** Celery workers with a Redis broker; Celery beat for schedules; queues `ingest_fast`, `ingest`, `backfill`, `compute`, `ai`,
`alerts`, `maintenance`; idempotent tasks with late acknowledgement, time limits, and transient-only retries; `ops.job_run` in Postgres as
the job history of record.

**Reason.** Mature, widely used in Python, supports routing, retries, schedules, and many workers; fits the user's proposal.

**Alternatives considered.** Dramatiq (simpler, fewer features); Arq/RQ (lightweight, less routing/scheduling depth); Temporal (durable workflows,
heavier to operate); Dagster/Prefect (data orchestration with lineage UI, heavier and overlapping).

**Trade-offs.** Celery configuration is intricate (visibility timeouts, acknowledgement semantics); not supported on Windows natively
(runs in Linux containers); broker is Redis, so Redis availability matters for job flow.

**Future implications.** If long multi-step workflows (e.g. multi-day backfills) become painful, Temporal or Dagster can be introduced for those only.

---

## ADR-0024 — Redis role and licence
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A8). Was: Proposed

**Decision.** Redis serves as Celery broker, cache, shared rate-limit state, session store, pub/sub for live updates, and (later) Streams for
real-time ingestion. It is never a source of truth. Cache invalidation is by data-version counters plus short TTLs.

**Reason.** One fast in-memory component covers several needs with little operational cost.

**Alternatives considered.** Valkey (Linux Foundation fork, BSD licence, wire-compatible); RabbitMQ as broker (more robust delivery semantics, one more
service); Memcached for cache (cache only).

**Trade-offs.** Redis 8 is offered under RSALv2, SSPLv1, or AGPLv3 (user's choice); using it unmodified inside our own system is not restricted in
practice, but some organisations avoid these licences — Valkey is a drop-in alternative. Several roles on one Redis instance share failure fate.

**Future implications.** Roles can be split across separate Redis instances (broker vs. cache) when load or reliability requires.

---

## ADR-0025 — API design
**Status:** Proposed

**Decision.** REST at `/api/v1` with OpenAPI; generated TypeScript client; evidence envelope on every data response (category, `as_of`,
`knowledge_time`, quality, sources, definition version, lineage link); `as_of` accepted on all reads; read-only for L0–L5; long work requested
via job endpoints; Server-Sent Events for live updates; RFC 9457 problem-details errors; cursor pagination with mandatory time bounds.

**Reason.** Simple, cacheable, well-tooled; the envelope enforces R2 at the contract level; `as_of` makes point-in-time a user-visible feature.

**Alternatives considered.** GraphQL (flexible queries, harder caching and cost control); tRPC (TypeScript-only); gRPC (great for services,
awkward for browsers); WebSockets for all live data (two-way, more complex than needed).

**Trade-offs.** Some screens need several calls (mitigated by purpose-built dashboard endpoints).

**Future implications.** Public or partner API access later can reuse the same contract with API tokens.

---

## ADR-0026 — Authentication
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A9). Was: Proposed

**Decision.** FastAPI-owned accounts; Argon2id password hashing; mandatory TOTP two-factor for owner/admin; server-side sessions in an
`HttpOnly`, `Secure`, `SameSite=Lax` cookie with CSRF protection; frontend and API under one site via a reverse proxy; scoped, expiring,
hashed personal API tokens for scripts.

**Reason.** Revocable sessions and no tokens in browser JavaScript; no external dependency for a single-user start; strong protection for a
system that will hold paid API keys.

**Alternatives considered.** Hosted identity provider (Auth0, Clerk) — fast, external dependency and cost; self-hosted Keycloak/Authentik —
full-featured, heavy for one user; Auth.js in Next.js — puts auth in the presentation layer; stateless JWTs — hard to revoke.

**Trade-offs.** We maintain the auth code (small, but security-sensitive; needs tests and review in Phase 25).

**Future implications.** OIDC login can be added later without changing sessions or roles.

---

## ADR-0027 — Authorization and database-role enforcement
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A10). Was: Proposed

**Decision.** Application roles `owner`, `analyst`, `viewer`; per-user ownership of user-layer rows; separate Postgres roles per service
(`cfi_ingest`, `cfi_compute`, `cfi_ai`, `cfi_alerts`, `cfi_api`, `cfi_readonly`, `cfi_migrator`) with grants that mirror the layer rule.

**Reason.** Defence in depth: the layer rule (ADR-0001) is enforced by the database even if application code has a bug.

**Alternatives considered.** Single DB user for all services (simple, no protection); Postgres row-level security for all tables
(powerful, complex; may be used later for multi-tenant user data).

**Trade-offs.** More connection configurations and migration grant management.

**Future implications.** Multi-user or multi-tenant use later can add row-level security on `usr` without redesign.

---

## ADR-0028 — Security baseline
**Status:** Proposed

**Decision.** Secrets via environment/secret manager only; read-only exchange keys only (never trading or withdrawal); only the reverse proxy
exposed; TLS; strict CORS, CSRF, Content-Security-Policy; parameterised SQL; ingested text treated as untrusted data in AI prompts; lockfiles,
pinned images, vulnerability scanning, non-root containers; append-only audit log; encrypted backups.

**Reason.** The system will hold paid API credentials and personal decision data, and it feeds external text to an AI model.

**Alternatives considered.** Deferring security to Phase 25 (cheaper now, expensive retrofits later).

**Trade-offs.** Slightly more setup in the infrastructure phase.

**Future implications.** Phase 25 becomes verification and hardening, not a redesign.

---

## ADR-0029 — Observability and logging
**Status:** Proposed (tooling level needs approval)

**Decision.** Structured JSON logs with correlation IDs; OpenTelemetry tracing; Prometheus metrics; Grafana dashboards for system health, data
freshness/quality, provider health, AI usage/validation, and cost. Application logs kept short-term; audit log and job runs kept in Postgres.

**Reason.** Most failures in a data platform are silent (stale feeds, partial data); they must be visible as metrics, not discovered in charts.

**Alternatives considered.** Logs only (cheapest, weak for trends); hosted SaaS observability (fast, recurring cost, data leaves the host);
Sentry for error tracking (useful add-on; optional).

**Trade-offs.** Two more containers (Prometheus, Grafana) and some instrumentation work.

**Future implications.** The same signals drive data-quality alerts and provider scorecards.

---

## ADR-0030 — Error handling taxonomy
**Status:** Proposed

**Decision.** Typed errors: `ProviderTransientError`, `ProviderPermanentError`, `SchemaMismatchError`, `DataValidationError`,
`InsufficientDataError`, `ComputationError`, `AIValidationError`, each with a defined handling (retry, alert, mark quality, fail loudly).
Partial failures produce `partial` quality with named gaps. API errors as RFC 9457 problem details.

**Reason.** R3/R7 forbid hiding errors; a taxonomy makes "retry vs. stop vs. mark" consistent.

**Alternatives considered.** Generic exceptions with log-and-continue (hides problems).

**Trade-offs.** Discipline required when adding code paths.

**Future implications.** Error codes become stable identifiers for alerts and dashboards.

---

## ADR-0031 — Data quality framework
**Status:** Proposed

**Decision.** Declarative checks per dataset (freshness, coverage, range/unit sanity, monotonicity, duplicates, cross-provider consistency, schema,
continuity) run after every ingest; results stored historically; statuses propagate worst-of to derived layers, snapshots, dashboards, alerts.

**Reason.** R3 requires stale, missing, and conflicting data to be visible; quality must travel with the numbers.

**Alternatives considered.** A data-testing framework (e.g. Great Expectations) — powerful, heavy; ad-hoc checks in each adapter — inconsistent.

**Trade-offs.** Some duplicated effort with adapter-level validation; thresholds need tuning.

**Future implications.** Quality history supports provider evaluation and explains past signal failures.

---

## ADR-0032 — Historical data and point-in-time reliability
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A5). Was: Proposed

**Decision.** Record history start per dataset; tag rows with `pit_reliability` (`native`, `vendor_pit`, `backfilled_latest`); keep our own vintages of
sources that overwrite history; resumable, low-priority backfills; research extracts only through the point-in-time loader.

**Reason.** Much historical crypto data is served "as it looks today"; treating it as point-in-time would leak future information.

**Alternatives considered.** Treat all history as point-in-time (simple, biased); refuse any backfilled data (honest but leaves little history).

**Trade-offs.** Backtests over older periods carry explicit reliability caveats.

**Future implications.** The longer the system runs, the more `native` history it owns — a compounding asset.

---

## ADR-0033 — Backtesting architecture
**Status:** Proposed (build-vs-library needs approval)

**Decision.** In-house thin framework: point-in-time loader as the only data door; experiment registry (spec, parameters, code SHA, data
`knowledge_time`, trial count); walk-forward and purged/embargoed splits; a vectorised research engine and an event-driven simulator that share
one execution-and-cost model (fees, slippage vs. liquidity, execution delay, funding, turnover, sizing, missing data).

**Reason.** Existing libraries do not natively enforce our bitemporal data model, crypto funding costs, or trial accounting; the core is small.

**Alternatives considered.** vectorbt (fast vectorised, not point-in-time aware); Backtrader/Zipline-reloaded (event-driven, equity-oriented,
aging); NautilusTrader (high-performance event-driven, larger learning curve). Any of these could be wrapped behind our loader later.

**Trade-offs.** We own correctness of the simulator; must be validated against hand-computed historical fixtures (R11).

**Future implications.** The same execution model powers paper trading, so paper results and backtests are comparable.

---

## ADR-0034 — AI architecture and grounding
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A11). Was: Proposed (models and budgets need approval)

**Decision.** Snapshot builder → immutable snapshot with field IDs, explicit missing entries and conflicts → versioned prompt → Claude API
(server-side `ai` workers only; structured JSON output with the nine R6 sections and evidence tags) → deterministic validator → store/display.
No arithmetic by Claude; no action tools; model IDs, prompt versions, and budgets in configuration; prompt caching and batch processing for cost;
evaluation harness for R12.

**Reason.** Guarantees R6: Claude can only cite numbers the database produced, must say "Insufficient data.", and must surface disagreement.

**Alternatives considered.** Let Claude query the database via tools (flexible, but citations are harder to verify and cost is unbounded);
retrieval over documents (not needed for structured data); free-text output (cannot be validated).

**Trade-offs.** Snapshot design work per analysis type; Claude cannot answer questions outside the snapshot (by design).

**Future implications.** Read-only evidence tools may be added later if every tool result is appended to the snapshot and validated.

---

## ADR-0035 — Alert architecture
**Status:** Proposed (channels need approval)

**Decision.** Rule-based alerts on L1–L4 and data-quality events only; evaluated event-driven after computations plus periodic sweeps; hysteresis,
cooldowns, deduplication, minimum-quality gates; alert events store rule version, triggering values, quality, and snapshot reference; channels via
a notification adapter (in-app first).

**Reason.** Alerts must be reproducible and explainable; AI text is not a reliable trigger (R6).

**Alternatives considered.** AI-generated alerts (unverifiable); polling-only evaluation (slower, wasteful).

**Trade-offs.** Users must define rules; defaults will be provided per phase.

**Future implications.** The same rule engine can drive paper-trading strategy triggers.

---

## ADR-0036 — Decision journal and paper trading
**Status:** Proposed

**Decision.** Append-only, versioned journal entries linked to snapshots, interpretations, user hypotheses, and invalidation conditions; paper trading
uses the backtest execution-and-cost model with point-in-time prices; no live execution component and no trading-enabled keys.

**Reason.** Closes the loop from evidence to decision to outcome while keeping the platform decision-support only (ADR-0007).

**Alternatives considered.** Integrating live broker/exchange execution (out of scope, high risk).

**Trade-offs.** Paper fills are approximations; the model's assumptions are displayed with results.

**Future implications.** Journal outcomes enable calibration studies of both the user's and the AI's confidence.

---

## ADR-0037 — Scalability path and real-time processing
**Status:** Proposed

**Decision.** Scale up first; scale out workers per queue; read replica when needed; real-time later via stream collectors → Redis Streams →
batched writer → incremental computation → pub/sub → SSE. No Kafka until Redis Streams is a measured bottleneck. Stateless API and workers.

**Reason.** Avoid distributed-systems cost before it is needed (R13) while keeping a clear path.

**Alternatives considered.** Kafka/Redpanda from day one (robust streaming, heavy); Kubernetes from day one (premature).

**Trade-offs.** A future migration step if volumes exceed a single node.

**Future implications.** L1 schema is identical for batch and streaming, so the switch does not affect metrics, signals, or UI.

---

## ADR-0038 — Cost control
**Status:** Proposed — budgets set by the user on 2026-09-23: data providers **$0/month** (free sources first), Claude API **$20/month** hard ceiling (AI pauses with a notice when reached).

**Decision.** Per-provider budgets and a request ledger; Claude daily/monthly ceilings enforced in code, model tiering, caching, batch processing;
compression and retention tiers; debounced recomputation and off-peak backfills; single-host deployment until load requires more.

**Reason.** Data vendors and AI usage are the largest variable costs; they must be visible before invoices arrive.

**Alternatives considered.** Monitor invoices only (too late).

**Trade-offs.** Hard ceilings can pause AI features when reached (the UI states this).

**Future implications.** Cost per dataset informs which paid sources are worth keeping.

---

## ADR-0039 — Time zones and calendars
**Status:** Proposed

**Decision.** UTC `timestamptz` everywhere; convert at the edges (provider → UTC at normalisation; UTC → user time zone in the UI, default Asia/Manila);
crypto days are UTC days, weeks start Monday 00:00 UTC; US exchange and macro release calendars with daylight-saving handling; bar `event_time` =
open, `available_at` ≥ close.

**Reason.** Mixed time zones and bar-open timestamps are a classic source of silent look-ahead bugs.

**Alternatives considered.** Store local times (error-prone); display UTC only (unfriendly).

**Trade-offs.** Daily aggregates for US-listed products must be mapped to UTC explicitly.

**Future implications.** Additional markets/calendars are added as calendar definitions, not code changes.

---

## ADR-0040 — Bias and leakage controls
**Status:** Proposed

**Decision.** Mandatory `as_of` on every engine function; point-in-time loader as the only data door; automated "future poison" leakage tests;
survivorship-safe master data (listings, delistings, closures kept) and as-of universes; rolling/expanding normalisation only; train-only
parameter selection with trial counts; purged/embargoed splits; filtered (not smoothed) regime states; label validity windows; similarity search
excluding overlapping outcome windows.

**Reason.** R4 requires avoiding look-ahead, survivorship, leakage, selection bias, and overfitting; these are the concrete mechanisms.

**Alternatives considered.** Code review only (misses subtle leaks).

**Trade-offs.** More test infrastructure; some convenient research shortcuts are disallowed.

**Future implications.** Phase 16 (quant red-team) audits against this list.

---

## ADR-0041 — Reproducibility and versioning
**Status:** Proposed

**Decision.** Every derived result records definition/model/prompt version, parameters, Git SHA and image digest, `as_of`, `knowledge_time`,
input fingerprint, and seeds. Versioning: `/api/vN`; Alembic migrations; `name.vN` definitions with old versions retained; prompt and output-schema
versions; adapter payload-schema versions; semantic-versioned releases. A recompute-and-compare job checks samples periodically.

**Reason.** Any number or AI statement must be explainable later exactly as it was produced.

**Alternatives considered.** Version only code (cannot reproduce data-dependent results).

**Trade-offs.** Extra metadata columns and discipline when changing formulas.

**Future implications.** Supports audits, debugging of historical signals, and trustworthy performance tracking.

---

## ADR-0042 — Disaster recovery
**Status:** Proposed (targets need approval)

**Decision.** Continuous WAL archiving + scheduled full backups (pgBackRest or WAL-G) to encrypted off-site object storage with point-in-time recovery;
versioned raw archive; Redis treated as disposable; infrastructure and configuration as code; proposed production RPO ≤ 15 minutes and RTO ≤ 4 hours;
scheduled restore drills.

**Reason.** Collected `native` history cannot be re-downloaded from providers; losing it loses the platform's most valuable asset.

**Alternatives considered.** Nightly dumps only (simple, up to 24 h loss); managed database with built-in backups (valid production option).

**Trade-offs.** Storage cost for backups and WAL; drill time.

**Future implications.** Enables moving hosts or recovering from mistakes (e.g. a bad migration) without data loss.

---

## ADR-0043 — Charting libraries
**Status:** Accepted — approved by the user on 2026-09-23 (checklist A12). Was: Proposed

**Decision.** TradingView Lightweight Charts for price and time-series charts (candles, lines, histograms with overlays); Apache ECharts for
analytical visuals (heatmaps, correlation matrices, distributions, flow/rotation diagrams, gauges). Both wrapped in our own chart components
that display evidence category, quality, and `as_of`.

**Reason.** Lightweight Charts is small and fast for financial time series; ECharts covers the analytical chart types Lightweight Charts lacks.

**Alternatives considered.** ECharts only (one library, less specialised for price charts); TradingView full charting library (licensing
application required); Recharts/Plotly (general-purpose, heavier for large time series).

**Trade-offs.** Two libraries to learn. Lightweight Charts (Apache 2.0) **requires attribution**: the NOTICE text and a link to tradingview.com
on the page/app (the built-in attribution logo option can satisfy the link).

**Future implications.** Wrappers let us swap a library without touching screens.

---

## ADR-0044 — Numeric precision for high-volume data
**Status:** Accepted in Phase 5 — keep exact `NUMERIC` for bars. Was: Proposed (amends ADR-0010 pending benchmark)

**Benchmark (2026-09-23, PostgreSQL 17.11 + TimescaleDB 2.30.1, 1,042,564 one-minute bars, 4 series, 30-day chunks,
uncompressed):** storage 152 MB (`NUMERIC`) vs 144 MB (`double precision`), +5 %; 4-hour roll-up over ~80 days of one
series 66 ms vs 37 ms; reading 1,000 bars 3.3 ms vs 3.0 ms. The difference is not material at this scale, so market
bars keep exact decimals. Revisit if compression or order-book/trade volumes change the picture.

**Decision.** Default remains exact `NUMERIC` for L1 values. In the infrastructure phase, benchmark storage size and query speed for high-volume
families (minute bars, order-book depth, trades) using `NUMERIC` vs. `double precision`. If the difference is material, those families may use
`double precision` while the exact source string stays in L0; money ledgers (paper trading, fees, PnL) always stay `NUMERIC`.

**Reason.** Exactness matters for accounting; statistical analysis of market data tolerates float64, and volume may make `NUMERIC` expensive.

**Alternatives considered.** `NUMERIC` everywhere without measuring; `double precision` everywhere (inexact ledgers); scaled integers (fast, awkward).

**Trade-offs.** Two numeric conventions if the benchmark justifies it.

**Future implications.** Decision recorded with benchmark numbers before large-scale ingestion starts.

---

## ADR-0045 — Phase 3 foundation implementation choices
**Status:** Accepted (implemented in Phase 3; checklist Part A approved by the user on 2026-09-23)

**Decision.**
- Implemented on the Phase 2 recommended defaults for A1 (stack), A2 (monorepo; FastAPI sole data gateway), A3 (self-hosted
  TimescaleDB) and A8 (Redis 8). Not yet exercised: A4–A7, A9–A12 (storage tables, raw archive, Celery, auth, DB roles, AI, charts) — all approved on
  2026-09-23 and to be implemented in the phases that need them.
- Pinned versions: Python 3.12 · FastAPI 0.141 · SQLAlchemy 2.0 (async, psycopg 3.3) · Alembic 1.20 · redis-py 8.1 · structlog 26.1 ·
  pytest 9.1 · mypy 2.3 (strict) · ruff 0.16 · uv 0.8.17 · Next.js 16.3.6 · React 19.2 · TypeScript 5.9 · ESLint 9 · Prettier 3.9 ·
  Vitest 5 · pnpm 10.28.0 · images `timescale/timescaledb:2.30.1-pg17`, `redis:8.8-alpine`, `python:3.12-slim`, `node:22-alpine`.
- `compose.yaml` at the repository root; one `Dockerfile` inside each app folder (`backend/`, `frontend/`) instead of `infra/docker/`
  (simpler paths on Windows). Backend image has `dev` (with test tools; used by Compose) and `runtime` targets.
- Configuration via `CFI_`-prefixed environment variables (pydantic-settings); URLs held as secrets; no implicit `.env` loading in
  the app — Compose supplies the environment, and refuses to start without `.env`.
- Migrations run in a one-shot `migrate` service before the API starts. Baseline revision `0001`: TimescaleDB extension + nine layer
  schemas; downgrade uses `RESTRICT` so it cannot delete data.
- Starlette's test client uses `httpx2` (the `httpx` path is deprecated upstream). Pytest treats warnings as errors, with one
  documented third-party exception.
- The frontend uses system fonts (no build-time font download) and reads `API_INTERNAL_URL` at request time (`connection()`), so one
  image serves every environment.
- Celery workers and authentication are **not** part of Phase 3 (not requested); they arrive with the phases that need them.

**Reason.** Smallest foundation that satisfies the Phase 3 brief and the Phase 2 architecture without pre-building later phases (R13).

**Alternatives considered.** Dockerfiles under `infra/docker/` (as first proposed); bind-mounted hot-reload containers (slow on Windows
drives); keeping `httpx` with a suppressed deprecation warning.

**Trade-offs.** No hot reload inside containers; developers who want it run the API/frontend locally against the Compose services.

**Future implications.** Version pins must be updated deliberately; the CI workflow runs the same checks once a Git remote exists.

---

## ADR-0046 — Phase 4 ingestion engine implementation choices
**Status:** Accepted (implemented in Phase 4; within approved ADR-0017, 0018, 0019, 0021, 0022, 0031)

**Decision.**
- **Adapter contract:** adapters only describe requests (`first_request` / `next_request`, which also carries pagination), validate
  payloads (`parse`, raising `SchemaMismatchError`) and map records (`normalise`). All HTTP behaviour lives in one shared client.
- **HTTP library:** `httpx2` for runtime requests (the maintained successor Starlette now expects; same API as `httpx`).
- **Rate limiter and circuit breaker are in-process** for now; they move to Redis when several workers ingest in parallel.
- **One request log** (`ops.provider_request`, one row per attempt with its outcome) replaces the planned separate provider-health and
  request-ledger tables; provider health is computed from it.
- **Missing data is explicit rows:** a `null` from a provider, or an expected point that never arrives (for datasets marked
  `expect_continuous`), is stored as `value NULL, quality_status missing` with a note. A later real value becomes revision 1.
- **Conflicts are marked on the incoming row** (`quality_status conflicting`, note names the other provider and value); the earlier
  provider's row is never modified (append-only). Both values are kept; no blending.
- **Availability rule per dataset** sets `available_at` (provider time, end of period + delay, or event time + delay); a record whose
  period had not closed at ingestion is rejected rather than stored as final.
- **Integration tests use a separate `<db>_test` database** created and migrated by the test suite, so `docker compose exec api pytest`
  never writes into the development database.
- **Mock providers ship in the package** (`cfi/providers/mock.py`) for tests but are never registered in the running application.
- **Deferred:** scheduling (Celery), shared limiter, backfill/reconcile/gap-fill job types, coverage table, database roles.

**Reason.** Delivers every Phase 4 requirement with one pipeline and one client, without building the worker infrastructure early (R13).

**Alternatives considered.** Separate health/ledger tables (more writes, same information); placeholder-free gap reporting (gaps only in
findings — weaker, because readers of the data would not see the hole); overwriting the earlier provider's row to mark a conflict
(violates append-only); using the development database for integration tests with cleanup (risk of deleting real data).

**Trade-offs.** Per-record queries for series lookup and existing values are simple but not yet batched for very large pages; in-process
limits do not coordinate across processes.

**Future implications.** Workers can call `IngestionEngine.ingest` unchanged; real adapters only implement the four adapter methods.

---

## ADR-0047 — Phase 5 market-data layer: providers, storage, workers, API, dashboard
**Status:** Accepted (implemented in Phase 5; within approved ADR-0017, 0018, 0020, 0021, 0022, 0023, 0025, 0043, 0044)

**Decision.**
- **Providers (free, verified against official documentation on 2026-09-23):** Coinbase Exchange (primary, USD;
  candles 1m/5m/15m/1h/1d and last trade), Kraken (USD; all six timeframes, but only its 720 most recent bars),
  Binance market-data endpoint, OKX and Bybit (USDT; all six timeframes, deep history), CoinGecko (market
  capitalisation, latest and daily). OKX, Bybit and Kraken were added at the user's request as further backups.
  Enabled providers are configurable (`CFI_MARKET_PROVIDERS`).
- **Access risk recorded, not hidden:** Binance (2024) and OKX, Bybit, Kraken (August 2025) are blocked by Philippine
  ISPs; Coinbase and CoinGecko are not on those lists. Unreachable providers show as failed runs and dashboard warnings.
- **Venues are separate series; units are never mixed.** Datasets are defined per quote currency
  (`market.ohlcv.usd.<tf>`, `market.ohlcv.usdt.<tf>`); USD and USDT prices are never combined or treated as equal.
  No cross-venue blending or "consensus price".
- **Storage:** `obs.market_bar` hypertable (30-day chunks) with the same provenance columns and natural key as
  `obs.observation`; the engine gained record families (scalar / bar) behind one pipeline. Explicit missing bars;
  OHLC consistency failures kept as `suspect`; changes are new revisions.
- **4h on Coinbase** (not published) is rolled up at read time from stored 1h bars, labelled with its derivation, and
  shown only when all four hourly bars exist — otherwise reported as missing. Evidence category stays "observed"
  because an OHLC roll-up is an exact regrouping of observed bars; the `derivation` field and UI badge disclose it.
  OKX 4h/1d use its UTC-aligned bars (`4Hutc`, `1Dutc`), never the Hong Kong-time variants.
- **Finality:** a bar is final one minute after its period ends; unfinished bars (and CoinGecko's running value)
  are skipped and counted (`job_run.skipped`), never stored.
- **Point-in-time reliability:** `native` when stored within the dataset's freshness limit after it became knowable,
  otherwise `backfilled_latest`.
- **Workers (ADR-0023 implemented):** Celery with Redis; `worker` (queues `ingest_fast`, `ingest`) and
  `worker-backfill` (queue `backfill`) as separate processes, one task at a time each, late acknowledgement, time
  limits, expiring schedule entries; `beat` holds the schedule. Latest ingestion catches up after downtime (bounded);
  backfill walks history backwards with a checkpoint (`ops.backfill_state`) and stops at the configured depth or
  after three consecutive empty chunks (start of the provider's available history).
- **HTTP client:** HTTP 418 (IP ban) is treated as rate limiting; a `Retry-After` longer than the maximum backoff is
  never retried early — the request fails and the circuit stays open for that long. Optional API keys supported.
- **API:** `GET /api/v1/market/catalog`, `/market/bars`, `/market/overview` — read-only, `as_of` point-in-time
  parameter, exact decimals as strings, evidence envelope with source, freshness, gaps, last ingestion run, warnings.
- **Dashboard:** server-rendered Market page (asset / timeframe / venue switching via links), Lightweight Charts
  candles + separate volume pane (TradingView attribution kept), freshness badges, source and missing-data warnings,
  30-second refresh. No signals, scores or recommendations.

**Reason.** Free sources only (B2), no single-provider dependency (R8), and complete transparency about gaps, units
and access problems (R3).

**Alternatives considered.** Binance as primary (blocked in the Philippines); storing derived 4h bars (duplicates data
and needs recomputation on revision); partial 4h candles (would misstate high/low/volume); an in-process scheduler
instead of Celery (deviates from approved ADR-0023); Bitstamp (official docs and API not verifiable from here).

**Trade-offs.** Many small scheduled requests; rate limiters and circuit breakers are per worker process (limits set
conservatively so both processes together stay under each provider's published limit); CoinGecko storage terms need
the user's decision; exchange terms not yet reviewed.

**Future implications.** Order-book, trades and derivatives datasets reuse the bar store pattern; cross-venue metrics
(premiums, venue share) belong to later metric phases (L2), not here.


---

## ADR-0048 — Phase 6 institutional capital: sources, storage, aggregation, transparent score
**Status:** Accepted (implemented in Phase 6; within approved ADR-0006, 0017, 0018, 0021, 0022, 0023, 0032, 0039, 0040)

**Decision.**
- **What counts as "institutional" here.** Institutional *channels* with identified actors only: US spot ETFs
  (direct evidence: fund creations/redemptions) and listed-company treasuries (attributed evidence: company
  disclosures compiled by a provider). No wallet is labelled institutional; `obs.institutional_flow` rejects
  `inferred` labels at the database level. ETF flows prove fund flows, not who bought the fund shares (end investors
  include retail); this is stated next to every score.
- **Sources (free; verified against official documentation on 2026-09-24):**
  - **SoSoValue OpenAPI** (free key, 20 requests/min, 100,000/month): US spot ETF daily totals
    (`/etfs/summary-history`) and per-fund history (`/etfs`, `/etfs/{ticker}/history`) for **BTC, ETH, SOL and XRP**,
    and listed-company bitcoin purchase history (`/btc-treasuries`, `/btc-treasuries/{ticker}/purchase-history`).
    The ETF endpoints serve **only the most recent month**; older history builds up natively as the system runs.
    API terms are not published in the documentation → `terms_verified = false`, user decision pending.
  - **CoinGecko** public treasury (`/companies/public_treasury/{coin}`, keyless): totals held by listed companies for
    BTC, ETH, SOL (snapshots; the response has no timestamp, so the receipt time is used and recorded).
  - **Not tracked (recorded, shown in the UI):** global fund flows (CoinShares weekly reports — no free API), 13F
    holdings (quarterly, lagged), Hong Kong ETFs (available, not configured), dated treasury purchases for ETH/SOL/XRP
    (no verified free source), ETF history older than one month.
- **Storage:** `obs.institutional_flow` hypertable (180-day chunks, migration 0004) — a third record family
  (`CanonicalFlow`) in the same engine: flow and holdings columns in USD and in coins, cumulative flow, value traded,
  premium/discount, unit cost, plus `entity_type`, `evidence_class`, `entity_name`; same provenance columns and
  natural key; append-only revisions; database checks for missing-means-null and allowed evidence classes.
  Sign convention: positive = capital entering the entity. A reported sale's cost is signed like the coins
  (transformation recorded).
- **Point in time.** ETF rows are labelled with the US trading date (00:00 UTC label). New availability rule
  `next_us_trading_day`: figures for day D are treated as public at 18:00 New York time on the next US trading day
  (NYSE calendar with rule-based holidays, verified against nyse.com for 2026–2028, plus listed special closures).
  Purchases: date + 7 days. Both are conservative *estimates*; `known_when_received` dates a value by its receipt time
  when it arrives earlier (it evidently was public then). Receipt times of native rows will calibrate these rules.
  Documented T+1 behaviour: the current day's row without settled figures is skipped (not final); an older row
  without figures is stored as explicit missing. Sporadic event datasets opt out of engine freshness checks
  (`check_freshness = False`); their freshness is the age of the last successful sweep.
- **Reads:** two cut-offs per ADR-0018 — `as_of` on `available_at` and `knowledge_time` on `ingested_at` (both default
  to now). Aggregation (daily, weekly Monday–Sunday, calendar month) happens at read time from daily rows; every
  trading day is accounted for as present, missing, not loaded (before stored history) or not due. Sums cover present
  days only and partial buckets say so. Daily totals are cross-checked against the sum of per-fund flows.
- **Institutional Flow Score v1** (evidence category: calculated metric — not a statistical signal, forecast or
  advice), per asset with US spot ETFs:

  | Component | Metric | Reference scale | Weight |
  |---|---|---|---|
  | ETF net flow, 5 trading days | Σ flow ÷ net assets (last day with data) × 100 | 1.0 % | 0.35 |
  | ETF net flow, 20 trading days | same | 3.0 % | 0.30 |
  | Inflow vs outflow days, 10 trading days | (in − out) ÷ days with data | — (already ±1) | 0.15 |
  | Listed-company net BTC acquisitions, 30 days (BTC only) | Σ BTC acquired ÷ Σ latest reported holdings × 100 | 2.0 % | 0.20 |

  Sub-score = metric ÷ scale, capped to ±1; score = 100 × Σ(weight × sub-score) ÷ Σ(available weights). A component
  covering < 90 % of its window is excluded (never filled); below 0.5 available weight the score is "Insufficient data".
  Bands (flow direction only): ≥ +50 strong net inflow, ≥ +15 net inflow, ≥ −15 balanced, ≥ −50 net outflow, below
  that strong net outflow. Weights, scales and bands are **judgment parameters chosen by design, published, not fitted
  to price outcomes**; any change creates a new version. Every component shows its value, unit, calculation with the
  numbers used, source, timestamp, freshness and data quality.
- **Jobs:** Celery task `institutional.ingest` per (provider, dataset). All SoSoValue work runs on the `backfill` queue
  so one process owns its 20/min budget; listing pages and the per-fund/per-company pages that follow run as one
  ingestion job (every page archived). Jobs are skipped — not failed — when the provider is disabled or its key is
  missing; beat queues each institutional job once at start-up (an interval entry would first run hours later).
- **API / UI:** `GET /api/v1/institutional/{catalog, overview, etf-flows, etf-funds, treasury, score}`; the Flows page
  shows overview tiles for BTC, ETH, SOL, XRP, the score with every component, the flow chart and table
  (daily/weekly/monthly), per-fund breakdown, treasuries, and a coverage-and-limits section.

**Reason.** The user asked for institutional capital "where reliable data is available", a transparent score with
visible components, and no assumption that large wallets are institutional (R5). Free sources only (B2).

**Alternatives considered.** Scraping Farside or issuer CSVs (terms risk, brittle); percentile-vs-history
normalisation (needs years of history the free API does not serve; planned once native history exists); a fitted or
AI-generated score (opaque — rejected by the user); storing each ETF field as a separate scalar series (loses the
row-level consistency checks and doubles the queries).

**Trade-offs.** One month of ETF history at start, so 20-day and history-based views fill in over time; SoSoValue is a
single source for ETF flows (no cross-provider conflict check yet); treasury purchase sweeps take several minutes at
20 requests/min; the score's parameters are judgments the user should review.

**Future implications.** v2 of the score can replace fixed reference scales with percentiles over native history; the
divergence engine (institutional vs retail) consumes the score's components with their evidence classes.

**Amendment (2026-09-24, after the first real run).** The real SoSoValue key returned HTTP 429 ("wait 58 s") after
10 requests sent back to back, below the documented 20 per minute. SoSoValue requests are now paced evenly at one
every 7.5 s with no bursts (`RateLimitSpec.burst = 1`), and provider-requested waits of up to 90 s are honoured
before retrying (`ProviderCapabilities.max_retry_wait_seconds`). Other providers are unchanged.

**Amendment 2 (2026-09-24, first real purchase sweep).** 333 of 521 purchases were flagged by the unit-cost check.
Cause: SoSoValue's `avg_btc_cost`, documented as USD per BTC, is not (MSTR 0.09 while cost ÷ BTC ≈ 79,700 USD). It is
no longer stored; the check is replaced by an implied-price plausibility band for BTC (1,000 to 1,000,000 USD per BTC),
which still catches genuinely inconsistent rows (e.g. 2 BTC for 111.84 M — probably another currency). Re-ingested rows
become new revisions; nothing is overwritten. **Farside Investors** (second ETF source requested by the user): not
used — its pages answer automated clients with a bot-check page, and the site is "All rights reserved" with no data
terms. HYPE ETF flows (Farside only) are deferred.


---

## ADR-0049 — Phase 7 whale intelligence: sources, entity classification, transfers, transparent score

**Status:** Accepted (implemented in Phase 7; within approved ADR-0006, 0017, 0018, 0021, 0022, 0023, 0032)

**Decision.**
- **Sources (free; verified 2026-09-24).**
  - **Coin Metrics Community API** (no key, 10 requests / 6 s; checked against real responses): daily exchange inflow,
    outflow and exchange supply (`FlowInExNtv`, `FlowOutExNtv`, `SplyExNtv`) and network supply / issuance
    (`SplyCur`, `IssTotNtv`) for **BTC and ETH**. Exchange metrics carry a status (`flash` / `reviewed`) and a status
    time, used as `available_at`; `flash` rows are stored `estimated`. Licence **CC BY-NC 4.0** (attribution shown;
    non-commercial only).
  - **Blockchair API** (no key up to 1,440 requests a day, 30 a minute; personal / non-commercial; documented shapes —
    the host is not reachable from Claude's workspace): top-100 address balances (BTC; ETH accounts, contracts
    excluded), large transfers (BTC outputs ≥ 500 BTC; ETH transactions ≥ 5,000 ETH, exact threshold re-applied on
    read because the wei filter is approximate), and Bitcoin daily aggregations — coin days destroyed, BTC spent from
    outputs ≥ 365 days / ≥ 155 days old, BTC spent from coinbase outputs.
  - **BitInfoCharts** top-100 page: 27 Bitcoin address labels copied once into a versioned CSV (attributed,
    confidence 0.6; nicknames without an identifiable entity skipped). Every address checksum-verified.
  - **Not available free (shown in the UI):** dormant / long-term-holder supply stock, miner → exchange flows, SOL and
    XRP whale data, labelled Ethereum addresses, balance bands, real-time alerts (Whale Alert is paid).
- **Entity classification (R5).** `ref.entity` (known actors) and `ref.entity_label` (address labels: chain, canonical
  address, class, entity, evidence class, confidence, evidence text, source, source URL, `valid_from`/`valid_to`,
  `available_at`, `recorded_at`; append-only). Known classes: exchange, institution, fund, market maker, protocol,
  miner, government, other — each needs a named entity and a direct or attributed label. Size alone only ever gives
  `unknown_large_holder` (inferred, confidence 0.5, no entity). Enforced three times: label validation in code, the
  import (a file with any invalid row is rejected whole), and **database CHECK constraints** (an inferred institution,
  fund or market maker cannot be stored). Classification happens at read time: labels that count at the classified
  time for the view (`available_at ≤ as_of`, `recorded_at ≤ knowledge_time`, inside the validity period); precedence
  direct > attributed > confidence > newest; disagreeing labels are returned as conflicts. Addresses are validated by
  checksum (Base58Check, Bech32/Bech32m, Ethereum hex) before any storage or match.
- **Storage.** Fourth record family `CanonicalTransfer` → `obs.large_transfer` (hypertable, 30-day chunks, one series per
  transfer; same provenance and append-only revisions). Balances and daily aggregates are scalar observations.
  A transfer address failing validation is kept as reported and the row is flagged `suspect`, never corrected.
- **Jobs.** One Celery task `whales.ingest(provider, dataset, asset)`: the recent window (complete UTC days for daily
  data; catch-up after downtime for transfers), then **one** older history chunk while history is incomplete
  (`ops.backfill_state`), so first starts spread their load and stay inside Blockchair's daily budget. Blockchair runs on
  the `backfill` queue (one process owns its rate limit). Seed labels are imported when the worker starts.
- **Whale Flow Score v1** (calculated metric; positive = accumulation, negative = distribution): 7-day net flow to
  exchanges as % of exchange supply (0.35, scale 1 %), 30-day exchange-supply change (0.15, scale 3 %), 7-day balance
  change of unknown large holders in the top 100 — membership taken from the earlier snapshot, ≥ 80 % still listed
  (0.25, scale 1 %), BTC coins ≥ 1 year old moving: 7-day vs prior-90-day daily average (0.25, scale 1.0 on ratio − 1).
  Same method as ADR-0048: capped sub-scores, components below 90 % coverage excluded (never filled), renormalised
  weights, "Insufficient data" below weight 0.5; bands ±15 / ±50. Coinbase-origin spending ÷ issuance is shown but not
  scored (mostly pool payouts, not miner selling).
- **Contradiction indicators.** Pairs of readings compared by direction (sub-score ±0.25, score ±15 points, balance
  change ±0.5 %): exchange flows vs old coins moving; exchange flows vs unknown large holders; Whale Flow Score vs the
  Institutional Flow Score (Phase 6); labelled top-100 exchange balances vs Coin Metrics exchange supply. Status:
  contradiction / consistent / no clear direction / insufficient data — shown, never averaged away.
- **API / UI.** `/api/v1/whales/*` (catalog, overview, flows, holders, transfers, addresses, entities, score) with
  `as_of` / `knowledge_time`; the **Whales** page shows the score with every component (source, timestamp, unit,
  calculation, freshness, quality), contradictions, daily flows chart and table, top holders with classifications
  (evidence, source, confidence one click away), large transfers and coverage limits.

**Alternatives considered.** Glassnode / CryptoQuant / Nansen / Arkham (better labels and cohorts, paid — B2 budget
$0); Whale Alert (paid); running our own nodes (too heavy for now); labelling large wallets as whales or institutions by
size (rejected by R5); storing inferred classifications (not needed: they are recomputed from observed balances at read
time, so a changed threshold never rewrites history).

**Consequences.** On-chain whale behaviour for BTC and ETH is observable with provenance and point-in-time reads, but
coverage is thinner than paid analytics: exchange attribution is Coin Metrics', labels are few (27 BTC addresses, no
ETH labels), and holder changes need a week of snapshots. Parameters are judgments, published and versioned. Licences
restrict commercial use (Coin Metrics CC BY-NC, Blockchair free tier).

## ADR-0050 — Phase 8 derivatives: sources, quote storage, calculations, Derivatives Health Score

**Status:** Accepted (implemented in Phase 8; within approved ADR-0006, 0017, 0018, 0021, 0022, 0023, 0032)

**Decision.**
- **Sources (free, no key; verified 2026-09-26).**
  - **OKX public data** (checked against real responses): hourly open interest of the USDT perpetuals in coins
    (`rubik/stat/contracts/open-interest-history`, `end` exclusive, ~1 month), funding-rate history (`after`
    exclusive, ~3 months), hourly long/short **account** ratio of all OKX contracts on the coin (`begin`/`end`
    inclusive), contract value (`public/instruments`) and liquidation orders (`public/liquidation-orders`, ~1 day
    retained).
  - **Deribit public API** (checked against real responses): futures curve and option chain snapshots
    (`get_book_summary_by_currency`, `usOut` = snapshot time) and hourly DVOL (`get_volatility_index_data`,
    `continuation` pagination). BTC and ETH only.
  - **Binance USDⓈ-M public data** (documented shapes only — Binance answered HTTP 451 to the development
    environment): hourly open interest and all-account long/short ratio (latest month), funding-rate history.
    Binance liquidations exist only as a live stream (not used); top-trader ratios skipped (definition unclear).
  - Perpetual assets BTC, ETH, SOL, XRP (USDT-margined perpetuals only; inverse / USDC contracts not mixed in).
- **Storage.** Open interest (coins), funding, account ratios, hourly liquidation totals and DVOL are scalar
  observations (`obs.observation`), one series per venue and subject. Futures and options snapshots are a fifth record
  family `CanonicalQuote` → **`obs.derivative_quote`** (hypertable, 7-day chunks; one series per instrument; expiry,
  strike and option type validated by CHECK constraints; an instrument listed after its expiry is kept and flagged
  `suspect`). **USD values are not stored** for open interest or liquidations — venues quote them in USDT or in
  different conventions — they are calculated at read time from coins × the Coinbase USD hourly close. Venue
  percentages (mark IV, DVOL) are stored as ratios with the conversion recorded in `transformations`.
- **Liquidations** are aggregated in the adapter into hourly long / short totals in coins (Σ `sz` × `ctVal`): every page
  back to the window start is read; orders sharing the millisecond at a page boundary are re-read and counted once;
  an hour is emitted only when all its orders were read and it lies within OKX's retention (18 h reach); older hours
  become explicit `missing` points. Zero is stored only for fully read hours. Inconsistent position / order sides are
  counted on neither side and flag the hour `suspect`.
- **Jobs.** The Phase 7 runner was generalised (`cfi.ingestion.scheduled`: recent window aligned to complete periods,
  catch-up after downtime, one history chunk per run) and serves both whales and derivatives. One Celery task
  `derivatives.ingest(provider, dataset, asset)`; the option chain (hundreds of instruments) runs on the `backfill`
  queue so it never delays minute bars.
- **Calculations (L2, read time, point-in-time).** OI change 24 h / 7 d over the venues present at both times (never a
  mixed venue set); OI expansion ≥ +5 % / 24 h or ≥ +15 % / 7 d (contraction: the negatives); leverage ratio =
  OI (coins × USD price) ÷ market cap, expansion / reduction at ± 10 % relative over 7 d; annualised funding =
  Σ settled rates over 7 d × 365 ÷ 7 (interval-independent, only with no settlement missing; OI-weighted across venues),
  extreme at |≥ 30 %|; annualised basis = (mark ÷ index − 1) × 365 ÷ days, headline = the future closest to 90 days
  (≥ 14 d), extreme ≥ +20 % or ≤ −5 %; liquidation event = an hour ≥ 5 × the median of earlier hours in 7 d (≥ 24
  of them) and ≥ 0.05 % of OI; options put/call OI and volume ratios, ATM IV and 10 %-OTM skew (put near 0.9 F minus
  call near 1.1 F, ± 3 %, expiry closest to 30 d, ≥ 7 d); long/short account ratios and price/OI context shown only as
  context. No reading is labelled bullish or bearish.
- **Derivatives Health Score v1** (calculated metric; 0–100, 100 = no stress; stress = 100 − health). Direction-neutral
  stress components 0 … 1: funding |annualised 7 d| ÷ 30 % (0.25), basis outside 0 … 10 % a year ÷ 15 % (0.15),
  leverage |7-day change| ÷ 20 % (0.20), liquidations 24 h ÷ OKX OI ÷ 1 % (0.20), DVOL on per-asset calm / stressed
  levels (BTC 30 → 80 %, ETH 40 → 100 %) (0.20). Components without complete inputs are excluded, weights renormalised,
  "Insufficient data" below weight 0.5; bands 75 / 50 / 25. Each component returns value, scale, stress, weight,
  contribution, calculation, inputs and direction context.
- **API / UI.** `/api/v1/derivatives/{catalog, overview, asset, history}` with `as_of` / `knowledge_time`; the
  **Derivatives** page shows the score and components, conditions, OI per venue, leverage, funding per venue, account
  ratios, price context, an OI / price chart, the Deribit curve, options, liquidations and per-source data quality.

**Alternatives considered.** Coinglass / Laevitas / Amberdata aggregates (paid or keyed; B2 budget $0); storing venue
USD / USDT values (mixes currencies and conventions); Binance liquidation websocket (needs a permanent connection —
Phase 27 real-time); 25-delta skew (needs greeks, not in the free summary); bullish / bearish scoring of leverage or
funding (rejected: the user asked for context, not direction).

**Consequences.** Open interest and funding cover two major venues, options and basis Deribit only, liquidations OKX only
(market-wide totals are larger). Account-ratio and OI history reach only about a month back on the free endpoints;
Deribit snapshots and liquidations accumulate from the first run, so the 7-day liquidation event rule and history
charts fill in over the first week. Weights and scales are judgments, published and versioned, to be reviewed against
stored history.

## ADR-0051 — Phase 8 addendum: versioned Derivatives Health Score parameters

**Status:** Accepted (implemented 2026-09-26, within approved ADR-0050)

**Context.** The user approved the Phase 8 Derivatives Health Score's v1 weights and reference scales, but
explicitly declined to call them "validated" (they are judgment parameters, not fitted to data — R2, R13) and asked
that they be moved out of hard-coded constants in `score.py` into a versioned, swappable representation, so that
Phases 15-16 (backtesting, quant red-team) can evaluate alternative parameter sets, or a future revision, without
rewriting the scoring engine — and so every score the system has ever produced stays reproducible against the exact
parameters that produced it, even after a later version changes them.

**Decision.**
- **New module `cfi/derivatives/score_parameters.py`**: a `ParameterSet` frozen dataclass (weights, reference scales,
  `basis_band`, `dvol_scales`, `min_available_weight`, `bands`) and an append-only `PARAMETER_SETS` registry keyed by
  version id. `parameters(version=None)` is the one function the scoring engine depends on; an unknown version id is
  a hard `KeyError`, never a silent fallback (R3). The current (and, for now, only) entry is `derivatives_health_v1`,
  holding exactly the numbers the user approved: weights 0.25/0.15/0.20/0.20/0.20, funding 30 %, basis 15 % outside
  0–10 %, leverage 20 %, liquidations 1 % of OI, DVOL BTC 30→80 %/ETH 40→100 %, `min_available_weight` 0.5, bands
  75/50/25.
- **A plain versioned Python module, not a database table.** There is exactly one active version at a time and
  nothing here is edited at runtime (R13 — avoid an unrequested config subsystem); `parameters()` is the seam a
  future database-backed registry would slot behind without any caller change, if multiple versions ever need to be
  compared live (Phase 16).
- **`score.py`** no longer hard-codes weights/scales: `COMPONENTS`' descriptive metadata (label, human-readable
  `scale` text, `definition`) is generated from a `ParameterSet` so the text can never drift from the numbers; every
  component function and `compute()` takes an optional `params` argument, defaulting to the current version, so
  every existing call site is unchanged. `ScoreResult` gained `parameter_version` (the version actually used — not
  inferred from the module default) and `calculated_at` (wall-clock time, distinct from `as_of`, the point-in-time
  market snapshot).
- **Version identifier renamed** from the generic `"v1"` to `derivatives_health_v1` (this score's own namespace,
  since the platform has several scores — institutional, whale, derivatives — each already versioned independently).
- **Reproducibility.** Every score result already exposes, per component and in total: value, stress (0–1, always
  clipped), effective weight after renormalisation, contribution, calculation string and inputs, plus the overall
  status, available weight, health, stress, band, `parameter_version` and `calculated_at`. No new table was added to
  snapshot every computed score over time — the platform does not currently persist any of its other calculated
  scores that way either (institutional, whale), and every derivatives calculation is already a pure, deterministic
  function of stored point-in-time observations (R2/R3) plus a named, immutable parameter set — so recomputing a
  past `as_of` against a named version reproduces the same result by construction, without a separate log table.
  **Flagged as a scope decision, not a certainty**: if the user wants computed scores snapshotted into a table on a
  schedule (e.g. for a dashboard of "the score as it stood each day" independent of recomputation), that is a
  reasonably-sized follow-up, deferred rather than built speculatively.
- **Semantic disclaimer.** The API now returns a fixed `semantic_note` on every score result and in the catalog
  definition: "Higher Derivatives Health Score means lower measured derivatives stress across the available
  components. It is not a probability of price increase and does not indicate market direction." Shown in the
  Derivatives page under the score.
- **Out of scope, deliberately**: the *condition* thresholds in `metrics.py` (OI expansion ±5 %/±15 %, leverage
  change ±10 %, funding extreme 30 %, basis extreme +20 %/−5 %, liquidation event 5×median/0.05 % OI) are a separate
  concept from the score's reference scales (they drive the `conditions` panel's active/inactive flags, not the
  score) and were left as hard-coded constants. Funding happens to reuse the same 30 % value in both places today;
  after this change the score's `funding_scale` and `metrics.FUNDING_EXTREME` are independent parameters that start
  equal but can diverge, so a future score-parameter change cannot silently change the condition flag or vice versa.
  Externalising the condition thresholds the same way was not requested and is not done here.

**Alternatives considered.** A database `score_parameters` table (rejected for now: no runtime editing is needed,
and a table adds a migration, an admin surface and a caching question for one row that changes rarely — the module
registry is a straightforward promotion path if that changes); a YAML/JSON config file (rejected: no type safety,
and nothing else in this codebase loads runtime config that way — Pydantic `Settings` covers environment config,
this is versioned judgment data, closer to a migration than a setting); persisting every computed score to a new
hypertable (deferred, see Decision above — not requested, and no existing score in the platform is persisted that
way).

**Consequences.** Publishing a v2 parameter set is: add a new `ParameterSet` entry to `PARAMETER_SETS`, keep
`derivatives_health_v1` untouched, point `CURRENT_VERSION` (or `score.SCORE_VERSION`) at the new id. Nothing in
`service.py`, the API routes or the frontend needs to change for that. Historical reproducibility depends on nobody
ever editing an existing `ParameterSet` entry's values in place — this is a code-review discipline, not something
the type system enforces.

---

## ADR-0052 — Phase 9: liquidity / stablecoin intelligence layer (DefiLlama only), Liquidity Score

**Status:** Accepted (implemented 2026-09-26)

**Context.** The user asked to track USDT/USDC/total stablecoin supply, market share, minting, burning, exchange
stablecoin balances and exchange stablecoin flows; calculate supply growth/contraction, growth acceleration/
deceleration and exchange liquidity changes; and build a Liquidity Score exposing every component, showing
observed data separately from interpretation (R2).

**Decision — provider and scope.**
- **DefiLlama only** (`stablecoins.llama.fi`), the sole free, keyless, real source found for stablecoin circulating
  supply. `GET /stablecoincharts/all[?stablecoin={1|2}]` gives one calendar-day snapshot per row, aggregated across
  every chain a stablecoin is issued on, for USDT (id `1`), USDC (id `2`) and — with no `stablecoin` parameter —
  every stablecoin DefiLlama tracks (used as the `TOTAL` subject; this is not the sum of USDT + USDC, it also
  includes DAI, USDe, USDS and others). Confirmed live and against DefiLlama's published API docs; not verifiable
  as a byte-exact captured response inside the sandboxed development workspace, whose egress proxy cannot reach
  `stablecoins.llama.fi` (the same limitation Blockchair had in Phase 7) — flagged plainly in
  `cfi/providers/defillama.py`'s docstring rather than glossed over (R3), with real verification deferred to the
  user's own ingestion run.
- **Provider quirk handled explicitly:** the chart endpoint takes no date-range parameters — every call returns the
  entire history (November 2017 to present) in one response. There is no page to request with `next_request`; the
  adapter fetches the full array every time and filters it, in `parse_page`, down to the rows inside the requested
  window, discarding the rest before they ever become `ProviderRecord`s. This is why the source is scheduled at a
  low frequency (every 6 h, `cfi/liquidity/sources.py`) — the underlying data only changes once a day.
- **No new migration.** The dataset (`liquidity.stablecoin_supply.1d`, one per subject: `USDT`, `USDC`, `TOTAL`) is
  `kind="scalar"`, stored in the existing `obs.observation` table via the generalised scheduled-source runner
  (`cfi/ingestion/scheduled.py`, built in Phase 7, already reused unchanged by Phase 8). Availability rule:
  `event_time_plus` (36 h), `known_when_received=True` — DefiLlama's exact crawl/publish timing for a given day is
  undocumented, so it is treated conservatively as knowable by the end of that UTC day plus a half-day margin,
  falling back to receipt time when seen earlier (the same pattern Phase 8 uses for Deribit snapshots). Note:
  `known_when_received` only applies to an *estimated* rule (`event_time_plus` / `next_us_trading_day`), not
  `period_end_plus` — an early implementation used `period_end_plus` and failed fast at import time
  (`domain/datasets.py`'s own validation), corrected to `event_time_plus` with an equivalent 36 h delay.
- **Not tracked, and said so** (`NOT_TRACKED`, `cfi/liquidity/universe.py`): exchange stablecoin balances and
  exchange stablecoin flows — no free source found publishes per-exchange stablecoin holdings or transfers; that
  needs labelled on-chain address attribution to known exchange wallets, which only paid providers (Nansen, Arkham,
  CryptoQuant) offer. The user's requested "exchange liquidity changes" calculation is implemented
  (`metrics.py:exchange_liquidity_change`) but **always** returns `status="unavailable"` with this reason — a named,
  visible gap (R3), never a silently omitted field and never folded into the Liquidity Score as a hidden zero.
  Individual mint/burn transactions are likewise not tracked as discrete on-chain events (would need per-chain
  contract-event tracking on every issuing chain); day-over-day change in stored circulating supply is used instead
  as the honest, clearly-labelled proxy for net minting/burning.

**Decision — Liquidity Score, versioned from the start.** Unlike Phase 8 (where versioned parameters were an
addendum after initial hard-coded constants), Phase 9 reuses that pattern from the first commit: `ParameterSet`
frozen dataclass, append-only `PARAMETER_SETS` registry, `CURRENT_VERSION`, `parameters(version=None)` raising
`KeyError` on an unknown version (`cfi/liquidity/score_parameters.py`), current version `liquidity_score_v1`. The
score is **signed** (−100 … +100), modeled on the Institutional Flow Score (`cfi/institutional/score.py`) rather
than the direction-neutral Derivatives Health Score, because supply growth is inherently directional (growing vs.
shrinking), unlike Phase 8's stress concept. Four components, each `clip(value ÷ scale, −1, +1)`: USDT 7-day growth
(weight 0.30, scale 5 %), USDC 7-day growth (0.30, 5 %), TOTAL 7-day growth (0.25, 4 %), TOTAL growth acceleration
— the 7-day growth rate ending now minus the 7-day growth rate ending 7 days earlier (0.15, 3 percentage points).
Market-share shift and the (always-unavailable) exchange liquidity change are deliberately **not** scored
components — displayed and calculated separately instead, exactly as the user asked ("show observed data
separately from interpretation"). `min_available_weight` 0.5 (below it: "Insufficient data"); bands are descriptive
labels of stablecoin-supply direction ("strong liquidity expansion" … "strong liquidity contraction"), never
advice. Every result records `parameter_version`, `calculated_at`, per-component value/sub-score/effective
weight/contribution/calculation, following the reproducibility fields the user required for Phase 8's addendum.
Parameters are labelled "v1 methodology / initial parameters" — never "validated" — matching the same
recommendation the user gave for Phase 8.

**Alternatives considered.** Modeling the score on the Derivatives Health Score's direction-neutral "stress"
concept (rejected: supply growth/contraction is inherently directional — a signed score, like the Institutional
Flow Score, states that directly instead of discarding the sign). Folding market share or the unavailable exchange
liquidity change into the score as a component (rejected: the user explicitly asked to show observed data
separately from interpretation, and an always-unavailable component would either permanently shrink the available
weight or need to be silently excluded — clearer to keep it a separate, clearly-labelled field). A database
parameter table for the score (rejected for the same reason as ADR-0051: no runtime editing is needed).

**Consequences.** No new database migration. Frontend work was not part of the Phase 9 request as given and was
not built (see PROGRESS.md); the backend API (`/api/v1/liquidity/{catalog,overview,history}`) is complete and
tested end-to-end (unit tests for the adapter, metrics and score; integration tests for ingestion and the API
against a synthetic DefiLlama history, verified against an independently-computed expected result). Publishing a
v2 Liquidity Score parameter set follows the same append-only pattern as ADR-0051.

## ADR-0053 — Phase 10: retail activity intelligence layer, DIRECT/PROXY classification, Retail Activity Score
and Retail Speculation Score

**Status:** Accepted (implemented 2026-09-26)

**Context.** The user asked to build the Retail Activity Intelligence layer from a specific list of potential
inputs — Google Trends, Reddit activity where legally/technically available, social activity, retail derivatives
activity, small transaction activity, meme-coin activity, retail trading proxies — with one hard requirement:
**every metric must clearly identify whether it is DIRECT RETAIL DATA or a RETAIL PROXY**, and proxies must never
be presented as direct measurements. Also required: a retail activity score, a retail speculation score, retail
sentiment metrics, and historical percentile calculations.

**Decision — nothing tracked is DIRECT RETAIL DATA, and this is enforced structurally, not just in prose.**
Research (WebSearch/WebFetch, not assumption — R3) confirmed no free, licensable source segments its data by
account type (retail vs. institutional): Google Trends has no official public API (the supported route needs a
paid Google Cloud BigQuery account; the common unofficial scrape of `trends.google.com` is not authorised by
Google's terms of service for sustained automated use); Reddit's API has been metered/paid beyond a small
non-commercial allowance since 2023, still in effect; X (Twitter)'s free tier does not support search or
aggregate content retrieval. All three are recorded as `NOT_TRACKED` business/licensing decisions for the user's
review (`cfi/retail/universe.py`, restated in `TODO.md`), not silently dropped or worked around with an
unauthorised scrape. Because nothing DIRECT exists to track, every metric this phase computes carries
`measurement_class: MeasurementClass = field(default="proxy", init=False)` on its dataclass
(`cfi/retail/metrics.py`) — a structural guarantee, not a comment: no code path can construct a "direct" instance
without deliberately changing the dataclass definition itself, so the requirement survives future edits by
default rather than by discipline.

**Decision — three tracked proxies, two of them via a genuine cross-module read, not re-ingestion.**
- **Retail derivatives positioning** reuses two datasets Phase 8 already ingests from Binance USDⓈ-M Futures:
  `deriv.funding_rate` and `deriv.long_short_account_ratio.1h`. A new `RetailQueries.derivatives_observations()`
  reads them directly from the shared `obs.observation` table, filtered to `venue = "binance"` only (Binance and
  OKX publish the ratio for different account populations that must never be blended — see
  `cfi.derivatives.universe.LONG_SHORT_RATIO`'s own docstring). This is a deliberate architectural precedent: R2's
  layer rule restricts which *layers* a module reads (never write past its own layer), not which module's
  ingestion job produced a given L1 row — every module already reads from the same shared table. No new provider,
  no new ingestion job, no data duplication; documented explicitly in both the query module's docstring and the
  API catalog response (`"reused_derivatives_datasets"`) so it is visible, not hidden plumbing.
- **Meme-coin / retail search-attention proxy** extends the already-integrated CoinGecko adapter (Phase 5/6) with
  its free, keyless `GET /search/trending` endpoint (confirmed live and against CoinGecko's published docs,
  2026-09-26). One call returns a live snapshot of the top ~15 coins by recent search interest, not a queryable
  history, so there is nothing to backfill: the scheduled source uses `history=0`/`max_catch_up=0` (all defaults).
  The set of assets returned is dynamic and not known in advance — unlike every other provider integration in this
  project, which requests a fixed, pre-registered coin-id list — solved with a sentinel `ScheduledSource.subject`
  (`TRENDING_SUBJECT = "GLOBAL"`) used purely for scheduling identity, while each stored observation's real `asset`
  comes from the response item's own `symbol` field. Every trending coin is stored regardless of a curated,
  explicitly non-exhaustive meme-coin list (`MEME_COIN_SYMBOLS`); the meme-coin-specific reading is computed from
  that same stored data, never a separately fetched or filtered feed.
- **Small on-chain transaction activity** extends the already-integrated Blockchair adapter (Phase 7, whale
  intelligence) with one new daily aggregation: count of Bitcoin outputs valued under $1,000. Deliberately kept out
  of the whale module's `DAILY_METRICS` iteration to avoid coupling that module to a retail dataset; scheduled
  exactly like Blockchair's other daily aggregations (12 h interval, day-closed-plus-2h availability, 120-day
  history in 30-day chunks). Explicitly **not** filtered for change outputs from large transactions,
  exchange-internal batching, or dust — stated plainly in the dataset description and every API response, never
  smoothed over (R3).

**Decision — historical percentile as the Statistical Signal (L3), computed by re-invoking the same pure
function at each historical point, not by storing pre-aggregated percentile-ready series.** `percentile_rank`
(`cfi/retail/metrics.py`) is a standard nearest-rank percentile (0-100) with an explicit `insufficient_history`
status below a 20-point minimum sample — never silently computed on too little data, and never hidden. For
inputs that are naturally single time series (small-output-count) this is direct. For inputs that are themselves
a computed reading over multiple raw series (the derivatives-turnover magnitude, and the meme-coin-trending
count derived from a dynamic multi-asset snapshot), `RetailService._turnover_history()` and `_meme_history()`
re-call the exact same pure metric functions (`derivatives_proxy()`, `meme_coin_activity()`) at every historical
timestamp seen in the raw data, rather than maintaining a second, parallel pre-computed series that could drift
out of sync with the "now" calculation. This trades a small amount of read-time recomputation for a correctness
guarantee: "now" and "history" are always computed identically, by construction.

**Decision — two scores, not one, because "how much" and "which direction" are different questions.** The
**Retail Activity Score** (0-100, unsigned) answers "how elevated is retail-proxy activity right now, relative to
its own recent history" — a pure intensity reading; every component is already a 0-100 historical percentile, so
the score is their weighted average with no reference scale needed (small-transaction percentile 0.35, meme-
trending percentile 0.30, derivatives-turnover-magnitude percentile 0.35; `min_available_weight` 0.5). The
**Retail Speculation Score** (−100…+100, signed) answers "does the tracked data lean toward crowded, long-biased
leveraged positioning, or short-biased, or balanced" — funding-rate bias (weight 0.40, scale 0.0005) and
account-ratio skew (weight 0.40, scale 0.5) are genuinely directional; the meme-coin-trending component (weight
0.20, scale 2) is explicitly **not** — a count of currently-trending meme coins is never negative, so it can only
push the score up toward "more speculative fervour," never down, and this is encoded as a `directional: bool =
False` field on its `ComponentDef` rather than left to prose, so it can never be mistaken for a balanced
two-sided signal by a future reader of the code or the API response. Both scores follow the versioned-parameters
pattern established in ADR-0051 and reused unchanged in ADR-0052 (frozen `ParameterSet`-style dataclasses,
append-only registries, `CURRENT_VERSION` constants, hard `KeyError` on an unknown version) and record the same
reproducibility fields (`parameter_version`, `calculated_at`, per-component value/sub-score/effective
weight/contribution/calculation string). Parameters are labelled "v1 methodology / initial parameters, chosen by
design" — never "validated" — matching Phase 8/9's own posture.

**Decision — retail sentiment is a deterministic rule over two already-computed readings, not a new metric.**
`RetailService._sentiment()` compares the derivatives proxy's funding-rate condition and account-ratio condition
(both already computed, already labelled) and reports whether they agree (`aligned_long_bias` /
`aligned_short_bias`), disagree (`divergent`), are both inside their neutral bands (`neutral`), or one/both are
unavailable (`unknown`). This is explicitly commented as a Calculated Metric (L2), not an AI Interpretation (L5)
— a fixed, published rule, never Claude-generated text, matching R2's evidence-hierarchy separation.

**Alternatives considered.** Scraping Google Trends or Reddit anyway via an unofficial route (rejected outright —
not authorised by either platform's terms of service for sustained automated use; a licensing decision left
explicitly to the user, restated in `TODO.md`, not made silently by this build). A single combined retail score
instead of two (rejected: "how much retail-proxy activity" and "which direction it leans" are different questions
or with different natural ranges — one unsigned intensity reading and one signed directional reading — and
collapsing them would either discard the sign or force an artificial direction onto a magnitude-only reading).
Re-ingesting Binance funding rate/account ratio under a new retail-owned dataset id (rejected: the data is
identical to what Phase 8 already stores: re-ingesting would duplicate storage and risk the two copies drifting
apart; a documented cross-module read is simpler and keeps a single source of truth).

**Consequences.** No new database migration (both new datasets are `kind="scalar"`, stored via the existing
scheduled-source runner; the two derivatives datasets are read, not written, by this module). Frontend work was
not part of the Phase 10 request as given and was not built (see PROGRESS.md). The backend API
(`/api/v1/retail/{catalog,overview,history}`) is complete and tested end-to-end: unit tests for both provider
extensions (CoinGecko trending, Blockchair small-output-count), the metrics module and both scores; integration
tests for ingestion (against synthetic CoinGecko/Blockchair histories, including no-duplication-on-rerun checks)
and for the API (derivatives proxy and small-transaction activity verified against an independently-computed
expected result using the same production metric functions; percentiles and both scores verified for shape —
status, sample size, measurement class — with their numeric formulas already covered at the unit level).
Publishing a v2 parameter set for either score follows the same append-only pattern as ADR-0051/ADR-0052.

---

## ADR-0054 — Phase 11: macroeconomic data layer, FRED provider, monthly cadence, Macro Environment Score

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user asked to build the macroeconomic data layer, tracking DXY, US 2-year and 10-year
yields, the Fed funds rate, CPI, PCE, unemployment, VIX, S&P 500, Nasdaq, gold, oil and global liquidity
proxies, wherever reliable historical/current data is available; to normalise all macro timestamps; to
support daily, weekly, monthly and event-based cadence; and to build a Macro Environment Score with its
components exposed, explicitly never converted into a deterministic crypto prediction.

**Decision — a single provider, the official FRED keyed JSON API, over the undocumented keyless CSV
endpoint.** FRED's raw data endpoints (both `fredgraph.csv` and `api.stlouisfed.org/fred/...`) are blocked by
the sandboxed build environment's egress proxy, but FRED's own HTML documentation pages are not — the same
class of split seen with Blockchair/Binance/DefiLlama in earlier phases. `WebSearch`/`WebFetch` against
`fred.stlouisfed.org/docs/api/fred/series_observations.html` confirmed the real, current shape of the
documented `series/observations` endpoint (base URL, required `api_key` and `file_type=json` parameters, and
the `realtime_start`/`realtime_end`/`vintage_dates` parameters for point-in-time vintage data) without ever
needing a live response. The official JSON API was chosen over `fredgraph.csv` (the graph page's underlying
CSV download, keyless but not a documented, versioned API surface) precisely because it is documented and
versioned — matching R8's adapter-architecture requirement and R3's "never fabricate provider capabilities"
rule. `CFI_PROVIDER_FRED_API_KEY` is required, not optional, the same pattern as SoSoValue (Phase 6).

**Decision — three scope calls, each recorded transparently rather than silently substituted or dropped.**
- **DXY substitute.** The real ICE US Dollar Index (DXY) is proprietary/licensed and not freely available
  from FRED or any other free source found. `DTWEXBGS`, the Fed's own trade-weighted Broad Dollar Index, is
  used instead — labelled "DXY substitute" everywhere it appears (dataset description, score component
  description, API field), never presented as the literal DXY (R3 — never silently substitute one provider
  or series for another).
- **US-only net liquidity, not a true global aggregate.** "Global liquidity proxies" was in the user's list,
  but no free source aggregates non-US central-bank balance sheets (China, EU, Japan, etc.) this phase. The
  system instead computes and clearly labels a **US-only** net-liquidity proxy: Fed balance sheet (`WALCL`,
  weekly) minus Treasury General Account (`WTREGEN`, weekly) minus overnight reverse repo (`RRPONTSYD`,
  daily), a commonly cited formulation. Every field and docstring referencing it says "US-only proxy, not a
  true global aggregate"; "true global liquidity aggregate" is recorded in `NOT_TRACKED` for the user's
  review rather than silently narrowed without saying so.
- **Gold marked `NOT_TRACKED`.** FRED's only free daily gold series (`GOLDAMGBD228NLBM`/`GOLDPMGBD228NLBM`,
  the LBMA fixing) was discontinued in January 2022 at ICE Benchmark Administration's own request — confirmed
  via `WebFetch` against FRED's own removal notice, not assumed. `WebSearch` for a free, keyless replacement
  found only unverified third-party aggregators, so gold is recorded `NOT_TRACKED` rather than sourced from an
  unverified provider (R3).

**Decision — extend the shared `parse_period` utility for monthly cadence, rather than a period string that
misrepresents true cadence.** The spec explicitly requires supporting monthly data (CPI, PCE, unemployment,
M2 monthly). `cfi/core/time.py`'s `parse_period` previously supported only minutes/hours/days/weeks; it now
also accepts `"1mo"` (a nominal 30-day month, `_NOMINAL_MONTH_DAYS = 30`), added as a new regex alternative
distinct from `"m"` (minutes) so existing period strings are unaffected — verified against the existing
`test_periods()` test, unchanged and still passing. This is a small, deliberate, backward-compatible
cross-cutting change to a shared utility, justified by an explicit phase requirement (R13 — not
over-engineered; not a private one-off parser bolted onto the macro module alone).

**Decision — conservative documented release-schedule delays for revised series, not full ALFRED vintage
tracking.** CPI, PCE, unemployment and M2 are revised by their publisher after first release. FRED's default
API returns only the current (most-revised) vintage; true point-in-time vintage data is available via FRED's
own `realtime_start`/`realtime_end`/`vintage_dates` parameters (confirmed in its docs), but building
full revision-history tracking was deliberately not done this phase — not requested, and would be
over-engineering relative to the stated goal (R13). Instead, each series' `available_at` uses a conservative,
documented publication-delay estimate via `AvailabilityRule("event_time_plus", delay, known_when_received=True)`
— the same conservative-estimate pattern as Phase 9's DefiLlama 36-hour rule. The universe module's docstring
records that true vintage support is available later if requested.

**Decision — tolerance windows sized to worst-case staleness, found and fixed via real ingestion, not
assumed.** Running the full FRED ingestion pipeline against a synthetic fake server (`tests/macro_fakes.py`)
surfaced a genuine design flaw before any user-facing bug could occur: `cfi/macro/metrics.py`'s
`latest()`/`trend()` tolerance windows (`DAILY_TOLERANCE`, `WEEKLY_TOLERANCE`, `MONTHLY_TOLERANCE`) were
originally sized to roughly a series' publication delay alone. In fact, a data point's worst-case staleness —
right before the *next* point supersedes it, under completely normal, correct operation — is
**period length + publication delay**: a weekly series (7-day cadence, 3-day delay) can legitimately be up to
~17 days old (7 + 3 + one more period before the next point clears its own delay), not just ~10. The original
windows (5d/11d/50d) were too tight and would have produced spurious "unavailable" readings — including
inside the Macro Environment Score itself — under ordinary, correct operation, not just at an edge case.
Fixed to 7d/18d/95d with the reasoning recorded in the module's own comments. This is the kind of bug R7
("never claim something works without testing it") exists to catch: it was found only by exercising the real
ingestion → API pipeline end-to-end, not by unit-testing formulas in isolation.

**Decision — one score, seven components, direction-annotated.** The **Macro Environment Score**
(`macro_environment_score_v1`, `cfi/macro/score_parameters.py`) follows the same versioned-parameters and
weighted-sub-score pattern established in ADR-0051/ADR-0052/ADR-0053 (frozen `ParameterSet` dataclass,
`CURRENT_VERSION`, hard `KeyError` on an unknown version; sub-score = clip(value ÷ scale, −1, +1); score =
100 × Σ(weight × sub-score) ÷ Σ(available weights); renormalisation on missing components; "Insufficient
data" below `min_available_weight` 0.5). Components: yield-curve slope (0.20), real policy rate (0.20,
inverted), VIX level (0.15, inverted), equity trend (0.15), dollar trend (0.10, inverted), net-liquidity trend
(0.15), oil trend (0.05, inverted) — each carries a `direction_note` explaining which direction is
accommodative vs. restrictive, since several components are inverted relative to their raw sign (e.g. a
*lower* real policy rate is more accommodative). The score's fixed `semantic_note` states plainly it is not a
crypto price prediction, matching the spec's explicit instruction not to convert macro data into a
deterministic crypto prediction, and matching the same non-prediction framing used by every prior phase's
score (Derivatives Health, Liquidity, Retail Activity/Speculation).

**Alternatives considered.** Scraping FRED's graph-download CSV endpoint instead of the JSON API (rejected:
undocumented, unversioned, more fragile to silent schema changes — R8). Sourcing gold from an unverified
third-party aggregator rather than marking it `NOT_TRACKED` (rejected: R3 forbids fabricating or assuming
provider capabilities that were not verified). Building a private one-off period parser inside the macro
module rather than extending the shared `parse_period` (rejected: would duplicate logic already centralised
in `cfi/core/time.py` and risk two divergent definitions of "a month"). Full ALFRED-style vintage tracking
for revised series (rejected this phase as not requested and out of proportion to the ask — R13; noted as
available later).

**Consequences.** No new database migration (all 18 datasets are `kind="scalar"`, stored via the existing
scheduled-source runner). The backend API (`/api/v1/macro/{catalog,overview,history}`) is complete and
tested end-to-end: unit tests for the FRED adapter (request building, FRED's own `"."` missing-value marker,
availability-rule wiring per period kind), the metrics module (all readings and conditions, including the
corrected tolerance windows) and the score; integration tests for ingestion against a synthetic FRED fake
(daily/weekly/monthly/event cadence, no-duplication-on-repeated-recent-window) and for the API (catalog
shape, an "ok" score once every component has data, "insufficient_data" with nothing loaded, history
endpoint). `CFI_PROVIDER_FRED_API_KEY` must be obtained and set by the user before this phase's data can flow
in a live environment (restated in `TODO.md`). Frontend work was not part of the Phase 11 request as given
and was not built. Publishing a v2 parameter set for the score follows the same append-only pattern as
ADR-0051/ADR-0052/ADR-0053.

## ADR-0055 — Phase 12: Market Structure Engine, TOTAL/dominance as calculated metrics, Market Structure Score

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user asked to build the Market Structure Engine, calculating trend, moving averages, RSI,
ATR, volatility, volume trends, VWAP where appropriate, relative strength, support/resistance, market breadth
where available, BTC dominance, ETH/BTC, TOTAL market capitalisation, TOTAL2 and TOTAL3; to create a Market
Structure Score with a transparent methodology; and to never turn these metrics into automatic trading
recommendations.

**Decision — one new ingested dataset (TOTAL market cap), everything else calculated.** The ingestion engine
enforces one dataset per `ingest()` call (`cfi/ingestion/engine.py`), so BTC/ETH dominance, TOTAL2 and TOTAL3
cannot be ingested as a single combined call alongside TOTAL itself, and deriving them from already-tracked
data is architecturally cleaner besides. CoinGecko's `/global` endpoint (verified 2026-09-27 against
`docs.coingecko.com/reference/crypto-global` — the sandbox's egress proxy blocks CoinGecko's raw API like
every other provider's raw endpoints, but not its documentation pages, the same pattern as FRED/Blockchair/
Binance/DefiLlama in earlier phases) is extended onto the existing `cfi/providers/coingecko.py` adapter (no
new adapter). Only `data.total_market_cap.usd` and `data.updated_at` are stored; CoinGecko's own
`market_cap_percentage` (BTC/ETH dominance, computed at CoinGecko's own snapshot time) is deliberately **not**
used — dominance is instead calculated here from this TOTAL value and the per-asset market caps Phase 5/6
already tracks (`cfi.market.universe.MARKET_CAP_USD`), keeping every dominance figure and its inputs
point-in-time consistent with each other rather than mixing a CoinGecko-computed percentage with
independently-fetched market caps. TOTAL2 = TOTAL − BTC market cap; TOTAL3 = TOTAL2 − ETH market cap, matching
the common charting convention (e.g. TradingView's CRYPTOCAP:TOTAL2/TOTAL3) — all Calculated Metrics (R2),
never directly observed. The one new dataset uses the sentinel-subject pattern established by Phase 9's
`TOTAL_SUBJECT` and Phase 10's `TRENDING_SUBJECT`: `asset = subject_ref = GLOBAL_SUBJECT = "GLOBAL"`, since a
global reading has no per-asset dimension.

**Decision — one venue (Coinbase), one benchmark (BTC), for every technical calculation.** Every technical
indicator (moving averages, trend, RSI, ATR, volatility, volume trend, VWAP, relative strength,
support/resistance) is computed from Coinbase Exchange's daily OHLCV bars — Phase 5's priority-10 default
venue, with native daily bars for all four tracked assets (BTC, ETH, SOL, XRP) — so every asset is compared on
the same venue and timeframe rather than blending venues (mirrors the market module's own "never blend
venues" rule, `cfi/market/sources.py`). Relative strength, ETH/BTC and (by construction) dominance are always
benchmarked against BTC (`BENCHMARK_ASSET`), the market's largest, most liquid, longest-history asset — a
judgment call recorded in `cfi/market_structure/universe.py`, not assumed silently. ETH/BTC needs no new
ingestion: it is ETH's close ÷ BTC's close from already-ingested Coinbase bars.

**Decision — market breadth is a four-asset proxy, recorded in `NOT_TRACKED`, never presented as full-market
breadth.** No free source publishes an advance/decline line across the whole crypto market (thousands of
listed assets). Market breadth here is the fraction of this platform's own four tracked assets trading above
their own 50-day SMA — restated in `NOT_TRACKED` and `TODO.md` for the user's review rather than silently
narrowed without saying so (R3), the same posture as Phase 11's US-only net-liquidity proxy (ADR-0054).

**Decision — standard, named formulas for every indicator, each a judgment parameter, not a fitted or
optimised one.** Moving averages: SMA over 20/50/200 daily bars. Trend: the conventional golden/death-cross
ordering (`uptrend`: close > SMA50 > SMA200; `downtrend`: close < SMA50 < SMA200; `mixed` otherwise). RSI:
Wilder's 14-day relative-strength index (average gain/loss, Wilder-smoothed). ATR: Wilder's 14-day average
true range, reported as a percentage of price and ranked as a nearest-rank percentile of its own trailing
~365-day history (minimum 20 readings) — the same percentile-ranking idea as every other phase's statistical
signals (e.g. `cfi.retail.metrics.percentile_rank`), reimplemented locally in `cfi/market_structure/metrics.py`
to keep the module self-contained rather than importing across unrelated business domains (R13). Realized
volatility: annualized standard deviation of 30-day rolling daily log returns (`std × √365`), computed with
`Decimal.ln()`/`Decimal.sqrt()` for full precision rather than converting to float, percentile-ranked the same
way as ATR. VWAP: a rolling 20-day volume-weighted average price, explicitly documented and labelled
everywhere as a **rolling-window approximation**, never a session-anchored intraday VWAP — daily bars have no
intraday session to anchor to. Support/resistance: a naive rolling 20-day and 50-day high/low (a
Donchian-channel-style method), explicitly never a fitted, clustered or ML-derived level. All thresholds
(RSI 70/30, ATR/volatility percentile 80/20, volume 1.5x/0.5x, relative strength ±5pp, breadth 75%/25%, ETH/BTC
trend ±3pp) are published verbatim in the `/catalog` endpoint's `parameters` field, matching every prior
phase's transparency posture.

**Decision — one score, five components, direction-annotated, explicitly not a trading recommendation.** The
**Market Structure Score** (`market_structure_score_v1`, `cfi/market_structure/score_parameters.py`) follows
the same versioned-parameters and weighted-sub-score pattern established in ADR-0051/ADR-0052/ADR-0053/
ADR-0054 (frozen `ParameterSet` dataclass, `CURRENT_VERSION`, hard `KeyError` on an unknown version; sub-score
= clip(value ÷ scale, −1, +1); score = 100 × Σ(weight × sub-score) ÷ Σ(available weights); renormalisation on
missing components; "Insufficient data" below `min_available_weight` 0.5). Components: BTC price vs. 200-day
SMA (0.25), BTC momentum/RSI vs. neutral (0.20), market breadth (0.20), altcoin relative strength — the
average of ETH/SOL/XRP's spread vs. BTC across whichever of the three have enough history (0.20, never a
fabricated fill-in for a missing asset — R3), and BTC's realized-volatility percentile (0.15, inverted: calmer
than usual is more constructive). The score's fixed `semantic_note` states plainly it does not convert these
metrics into an automatic trading recommendation, matching the phase's explicit instruction and the same
non-prediction framing used by every prior phase's score.

**Alternatives considered.** Storing CoinGecko's own `market_cap_percentage` for BTC/ETH dominance instead of
calculating it (rejected: would mix a CoinGecko-computed snapshot with independently-fetched market caps,
breaking point-in-time consistency between dominance and its own inputs). Ingesting BTC/ETH dominance as part
of the same `/global` call as TOTAL (rejected: the two would still need separate `dataset_id`s under the
ingestion engine's one-dataset-per-call rule, so nothing is saved by combining them versus calculating
dominance directly). Importing `cfi.retail.metrics.percentile_rank` instead of a local `_percentile_rank()`
helper (rejected: would couple two unrelated business-domain modules for a few lines of identical logic —
R13). Blending OHLCV bars across multiple venues per asset (rejected: would violate the project's existing
never-blend-venues rule and make cross-asset comparisons venue-inconsistent).

**Consequences.** One new migration-free dataset (`market_structure.total_market_cap.usd`, `kind="scalar"`,
stored via the existing scheduled-source runner, no new database migration). The backend API
(`/api/v1/market-structure/{catalog,overview,history}`) is complete and tested end-to-end: unit tests for the
CoinGecko `/global` adapter extension (request building, schema validation, non-positive-value rejection), the
metrics module (every reading and condition, including edge cases like flat prices and too-little history) and
the score (renormalisation, insufficient-data floor, bands, clipping, the inverted volatility component);
integration tests for ingestion against a synthetic CoinGecko `/global` fake (stored value, sentinel subject,
no-duplication-on-repeated-recent-window) and for the API (catalog shape, an "ok" score once bars and TOTAL are
loaded, "insufficient_data"/"unavailable" with nothing loaded, history endpoint). Frontend work was not part
of the Phase 12 request as given and was not built. Publishing a v2 parameter set for the score follows the
same append-only pattern as ADR-0051/ADR-0052/ADR-0053/ADR-0054.

---

## ADR-0056 — Phase 13: Capital Flow Divergence Engine — 10 comparisons, the Capital Flow Map, hedged rotation

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user's Phase 13 instruction — quoted verbatim in `PROGRESS.md`'s Phase 13 log entry — asked for
the platform's central feature: a standardized divergence matrix across 10 named comparisons (institutional vs.
retail, institutional vs. price, whale vs. retail, whale vs. price, liquidity vs. price, open interest vs.
price, funding vs. price, stablecoin supply vs. price, derivatives leverage vs. price, macro vs. market
structure), each reporting observed divergence, magnitude, historical percentile, duration, supporting and
contradicting evidence, historical examples and data quality — explicitly never auto-labelled bullish/bearish —
plus a Capital Flow Map (institutions → whales → liquidity → BTC → ETH → SOL → large caps → mid caps → DeFi →
AI-related → meme → retail) that clearly distinguishes OBSERVED FLOW from INFERRED ROTATION and never claims
money moved between assets unless the data supports the claim.

**Decision — a pure computation module, no ingestion of its own.** `cfi/divergence/` follows the same
"no-ingestion" posture as `market_structure` (which ingests exactly one dataset): the Divergence Engine ingests
literally nothing. Every input is read through each already-tested domain's own public service methods
(`InstitutionalService.etf_flows()`, `WhaleService.flows()`, `RetailService.history()`,
`LiquidityService.history()`, `DerivativesService.history()`, `MarketStructureService.history()`), never raw
queries, so the Divergence Engine inherits each domain's own point-in-time discipline (`available_at <= as_of`,
latest revision wins — ADR-0018) for free rather than re-implementing it. The two documented exceptions are
price bars (read via `MarketQueries.series_id` + `.bars()`, mirroring `market_structure/service.py`'s own
`_asset_bars` helper) and macro net liquidity, which is recomputed daily from raw `MacroQueries.observations()`
through `cfi.macro.metrics.us_net_liquidity()` because no domain service currently exposes a ranged net-liquidity
history endpoint. There is no `sources.py`, no `jobs.py`, no worker/schedule change, and no new provider
configuration for this phase.

**Decision — an "as-of style" window-reading methodology, new to this phase, documented transparently.**
Direction and magnitude for every comparison leg are computed as (latest known value at-or-before `as_of`)
minus (latest known value at-or-before `as_of − window_days`) — the last known reading is carried forward for
series that update less than daily (e.g. weekly/monthly macro releases), consistent with the point-in-time
philosophy used everywhere else in the platform, and explicitly never an invented interpolation between two
known points. `window_reading()`'s own module docstring states this plainly so a reader does not mistake it for
a naive same-day-only diff.

**Decision — reuse `percentile_rank`, build `duration`/`historical_examples` new.** A research pass across every
domain module (delegated to a subagent, cross-checked directly) confirmed `cfi.retail.metrics.percentile_rank`
is a genuinely generic, pure, directly-reusable nearest-rank percentile function — imported unchanged rather
than reimplemented a sixth time (contrast ADR-0055, which deliberately did *not* import it across an unrelated
business domain for a few lines of logic; here the function is imported as-is with no modification, which is a
materially different and lower-coupling case). By contrast, no streak/duration or historical-episode-scanning
helper existed anywhere in the codebase before this phase — `duration()` (a capped backward walk over matching
direction pairs) and `historical_examples()` (a percentile-ranked scan of prior matching runs, threshold ≥ 70th
percentile, most recent first, capped at 3) are new, purpose-built for this engine, and documented in
`DATA_DICTIONARY.md` §5i as new methodology rather than an established platform-wide pattern.

**Decision — deterministic, rule-based evidence text, never AI-generated.** Per R2/R6 (Claude interprets, it
does not compute), every supporting/contradicting bullet in `evidence()` cites a number already computed
elsewhere in the same response (percentile thresholds, duration vs. window length, per-leg data quality) — an L3
Statistical Signal fact, not an L5 AI Interpretation. No language model is invoked anywhere in this module.

**Decision — resolve the apparent redundancy between comparisons #5/#8 and #6/#9 with genuinely distinct
metrics, rather than merging them or fabricating a difference.** #5 "liquidity vs. price" uses the *combined*
USDT+USDC TOTAL stablecoin supply (a broad dry-powder proxy); #8 "stablecoin supply vs. price" uses USDT *alone*
(a single-issuer view) — genuinely different aggregations of genuinely tracked data, both documented in each
`ComparisonDef.notes`. #6 "open interest vs. price" uses the raw OI aggregate level; #9 "derivatives leverage vs.
price" uses a leverage-skew proxy (mean `|long/short account ratio − 1|` across venues — a directional-crowding
measure, not a level) — again genuinely distinct, not a cosmetic renaming of the same input.

**Decision — comparison #10 substitutes TOTAL crypto market cap for the Market Structure Score.** The Market
Structure Score (ADR-0055) has no ranged/historical time series in this platform — it is computed fresh at read
time with no persisted history — so it cannot supply a windowed direction/magnitude reading. Rather than
fabricate a historical score series, #10 "macro vs. market structure" is built from TOTAL crypto market cap
(already a Phase 12 calculated metric with real historical bars behind it), and this substitution is documented
in `cfi/divergence/universe.py::NOT_TRACKED` and `TODO.md`, not silently narrowed (R3).

**Decision — the Capital Flow Map is an explicit, versioned 12-node registry; untracked categories are marked
`unavailable`, not populated.** An exhaustive grep (via the same research subagent) confirmed no asset-category
taxonomy (large-cap/mid-cap/DeFi/AI/meme) exists anywhere in the codebase — this is new, `cfi/divergence/
capital_flow_map.py::NODES`. Mid Caps, DeFi and AI-related assets are honestly marked `measurement_class =
"unavailable"`, `fetch_key = None` (recorded in `NOT_TRACKED`) rather than backfilled with loosely-related or
fabricated data. "Large Caps" uses XRP price as a documented proxy — the only additional large-cap asset this
platform tracks beyond BTC/ETH/SOL. "Meme assets" uses retail's meme-trending-count, explicitly labelled a
retail-**attention** proxy in its `scope_note`, never presented as an observed capital flow — R1's "never present
uncertain inference as fact" applies as much to a node label as to a sentence of prose.

**Decision — `classify_edge()` only ever hedges; it never asserts a transfer.** Directly implementing the user's
explicit "do not claim money moved between assets unless the data supports the claim": an edge only emits a
`possible_rotation` hypothesis (`evidence_class = "inferred"`) when its two adjacent nodes move in strictly
opposite directions over the same window, and the hypothesis text is fixed, hedged wording — "consistent with
(but not proof of) ...; no transfer between these nodes is directly observed" — never a bare directional claim.
Same-direction pairs get `no_rotation_signal`; any node with an unknown/unavailable direction gets `status =
"unavailable"` and no hypothesis text at all. A dedicated unit test
(`test_classify_edge_never_claims_money_moved`) asserts the hedging phrases are always present.

**Alternatives considered.** Computing all 10 comparisons' data directly from each domain's raw ORM queries
(rejected: would duplicate each domain's own point-in-time filtering logic and risk drifting out of sync with
it — R13, DRY). Reimplementing `percentile_rank` locally as ADR-0055 chose for market_structure (rejected here:
that decision was about avoiding coupling two business domains for a few lines of near-identical logic; here the
function is imported completely unchanged, which is direct, low-risk reuse rather than domain coupling).
Silently dropping comparisons #8 and #9 as "duplicates" of #5 and #6 (rejected: each pair measures a genuinely
different quantity — R3 forbids silently narrowing scope without saying so). Fabricating a historical Market
Structure Score series for comparison #10 (rejected outright: R3, never invent missing values). Populating Mid
Caps/DeFi/AI-related with loosely related tracked assets to avoid empty map nodes (rejected: R3 and R5 — that
would misrepresent proxy data as an observed category).

**Consequences.** No new database migration (the engine has zero storage of its own). New API surface:
`/api/v1/divergence/{catalog,pair,matrix,capital-flow-map}`, registered in `cfi/api/app.py` alongside every
other domain router. New ruff per-file-ignore (`RUF001/RUF002/RUF003`) for `src/cfi/divergence/**`, matching the
precedent already set for every prior phase that legitimately uses arrow/minus-sign characters in docstrings.
Unit tests cover `metrics.py` (window reading, rolling series, percentile, duration, historical examples,
quality summary, evidence rules), `comparisons.py` (matrix shape, registry completeness, asset-scope validity)
and `capital_flow_map.py` (node order, unavailable/proxy marking, edge classification, the never-claims-a-
transfer guarantee) against fully synthetic data — no database required. Integration tests (DB-gated) cover the
full API against real price bars, TOTAL market cap and macro FRED series (the lightest harnesses already proven
in Phases 11/12); they deliberately do not additionally re-seed institutional/whale/retail/liquidity/derivatives
fixtures, since those domains' own integration suites already cover ingestion and every divergence adapter
reading them is unit-tested against synthetic series — a documented scope decision, not an oversight. Frontend
work was not part of the Phase 13 request as given and was not built.

---

## ADR-0057 — Phase 14: Market Regime Engine — seven rule-based regimes, confidence-as-definition-fit,
duration by daily walk vs. historical examples by weekly sample

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user's Phase 14 instruction asked for a Market Regime Engine classifying the market into one
of seven regimes (Accumulation, Recovery, Expansion, Euphoria, Distribution, Capitulation, Mixed/Unclear) using
measurable inputs from institutional flows, whale behaviour, retail activity, liquidity, derivatives, macro and
market structure — explainable, with confidence, contributing metrics, contradicting metrics, historical
examples, regime start date and regime duration. Confidence was explicitly defined by the user as "confidence
that the market satisfies the regime definition," **not** a probability that price will rise or fall.

**Decision — a pure computation module, no ingestion of its own, reusing `cfi.divergence.adapters.Adapters` as
a cross-module service factory.** `cfi/regime/` follows the exact "no-ingestion" posture established by
`market_structure` (Phase 12) and `divergence` (Phase 13): it ingests nothing. Rather than re-implementing each
domain's `*Service(queries)` construction, `cfi.regime.snapshot.gather_snapshot` reuses
`cfi.divergence.adapters.Adapters(engine)` as a plain service factory (`.institutional()`, `.whales()`,
`.retail()`, `.liquidity()`, `.derivatives()`, `.market_structure()`), calling each domain's own already-tested
public method (`score()`/`overview()`/`asset()`) exactly the way `cfi.whales.service._institutional` already
calls `InstitutionalService.score()` and re-parses its string-encoded `"value"` field back into a `Decimal` —
a pre-existing, direct precedent for this exact conversion, not a new pattern invented for this phase. Macro is
the one exception: `Adapters.macro()` returns a raw `MacroQueries` object (divergence's own documented
exception, since it recomputes net liquidity directly), so `cfi.regime.snapshot` constructs a `MacroService`
directly from that same `MacroQueries` rather than misusing `Adapters.macro()` for something it was not built
to provide.

**Decision — confidence is (matched weight) / (available weight) among a regime's own conditions, never a
price-direction probability.** Each of the six substantive regimes (`mixed_unclear` is the classifier's own
fallback, never itself a defined regime — see below) is a named set of single-metric conditions
(`cfi.regime.parameters.ConditionDef`): a comparator (`gte`/`lte`/`between`/`categorical`), a threshold, and a
weight; weights within one regime sum to 1. A condition whose underlying metric is not `"ok"` is excluded from
both the numerator and denominator (never scored as "failed") — a regime with too little available data across
its own conditions (`available_weight < min_available_weight`, 0.5) is not scored at all
(`status="insufficient_data"`), rather than being assigned a low but misleadingly precise confidence. Every
response carries a fixed `confidence_semantic_note` restating the user's own definition verbatim, so no reader
mistakes a high regime confidence for a bullish/bearish price call.

**Decision — thresholds are anchored to each domain score's own already-published bands, not fabricated fresh
numbers.** Where a regime condition tests a domain score (institutional/whale/liquidity/macro/market-structure
±15/±50, retail activity 40/60/80, derivatives health 25/50/75), the exact same threshold that score's own
`bands` tuple already uses is reused — e.g. "whale accumulating" tests `whale_score >= 15`, the identical
number `whales/score.py`'s own band table calls "accumulation." This keeps the regime engine's judgment
parameters consistent with, and traceable to, decisions the platform has already published and documented,
rather than inventing a second, uncoordinated threshold for the same underlying concept. RSI 70/30 and market
breadth 75%/25% are reused from `market_structure`'s own parameters the same way.

**Decision — assignment requires both a confidence floor and a clear lead over the runner-up; anything short of
that is "mixed_unclear," reported with the specific reason.** A regime is assigned outright only when its
confidence is at or above `min_confidence_assign` (0.55) **and** it leads the second-best regime by at least
`tie_margin` (0.08). Falling short of either produces `mixed_unclear` — never an arbitrary tie-break — with the
top candidate(s) and a plain-language reason (a close tie between two named regimes, or the closest match's own
confidence falling below the threshold) attached, so "mixed/unclear" is itself explainable rather than a silent
failure mode. Every regime's own candidate score (not just the winner's) is returned for full transparency.

**Decision — regime duration is a daily backward walk; historical examples are a coarser weekly sample — two
deliberately different, documented performance trade-offs, not an oversight.** No domain score has a
persisted, ranged history of its own (the Market Structure Score gap already documented in Phase 12/13; the
same gap applies to every other domain score here), and there is no stored regime-history table. `regime
duration` therefore walks backward from `as_of` one day at a time, re-classifying each day, until the label
changes or a cap (`MAX_DURATION_LOOKBACK_DAYS`, 120) is reached — usually a short walk in practice, since most
regimes do not persist anywhere near the cap, but capped conservatively because each day re-runs the full
seven-domain classification. `historical_examples` instead samples weekly
(`HISTORICAL_STEP_DAYS=7`) over a much longer lookback (`HISTORICAL_LOOKBACK_DAYS=365`) further back than the
current streak — intentionally coarser and cheaper, since finding *a* prior similar episode does not need
day-level precision the way "how long has this held" does. Each historical `as_of` is classified with
`knowledge_time` pinned to that same instant, deliberately excluding any later-ingested data revision from
leaking into a historical read (R4). As a further, documented performance short-circuit: when the *current*
classification itself is `"insufficient_data"` (no regime could be evaluated at all — e.g. an empty database),
both the duration walk and the historical sample are skipped outright, since they would only rediscover the
same empty result at every prior point checked; duration is reported as 0 with no start date, and the examples
list is empty.

**Alternatives considered.** Building a weighted composite "regime score" the way every prior phase's score
works (rejected: R2 explicitly defines a Regime Classification as a *label with confidence*, a different kind
of output from a continuous −100…+100 score — the seven domain scores are themselves already that kind of
value and are consumed as inputs here, not duplicated). Re-deriving each domain's own construction
(`*Service(*Queries(engine))`) independently instead of reusing `cfi.divergence.adapters.Adapters` (rejected:
would duplicate already-tested, already-reviewed construction code for no benefit — `Adapters` was designed as
a generic per-domain service factory and this is a natural, low-risk second use of it). Walking every single
day for `historical_examples` the same way `regime_duration` does (rejected: over a full year that is roughly
7x more re-classification work for a feature that does not need day-level precision — a documented, deliberate
trade-off, not a shortcut taken silently). Assigning a regime purely on "highest confidence, no threshold or
tie check" (rejected: would produce a confident-sounding label even when nothing is clearly indicated, directly
contradicting R1's "never present uncertain inference as fact").

**Consequences.** No new database migration (the engine has zero storage of its own). New API surface:
`/api/v1/regime/{catalog,current}`, registered in `cfi/api/app.py` alongside every other domain router. Unit
tests cover `cfi.regime.parameters` (registry completeness, weights summing to 1, hard `KeyError` on an unknown
version), `cfi.regime.classifier` (condition evaluation for every comparator, insufficient-data handling,
regime selection, both mixed_unclear paths — a close tie and a below-threshold best candidate), `cfi.regime.
history` (duration counting/capping, historical-example sampling) and `cfi.regime.snapshot`'s pure parsing
helpers — all against fully synthetic data, no database required. Integration tests (DB-gated) cover the
catalog's shape and the empty-database `"insufficient_data"`/`mixed_unclear` path through the real API; a fully
"ok" classification needs all seven domains populated at once, each of which already has its own integration
suite proving its own ingestion/scoring pipeline, so re-seeding all seven here was deliberately scoped out
rather than duplicating that coverage (documented, not silently narrowed). Frontend work was not part of the
Phase 14 request as given and was not built.

## ADR-0058 — Phase 15: Historical Similarity Engine — 9 fixed-normalized features, weekly-sampled
candidates, forward returns/drawdown gated by knowability

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user's Phase 15 instruction asked for a Historical Similarity Engine comparing the current
market state against historical periods, using features from institutional flows, whale flows, retail
activity, liquidity, funding, open interest, volatility, market structure and macro; normalizing them
appropriately; using a documented similarity methodology; and for each historical analogue showing date,
similarity score, regime, 7/30/90-day forward return, maximum drawdown and volatility. Two constraints were
explicit and non-negotiable: "Historical future returns may only be displayed when they would genuinely have
been known after that historical date. Never allow future information to influence the similarity score,"
and "Do not produce a predicted future return. Show distributions and historical ranges instead."

**Decision — feature normalization uses fixed, documented bounds decided once, never derived from any date's
own data.** The 9 features map directly onto already-published fields: 5 are existing composite scores on a
fixed, documented `-100..+100` range of their own (institutional, whale, liquidity, market structure, macro —
all from the same `score = 100 x sum(weight x sub-score) / sum(available weights)` formula, confirmed by
direct read of each domain's `score.py`), 1 is already a `0..100` score (retail activity), 1 is already a
percentile (`market_structure`'s `volatility.percentile`), and the remaining 2 are raw, standalone fields with
no natural 0..100 range of their own (`derivatives.asset()`'s `funding.annualised_7d_pct` and
`open_interest.change_7d_pct`), given fixed clamp bounds (`±100%` and `±50%` respectively) chosen as generous,
documented v1 judgment values, not fitted to data. An alternative — normalizing every feature via percentile
rank against a trailing window, or via min/max scaling across the batch of dates actually being searched — was
considered and rejected: either approach would make a candidate date's own similarity score depend on data
from OTHER dates in the search (including dates chronologically after that candidate), which is exactly the
kind of indirect look-ahead leakage the user's explicit instruction rules out. Fixed, data-independent bounds
make it structurally impossible for the similarity score to be influenced by anything outside that one
date's own snapshot.

**Decision — pure computation, no ingestion of its own, its own self-contained snapshot module (not importing
`cfi.regime`).** `cfi/similarity/` follows the same no-ingestion posture as `cfi.regime` (Phase 14) and
`cfi.divergence` (Phase 13), reusing `cfi.divergence.adapters.Adapters` as a service factory. Seven of the nine
features are the same underlying fields `cfi.regime.snapshot` already reads, but `cfi.similarity.snapshot` is a
separate, self-contained copy rather than an import from `cfi.regime`: the two engines are independent
consumers of the same domain services, and Phase 14's already-committed, already-verified module is not
reopened to serve a later phase (R13). The 2 new standalone fields (funding, open interest) come from the same
`derivatives().asset()` call `cfi.regime.snapshot` already makes for its own `derivatives_health` metric.

**Decision — similarity is a weighted RMSE-based distance converted to a 0..100 score, insufficient-data-gated
per pair.** For a query date and a candidate date, only features where BOTH are `"ok"` are compared; the
similarity score is `100 - sqrt(weighted mean squared difference of normalized values)`, restricted to the
common features, and the pair is not scored at all (`"insufficient_data"`) if the compared features' combined
weight falls below `min_available_weight` (0.5) — the same discipline `cfi.regime.classifier` already applies
to confidence, rather than assigning a misleadingly precise score from too little evidence.

**Decision — weekly-sampled candidates over a 2-year lookback, greedily de-duplicated by a minimum gap.**
Scoring every single day over a multi-year lookback would require one full 9-feature snapshot (7 domain
service calls) per day; a weekly sample (`step_days=7`) over `lookback_days=730` is a deliberate, documented
cost/precision trade-off, mirroring the same trade-off `cfi.regime.history.historical_examples` already made
for Phase 14. Selecting the top-N candidates by raw similarity score alone was considered and rejected: it
would often return several consecutive weeks of the same historical episode as if they were N independent
analogues. Instead, candidates are ranked by similarity and greedily selected only if at least `min_gap_days`
(30) from every already-selected date, so the results span genuinely different episodes.

**Decision — forward returns and maximum drawdown are gated by the query's own `as_of`, never by what
happens to be present in the fetched bar range.** `cfi.similarity.outcomes.forward_return` and `max_drawdown`
both check that the horizon's target date is at or before the caller's `as_of` before reporting a value —
returning a first-class `"not_yet_known"` status otherwise (R3: missing is a first-class state), regardless of
whether a bar dated after that target happens to exist in the fetched range (a deliberate look-ahead-leak test
proves this in `test_similarity_outcomes.py`, per TODO.md's own long-standing suggestion for this phase). A
partial (not-yet-complete) drawdown window is reported with a `partial` flag rather than withheld entirely,
since it reflects only genuinely elapsed, real data — never a projection of what the remainder of the window
might bring.

**Decision — no predicted future return; a distribution across analogues instead.** The API never produces
a single expected/forecast return. Each of the (up to 5) detailed analogue rows reports its own actual
historical forward returns; a broader, still de-duplicated set of up to 15 analogues (`max_distribution_sample`)
feeds a per-horizon distribution (count, min, p25, median, p75, max) built with Python's `statistics` module,
reported as `"insufficient_data"` below `min_distribution_sample` (3) rather than a distribution built from too
few points.

**Alternatives considered.** Reusing `cfi.regime.snapshot.gather_snapshot` directly and only adding the 2 new
fields via a second, separate `derivatives().asset()` call (rejected: would call the same domain service twice
per date for no benefit, and Phase 14's committed module would need to either be modified — reopening a closed
phase, R13 — or imported for internals it was not designed to expose). Recomputing volatility from scratch for
each analogue (rejected: `market_structure.overview()`'s own `volatility.annualized_pct`, already fetched as
part of the 9-feature snapshot, is the same figure and reusing it avoids a second, redundant bar-range fetch
per analogue). A single combined drawdown+forward-return bar fetch per analogue (rejected in favour of one
bulk bar fetch per request, covering the earliest selected analogue through `as_of` — cheaper, and the
point-in-time cutoff is identical either way since both use the same `as_of`).

**Consequences.** No new database migration (the engine has zero storage of its own). New API surface:
`/api/v1/similarity/{catalog,current}`, registered in `cfi/api/app.py` alongside every other domain router.
Unit tests cover `cfi.similarity.parameters` (weights summing to 1, fixed-bound normalization, hard `KeyError`
on an unknown version), `cfi.similarity.scorer` (common-feature comparison, insufficient-data gating), `cfi.
similarity.outcomes` (forward return/drawdown knowability gating, including deliberate look-ahead-leak tests),
`cfi.similarity.search` (candidate sampling, de-duplicated selection, and a look-ahead test proving each
candidate is gathered at its own date only) and `cfi.similarity.snapshot`'s pure parsing helpers — all against
fully synthetic data, no database required. Integration tests (DB-gated) cover the catalog's shape and the
empty-database `"insufficient_data"` path through the real API; a fully "ok" search needs the same seven
domains populated across many historical dates, each already covered by its own integration suite, so
re-seeding them here was deliberately scoped out (documented, not silently narrowed). Frontend work was not
part of the Phase 15 request as given and was not built.

## ADR-0059 — Phase 16: Backtesting Engine — event-driven replay, execution-lag anti-look-ahead,
long-only v1, no optimizer, persistence/API deliberately deferred pending quantitative review

**Status:** Accepted (implemented 2026-09-27)

**Context.** The user's Phase 16 instruction asked for a production-quality research and backtesting engine
supporting historical replay, strategy/signal/entry/exit definitions, position sizing, fees, slippage,
liquidity constraints, turnover, exposure, leverage, stop conditions and time-based exits; in-sample/
validation/out-of-sample and walk-forward testing; prevention of look-ahead bias, survivorship bias, data
leakage and future revisions leaking into past decisions; a fixed list of 17 named performance metrics;
storage of strategy/parameter/dataset/code version, timestamp and assumptions for full reproducibility;
synthetic datasets specifically designed to detect look-ahead bias; tests; and an explicit instruction not to
optimize parameters against the test set. Unlike every prior phase, the closing instruction was **"After
implementation, stop and wait for a quantitative review"** rather than "Commit. Stop." — a distinct signal
that this phase's own methodological soundness, not the next phase, is what the user wants to check first.

**Decision — a single-asset (BTC), long-only, event-driven day-by-day replay loop
(`cfi.backtest.engine.run_backtest`).** Per simulated day: (1) execute any order scheduled the PRIOR day at
TODAY's open; (2) check stop-loss/take-profit intrabar against TODAY's own high/low (the one exception to the
execution lag, since a stop is a risk control, not a signal decision); (3) mark to market at TODAY's close,
recording one `EquityPoint`; (4) compute the strategy's signal from `bars[: i + 1]` only and decide tomorrow's
order. No parameter search exists anywhere in `cfi.backtest` (`cfi.backtest.splits` only partitions time into
in-sample/validation/out-of-sample and walk-forward train/test windows for the user to manually judge
generalization of a strategy definition that is already fully specified before any run starts) — directly
satisfying "do not optimize parameters against the test set."

**Decision — the execution-lag anti-look-ahead convention.** A signal computed from day D's data (through
D's own close) can only be acted on at day D+1's open — never at D's own close, which would let a decision
see a price it could not yet have known. Position sizing is capped by the TRAILING average volume through the
decision day, never the (not-yet-known) execution bar's own volume. Both conventions are asserted directly by
integration tests that insert a future price shock as a later revision (`revision=1`, a far-future
`available_at`) of an existing bar and prove the result is byte-identical to a run against the original,
single-revision data — and only changes once the run's own `as_of` is moved past that revision's actual
availability (`tests/integration/test_backtest_engine.py`). A second test proves a run over `[start, end]` is
identical whether or not bars strictly after `end` exist in the database at all. These are this phase's
required "synthetic datasets specifically designed to detect look-ahead bias."

**Decision — long-only v1 scope (not silently narrowed).** The user's spec lists "exposure" and "leverage"
but never "short selling" or "long/short"; long-only already exercises both (leverage > 1x borrows capital to
hold more BTC than equity alone would buy; exposure ranges 0..leverage). `cfi.backtest.universe.NOT_TRACKED`
documents this and two other explicit scope decisions (no survivorship-bias handling, since there is only one
tradable asset and so no universe of assets to have survivors or delistings; the execution-lag/stop exception
above) as first-class, readable strings rather than silent omissions.

**Decision — one uniform, always-`async` `Signal` protocol (`cfi.backtest.signals.Signal`) rather than a
`PriceSignal | DomainSignal` union.** An earlier version of this module split signals into two Protocols with
different call signatures (`value_at(bars)` vs. `async value_at(adapters, *, as_of)`) and dispatched between
them with `isinstance`; this type-checked incorrectly under mypy strict (a Protocol-typed union does not
narrow reliably through `isinstance` against one concrete implementation) and, independently of the type
checker, made every future signal author responsible for updating a central dispatcher. The fix was to give
every signal — price-based (`SmaCrossoverSignal`, `RsiSignal`, reusing `cfi.market_structure.metrics`'s
already-tested `moving_averages`/`rsi`) and domain-based (`DomainScoreSignal`, reusing
`cfi.similarity.snapshot.gather_snapshot`'s already-tested 9-feature extraction) — the same signature:
`async def value_at(self, bars_through_today, adapters, *, as_of)`. A price signal ignores the
`adapters`/`as_of` it does not need; a domain signal ignores `bars_through_today`. The engine's own
`_signal_value` helper is now a single unconditional call with no branching at all.

**Decision — single-scalar equity bookkeeping (no separate cash/BTC ledgers).** Equity is one running
`Decimal`, adjusted by fees at entry/exit and by daily mark-to-market P&L
(`size_base * (close_t - close_{t-1})`), with special handling for the entry day (mark from the slipped entry
price) and the exit day (mark from the prior close to the exit price, then flat). This is simpler than
tracking cash and BTC balances separately and is sufficient because the engine never holds more than one
position at a time (a consequence of the long-only, single-asset v1 scope above).

**Decision — a versioned `CostParameterSet` (fee/slippage/liquidity-participation-cap), same registry pattern
as every other parameter set in this platform.** `cost_model_v1` (10 bps fee, 5 bps slippage, 5% max
participation of trailing volume) are documented, generic, un-fitted v1 defaults — the same posture every
score band and weight set in this platform has taken since Phase 12.

**Decision — reproducibility fields are attached to every `BacktestResult`, not persisted to a database
table.** `RunVersions` (strategy id/version, cost-parameter version, a SHA-256 dataset fingerprint over
asset/start/end/as_of/knowledge_time/provider_id, the installed `cfi` package version, a timestamp) and
`Assumptions` (every cost/sizing/execution-lag assumption behind the numbers, restated in full) are returned
alongside `metrics`, `trades` and `equity_curve` on every call to `run_backtest`, satisfying the user's
"every backtest must be reproducible" requirement without yet requiring a database migration.

**Decision — persistence (a `sig`-schema table + migration) and an API surface are deliberately NOT built in
this phase**, unlike every previous engine phase (13–15), each of which shipped a migration and an API route
alongside its core logic. This is a direct reading of the user's own closing instruction — "after
implementation, **stop and wait for a quantitative review**" — as distinct from every prior phase's "Commit.
Stop.": the user asked to review the backtesting methodology itself before more engineering investment goes
into storing and serving its results. `cfi.backtest` therefore has zero database footprint today (no new
migration was written). This is a scope decision to flag explicitly, not an oversight — see TODO.md.

**Alternatives considered.** A `PriceSignal | DomainSignal` Protocol union with `isinstance`-based dispatch
(rejected: see the Signal-protocol decision above — both a type-checking dead end and a maintenance burden).
Tracking cash and BTC as two separate running balances (rejected: unnecessary given the single-position,
long-only v1 scope; would only earn its complexity once short-selling or multi-asset exposure exists).
Numpy/pandas for the metrics module (rejected: no numpy/pandas/scipy dependency exists anywhere in this
codebase — confirmed by a full `pyproject.toml` survey before writing this module — and stdlib
`Decimal`/`statistics` are sufficient for every one of the 17 required metrics).

**Consequences.** No new database migration and no new API route this phase (see the persistence/API
decision above). New package: `cfi/backtest/` (`universe`, `costs`, `signals`, `strategy`, `splits`, `metrics`,
`versioning`, `engine`, plus `__init__.py`). Unit tests cover every pure-function module (`costs`, `signals`'
price-signal branches and domain-signal feature-id validation, `strategy`'s comparator and example-strategy
shapes, `splits`' partitioning, `metrics`' None-guarding, `versioning`'s fingerprint determinism) against
synthetic data, no database required. Integration tests (DB-gated) seed a fully controlled, deterministic
price path directly into `obs.series`/`obs.market_bar` (bypassing the ingestion pipeline) and cover: a
trending path producing trades and metrics; exact reproducibility of two identical runs; the two look-ahead-
bias/leakage tests described above; and `"insufficient_data"` status for too-short windows and unknown
assets. Frontend work was not part of the Phase 16 request as given and was not built.

---

## ADR-0060 — Phase 18: `resolve_query_times` — `knowledge_time` defaults to `as_of`, not `now()`

**Status:** Accepted (implemented 2026-09-27)

**Context.** RED_TEAM_REPORT.md finding #1 (CRITICAL): every one of the ten point-in-time API routes
(`derivatives`, `divergence`, `institutional`, `liquidity`, `macro`, `market_structure`, `regime`, `retail`,
`similarity`, `whales`) carried its own copy-pasted local `_times()` helper that resolved `as_of` and
`knowledge_time` **independently** — each defaulted to `utc_now()` on its own when omitted. A caller who
supplied only `as_of` (the single most natural way to ask "what did this look like as of date X") silently
got `knowledge_time = now()`, which turns the `ingested_at <= knowledge_time` revision/leakage gate (R3) into
a no-op: any revision stored between `as_of` and the real "now" would leak into a query that was supposed to
be pinned to the past.

**Decision — a single shared `cfi.api.params.resolve_query_times(as_of, knowledge_time)` replaces all ten
copies.** The corrected rule: if `as_of` is supplied and `knowledge_time` is not, `knowledge_time` now
defaults to `as_of` (only what was knowable *by that same date* is visible — the safe assumption for the most
common call shape). If both are omitted, both default to `now()` (no leakage risk in asking for the current
state). An explicitly supplied `knowledge_time` is always honored, including one earlier or later than
`as_of` (a caller may legitimately ask "what does today's fully-settled data say about that past date").

**Decision — both resolved values are capped at `now()` (`min(value, now())`), including an explicitly
supplied `as_of`.** This is a direct reading of R3 ("never use future information in historical
calculations"): a caller-supplied future timestamp must not be able to pull in data that, by definition,
cannot yet have been observed. This is slightly broader than finding #1's literal wording (which is about the
`knowledge_time`-defaults-independently bug specifically) but is the same principle applied consistently, and
is covered by its own dedicated unit test (`test_future_values_are_capped_at_now`).

**Consequences.** All ten route files: removed the local `_times()` function, imported
`resolve_query_times` instead, updated docstrings/`Query(...)` descriptions describing the old "both default
to now" behavior. No database or migration changes — this is a request-parameter resolution fix only. New
tests: `tests/unit/test_api_params.py` (7 tests directly against the shared helper: both omitted, `as_of`-only
[the core fix], explicit `knowledge_time` before/after `as_of`, `knowledge_time`-only, future-capping, naive-
datetime rejection) and a new integration leakage test in `tests/integration/test_market_structure_api.py`
(`test_history_omitting_knowledge_time_does_not_leak_a_later_revision`) that inserts two genuine observation
revisions and proves that omitting `knowledge_time` with only `as_of` given returns the earlier revision, not
the later one. One pre-existing integration test (`tests/integration/test_divergence_api.py`) needed its own
future-`as_of` fixture pinned via `monkeypatch.setattr("cfi.api.params.utc_now", ...)` so the new
future-capping behavior does not truncate its deliberately-future `as_of` down to whatever real calendar date
the suite happens to run on.

---

## ADR-0061 — Phase 18: Backtest execution-realism corrections — intrabar stop/gap fills, size-dependent
slippage, warmup-shortfall disclosure

**Status:** Accepted (implemented 2026-09-27)

**Context.** RED_TEAM_REPORT.md's quantitative review of the Phase 16 Backtesting Engine (ADR-0059) found
five related execution-realism gaps, all inside `cfi.backtest`: (#3, HIGH) stop-loss/take-profit fills used
no slippage at all and ignored the case where the day's `open` already gapped through the stop/take-profit
level — silently using an unrealistically favorable fill price; (#5, MEDIUM) the cost model applied the same
flat slippage regardless of trade size relative to the day's own trading volume, understating costs for large
trades; (#11, MEDIUM) the execution-lag convention (ADR-0059) was correct but under-documented as an
assumption; (#12, MEDIUM) the existing backtest test suite asserted trade counts and statuses but never a
single exact fill price, fee or P&L value, so a wrong constant could pass unnoticed; (#14, LOW) a strategy
whose warmup requirement (`WARMUP_DAYS`) exceeds the available lookback before `start` silently produced a
result with no signal computed for that gap, with no flag.

**Decision — `_intrabar_stop_fill()` (finding #3).** A new pure function checks the day's `open` against the
stop-loss/take-profit levels *first*: if the open itself already cleared the level (a gap-through), the fill
is the open, not the stop/take-profit price itself — the one exception to the execution-lag convention
(ADR-0059), since a stop is a risk control reacting to the realized bar, not a forward-looking signal
decision. Only if the open did not already clear the level does the function fall back to an intrabar
high/low pierce check. Stop-loss is checked before take-profit when a bar's range spans both (the
conservative assumption per ADR-0059's existing conventions).

**Decision — size-dependent slippage via a new `participation_impact_coefficient` (finding #5), added as a
versioned parameter, not a mutation of `cost_model_v1`.** `_participation_fraction()` computes a trade's
notional as a fraction of the day's own trading volume (`None` when volume is unknown, preserving the
existing flat-slippage behavior for that case). `CostParameterSet` gained
`participation_impact_coefficient: Decimal = Decimal("0")` (safe/neutral default, so `cost_model_v1` is
byte-for-byte unchanged and every historical result computed under it remains reproducible). A new
`cost_model_v2` (coefficient = 1) is registered alongside `cost_model_v1` in `PARAMETER_SETS`, and
`CURRENT_VERSION` moves to `cost_model_v2` — new runs get the corrected, convex-in-size slippage by default;
old runs keep re-deriving under the version they recorded (`RunVersions.cost_parameter_version`).

**Decision — the execution-lag and slippage-participation assumptions are now restated as explicit fields on
`Assumptions` (finding #11), not left to a docstring** — `sizing_price_gap_note` and
`slippage_participation_note`, following the same runtime-visible-disclosure convention as the score
`*_caveat`/`*_note` fields added in ADR-0064.

**Decision — exact-value tests (finding #12).** A new integration test constructs a custom always-on test
strategy and NULL-volume synthetic bars (eliminating participation-fraction complexity from the hand
computation) and asserts the exact `Decimal` entry/exit fill prices, fees, P&L and return percentage against
independently hand-derived formulas — not just status and counts. New unit tests
(`tests/unit/test_backtest_engine.py`) cover `_intrabar_stop_fill` (no-stop, pierce, gap-through, sl-before-tp
priority) and `_participation_fraction` in isolation, without a database.

**Decision — `_warmup_shortfall_warning()` (finding #14).** A pure function compares the strategy's
`WARMUP_DAYS` requirement against the bars actually available before `start`; if short, a descriptive string
is appended to the existing `warnings: list[str]` already returned by `run_backtest` — no new field, reusing
an existing, already-surfaced mechanism.

**Consequences.** No database migration (all changes are inside the existing `cfi.backtest` package and its
in-memory `CostParameterSet`/`Assumptions` dataclasses). `tests/unit/test_backtest_costs.py`: one existing
test updated (`CURRENT_VERSION` is now `cost_model_v2`) plus four new tests (v1 registered and byte-identical,
v1 slippage flat regardless of participation, v2 slippage convex in participation, v2 participation fraction
clamped to `[0, 1]`). `tests/unit/test_backtest_engine.py` is a new file (11 tests). One new integration test
in `tests/integration/test_backtest_engine.py`. Before/after: any backtest re-run under `cost_model_v1`
reproduces byte-identical results to before this phase; a new run under the new default `cost_model_v2` will
show larger slippage on trades sized close to or above the participation cap, and any run through a
previously-silent warmup gap now carries an explicit warning string.

---

## ADR-0062 — Phase 18: Regime-classifier hysteresis — a `previous_regime_id` parameter, no persisted state

**Status:** Accepted (implemented 2026-09-27)

**Context.** RED_TEAM_REPORT.md finding #4 (MEDIUM): the Phase 14 Regime Engine (ADR-0057) classifies each
day independently with a hard `min_confidence_assign` cutoff — a metric oscillating narrowly around a regime
boundary flips the classification back and forth day to day even when the underlying evidence has barely
moved, producing a noisy regime history that overstates how often the market's state actually changed.

**Decision — hysteresis is a pure function parameter, not new persisted state.** `classify()` gained an
optional `previous_regime_id: str | None = None` keyword parameter. When the challenger regime (today's
top-scoring regime) differs from `previous_regime_id`, is not `MIXED_UNCLEAR`, and its confidence beats the
previous regime's own confidence by less than `params.hysteresis_margin` — while the previous regime still
independently clears `min_confidence_assign` — `classify()` returns the **previous** regime's
`ClassificationResult` instead, marked `held_by_hysteresis=True` with an explanatory `reason`. No new
database table or column: `RegimeService.current()` supplies `previous_regime_id` by making one extra,
non-hysteresis classification call for `as_of - timedelta(days=1)` and reading its `regime_id` — a plain
lookback the service already had the machinery for, at the cost of exactly one extra call per request.

**Decision — the existing backward-walk closure (`classify_at`, used by `regime_duration` and
`historical_examples`) threads the anchor day's own regime_id through every historical `_classify_at()` call
in the walk**, extending hysteresis-damping across the whole lookback at zero extra API-call cost (these
calls already existed for the walk; only the threading is new).

**Decision — `hysteresis_margin` is a versioned parameter (`ParameterSet`), following the same
non-destructive-new-version pattern as ADR-0061's cost model.** `ParameterSet` gained
`hysteresis_margin: Decimal = Decimal("0")` (safe/neutral default — `regime_classifier_v1` is unchanged and
remains byte-for-byte reproducible, and is a no-op with `hysteresis_margin == 0` regardless of
`previous_regime_id`). A new `regime_classifier_v2` (`hysteresis_margin = Decimal("0.05")`) is registered
alongside v1, and `CURRENT_VERSION` moves to v2.

**Decision — scope: the regime engine only, not `cfi.market_structure.score_parameters`'s own band
thresholds.** Market Structure Score bands were not part of finding #4's evidence and are a disclosed,
deliberate scope boundary for this phase, not an oversight — a candidate follow-up if the same flip-flopping
is later observed there.

**Consequences.** No database migration (parameter is registered the same way every other versioned parameter
set in this platform is — a Python module constant, not a table row). `ClassificationResult` gained
`held_by_hysteresis: bool = False`. `RegimeService`'s response dict gained `"held_by_hysteresis"`; its
`catalog()` params dict gained `"hysteresis_margin"`. `tests/unit/test_regime_classifier.py`: 7 new tests
(challenger barely wins → held; challenger clears the margin → yields; `regime_classifier_v1`'s zero margin is
a no-op; no previous id → no hysteresis; a previous regime that no longer independently qualifies is never
held; the default `classify()` call — no `previous_regime_id` — is unaffected, proving no accidental behavior
change for any existing caller that does not opt in). `tests/integration/test_regime_api.py`: two assertions
added (`hysteresis_margin` present in the catalog; `held_by_hysteresis is False` on an empty-data response).
Before/after: any caller not passing `previous_regime_id` (i.e., every caller before this phase) sees
identical output; `RegimeService.current()` and the historical-walk endpoints now damp single-day boundary
flips under the new default `regime_classifier_v2`.

---

## ADR-0063 — Phase 18: Market Structure Score — a minimum-count floor for the altcoin relative-strength
component

**Status:** Accepted (implemented 2026-09-27)

**Context.** RED_TEAM_REPORT.md finding #6 (MEDIUM): `_altcoin_relative_strength_component()` (20% weight in
the Market Structure Score) previously went `"unavailable"` only when *zero* of the three tracked altcoins
(ETH/SOL/XRP) had a reading, and otherwise averaged whatever subset was available — including a single
reading standing in for the whole component. One altcoin's idiosyncratic move (a hack, a listing event, a
temporary de-peg-adjacent wobble) could then swing 20% of the overall score while being presented as a
three-asset "altcoin" read.

**Decision — `MIN_ALTCOIN_COUNT = 2`.** `_altcoin_relative_strength_component()` now returns `"unavailable"`
(with a reason string naming how many of the three were available and the minimum required) whenever fewer
than 2 of the 3 tracked altcoins have a reading, not just when none do. This is a judgment parameter chosen by
design (consistent with every other band/weight/threshold in this score), not fitted to data.

**Consequences.** No database migration (a pure in-module constant and an added conditional). Existing unit
tests in `tests/unit/test_market_structure_score.py` that implicitly assumed a single altcoin reading counted
as full weight needed their fixture default bumped from 1 to 2 available spreads (`full_score()`'s default),
with the two full-weight directional tests updated accordingly; the "uses only available readings" test was
rewritten for 2-of-3 (still above the new floor); a new dedicated test
(`test_altcoin_relative_strength_is_unavailable_below_min_altcoin_count`, 1-of-3 available) proves the new
floor triggers `"unavailable"` while the score as a whole still renormalizes to `"ok"` over the remaining
components. Before/after: a market state with only one of three altcoin readings available now renormalizes
the Market Structure Score over the remaining components instead of quietly presenting a single-asset
average as the 20%-weighted altcoin read.

---

## ADR-0064 — Phase 18: Runtime-visible disclosure notes — shared inputs, proxy measurement, single-venue
scope, and transfer-date balance snapshots

**Status:** Accepted (implemented 2026-09-27)

**Context.** RED_TEAM_REPORT.md raised four related findings whose common thread is that a real, disclosed
scope limitation existed only in a docstring or ADR prose, never in the API response itself — the same gap
the pre-existing `measurement_class="proxy"` convention in `cfi.retail.metrics` was designed to close, just
not yet applied everywhere it should have been:

- **#7 (MEDIUM):** the Retail Speculation Score's `funding_rate_bias` component (0.40 weight) and the
  Derivatives Health Score's own funding component are derived from the same underlying series — a user
  reading both scores as independent evidence could double-count one real signal as two.
- **#8 (MEDIUM):** the Liquidity Score measures stablecoin supply growth, not market liquidity or peg
  stability directly — a real, disclosed (ADR-0052) proxy relationship, but invisible in the API response.
- **#9 (MEDIUM):** the Derivatives Health Score's liquidation-stress component is sourced from a single venue
  (OKX), understating true liquidation risk during venue-specific stress and not disclosed at read time.
- **#13 (LOW):** large-transfer size classification used the *latest* whale balance snapshot regardless of
  when the transfer actually happened, so an address that only grew large after a historical transfer would
  retroactively be classified using a balance it did not hold at the time (and the reverse for an address
  that has since drawn down) — a point-in-time (R3) violation distinct from #1's `knowledge_time` gate.

**Decision — for #7, #8, #9: an always-present string field on the relevant `ScoreResult`,** populated
regardless of `status` (so the caveat is visible even on an `"insufficient_data"` response), mirroring
`cfi.retail.metrics`'s existing `measurement_class="proxy"` pattern:
`cfi.retail.score.ScoreResult.shared_input_note` (Speculation only — Activity carries none, since the overlap
is specific to Speculation's funding component), `cfi.derivatives.score.ScoreResult.shared_input_note` (the
reciprocal note, correctly scoped to the same 25%/40% weight relationship), `cfi.liquidity.score.ScoreResult`
gained both `measurement_class = "proxy"` and `proxy_caveat`, and the derivatives liquidation component's
`context` field (already existed, used for other component-level notes) now always includes a single-venue
caveat string. Each note/caveat is propagated into the corresponding `service.py`'s dict-building method so it
reaches the API response.

**Decision — for #13: a `_balances_as_of(snapshots, at)` pure function replaces the single
`latest_balances = snapshots[-1].balances` computed once before the transfer loop.** Each transfer row is now
classified using the balance snapshot in effect *at that transfer's own `event_time`* — the latest snapshot
at-or-before it, never a later one. A transfer predating every stored snapshot gets no balance (`{}`) rather
than borrowing a later one, which would be a different, worse form of look-ahead.

**Consequences.** No database migration for any of the four (all are additive dataclass fields or a
same-shape helper function change; no new columns or tables). New/updated unit tests:
`tests/unit/test_retail_score.py` (shared-input note present on Speculation, absent on Activity),
`tests/unit/test_liquidity_score.py` (proxy caveat present and identical across `ok`/`insufficient_data`),
`tests/unit/test_derivative_metrics.py` (single-venue caveat text present in the liquidation component's
context), `tests/unit/test_macro_score.py` (the pre-existing `vintage_risk_note` for finding #2, which reuses
ADR-0054's already-accepted FRED-vintage limitation rather than needing a new ADR), and a new
`tests/unit/test_whale_service.py` (6 tests directly against `_balances_as_of`, including the report's own
synthetic scenario: an address small at T1, large by T2, classified on its T1 balance for a T1 query and its
T2 balance for a T2 query). One pre-existing integration test
(`tests/integration/test_whale_api.py::test_transfers_are_listed_with_direction_and_classification`) asserted
a transfer's recipient evidence text using the *latest* snapshot's balance (10,100 BTC) — this was exactly
the bug finding #13 describes, and the assertion was corrected to the balance in effect at the transfer's own
time (10,000 BTC, the 2026-09-03 snapshot) once the fix was applied. Before/after: every affected score's API
response now always carries its disclosure field; whale transfer classifications for historical transfers
that predate a balance change no longer silently reflect today's balance.

---

## ADR-0065 — Phase 18: Findings #10 and #15 — reviewed, correction deferred, no code change this phase

**Status:** Accepted (deferred; implemented 2026-09-27 as a documentation-only decision)

**Context.** RED_TEAM_REPORT.md's own priority ordering and per-finding "Recommended correction" text treat
two of its fifteen findings as out of scope for an immediate code fix, and this phase's corrections respect
that guidance rather than silently expanding scope (R13: "do not implement features that have not been
requested").

**Finding #10 (LOW) — Similarity candidate sampling is locked to one weekday per query.**
`cfi.similarity.search.candidate_dates()` samples backward from `as_of` in fixed `step_days=7` increments, so
every candidate in a single query falls on the same day-of-week as `as_of` — a short, sharp historical episode
that does not land on that weekday is structurally invisible to a given query, while a similar episode that
happens to align is captured. The report's own recommended correction (a calendar-anchored or
multi-phase/rotating sampling grid, merging and de-duplicating results) is a genuine design change to
`cfi.similarity.search`'s sampling strategy — not a parameter tweak — and was not part of this phase's
"implement the approved corrections" instruction as interpreted (the 13 findings with a direct, scoped
correction). Deferred to a future Similarity Engine follow-up phase; tracked in TODO.md. No test was added
this phase (the report's own required test — a synthetic short-spike event on an off-grid weekday — is
specified for whenever that follow-up is scheduled).

**Finding #15 (LOW) — Fixed 4-asset universe with no first-class "delisted/discontinued" state.**
`ASSET_SYMBOLS` and `VENUES` are static tuples with no state distinguishing "delisted" from "temporarily
stale." The report itself states this is low-severity **today** (no current instance of survivorship bias is
occurring with the current small, still-live asset/venue set) and explicitly recommends "no immediate code
change needed given the current single-benchmark, 4-asset scope" — deferring the fix until a multi-asset
universe is actually added (already tracked as future work in TODO.md), at which point it recommends an
explicit `valid_from`/`valid_to` membership record per asset-venue pair, mirroring the existing
`ref.entity_label` pattern. No code change and no test this phase, per the report's own explicit guidance.

**Consequences.** Neither finding required a database migration, a code change, or a new test this phase.
Both remain open, tracked items: #10 in TODO.md as a candidate for a future Similarity Engine follow-up
phase; #15 already covered by TODO.md's existing multi-asset-universe future-work entry, cross-referenced
here so a future reader of RED_TEAM_REPORT.md does not mistake "no code change" for "not reviewed."
