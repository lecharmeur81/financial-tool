# PROGRESS.md

Single source of truth for what has been done. Updated at the end of every task.

**Current phase:** 7 — Whale intelligence → built, awaiting the user's Windows run and commit
**Next phase:** 8 — to be defined by the user (do not start automatically)

---

## Phase overview

| Phase | Name | Status |
|---|---|---|
| 0 | Project foundation | ✅ Complete |
| 1 | Master engineering rules | ✅ Complete |
| 2 | Architecture | ✅ Complete (checklist Part A approved 2026-09-23) |
| 3 | Foundation (infrastructure) | ✅ Complete — verified on Windows |
| 4 | Data ingestion engine | ✅ Complete — verified on Windows (`69b5442`) |
| 5 | Market data | ✅ Complete — verified on Windows with real data (`6ad4eaf`) |
| 6 | Institutional capital | ✅ Complete — verified on Windows (`ef852b6`); real data pending a SoSoValue API key |
| 7 | Whale intelligence | 🟡 Built and tested in Claude's workspace; Windows run and commit pending |
| — | Derivatives | ⏳ Not started |
| — | Liquidity | ⏳ Not started |
| — | Retail | ⏳ Not started |
| — | Macro | ⏳ Not started |
| — | Market structure | ⏳ Not started |
| — | Divergence engine | ⏳ Not started |
| — | Regime engine | ⏳ Not started |
| — | Historical similarity | ⏳ Not started |
| — | Backtesting | ⏳ Not started |
| — | Quant red-team | ⏳ Not started |
| — | Anomaly engine | ⏳ Not started |
| — | Capital rotation | ⏳ Not started |
| — | Claude AI Analyst | ⏳ Not started |
| — | Daily intelligence | ⏳ Not started |
| — | Alerts | ⏳ Not started |
| — | Paper trading | ⏳ Not started |
| — | Decision journal | ⏳ Not started |
| — | Executive dashboard | ⏳ Not started |
| — | Security + AI + stress testing | ⏳ Not started |
| — | Production | ⏳ Not started |
| — | Real-time intelligence | ⏳ Not started |

Phases 0–7 follow the user's guide. The remaining topics are provisional and get their numbers when the user issues them.

---

## Log

### 2026-09-23 — Phase 0: Project foundation

**What changed**
- Inspected `E:\FINANCIAL TOOL`: folder was empty (no existing code, no Git repository).
- Created foundation documentation: `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `DATA_DICTIONARY.md`, `DECISIONS.md`, `PROGRESS.md`, `TODO.md`.
- Added `.gitignore` (secrets, Python, data, IDE files) and `.gitattributes` (LF normalisation).
- Git: initialised by the user on the Windows machine (branch `main`). Claude's file bridge cannot
  write into `.git` or run Git on that machine, so the user runs Git commands; Claude supplies them.

**Tests run:** None applicable — no code exists yet. Files were read back from `E:\FINANCIAL TOOL` and compared byte-for-byte with the originals.

**Known limitations**
- Technology stack (ADR-0008) and batch-first approach (ADR-0009) are *proposed*, not accepted.
- No data provider has been selected or verified. The dataset catalogue in `DATA_DICTIONARY.md` is a plan, not a capability statement.
- No shell on the Windows machine was available in this session, so Git could not be run there.

**Git commit:** `d59cb20` — `[A] project foundation documentation` (created by the user, 2026-09-23).
(Its message uses the old letter label `[A]`, which is Phase 0.)

### 2026-09-23 — Phase 0: follow-up

**What changed**
- Phases renumbered from letters to numbers at the user's request: A→0, B→1 … Z→25, Production→26, Real-time intelligence→27 (ADR-0012). All docs updated.
- Commit prefix changed to `[P<number>]`; branch pattern to `phase-<number>/<name>`.
- Recorded commit `d59cb20` and the Git-on-user-machine workflow (`CLAUDE.md` §7).

**Tests run:** None applicable (documentation only). Files read back from `E:\FINANCIAL TOOL` and compared byte-for-byte; no leftover letter-based phase references found by search.

**Git commit:** `7ca0345` — `[P0] renumber phases and record git workflow` (created by the user).

### 2026-09-23 — Phase 1: Master engineering rules

**What changed**
- `CLAUDE.md` restructured into Part A (context), Part B (master engineering rules R1–R13, as issued by the user), Part C (workflow).
  Earlier hard rules merged into R1–R13 without loss; phase-end report format added (C2).
- `ARCHITECTURE.md`: Hypothesis category (§2), adapter failure-mode requirements and idempotent writes (§5),
  `conflicting` quality status (§6), nine-section AI output contract with "Insufficient data." rule (§8),
  backtest cost/constraint list and survivorship handling (§10).
- `DATA_DICTIONARY.md`: new universal fields `metric`, `asset`, `original_source`, `confidence` (§2);
  `conflicting` status (§3); AI output sections (§9).
- `DECISIONS.md`: ADR-0013. `TODO.md`: section reference fixed.

**Tests run:** None applicable (documentation only, no code). Checks: every rule in the user's brief located in `CLAUDE.md`
by search; cross-references between files checked; files read back from `E:\FINANCIAL TOOL` and compared byte-for-byte.

**Known limitations:** Architecture design items (data model, point-in-time contract, adapter interface, metric registry,
snapshot/validator contract, quality checks, ADR-0008/0009) are not started and are unscheduled. Q1–Q10 in `TODO.md` remain open.

**Git commit:** `e4cca71` — `[P1] add master engineering rules` (created by the user).

**Phase 1 closed** (2026-09-23): the user confirmed Phase 1 consists only of the master engineering rules.
Phase 1 renamed from "Architecture" to "Master engineering rules" in `CLAUDE.md` and here; architecture design work moved to
"Unscheduled" in `TODO.md`. This closing update was to be committed by the user as `[P1] close phase 1` (hash not reported; verify with `git log`).

### 2026-09-23 — Phase 2: Architecture (design only, no code)

**What changed**
- `ARCHITECTURE.md` rewritten as v1.0: system containers, layer/DB-schema/role mapping, technology stack, and all 30 review areas
  (§5.1–5.30), entity classification, user layer, repository layout, deployment topology, component-to-phase map, risk register.
- `DECISIONS.md`: 31 new ADRs (0014–0044), each with decision, reason, alternatives, trade-offs, future implications; ADR-0008 superseded
  by ADR-0014; ADR-0010 cross-referenced to ADR-0044; ADR-0012 amended for the phase plan.
- `DATA_DICTIONARY.md` v0.2: series-level vs. row-level fields, new enums (`evidence_category`, `pit_reliability`, `job_status`,
  `circuit_state`, `app_role`), full logical schema for 9 DB schemas (§4), AI snapshot format (§9a).
- `TODO.md`: Architecture Approval Checklist (Parts A–D) replaces the open-questions list; infrastructure tasks listed as unscheduled.
- `CLAUDE.md` §C3: Phase 2 = Architecture; later phase numbers provisional.

**Verification:** Licence facts checked against primary sources on 2026-09-23 (Timescale License terms, Redis licences,
Lightweight Charts licence/attribution). Cross-references (ADR numbers, section numbers) checked by script.
No software tests apply (no code).

**Known issues:** All Phase 2 ADRs are *Proposed* until the user approves the checklist. Storage volumes, retention, and numeric-type
performance are estimates to be benchmarked. Provider capabilities remain unverified.

**Git commit:** `ca0bd80` — `[P2] architecture review` (created by the user). The Phase 1 closing edits were included in this
commit; no separate `[P1] close phase 1` commit exists.

### 2026-09-23 — Phase 3: Foundation

**What changed**
- **Development environment:** `compose.yaml` (db: TimescaleDB 2.30.1/PG17, redis 8.8, one-shot `migrate`, `api`, `frontend`; health
  checks; ports bound to 127.0.0.1; named volumes), `.env.example`, Dockerfiles in `backend/` and `frontend/`.
- **Backend** (`backend/`, Python 3.12, uv): FastAPI app factory; `CFI_` configuration with secret URLs; structured JSON logging
  with request IDs and secret redaction; error taxonomy (ADR-0030) with RFC 9457 problem-details responses; `/health/live`,
  `/health/ready` (DB + TimescaleDB version + migration revision + Redis), `/api/v1/meta`; async SQLAlchemy/psycopg engine; Redis
  client; canonical domain enums and `CanonicalObservation` (R3 invariants); provider adapter interface, registry, and a stub that
  refuses every call (no real providers).
- **Migrations:** Alembic, revision `0001` — TimescaleDB extension and the nine layer schemas; `RESTRICT` downgrade.
- **Frontend** (`frontend/`, Next.js 16.3.6, React 19.2, TypeScript strict): app shell with navigation; placeholders for
  Dashboard, Market, Flows, Derivatives, Liquidity, Analytics, Alerts, Settings (no numbers shown); Settings shows live API/DB/Redis
  status; `/healthz`; baseline security headers; standalone output for Docker.
- **Quality tooling:** ruff (lint + format), mypy strict (src, tests, migrations), pytest (warnings are errors); ESLint, Prettier,
  `next typegen` + `tsc`, Vitest + Testing Library.
- **CI:** `.github/workflows/ci.yml` — backend (lint, format, types, migrate, all tests with TimescaleDB + Redis service containers),
  frontend (lint, format, types, tests, build), compose (validate + build images).
- Docs: README (getting started), CLAUDE.md §C3/§C5, ARCHITECTURE §8–9, DECISIONS ADR-0045, DATA_DICTIONARY §4 note, TODO.

**Tests run (in Claude's cloud workspace)**
| Check | Result |
|---|---|
| Backend `ruff check` / `ruff format --check` | pass / pass (41 files) |
| Backend `mypy --strict` (40 files incl. tests, migrations) | pass |
| Backend `pytest` — unit + API + integration | **56 passed** (51 unit/API, 5 integration) |
| Alembic `upgrade head` → `downgrade base` → `upgrade head` | pass |
| Downgrade safety: schema holding a table → downgrade refused, row kept | pass |
| Live API server: live/ready/meta/404 problem JSON; readiness 503 when Redis stopped, 200 after restart; no password in logs | pass |
| Frontend `pnpm lint` / `format:check` / `typecheck` | pass / pass / pass |
| Frontend `pnpm test` (Vitest) | **24 passed** (5 files) |
| Frontend `pnpm build` + standalone server: all 8 pages 200, unknown page 404, `/healthz` 200, Settings shows live readiness | pass |
| Dockerfile steps replayed in clean folders (backend dev + runtime targets; frontend deps + build) | pass |
| `docker compose config` (with `.env.example`); refuses to run without `.env` | pass |
| `actionlint` on the CI workflow | pass |

**Known limitations**
- **Docker Compose was not started here:** Docker Hub is blocked from Claude's workspace by policy, so images could not be pulled or
  built. Every Dockerfile step was replayed outside Docker instead. The first real `docker compose up --build` is on your machine.
- ~~Integration tests ran against PostgreSQL 16 + Redis 7.0 instead of the Compose versions~~ — resolved in the follow-up below
  (re-run on PostgreSQL 17.11 + TimescaleDB 2.30.1 + Redis 8.8.3).
- CI workflow not executed (no Git remote); validated with actionlint only. **`.github/workflows/ci.yml` could not be written
  to the drive** (the remote file bridge protects `.github/`); it was sent to the user to place manually.
- Not in Phase 3 scope: Celery workers, authentication, database roles, tables beyond schemas, real providers.
- ~~The Phase 2 approval checklist is still open~~ — Part A approved and B1–B3 answered in the follow-up below.

**Git commit:** pending — user to commit as `[P3] application foundation`.

### 2026-09-23 — Phase 3 follow-up: known issues

**What changed**
- **Versions now match Compose exactly.** Built PostgreSQL 17.11, TimescaleDB 2.30.1 (for PG17) and Redis 8.8.3 from official source and
  re-ran everything: migrations up → down → up; downgrade refused when a schema holds data (row kept); **56/56 backend tests** (incl.
  5 integration); ruff, format, mypy strict; live API readiness reporting `timescaledb_version 2.30.1`, `redis_version 8.8.3`; frontend
  Settings page showing both live. No password in logs.
- **Approvals recorded:** checklist Part A (A1–A12) approved → ADR-0014, 0015, 0016, 0017, 0018, 0019, 0023, 0024, 0026, 0027, 0032,
  0034, 0043 now **Accepted**. B1 = BTC, ETH + major altcoins (list to confirm); B2 = $0 data budget; B3 = $20/month Claude ceiling
  (recorded in ADR-0038). B4–B8 remain on their defaults.
- **CI file:** writing to `.github\` is refused by a fixed rule in the Claude app's file access (not Windows permissions; retried after the
  user changed folder permissions — still refused). The user's copy at the project root was verified byte-identical; the user moves it.

**Still open by design (not defects):** Celery workers, authentication, database roles and data tables are approved but belong to the
phases that need them (R13: do not build unrequested features). The Docker Compose run on Windows is still to be confirmed by the user.

**Git commit:** pending — user to commit (together with Phase 3) as `[P3] application foundation`.

### 2026-09-23 — Phase 3: first Docker Compose run on Windows (user's machine)

- `docker compose up --build`: all images pulled/built; `db` (PostgreSQL 17.11 + TimescaleDB), `redis` 8.8.3 healthy; `migrate` exited 0
  (revision 0001); `api` healthy; `frontend` ready on :3000.
- `docker compose exec api pytest`: **56 collected, all 56 passed** (incl. 5 integration against the real Compose services), then the
  run crashed while writing pytest's cache: `/app` was root-owned and the container runs as the unprivileged `cfi` user; with warnings
  treated as errors, the cache warning failed the run. Claude's earlier Docker simulation ran as root, which hid this.
- **Fix:** `backend/Dockerfile` dev target now gives `cfi` ownership of the `/app` directory only (source files stay root-owned,
  read-only). Reproduced the failure as an unprivileged user, then verified the fix: pytest exit 0, ruff and mypy caches work,
  source files still not writable by `cfi`.
- **Re-run after the fix (user's machine):** `docker compose exec api pytest` → **56 passed in 1.08s**, no errors. Settings page:
  "All systems ready" — database OK (timescaledb_version 2.30.1, schema_revision 0001, session_timezone UTC), Redis OK (8.8.3).
- `.github/workflows/ci.yml` placed by the user (2,592 bytes, identical to the original).
- **Phase 3 complete.** Git commit: `ec7ab27` — `[P3] application foundation` (99 files; created by the user).

### 2026-09-23 — Phase 4: Data ingestion engine

**What changed**
- **Provider abstraction** (`cfi/providers/base.py`): `ProviderAdapter` with `first_request` / `next_request` (pagination) / `parse`
  (response validation → `SchemaMismatchError`) / `normalise`; declared capabilities (auth, rate limit, timeout, page limit, original
  source).
- **HTTP client layer** (`cfi/providers/http.py`): authentication (API-key header or query parameter, bearer; secret from an environment
  variable, redacted from records), timeouts, retries with exponential backoff + jitter honouring `Retry-After`, token-bucket rate
  limiter, circuit breaker, one record per attempt.
- **Normalisation**: epoch/ISO/naive-local timestamps → UTC with declared units and time zones (DST-aware, `tzdata` added); unit
  conversion recorded in `transformations`; availability rules set `available_at` (unfinished bars rejected).
- **Ingestion engine** (`cfi/ingestion/`): raw payload archive (content-addressed files), pipeline with duplicate / revision / missing /
  gap / stale / conflict / rejection detection, quality findings, job runs, provider health.
- **Migration `0002`**: `ops.provider`, `ops.dataset`, `ops.dataset_provider`, `ops.job_run`, `ops.provider_request` (HT),
  `ops.quality_check_result` (HT), `raw.payload` (HT), `obs.series`, `obs.observation` (HT). Downgrade refuses if any table has data.
- **API**: `GET /api/v1/providers/health`, `GET /api/v1/ingestion/runs` (operational, no market values).
- **Mock providers** (tests only): two deliberately different formats + scriptable servers (timeout, 429, 5xx, malformed body).
- **Docker**: `/data/raw` archive directory owned by the app user; `rawarchive` volume and `CFI_RAW_ARCHIVE_DIR` in Compose.
- **Tests**: integration tests now run in a separate `<db>_test` database created by the test suite (never the development data).
- Docs: ARCHITECTURE §5.3/§5.4 (implemented behaviour table), DATA_DICTIONARY §4, DECISIONS ADR-0046, CLAUDE.md §C3, TODO.

**Tests run (Claude's workspace: PostgreSQL 17.11 + TimescaleDB 2.30.1, Redis 8.8.3, Python 3.12)**

| Check | Result |
|---|---|
| `uv run pytest` (unit + integration) | 106 passed (run twice, same result) |
| `uv run pytest` without database/Redis | 85 passed, 21 skipped (integration tests skip) |
| `uv run ruff format --check .` / `uv run ruff check .` | clean |
| `uv run mypy` (strict, 58 files) | no issues |
| `docker compose config` with `.env.example` | valid |

Required test cases → where: successful ingestion, timeout, retry, rate limit, malformed response, duplicate record, missing value,
stale value, conflicting provider values → `tests/integration/test_ingestion.py` (end to end through the database) and
`tests/unit/test_http_client.py`, `test_detection.py`, `test_normalisation.py`.

**Known limitations**
- Nothing runs ingestion on a schedule yet (Celery workers deferred); the engine is invoked from code/tests only.
- Rate limiter and circuit breaker are in-process; a shared (Redis) version is needed once several workers run.
- No real provider adapters (by instruction); mock providers are test-only and never registered in the app.
- Docker images were not rebuilt in Claude's workspace (Docker Hub unreachable there); the Windows Docker check is pending.

**Windows check (user, 2026-09-23):** `docker compose up --build` — migration `0002` applied, all services healthy;
`docker compose exec api pytest` → 106 passed.

**Git commit:** `69b5442` — `[P4] data ingestion engine`.

### 2026-09-23 — Phase 5: Market data

**What changed**
- **Providers** (verified against official docs on 2026-09-23; no keys needed): Coinbase Exchange (USD candles 1m/5m/15m/1h/1d,
  last trade — response format also confirmed with a real captured response), Kraken (USD, all six timeframes, 720 most
  recent bars only), Binance market-data endpoint, OKX and Bybit (USDT, all six timeframes), CoinGecko (market cap,
  latest and daily). OKX, Bybit and Kraken added at the user's request mid-phase.
- **Storage:** migration `0003` — `obs.market_bar` hypertable (OHLCV + full provenance), `ops.backfill_state`,
  `ops.dataset.kind`, `ops.job_run.subject/skipped/suspect`. Exact decimals kept (ADR-0044 benchmark: +5 % storage).
- **Engine:** record families (scalar/bar) through the same pipeline; unfinished bars skipped and counted; OHLC consistency
  failures kept as `suspect`; provider-specific gap notes; backfill job type; only in-window data counts as coverage.
- **HTTP client:** 418 treated as rate limiting; long `Retry-After` never retried early (circuit held open); optional API
  keys; fixed a token-bucket rounding loop found by the new tests.
- **Workers:** Celery `worker` (latest data), `worker-backfill` (history) and `beat` services; catch-up after downtime;
  resumable backfill with checkpoints.
- **API:** `/api/v1/market/catalog`, `/market/bars` (point-in-time `as_of`, gaps, freshness, source, derivation,
  warnings), `/market/overview`; `/ingestion/runs` now shows subject, job type, skipped and suspect counts.
- **Market page:** asset / timeframe / venue switching, candlestick chart with separate volume pane (TradingView
  Lightweight Charts 5.2.1, attribution kept), last trade, market cap (CoinGecko attribution), latest 1m close per venue,
  freshness badges, data status (source, units, last update, completeness, last ingestion, history) and missing-data
  warnings; refreshes every 30 s. No signals or recommendations.
- **Docs:** ADR-0047 (and ADR-0044 accepted, ADR-0023 implemented), ARCHITECTURE §5.1/5.3/5.5/5.6/§10/§11,
  DATA_DICTIONARY §4/§5/§5a, CLAUDE.md §C3 (Phase 5 = Market data), README, TODO, THIRD_PARTY_NOTICES.md, `.env.example`.

**Tests run (Claude's workspace: PostgreSQL 17.11 + TimescaleDB 2.30.1, Redis 8.8.3, Python 3.12, Node 22)**

| Check | Result |
|---|---|
| Backend `uv run pytest` (unit + integration + API) | 164 passed (run twice) |
| Backend without database/Redis | 113 passed, 51 skipped |
| `ruff format --check` / `ruff check` / `mypy` (strict, 85 files) | clean |
| Frontend `pnpm test` / `lint` / `format:check` / `typecheck` / `build` | 34 passed / clean / clean / clean / built |
| `docker compose config` | valid |
| Running stack (API + built frontend + Playwright) | charts render on 6 pages (5 venues, native and derived 4h), timeframe switching works, TradingView link present, no browser console errors — **with synthetic test data** (this workspace cannot reach the providers) |
| Celery worker + beat against a test database | tasks scheduled and executed; with no network, every run is recorded as `failed` (connection error), circuit breaker engaged — failures visible, nothing invented |

Required behaviour covered by tests: historical ingestion (backfill, pagination, listing/history start, failed chunk
retry), latest data (catch-up), normalised storage with provenance, market API (exact decimals, gaps, freshness,
point-in-time leakage test, derived 4h), OKX/Bybit/Kraken formats and error payloads.

**Known limitations**
- Real provider data has **not** been seen by the system yet: this workspace has no access to the providers. The first
  real run is on the user's machine. Binance, OKX, Bybit and Kraken are blocked by Philippine ISPs and may fail there.
- Decisions pending (TODO.md): CoinGecko storage terms; exchange terms review; history depth / retention; blocked providers.
- Kraken offers only its 720 most recent bars per timeframe; Coinbase 4h is derived from 1h.
- Rate limiters and circuit breakers are per worker process (limits set so both processes together stay under each
  provider's published limit).
- Times on the Market page are UTC (Asia/Manila display not built). Quality findings grow quickly (retention to add).

**Windows check (user, 2026-09-23):** `docker compose exec api pytest` → 164 passed. Real data on the Market page: Coinbase
BTC-USD 1h candles (about 84–86k USD), 300 of 300 expected bars, 2 years of hourly history loaded; last trade and CoinGecko
market cap fresh. Provider health: Coinbase, Kraken, Binance, OKX, CoinGecko succeeding; **Bybit answered HTTP 403 on every
request** (location blocked), so it was removed from `CFI_MARKET_PROVIDERS` in the user's `.env` (adapter kept; can be re-enabled).

**Git commit:** `6ad4eaf` — `[P5] market data layer`.

---

### 2026-09-24 — Phase 6: Institutional capital

**What changed**
- **Sources** (verified against official docs on 2026-09-24, $0): **SoSoValue OpenAPI** (free key, 20 req/min,
  100k/month) — US spot ETF daily totals and per-fund history for **BTC, ETH, SOL and XRP** (SOL and XRP confirmed at
  the user's request mid-phase), and listed-company bitcoin purchase history; **CoinGecko** public treasury — BTC, ETH,
  SOL holdings of listed companies. Not available from a verified free source (shown in the UI): CoinShares weekly fund
  flows, 13F holdings, ETH/SOL/XRP treasury purchases, ETF history older than one month. No wallet is ever labelled
  institutional.
- **Storage:** migration `0004` — `obs.institutional_flow` hypertable (flows/holdings in USD and coins, cumulative flow,
  value traded, premium/discount, unit cost, entity type, evidence class; `inferred` labels and silent missing values
  rejected by database checks); `ops.dataset.kind` now also `flow`.
- **Engine:** third record family (`CanonicalFlow`); adapter hook `parse_page` (listing → per-fund/per-company pages in
  one job, every page archived); availability rule `next_us_trading_day` + `known_when_received`; US trading calendar
  (NYSE holidays verified for 2026–2028); `check_freshness` off for sporadic events. T+1 settlement: the current day is
  skipped as not final, older gaps are explicit missing rows; changed values become revisions.
- **Aggregation:** daily / weekly (Mon–Sun) / monthly at read time with `as_of` and `knowledge_time`; each trading day
  counted as present, missing, not loaded or not due; per-fund reconciliation with the total.
- **Institutional Flow Score v1** (calculated metric): four published components (5-day and 20-day ETF flow as % of net
  assets, 10-day inflow/outflow day balance, 30-day listed-company BTC acquisitions), fixed weights and reference
  scales, capped sub-scores, missing components excluded with renormalised weights, "Insufficient data" below half the
  weight. Every component shows value, unit, calculation with the numbers, source, timestamp, freshness, data quality.
- **Workers:** Celery task `institutional.ingest` (SoSoValue on the `backfill` queue, CoinGecko on `ingest`), skipped
  when the provider is disabled or has no key, queued once when beat starts.
- **API:** `/api/v1/institutional/catalog`, `/overview`, `/etf-flows`, `/etf-funds`, `/treasury`, `/score`.
- **Flows page:** tiles for BTC, ETH, SOL, XRP; score card with every component; net-flow chart and table (daily /
  weekly / monthly); per-fund breakdown; treasuries (holdings, purchases, largest holders); coverage and limits.
- **Test fix (latent since Phase 5):** the worker-runtime test assumed the default provider lists, so it would have
  failed once a provider is removed in `.env` (as done for Bybit). It now sets its provider lists explicitly; the suite
  passes with reduced lists too.
- **Historical fixtures:** `backend/tests/fixtures/institutional/` — synthetic values in the documented response shapes,
  with hand-derived expected results (README there).
- **Docs:** ADR-0048, DATA_DICTIONARY §4/§5/§5b/§7, ARCHITECTURE §5.1/5.3/5.5/§11, CLAUDE.md §C3 (6 = Institutional
  capital), README, TODO, THIRD_PARTY_NOTICES.md, `.env.example`, `compose.yaml`.

**Tests run (Claude's workspace: PostgreSQL 17 + TimescaleDB 2.30.1, Redis 8.8, Python 3.12, Node 22)**

| Check | Result |
|---|---|
| Backend `uv run pytest` (unit + integration + API) | 228 passed |
| Backend without database/Redis | 157 passed, 71 skipped |
| `ruff format --check` / `ruff check` / `mypy` (strict) | clean |
| Frontend `pnpm test` / `lint` / `format:check` / `typecheck` / `build` | 46 passed / clean / clean / clean / built |
| Running stack (API + built frontend + Playwright) | Flows page renders for BTC, SOL (weekly) and XRP (monthly); no browser console errors — **with the synthetic fixtures, dates shifted to the current week, in a scratch database** (this workspace cannot reach SoSoValue) |

Covered by tests: calendar vs published NYSE holidays; documented example payloads; T+1 skip vs explicit missing;
listing chains and purchase pagination (no loop when a parameter is ignored); sale sign; suspect unit cost kept;
idempotent re-runs and revisions; weekly/monthly totals; missing vs not loaded vs not due; score values for BTC 69.5,
ETH 71.9, XRP 71.9, SOL 85.0 (20-day component excluded) and 58.5 with a missing day; point-in-time leakage (rows
published after `as_of` or stored after `knowledge_time` never change the score); invalid key → recorded auth failure;
downgrade refuses to delete institutional data.

**Known limitations**
- No real SoSoValue data seen yet: this workspace cannot reach it and a personal key is needed.
- ETF history from the API is one month; 20-day and history-based views fill in as the system runs.
- SoSoValue is the only ETF source (no cross-provider check); its API terms are not published.
- Score parameters are judgments awaiting the user's review; availability times are estimates.

**Windows check (user, 2026-09-24):** `docker compose up -d --build` → all services started, api healthy;
`docker compose exec api pytest` → 228 passed. Real institutional data not yet checked (SoSoValue key not yet set).

**Git commit:** `ef852b6` — `[P6] institutional capital` (76 files).

---

### 2026-09-24 — Phase 6 follow-up: first real SoSoValue run

**What the user's run showed:** the key works. US spot ETF totals for BTC, ETH, SOL and XRP were ingested and the Flows
page showed real flows, scores and freshness. After 10 requests sent within seconds, SoSoValue answered **HTTP 429
"wait 58 s"**. The client did not retry (its longest wait was 30 s), the circuit breaker held SoSoValue closed for
that time, and the per-fund job (5 BTC funds loaded) and the treasury purchase sweep failed with visible errors.
Nothing was invented. Because only 5 funds were loaded, the "sum of funds" cross-check showed differences.

**Fix**
- Rate limits can declare a burst size (`RateLimitSpec.burst`). SoSoValue now sends one request every 7.5 s
  (8 per minute, no bursts). The documentation says 20 per minute, but the real key refused a burst of 10.
- Providers can declare the longest `Retry-After` wait to honour (`max_retry_wait_seconds`; SoSoValue: 90 s). A
  58-second wait is now waited out and retried; longer waits still fail and hold the circuit open.
- The institutional task time limit is raised to 60 min: the purchase sweep takes about 1 request per company at
  7.5 s each.
- ETF date ranges end on the **New York** date, so a trading day that has not started is not listed as "not reported
  yet".

**Tests:** 233 passed (5 new: pacing, 58 s wait honoured, >90 s wait fails and holds the circuit, burst default for
other providers, New York date range). Lint and types clean.

**Git commit:** `a1ed9f7` — `[P6] SoSoValue pacing fix` (verified on Windows: 233 passed; all 12 BTC funds loaded and
reconcile with the totals except 2026-08-24, the edge of the one-month window; BTC flows match Farside Investors for
14–22 Sep to within 0.1 M).

---

### 2026-09-24 — Phase 6 follow-up: treasury purchase check corrected

**What the user's run showed:** the purchase sweep succeeded (521 disclosed purchases), but 333 were flagged `suspect`
by the unit-cost check. The rows showed that SoSoValue's `avg_btc_cost` is not a USD price per BTC as documented
(MSTR 0.09 while cost ÷ BTC ≈ 79,700 USD; other companies 2.7 … 657). One row is genuinely inconsistent: 2 BTC for
111.84 M (company 3825), probably a cost in another currency.

**Fix:** `avg_btc_cost` is no longer stored (raw value kept in the archive; transformation recorded). New BTC
implied-price plausibility check (1,000 to 1,000,000 USD per BTC). The purchases table shows a calculated cost per BTC.
On the next sweep, affected rows become new revisions with the corrected status; nothing is overwritten.

**Farside / HYPE:** Farside answered every automated request with a bot-check page ("Just a moment...") — not usable;
the downloaded samples were removed from the commit. HYPE deferred.

**Tests:** 234 passed (backend), 46 passed (frontend); lint and types clean.

**Verified on Windows:** 234 passed; purchase re-sweep: 468 revisions, 53 unchanged, 1 suspect (company 3825, 2 BTC
for 111.84 M — probably a cost in another currency; kept as reported).

**Git commit:** `9dcf2f1` — `[P6] treasury purchase check`.

---

### 2026-09-24 — Phase 7: Whale intelligence

**What changed**
- **Sources** (verified 2026-09-24, $0, no keys): **Coin Metrics Community** — daily exchange inflow, outflow and
  exchange supply, current supply and issuance for BTC and ETH (checked against real responses; licence CC BY-NC 4.0);
  **Blockchair** — top-100 address balances (BTC; ETH accounts), large transfers (BTC outputs ≥ 500 BTC, ETH
  transactions ≥ 5,000 ETH) and Bitcoin daily coin days destroyed, coins ≥ 1 y / ≥ 155 d old moved and coinbase-origin
  coins moved (documented shapes; the host is not reachable from Claude's workspace); **BitInfoCharts** — 27 Bitcoin
  address labels (Binance, Robinhood, Bitfinex, OKX, Coincheck, Crypto.com, bitbank, Gate.io, Tether, Binance Pool, US
  and UK government seizures, Bitfinex and Mt. Gox hack funds), each address checksum-verified. Not available free
  (shown in the UI): dormant supply stock, miner → exchange flows, SOL/XRP whale data, ETH labels, balance bands.
- **Entity classification:** migration `0005` — `ref.entity`, `ref.entity_label` (evidence, source, confidence,
  validity period, publication and record times; append-only) with database checks: an inferred label can only be
  "unknown large holder"; institution / fund / market maker need direct or attributed evidence. Classes: known
  exchange, institution, fund, market maker, protocol, miner, government, other; unknown large holder (size only,
  never an institution); unlabelled. Point-in-time label use, precedence rules, conflicts shown. Label files import
  idempotently (worker start, or `python -m cfi.whales.label_store import <csv>`); any bad row rejects the file.
- **Storage / engine:** `obs.large_transfer` hypertable (fourth record family `CanonicalTransfer`); address checksum
  validation (Base58Check, Bech32/Bech32m, Ethereum); invalid addresses kept as reported and flagged `suspect`.
- **Jobs:** Celery task `whales.ingest` per provider / dataset / asset — recent window plus one history chunk per run
  (Coin Metrics 730 days, Blockchair aggregates 120 days, transfers 7 days); queued once when beat starts.
- **Metrics:** daily net flow to exchanges; cohort balances and 7-day changes by class; transfer directions (to / from
  labelled exchanges); **Whale Flow Score v1** (net flow 7 d, exchange supply 30 d, unknown large holders 7 d, coins
  ≥ 1 y moving 7 d vs 90 d) with every component's value, calculation, source, freshness and quality; miner spending
  ratio (shown, not scored); **four contradiction indicators** (exchange flows vs old coins, vs large holders; whale vs
  institutional score; labelled exchange balances vs Coin Metrics).
- **API:** `/api/v1/whales/catalog`, `/overview`, `/flows`, `/holders`, `/transfers`, `/addresses/{chain}/{address}`,
  `/entities`, `/score` (all with `as_of` / `knowledge_time`).
- **Whales page** (new navigation item): score card, contradictions, net-flow chart and daily table, largest addresses
  with classification (evidence, source, confidence), cohorts, large transfers, rules and coverage.
- **Historical fixtures:** `backend/tests/fixtures/whales/README.md` — synthetic values with hand-derived results
  (BTC score 22.5, ETH −37.2, point-in-time view −1.4).
- **Docs:** ADR-0049 (and the missing ADR-0048 index row), DATA_DICTIONARY §3/§4/§5/§5c, ARCHITECTURE §5.1/§5.3/§5.5/§6/§11,
  CLAUDE.md §C3 (7 = Whale intelligence), README, TODO, THIRD_PARTY_NOTICES.md, `.env.example`, `compose.yaml`.

**Tests run (Claude's workspace: PostgreSQL 17 + TimescaleDB 2.30.1, Redis 8.8, Python 3.12, Node 22)**

| Check | Result |
|---|---|
| Backend `uv run pytest` (unit + integration + API) | 364 passed (129 new) |
| Backend without database/Redis | 266 passed, 98 skipped |
| `ruff format --check` / `ruff check` / `mypy` (strict) | clean |
| Frontend `pnpm test` / `lint` / `format:check` / `typecheck` / `build` | 59 passed / clean / clean / clean / built |
| Running stack (API + built frontend + Playwright) | Whales page renders for BTC and ETH with the synthetic fixtures shifted to yesterday, in a scratch database; score, contradictions, chart, holders and transfers as expected |

Covered by tests: address checksums (BIP-173/350 vectors, mistyped, testnet, mixed case); every label rule in code and
as database constraints (inferred institution / fund / market maker / exchange rejected); size rule never gives a known
class; precedence and conflicts; label validity and publication time; label file rejection listing every bad row;
seed file validity; Coin Metrics real row, flash → estimated, status time as `available_at`, pagination, unfinished
day skipped, schema changes; Blockchair documented queries, rich-list units, transfer normalisation, invalid addresses
flagged, offset pagination, aggregations, provider errors; chunked history and resumable checkpoints; revisions
appended; hand-computed score values and coverage exclusions; contradiction statuses; point-in-time leakage (data,
snapshots and labels published after `as_of`, and rows stored after `knowledge_time`, never used).

**Known limitations**
- No live Blockchair response seen (host unreachable from the workspace): shapes are the documented ones; a change
  fails the run with a schema error, visible in ingestion runs.
- Free sources are thinner than paid analytics: Coin Metrics' exchange attribution only, 27 BTC labels, no ETH labels;
  7-day holder changes need a week of daily snapshots; transfers keep 7 days of history at first.
- Licences: Coin Metrics CC BY-NC and Blockchair's free tier are non-commercial; BitInfoCharts label terms unverified.
- Bitcoin "transfers" are outputs (may be change or consolidation); Ethereum transfers exclude internal calls.
- Score parameters and thresholds are judgments awaiting the user's review (TODO.md, Phase 7).

**Git commit:** pending — the user commits on Windows.

