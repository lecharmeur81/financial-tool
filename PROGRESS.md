# PROGRESS.md

Single source of truth for what has been done. Updated at the end of every task.

**Current phase:** 11 — Macro → ✅ complete (backend only, as requested); built and tested in the scratch environment, pending delivery to and verification on Windows
**Next phase:** to be defined by the user (do not start automatically)

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
| 7 | Whale intelligence | ✅ Complete — verified on Windows (`0529017`); first real whale runs to be checked |
| 8 | Derivatives | ✅ Complete — verified on Windows (`ea124b5`); first real derivatives runs to be checked |
| 9 | Liquidity | ✅ Complete (backend only, as requested) — fully verified on Windows (`f1b8f6a`); first real DefiLlama run to be checked |
| 10 | Retail | ✅ Complete (backend only, as requested) — fully verified on Windows (`2fae0e6`); first real CoinGecko/Blockchair runs to be checked |
| 11 | Macro | ✅ Complete (backend only, as requested) — built and tested in the scratch environment; pending delivery to and commit/verification on Windows; first real FRED run needs `CFI_PROVIDER_FRED_API_KEY` |
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

Phases 0–11 follow the user's guide. The remaining topics are provisional and get their numbers when the user issues them.

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

**Windows check (user, 2026-09-24):** `docker compose up -d --build` → all services started, api healthy;
`docker compose exec api pytest` → 364 passed. First real Coin Metrics / Blockchair runs not yet checked.

**Git commit:** `0529017` — `[P7] whale intelligence` (63 files).

### 2026-09-26 — Phase 8: Derivatives

**What changed**
- **Sources** (verified 2026-09-26, $0, no keys): **OKX** — hourly open interest (coins), funding history, hourly
  long/short account ratio, liquidation orders + contract value (checked against real responses); **Deribit** — futures
  curve and option chain snapshots, hourly DVOL for BTC and ETH (real responses); **Binance USDⓈ-M** — hourly open
  interest, funding history, all-account long/short ratio (documented shapes: Binance answers HTTP 451 to Claude's
  workspace). Not available free (shown in the UI): Binance liquidation history, SOL/XRP options and basis, top-trader
  positioning, market-wide totals.
- **Storage / engine:** migration `0006` — `obs.derivative_quote` hypertable (fifth record family `CanonicalQuote`:
  futures, perpetuals and options per snapshot; expiry / strike / option-type checks; an instrument listed after its
  expiry is flagged `suspect`); `ops.dataset.kind` also `quote`. Scalar series for open interest, funding, account
  ratios, hourly liquidation totals (aggregated across pages in the adapter; incompletely read hours become missing
  points) and DVOL. USD values are calculated at read time (coins × Coinbase close), never stored from venues.
  Percent values stored as ratios with the conversion recorded.
- **Jobs:** the Phase 7 runner became the shared `cfi/ingestion/scheduled.py` (whales moved onto it unchanged);
  Celery task `derivatives.ingest` per provider / dataset / asset (hourly OI, ratios, liquidations, DVOL, futures;
  4-hourly funding and option chain — the chain on the `backfill` queue); history ~1 month (OI, ratios), 365 / 90 days
  (funding), 365 days (DVOL); `CFI_DERIVATIVE_PROVIDERS`.
- **Calculations:** OI change 24 h / 7 d per venue and aggregate (same venue set only), OI expansion / contraction,
  leverage ratio (OI ÷ market cap) and leverage expansion / reduction, annualised 7-day funding (per venue,
  OI-weighted) and funding extremes, annualised basis curve with a 90-day headline and basis extremes, liquidations
  (24 h, long share, share of OI) and liquidation-event hours, options put/call (OI, volume), ATM IV, 10 %-OTM skew,
  DVOL, long/short account ratios (context only), price / OI context sentence. No reading labelled bullish or bearish.
- **Derivatives Health Score v1** (0–100, 100 = no stress; stress = 100 − health): funding 0.25, basis 0.15, leverage
  0.20, liquidations 0.20, DVOL 0.20 — each a direction-neutral stress 0 … 1 with its value, scale, weight,
  contribution, calculation, inputs and direction context; "Insufficient data" below weight 0.5.
- **API:** `/api/v1/derivatives/catalog`, `/overview`, `/asset`, `/history` (all with `as_of` / `knowledge_time`).
- **Derivatives page** (placeholder replaced): score card with every component, conditions, OI per venue, leverage,
  funding per venue, account ratios, price context, OI / price chart, Deribit curve and options, liquidations and
  events, per-source data quality, method and limits.
- **Historical fixtures:** `backend/tests/fixtures/derivatives/README.md` — real OKX / Deribit responses (basis 4.96 %
  a year, skew +1.75 points computed by hand) and a synthetic history with hand-derived results (BTC health 59.4,
  stress 40.6; SOL Insufficient data; point-in-time OI 125,000).
- **Docs:** ADR-0050, DATA_DICTIONARY §4/§5d, ARCHITECTURE §5.1/§5.3/§5.5, CLAUDE.md §C3 (8 = Derivatives), README,
  TODO, THIRD_PARTY_NOTICES.md, `.env.example`, `compose.yaml`.

**Tests run (Claude's workspace: PostgreSQL 17 + TimescaleDB 2.30.1, Redis 8.8, Python 3.12, Node 22)**

| Check | Result |
|---|---|
| Backend `uv run pytest` (unit + integration + API) | 418 passed (54 new) |
| Backend without database/Redis | 311 passed, 107 skipped |
| `ruff format --check` / `ruff check` / `mypy` (strict) | clean |
| Frontend `pnpm test` / `lint` / `format:check` / `typecheck` / `build` | 70 passed / clean / clean / clean / built |
| Running stack (API + built frontend + Playwright) | Derivatives page renders for BTC and SOL with the synthetic history shifted to the present, in a scratch database; score, conditions, chart, curve, options, liquidations and data quality as expected, no console errors |

Covered by tests: real OKX / Deribit rows read exactly (open interest in coins, funding, account ratio, contract value,
futures curve with exponent notation, options with IV → ratio, DVOL); documented Binance requests and shapes;
pagination (OKX `end` / `after` / `begin`–`end`, Binance `startTime`, Deribit `continuation`); liquidation aggregation
across pages with orders sharing the page-boundary millisecond counted once, inconsistent sides flagged, hours beyond
retention not emitted; unfinished DVOL hour skipped; clock-ahead Deribit snapshots dated by receipt; provider error
envelopes; every calculation and the score by hand (OI venue-set rule, stale values, leverage, funding with a missing
settlement, basis and options on real data, liquidation events, bands, re-weighting, Insufficient data); ingestion
provenance, idempotent re-runs, gaps stored as missing, failures recorded; API values, conditions and wording (no
bullish / bearish); point-in-time leakage (snapshots and liquidation events after `as_of`, rows stored after
`knowledge_time`, never used).

**Known limitations**
- No live Binance response seen (HTTP 451 from the workspace): shapes are the documented ones; a change fails the run
  with a schema error, visible in ingestion runs.
- Coverage: open interest and funding on Binance + OKX only, basis / options / DVOL Deribit only (BTC, ETH),
  liquidations OKX only; free history reaches about a month for OI and account ratios; Deribit snapshots and
  liquidations build up from the first run (events need more than 24 stored hours).
- Put/call and skew use Deribit mark IVs without greeks (moneyness skew, not 25-delta).
- Score weights, scales and thresholds are **v1 methodology / initial parameters, approved by the user (2026-09-26)
  after reviewing the full component/threshold/band breakdown** — see the addendum below. Not described as
  validated: chosen by design, not fitted to data.
- Terms of use of Binance, OKX and Deribit public data not yet reviewed (`terms_verified = false`).

**Windows check (user, 2026-09-26):** `docker compose up -d --build` → all services started, api healthy;
`docker compose exec api pytest` → 418 passed. First real Binance / OKX / Deribit runs not yet checked.

**Git commit:** `ea124b5` — `[P8] derivatives intelligence` (69 files).

### 2026-09-26 — Phase 8 addendum: versioned Derivatives Health Score parameters

**What changed** (ADR-0051; user approved the v1 weights/scales/bands after reviewing the exact breakdown, and asked
for them to be externalised and versioned before locking, plus a reproducibility/semantic-note requirement)
- **New module `backend/src/cfi/derivatives/score_parameters.py`:** a frozen `ParameterSet` dataclass and an
  append-only `PARAMETER_SETS` registry keyed by version id, holding the approved v1 numbers unchanged (weights
  0.25/0.15/0.20/0.20/0.20, funding 30 %, basis 15 % outside 0–10 %, leverage 20 %, liquidations 1 % of OI, DVOL BTC
  30→80 %/ETH 40→100 %, `min_available_weight` 0.5, bands 75/50/25). `parameters(version)` is the one loader
  function; an unknown version id is a hard error, never a silent fallback.
- **`score.py`** no longer hard-codes these numbers: component metadata (label, human-readable scale text,
  definition) is generated from a `ParameterSet` so text can't drift from the numbers; every component function and
  `compute()` take an optional `params` argument (default: current version) — no existing call site changed.
  `ScoreResult` gained `parameter_version` (the version actually used) and `calculated_at` (wall-clock time, distinct
  from `as_of`). Version id renamed from generic `"v1"` to `derivatives_health_v1`.
- **API:** every score result and the catalog's score definition now also return `calculated_at` and a fixed
  `semantic_note`: "Higher Derivatives Health Score means lower measured derivatives stress across the available
  components. It is not a probability of price increase and does not indicate market direction." No per-component
  qualitative labels added (not requested).
- **Frontend:** `HealthScoreCard` shows the semantic note and "Calculated <time> from parameters version <id>".
- **Scope decision, recorded rather than assumed:** the *condition* thresholds in `metrics.py` (OI expansion,
  leverage change, funding extreme, basis extreme, liquidation event) are a separate concept from the score's
  reference scales and were left as hard-coded constants — externalising those was not requested. No new database
  table was added to snapshot every computed score over time (no other score in the platform is persisted that way
  either, and every result is already a pure function of stored point-in-time data plus a named immutable parameter
  set) — flagged in ADR-0051 as a scope call the user can override if a scheduled snapshot table is actually wanted.
- **Docs:** ADR-0051, DATA_DICTIONARY.md §5d.

**Tests run**

| Check | Result |
|---|---|
| New `backend/tests/unit/test_derivative_score_parameters.py` (the 8 required proofs) | 27 new tests, all passed |
| Backend `uv run pytest` (unit + integration + API, scratch PostgreSQL 16 + TimescaleDB 2.30.1 + Redis) | 445 passed (418 + 27 new) |
| `ruff format --check` / `ruff check` / `mypy` (strict), whole backend | clean |
| Frontend `pnpm test` / `lint` / `format:check` / `typecheck` | 70 passed / clean / clean / clean |
| Live check: scratch API server, `/api/v1/derivatives/catalog` and `/asset?asset=BTC` | `version` = `derivatives_health_v1`, weights/scales match approved values exactly, `semantic_note` and `calculated_at` present, `Insufficient data` returned cleanly with no ingested data |

**Final parameter representation:** `backend/src/cfi/derivatives/score_parameters.py`, version id
`derivatives_health_v1`, one immutable `ParameterSet` entry in `PARAMETER_SETS`.

**Known limitations**
- Reproducibility is achieved via immutable versioned parameters + complete field exposure on every computed result,
  not via a database snapshot table — see the scope decision above. If per-run history of the score itself (not
  just its inputs) is wanted later, that is a follow-up, not built here.
- The condition thresholds in `metrics.py` remain hard-coded (out of scope; see above). Funding's condition
  threshold and the score's funding scale both start at 30 % but are now independent parameters that can diverge.
- Still open from the original Phase 8 build: no live Binance response seen (HTTP 451 from Claude's workspace);
  terms of use for Binance/OKX/Deribit not yet reviewed.

**Delivered to the user's machine** via the device bridge (checksum-verified); commit is the user's own step on
Windows (Git runs there — C5).

### 2026-09-26 — Phase 9: Liquidity / stablecoins (DefiLlama), Liquidity Score

**What changed** (ADR-0052; user's exact spec: "Track USDT/USDC/total stablecoin supply, market share, minting,
burning, exchange stablecoin balances, stablecoin exchange flows where available. Calculate supply growth,
contraction, growth acceleration, growth deceleration, exchange liquidity changes. Create Liquidity Score. Expose
all components. Show observed data separately from interpretation. Build tests. Commit. Stop.")

- **New provider adapter `backend/src/cfi/providers/defillama.py`:** DefiLlama stablecoins (`stablecoins.llama.fi`),
  free and keyless — the only free source found for stablecoin circulating supply; confirmed live and against
  DefiLlama's published API docs, though not as a byte-exact response captured inside the sandboxed workspace
  (its host is unreachable from there, like Blockchair in Phase 7 — flagged plainly in the module docstring, real
  verification deferred to the user's own ingestion run). Handles the endpoint's key quirk: it takes no date-range
  parameters and always returns its entire history in one response, so the adapter filters client-side to the
  requested window in `parse_page`.
- **New `backend/src/cfi/liquidity/` package:** `universe.py` (dataset spec + `NOT_TRACKED`), `records.py`
  (canonical-record helpers), `metrics.py` (supply growth/contraction, market share, growth acceleration/
  deceleration, and `exchange_liquidity_change()` — always `"unavailable"`, a named gap rather than a silent one),
  `score_parameters.py` + `score.py` (the versioned Liquidity Score, `liquidity_score_v1` — signed −100…+100,
  modeled on the Institutional Flow Score since supply growth is directional, unlike Phase 8's stress concept;
  versioned from the start, following the Phase 8 addendum's pattern rather than needing its own addendum),
  `sources.py` (the generalised scheduled-source runner, no new migration — reuses `obs.observation`), `jobs.py`,
  `queries.py`, `service.py`.
- **API:** new router `backend/src/cfi/api/routes/liquidity.py` — `/api/v1/liquidity/{catalog,overview,history}`,
  registered in `api/app.py`. New setting `CFI_LIQUIDITY_PROVIDERS` (default `defillama`). Worker wiring
  (`worker/app.py`, `worker/schedule.py`): a `liquidity.ingest` Celery task, scheduled every 6 h per subject (the
  data itself changes at most daily).
- **Not tracked, and said so** (`NOT_TRACKED`): exchange stablecoin balances and exchange stablecoin flows — no
  free source found (checked DefiLlama, Coin Metrics, Blockchair); would need paid, labelled on-chain address
  attribution (Nansen, Arkham, CryptoQuant). The requested "exchange liquidity changes" calculation is implemented
  but always reports `unavailable` with this reason, and is never folded into the score. Individual mint/burn
  events are likewise not tracked (would need per-chain contract-event tracking); day-over-day change in stored
  supply is used instead, and stated plainly as a proxy, never as an exact event count.
- **Frontend: not built.** The Phase 9 instruction as given did not ask for it (unlike Phases 7–8, which explicitly
  did); building it would have been unrequested scope (R13). The backend API is complete and ready for a frontend
  page whenever the user asks for one.
- **Docs:** ADR-0052, DATA_DICTIONARY.md §5e, CLAUDE.md phase table (9 = Liquidity; Retail demoted back to
  provisional).

**Tests run**

| Check | Result |
|---|---|
| New unit tests: `test_liquidity_adapters.py`, `test_liquidity_metrics.py`, `test_liquidity_score.py` | 48 new tests, all passed |
| New integration tests: `test_liquidity_ingestion.py`, `test_liquidity_api.py` (real PostgreSQL + TimescaleDB, fake DefiLlama server serving a synthetic multi-month supply history) | 12 new tests, all passed |
| Backend `uv run pytest` (unit + integration + API, scratch PostgreSQL 16 + TimescaleDB 2.30.1 + Redis) | 505 passed (445 + 48 + 12 new) |
| `ruff format --check` / `ruff check` / `mypy` (strict), whole backend | clean |
| Live check: scratch API server, `/api/v1/liquidity/catalog` and `/overview` | catalog lists the DefiLlama provider, dataset, schedule and the 4-component score definition; overview with no ingested data returns `"Insufficient data"` cleanly (no fabricated values) |

**Final parameter representation:** `backend/src/cfi/liquidity/score_parameters.py`, version id
`liquidity_score_v1`, one immutable `ParameterSet` entry in `PARAMETER_SETS`.

**Known limitations**
- No live DefiLlama response has been captured from a network that can actually reach it (see above); the user's
  first real ingestion run on Windows is the real verification, same as Blockchair (Phase 7) and Binance (Phase 8).
- Terms of use for DefiLlama not yet reviewed (`terms_verified = false` in `ProviderCapabilities`).
- No frontend page — out of scope for this phase as instructed; a natural next step if the user wants one.
- `TOTAL` is every stablecoin DefiLlama tracks, not the sum of USDT + USDC — stated in the docstring and the data
  dictionary, but worth restating here since it is easy to misread.

**Delivered to the user's machine** via the device bridge (checksum-verified, all 30 files byte-for-byte match);
commit is the user's own step on Windows (Git runs there — C5).

**Committed on Windows:** `f1b8f6a` — `[P9] add liquidity/stablecoin intelligence layer (DefiLlama), Liquidity Score`
(30 files changed, 2843 insertions, 10 deletions). Confirmed from the user's own terminal transcript.

**Verified on Windows (2026-09-26):** `uv` was missing from PATH the first time (see prior note in an earlier
draft of this section — resolved by installing `uv` via the official PowerShell installer, `irm
https://astral.sh/uv/install.ps1 | iex`, then reopening the terminal). Once installed, the user ran the full
suite from `E:\FINANCIAL TOOL\backend` in PowerShell:
- `uv sync` — 60 packages installed cleanly.
- `uv run pytest -q` — **386 passed, 119 skipped, 0 failed** in 6.58s. All skips are integration tests
  (`CFI_DATABASE_URL` / `CFI_REDIS_URL` not set — no local Postgres/Redis running on the dev machine), the
  same expected pattern as Phases 7–8's first Windows verification; not a failure.
- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 175 files already formatted.
- `uv run mypy` — success, no issues found in 170 source files.

Phase 9 is therefore fully verified end-to-end on the development machine, not just in the scratch environment
here. No outstanding verification gap remains.

### 2026-09-26 — Phase 10: Retail Activity Intelligence, Retail Activity Score, Retail Speculation Score

**What changed** (ADR-0053; user's exact spec: "Build the Retail Activity Intelligence layer. Potential inputs:
Google Trends; Reddit activity where legally/licensed and technically available; social activity; retail
derivatives activity; small transaction activity; meme-coin activity; retail trading proxies. Every metric must
clearly identify whether it is: DIRECT RETAIL DATA or RETAIL PROXY. Do not present proxies as direct measurements
of retail behavior. Create: retail activity score; retail speculation score; retail sentiment metrics; historical
percentile calculations. Build tests. Document limitations. Commit. Stop.")

- **Research first** (WebSearch/WebFetch, not assumption — R3): confirmed no free source segments any data by
  account type (retail vs. institutional). Google Trends has no official public API (the supported route needs a
  paid Google Cloud BigQuery account); Reddit's API has been metered/paid beyond a small non-commercial allowance
  since 2023; X (Twitter)'s free tier does not support search or aggregate content retrieval. All three recorded
  as `NOT_TRACKED` business/licensing decisions, not silently skipped or worked around with an unauthorised
  scrape — restated in TODO.md for the user's review. Confirmed CoinGecko's `/search/trending` schema live and
  against its published docs before writing any adapter code.
- **New `backend/src/cfi/retail/` package:** `universe.py` (two new dataset specs + `NOT_TRACKED`), `metrics.py`
  (historical `percentile_rank`, `derivatives_proxy`, `meme_coin_activity`, `small_transaction_activity` — every
  metric dataclass carries `measurement_class = "proxy"` as a structurally-enforced field, `init=False`, so
  nothing can be silently constructed as "direct"), `score_parameters.py` + `score.py` (two versioned scores —
  Retail Activity Score, unsigned 0-100; Retail Speculation Score, signed −100…+100, with its meme-trending
  component explicitly marked non-directional via `ComponentDef.directional = False`), `queries.py` (point-in-time
  reads, including a deliberate cross-module read of two derivatives-owned datasets, documented in both the
  module docstring and the API catalog response), `service.py`, `sources.py`, `jobs.py`.
- **Two provider extensions, no new adapters:** `cfi/providers/coingecko.py` gained the free, keyless
  `/search/trending` endpoint (meme-coin / retail search-attention proxy); `cfi/providers/blockchair.py` gained a
  new daily aggregation (count of Bitcoin outputs under $1,000 — small on-chain transaction proxy). Both are
  strictly additive changes to already-tested provider files (new branches inserted as early-return checks, one
  new dict entry, one new frozenset member) — no existing branch's logic was altered.
- **Cross-module read, not re-ingestion:** retail derivatives-positioning proxy reads Phase 8's already-ingested
  `deriv.funding_rate` and `deriv.long_short_account_ratio.1h` directly from the shared `obs.observation` table,
  filtered to `venue = "binance"` only (Binance and OKX publish the ratio for different account populations that
  must never be blended). No new ingestion job, no data duplication.
- **API:** new router `backend/src/cfi/api/routes/retail.py` — `/api/v1/retail/{catalog,overview,history}`,
  registered in `api/app.py`. New setting `CFI_RETAIL_PROVIDERS` (default `coingecko,blockchair`). Worker wiring
  (`worker/app.py`, `worker/schedule.py`): a `retail.ingest` Celery task — CoinGecko trending polled every 3 h (a
  live snapshot feed with no history to backfill), Blockchair small-output-count every 12 h (120-day history in
  30-day chunks, matching the whale module's own Blockchair scheduling).
- **Frontend: not built.** Not requested for this phase (matching Phase 9's own scope decision). The backend API
  is complete and ready for a frontend page whenever the user asks for one.
- **Docs:** ADR-0053, DATA_DICTIONARY.md §5f, CLAUDE.md phase table (10 = Retail).

**Tests run (scratch environment: PostgreSQL 16 + TimescaleDB, Redis, Python 3.12)**

| Check | Result |
|---|---|
| New unit tests: `test_retail_adapters.py`, `test_retail_metrics.py`, `test_retail_score.py` | 56 new tests, all passed |
| New integration tests: `test_retail_ingestion.py` (real CoinGecko/Blockchair adapters against synthetic fakes), `test_retail_api.py` (real PostgreSQL, independent hand-computation cross-check) | 16 new tests, all passed |
| Backend `uv run pytest` (unit + integration + API, scratch PostgreSQL 16 + TimescaleDB + Redis) | 577 passed (505 + 56 + 16 new) |
| `ruff format --check` / `ruff check` / `mypy` (strict), whole backend | clean |

**Bugs found and fixed during this phase's own test run** (first time any of this code executed — R7: never
claim something works without testing it):
- The CoinGecko trending fake test double matched the request path against `/search/trending`, but the real
  adapter's base URL already includes `/api/v3`, so the full request path is `/api/v3/search/trending` — every
  simulated poll returned 404 and silently ingested nothing. Fixed in `tests/retail_fakes.py` to match the full
  path, matching the convention every other provider fake in this project already follows.
- The `retail` integration-test fixture (`tests/integration/retail_support.py`) directly inserts synthetic
  funding-rate / account-ratio rows as context data (mirroring `derivative_support.py`'s own established
  pattern), but never registered those two datasets with the ingestion engine first — every insert failed with a
  foreign-key violation (`series_dataset_id_fkey`). Fixed by registering `FUNDING_RATE` and `LONG_SHORT_RATIO`
  with the engine before use, exactly as `derivative_support.py` registers its own context datasets.
- Several `E501` (line too long) and one unsorted-import violation across `metrics.py`, `score.py`, `service.py`
  and the new test files; one `mypy` `dict` invariance error on `derivatives_proxy`'s parameter types (fixed by
  widening them to `Mapping`, since the function only reads from them); one missing test-helper type annotation;
  one `max()` type-var error from an overly-loose `dict[object, ...]` annotation in a test. All fixed; no
  production behavior changed by any of these fixes except the `Mapping` widening (a pure type-signature
  loosening — `Mapping` is a superset of what `dict` already accepted).

Covered by tests: every metric's `measurement_class == "proxy"`; percentile rank (insufficient-history floor,
ties, top-of-range); derivatives proxy (partial-asset availability, all three funding/ratio conditions,
unavailable); meme-coin activity (curated-symbol filtering, no-snapshot case); small-transaction activity
(week-average and percent-change math, no-trailing-history case); both scores' parameter loading, weighted
combination, renormalisation on a missing component, the insufficient-data floor, band boundaries, clipping, and
the meme-trending component's always-nonnegative behavior; real ingestion of both new datasets against
synthetic histories including no-duplication-on-rerun; the full overview/catalog/history API responses against
independently hand-computed expected values (derivatives proxy, small-transaction activity) and against expected
*shape* for percentile/score fields (status, sample size, measurement class, evidence labelling — their exact
numeric formulas are already covered at the unit level).

**Known limitations**
- `NOT_TRACKED` (Google Trends, Reddit, X/Twitter) are business/licensing decisions for the user to make, not
  technical dead ends — see DATA_DICTIONARY.md §5f and TODO.md.
- Small-output-count is **not** filtered for change outputs, exchange-internal batching, or dust — stated
  plainly in the dataset description and every API response, never smoothed over.
- No source publishes retail-labelled data, so every metric in this phase is a RETAIL PROXY; none is ever
  presented as DIRECT RETAIL DATA (structurally enforced, not just documented — see ADR-0053).
- Score weights, scales and band boundaries are v1 methodology / initial parameters, chosen by design and not
  fitted to data — awaiting the user's review, same posture as every other score in this platform.
- No live CoinGecko or Blockchair response for the new endpoints has been captured from a network that can
  actually reach them from this workspace; the user's first real ingestion run on Windows is the real
  verification, same pattern as Phases 7–9.
- Terms of use for the new CoinGecko/Blockchair endpoints not yet separately reviewed (`terms_verified` unchanged
  from the existing adapter capabilities).
- No frontend page — out of scope for this phase as instructed.

**Delivered to the user's machine** via the device bridge (checksum-verified, all 28 changed/new files
byte-for-byte match); commit is the user's own step on Windows (Git runs there — C5).

**Committed on Windows:** `2fae0e6` — `[P10] add retail activity intelligence layer, Retail Activity/Speculation
Scores` (29 files changed, 3738 insertions, 13 deletions). Confirmed from the user's own terminal transcript.

**Verified on Windows (2026-09-26):** the user ran the full suite from `E:\FINANCIAL TOOL\backend` in PowerShell:
- `uv sync` — 62 packages resolved, 60 checked (already installed from Phase 9).
- `uv run pytest -q` — **442 passed, 135 skipped, 0 failed** in 6.74s. All skips are integration tests
  (`CFI_DATABASE_URL` / `CFI_REDIS_URL` not set — no local Postgres/Redis running on the dev machine, including
  all 8 new `test_retail_ingestion.py`/`test_retail_api.py` tests), the same expected pattern as every prior
  phase's first Windows verification; not a failure.
- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 192 files already formatted.
- `uv run mypy` — success, no issues found in 187 source files.

Phase 10 is therefore fully verified end-to-end on the development machine, not just in the scratch environment
here. No outstanding verification gap remains.

### 2026-09-27 — Phase 11: Macroeconomic Data Layer, FRED provider, Macro Environment Score

**What changed** (ADR-0054; user's exact spec: "PHASE 11 — MACRO: Build the macroeconomic data layer. Track
where reliable historical/current data is available: DXY; US 2-year yield; US 10-year yield; Fed funds rate;
CPI; PCE; unemployment; VIX; S&P 500; Nasdaq; gold; oil; global liquidity proxies. Normalize all macro
timestamps. Support: daily; weekly; monthly; event-based data. Build: Macro Environment Score. Expose the
components. Do not convert macro data into deterministic crypto predictions. Build tests. Commit. Stop.")

- **Research first** (WebSearch/WebFetch, not assumption — R3): FRED's raw data endpoints are blocked by this
  workspace's egress proxy, but FRED's own HTML documentation pages are not — confirmed the real, documented
  shape of the official keyed `series/observations` JSON API this way, without live data access, the same
  split seen with Blockchair/Binance/DefiLlama in earlier phases. Confirmed via `WebFetch` that FRED's only
  free daily gold series was discontinued in January 2022 at ICE Benchmark Administration's own request, and
  via `WebSearch` that no other verified free/keyless gold source exists — recorded `NOT_TRACKED` rather than
  sourced from an unverified aggregator.
- **New `backend/src/cfi/macro/` package:** `universe.py` (18 dataset specs across daily/weekly/monthly/event
  cadence + `NOT_TRACKED`: gold, true global liquidity aggregate), `metrics.py` (`yield_curve_slope`,
  `real_policy_rate`, `cpi_year_over_year`, `vix_condition`, generic `trend`, `us_net_liquidity`,
  `net_liquidity_trend`, with worst-case-staleness-sized tolerance windows — see bugs below),
  `score_parameters.py` + `score.py` (Macro Environment Score, versioned, signed −100…+100, 7 direction-
  annotated components), `queries.py`, `service.py`, `sources.py`, `jobs.py`.
- **New provider adapter, `cfi/providers/fred.py`:** the official FRED keyed JSON API
  (`api.stlouisfed.org/fred/series/observations`), chosen over the undocumented keyless `fredgraph.csv`
  endpoint because only the JSON API is documented and versioned (R8). Requires
  `CFI_PROVIDER_FRED_API_KEY` (not optional — same pattern as SoSoValue, Phase 6). Handles FRED's own `"."`
  missing-value marker as `quality_status = missing`, never a fabricated zero.
- **Extended `cfi/core/time.py`'s shared `parse_period`** to support `"1mo"` (nominal 30-day month), a small,
  deliberate, backward-compatible cross-cutting change justified by the phase's explicit "Support: monthly"
  requirement, rather than a private one-off parser local to the macro module. Existing period-string tests
  unaffected.
- **API:** new router `backend/src/cfi/api/routes/macro.py` — `/api/v1/macro/{catalog,overview,history}`,
  registered in `api/app.py`. New setting `CFI_MACRO_PROVIDERS` (default `fred`). Worker wiring
  (`worker/app.py`, `worker/schedule.py`): a `macro.ingest` Celery task, all 18 datasets scheduled on the
  `"backfill"` queue (not latency-sensitive, matching the SoSoValue precedent) at a cadence matched to each
  series' own reporting frequency.
- **Three scope decisions, each recorded transparently, not silently substituted or dropped:** `DTWEXBGS`
  (Fed Broad Dollar Index) as a labelled **DXY substitute** (the real ICE DXY is proprietary/licensed); a
  **US-only** net-liquidity proxy (Fed balance sheet − TGA − reverse repo), explicitly never presented as a
  true global aggregate; gold `NOT_TRACKED` (see research above). All three restated in `TODO.md` for the
  user's business/licensing review.
- **Frontend: not built.** Not requested for this phase (matching Phases 9/10's own scope decisions). The
  backend API is complete and ready for a frontend page whenever the user asks for one.
- **Docs:** ADR-0054, DATA_DICTIONARY.md §5g, CLAUDE.md phase table (11 = Macro).

**Tests run (scratch environment: PostgreSQL 16 + TimescaleDB, Redis, Python 3.12)**

| Check | Result |
|---|---|
| New unit tests: `test_macro_adapters.py`, `test_macro_metrics.py`, `test_macro_score.py` | 43 new tests, all passed |
| New integration tests: `test_macro_ingestion.py` (real FRED adapter against a synthetic fake), `test_macro_api.py` (real PostgreSQL) | 10 new tests, all passed |
| Backend `uv run pytest` (unit + integration + API, scratch PostgreSQL 16 + TimescaleDB + Redis) | 630 passed (577 + 53 new) |
| `ruff format --check` / `ruff check` / `mypy` (strict), whole backend | clean |

**Bugs found and fixed during this phase's own test run** (first time any of this code executed — R7: never
claim something works without testing it):
- **Tolerance windows too tight (a real production-logic bug, not a test artifact).** Running the full
  ingestion → API pipeline against a synthetic FRED fake surfaced `net_liquidity_trend` reading
  "unavailable" even with correct data present in the database. Root cause: a series' worst-case staleness
  right before its *next* point supersedes it is `period_length + publication_delay`, not just the delay
  (e.g. a weekly series with a 3-day delay can legitimately be up to ~17 days stale under normal, correct
  operation). The original tolerances (5d/11d/50d) were too tight for ordinary operation. Fixed to 7d/18d/95d
  in `cfi/macro/metrics.py`, with the reasoning recorded in the module's own comments.
- The FRED fake test double (`tests/macro_fakes.py`) matched the request path against
  `/series/observations`, but the adapter's `base_url` already includes `/fred`, so the full request path is
  `/fred/series/observations` — every simulated request 404'd. Fixed to match the full path, the same class
  of bug as Phase 10's CoinGecko fake.
- A test fixture's fixed "now" clock was set one day *after* the real system clock; the API's
  `as_of = min(given, real utc_now())` clamp then cut off data ingested against the fixture's own (future)
  clock. Fixed by moving the fixture clock safely into the past and passing it explicitly as `as_of` in every
  affected test, matching the established pattern in the liquidity/retail test suites.
- A test incorrectly assumed a second identical ingestion run would add no rows; in fact the backfill state
  machine legitimately continues advancing history on every call until complete. Renamed and rewrote the test
  to check the true "no duplicate on a repeated *recent* window" behavior directly.
- Several `E501` (line too long) and `PT018` (compound assertion) violations across the new module and test
  files, one non-raw `pytest.raises(match=...)` regex, and two missing test-helper type annotations. All
  fixed; no production behavior changed by any of these except the tolerance-window fix above, which is a
  genuine correctness fix, and a new `pyproject.toml` per-file `RUF001`/`RUF002`/`RUF003` ignore for
  `src/cfi/macro/**` (the module's formulas intentionally use real math symbols −, ×, ÷ — the same precedent
  already established for `institutional/`, `whales/`, `derivatives/` and `liquidity/`).

Covered by tests: FRED request building and FRED's own `"."` missing-value marker; availability-rule wiring
per period kind (daily `period_end_plus`, monthly/event `event_time_plus` with `known_when_received`); every
metric's conditions (yield-curve inverted/steep/normal, VIX elevated/calm/normal, generic trend up/down/flat)
and unavailable/insufficient-data paths; the net-liquidity composite's unit conversion math; the score's
parameter loading, weighted combination, renormalisation on a missing component, the insufficient-data floor,
band boundaries, clipping, and the neutral-baseline default; real ingestion of all four cadence kinds against
a synthetic FRED history, including the corrected no-duplication check; the full catalog/overview/history API
responses, including an "ok" score once every component has data and "insufficient_data" with nothing loaded.

**Known limitations**
- `NOT_TRACKED` (gold spot price, true global liquidity aggregate) are sourcing-gap/scope decisions for the
  user to review, not technical dead ends — see DATA_DICTIONARY.md §5g and TODO.md.
- DXY is tracked via the Fed's Broad Dollar Index (`DTWEXBGS`) substitute, not the real, proprietary ICE DXY
  — labelled as a substitute everywhere it appears, never presented as the real index.
- CPI, PCE, unemployment and M2 use conservative documented release-delay estimates for point-in-time
  availability, not full FRED vintage (`realtime_start`/`realtime_end`) tracking — deliberately out of scope
  this phase (R13); available later if requested.
- Score weights, scales and band boundaries are v1 methodology / initial parameters, chosen by design and not
  fitted to data — awaiting the user's review, same posture as every other score in this platform.
- No live FRED response has been captured from a network that can actually reach it from this workspace; the
  user's first real ingestion run on Windows, after obtaining and setting `CFI_PROVIDER_FRED_API_KEY`, is the
  real verification — same pattern as Phases 6–10.
- No frontend page — out of scope for this phase as instructed.

**Delivery to the user's machine, commit, and Windows verification are the next step** (device bridge,
checksum-verified, then the user's own `uv run pytest` / `ruff` / `mypy` / commit on Windows — Git runs there,
C5); not yet done as of this entry.

