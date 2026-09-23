# PROGRESS.md

Single source of truth for what has been done. Updated at the end of every task.

**Current phase:** 4 — Data ingestion engine → ✅ complete in Claude's workspace; awaiting the user's Docker check and commit
**Next phase:** 5 — to be defined by the user (do not start automatically)

---

## Phase overview

| Phase | Name | Status |
|---|---|---|
| 0 | Project foundation | ✅ Complete |
| 1 | Master engineering rules | ✅ Complete |
| 2 | Architecture | ✅ Complete (checklist Part A approved 2026-09-23) |
| 3 | Foundation (infrastructure) | ✅ Complete — verified on Windows |
| 4 | Data ingestion engine | ✅ Complete — Docker check on Windows pending |
| 5 | Institutional data | ⏳ Not started |
| 6 | Whale data | ⏳ Not started |
| 7 | Derivatives | ⏳ Not started |
| 8 | Liquidity | ⏳ Not started |
| 9 | Retail | ⏳ Not started |
| 10 | Macro | ⏳ Not started |
| 11 | Market structure | ⏳ Not started |
| 12 | Divergence engine | ⏳ Not started |
| 13 | Regime engine | ⏳ Not started |
| 14 | Historical similarity | ⏳ Not started |
| 15 | Backtesting | ⏳ Not started |
| 16 | Quant red-team | ⏳ Not started |
| 17 | Anomaly engine | ⏳ Not started |
| 18 | Capital rotation | ⏳ Not started |
| 19 | Claude AI Analyst | ⏳ Not started |
| 20 | Daily intelligence | ⏳ Not started |
| 21 | Alerts | ⏳ Not started |
| 22 | Paper trading | ⏳ Not started |
| 23 | Decision journal | ⏳ Not started |
| 24 | Executive dashboard | ⏳ Not started |
| 25 | Security + AI + stress testing | ⏳ Not started |
| 26 | Production | ⏳ Not started |
| 27 | Real-time intelligence | ⏳ Not started |

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

**Git commit:** pending — user to commit as `[P4] data ingestion engine`.
