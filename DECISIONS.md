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
| 0014 | Technology stack | **Proposed** | 2026-09-23 |
| 0015 | Service boundaries and monorepo | **Proposed** | 2026-09-23 |
| 0016 | PostgreSQL + TimescaleDB as the single primary store | **Proposed** | 2026-09-23 |
| 0017 | Hybrid storage model with a series registry | **Proposed** | 2026-09-23 |
| 0018 | Bitemporal knowledge model | **Proposed** | 2026-09-23 |
| 0019 | Raw payload archive in object storage | **Proposed** | 2026-09-23 |
| 0020 | Time-series strategy | **Proposed** | 2026-09-23 |
| 0021 | Ingestion pipeline and dataset registry | **Proposed** | 2026-09-23 |
| 0022 | Provider adapters, health, fallback, and rate limits | **Proposed** | 2026-09-23 |
| 0023 | Background processing with Celery | **Proposed** | 2026-09-23 |
| 0024 | Redis role and licence | **Proposed** | 2026-09-23 |
| 0025 | API design | **Proposed** | 2026-09-23 |
| 0026 | Authentication | **Proposed** | 2026-09-23 |
| 0027 | Authorization and database-role enforcement | **Proposed** | 2026-09-23 |
| 0028 | Security baseline | **Proposed** | 2026-09-23 |
| 0029 | Observability and logging | **Proposed** | 2026-09-23 |
| 0030 | Error handling taxonomy | **Proposed** | 2026-09-23 |
| 0031 | Data quality framework | **Proposed** | 2026-09-23 |
| 0032 | Historical data and point-in-time reliability | **Proposed** | 2026-09-23 |
| 0033 | Backtesting architecture | **Proposed** | 2026-09-23 |
| 0034 | AI architecture and grounding | **Proposed** | 2026-09-23 |
| 0035 | Alert architecture | **Proposed** | 2026-09-23 |
| 0036 | Decision journal and paper trading | **Proposed** | 2026-09-23 |
| 0037 | Scalability path and real-time processing | **Proposed** | 2026-09-23 |
| 0038 | Cost control | **Proposed** | 2026-09-23 |
| 0039 | Time zones and calendars | **Proposed** | 2026-09-23 |
| 0040 | Bias and leakage controls | **Proposed** | 2026-09-23 |
| 0041 | Reproducibility and versioning | **Proposed** | 2026-09-23 |
| 0042 | Disaster recovery | **Proposed** | 2026-09-23 |
| 0043 | Charting libraries | **Proposed** | 2026-09-23 |
| 0044 | Numeric precision for high-volume data | **Proposed** | 2026-09-23 |

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
**Status:** Proposed (stack proposed by the user; supersedes ADR-0008)

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
**Status:** Proposed

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
**Status:** Proposed

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
**Status:** Proposed

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
**Status:** Proposed (implements accepted ADR-0003)

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
**Status:** Proposed

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
**Status:** Proposed (Celery named by the user; alternatives listed for approval)

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
**Status:** Proposed

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
**Status:** Proposed

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
**Status:** Proposed

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
**Status:** Proposed

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
**Status:** Proposed (models and budgets need approval)

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
**Status:** Proposed (budgets need approval)

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
**Status:** Proposed

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
**Status:** Proposed (amends ADR-0010 pending benchmark)

**Decision.** Default remains exact `NUMERIC` for L1 values. In the infrastructure phase, benchmark storage size and query speed for high-volume
families (minute bars, order-book depth, trades) using `NUMERIC` vs. `double precision`. If the difference is material, those families may use
`double precision` while the exact source string stays in L0; money ledgers (paper trading, fees, PnL) always stay `NUMERIC`.

**Reason.** Exactness matters for accounting; statistical analysis of market data tolerates float64, and volume may make `NUMERIC` expensive.

**Alternatives considered.** `NUMERIC` everywhere without measuring; `double precision` everywhere (inexact ledgers); scaled integers (fast, awkward).

**Trade-offs.** Two numeric conventions if the benchmark justifies it.

**Future implications.** Decision recorded with benchmark numbers before large-scale ingestion starts.
