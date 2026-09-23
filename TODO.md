# TODO.md

Upcoming work and open questions. Items move to `PROGRESS.md` when done.
Nothing here is started until the user opens the corresponding phase.

---

## Immediate

- [ ] **User:** answer the Architecture Approval Checklist below.
- [x] **User (Windows machine):** initialise Git — done 2026-09-23, commit `d59cb20`.
- [ ] **User:** decide whether to connect a remote (GitHub/GitLab, private) — nothing has been pushed anywhere.

---

## ARCHITECTURE APPROVAL CHECKLIST (Phase 2)

Implementation does not start until the items in **Part A** are answered. Each row gives the recommended default;
reply "approve A1–A12 as recommended" or name the changes. Details: `ARCHITECTURE.md` section and ADR shown.

### Part A — must be approved before any implementation

| # | Decision | Recommended default | Ref | Approved? |
|---|---|---|---|---|
| A1 | Technology stack: Next.js/React/TypeScript · Python 3.12+/FastAPI · PostgreSQL+TimescaleDB · Redis · Celery · Claude API · Docker Compose | Approve as proposed | ADR-0014 | [ ] |
| A2 | One repository (`backend/`, `frontend/`, `infra/`); FastAPI is the only data gateway; Next.js presentation-only | Approve | ADR-0015 | [ ] |
| A3 | Self-hosted TimescaleDB under the Timescale License (free for our own application; cannot resell the database as a service) | Approve; managed Timescale considered at production time | ADR-0016 | [ ] |
| A4 | Hybrid storage: series registry + typed tables for market data + one generic table for scalar series; providers side by side, never blended | Approve | ADR-0017 | [ ] |
| A5 | Bitemporal model: `available_at` (publicly knowable) + `ingested_at` (when we knew) + revisions; `pit_reliability` tag on history | Approve | ADR-0018, 0032 | [ ] |
| A6 | Raw payload archive: local folder in development, S3-compatible object storage in production | Approve | ADR-0019 | [ ] |
| A7 | Queue: **Celery** with Redis broker (alternatives: Dramatiq, Arq, Temporal) | Celery | ADR-0023 | [ ] |
| A8 | Cache/broker product: **Redis 8** (RSAL/SSPL/AGPL licences) or **Valkey** (BSD, drop-in compatible) | Redis 8 (unmodified, internal use); switch to Valkey if you prefer a permissive licence | ADR-0024 | [ ] |
| A9 | Authentication: own accounts in FastAPI, Argon2id, mandatory 2FA (TOTP) for owner, server-side session cookies; single user now, multi-user capable | Approve | ADR-0026 | [ ] |
| A10 | Authorization: roles `owner`/`analyst`/`viewer` + separate database roles per service enforcing the layer rule | Approve | ADR-0027 | [ ] |
| A11 | AI: Claude called only by background workers; snapshot grounding; strict validator (reject unsupported numbers); no action tools; model tiering by config | Approve | ADR-0034 | [ ] |
| A12 | Charts: Lightweight Charts (requires a visible TradingView link/attribution) + ECharts for analytics | Approve both | ADR-0043 | [ ] |

### Part B — business inputs (needed before data ingestion; defaults used if not answered)

| # | Question | Default if not answered | Ref | Answer |
|---|---|---|---|---|
| B1 | Asset scope for v1 | BTC and ETH only | — | |
| B2 | Monthly data-provider budget (USD) | 0 — free/public sources only at first | ADR-0038 | |
| B3 | Monthly Claude API budget (USD) and hard ceiling behaviour | Small fixed ceiling; AI pauses (with notice) when reached | ADR-0034, 0038 | |
| B4 | Historical depth for research/backtests | As far back as each free source allows, tagged by `pit_reliability` | ADR-0032 | |
| B5 | Primary granularity for v1 | 1 hour for derivatives/market data; daily for ETF, on-chain, macro | §5.2 | |
| B6 | Where ingestion runs in production (your PC, VPS, cloud) and which country | Decide before production; verify exchange API access from that location | §9 | |
| B7 | Alert channels | In-app + email; Telegram optional | ADR-0035 | |
| B8 | Display time zone | Asia/Manila (changeable per user) | ADR-0039 | |

### Part C — can be decided later (defaults recorded; revisit at the named phase)

| # | Decision | Default | When | Ref |
|---|---|---|---|---|
| C1 | Data retention: full-resolution window for minute-level data; raw payload retention for high-frequency endpoints | Keep everything until storage is measured; decide before large backfills | Ingestion phases | ADR-0020 |
| C2 | `NUMERIC` vs `double precision` for high-volume tables | Benchmark first, keep `NUMERIC` by default | Infrastructure | ADR-0044 |
| C3 | Observability level: full (Prometheus + Grafana + tracing) vs. light start (logs + DB health tables) | Light start, full stack before production | Infrastructure / 25 | ADR-0029 |
| C4 | Backtest engine: in-house thin framework vs. library | In-house, validated with historical fixtures | 15 | ADR-0033 |
| C5 | Backup targets: production RPO ≤ 15 min, RTO ≤ 4 h; backup destination | Approve targets at production | 26 | ADR-0042 |
| C6 | Real-time path: Redis Streams (Kafka only if needed) | Redis Streams | 27 | ADR-0037 |
| C7 | Batch first, real-time last | Accept | — | ADR-0009 |
| C8 | Dev setup: code on `E:\FINANCIAL TOOL` (simple, slower Docker file sharing) vs. working copy inside WSL2 (faster) | Keep on E: until it is too slow | Infrastructure | §9 |
| C9 | Remote Git hosting (private GitHub/GitLab) | None yet; recommended before infrastructure for backup | Any time | ADR-0011 |

### Part D — phase plan

| # | Question |
|---|---|
| D1 | What is Phase 3 in your guide? The table in `CLAUDE.md` §C3 currently shows "Data ingestion framework"; **infrastructure** (Compose, database, migrations baseline, tooling) is not yet placed and must come before any ingestion code. |

---

## Infrastructure (unscheduled — phase to be set by the user)

- [ ] Project skeleton (`backend/`, `frontend/`, `infra/`), dependency management (uv, pnpm), pre-commit.
- [ ] Docker Compose: TimescaleDB, Redis, API, worker, beat, frontend; named volumes.
- [ ] Alembic baseline: schemas `ref`, `raw`, `obs`, `calc`, `sig`, `regime`, `ai`, `usr`, `ops`; database roles and grants (ADR-0027).
- [ ] Config and secret handling (`.env.example`, no real keys in Git).
- [ ] Structured logging, error taxonomy, `ops.job_run`.
- [ ] Test, lint, type-check commands wired and documented in `CLAUDE.md` §C5.
- [ ] Benchmark `NUMERIC` vs `double precision` (ADR-0044).
- [ ] CI (if a remote is added).

## Phase 3 — Data ingestion: provider research

Names below are **candidates to evaluate only**. Their current endpoints, coverage, history depth, pricing,
rate limits, and terms of use (including storage/redistribution) are **not verified** and must be checked
against official documentation before any adapter is written.

| Category | Candidates to evaluate |
|---|---|
| Spot / perps / funding / OI / liquidations | Exchange public APIs (e.g. Binance, Bybit, OKX, Coinbase, Kraken, Deribit); aggregators (e.g. Coinglass, Kaiko, Amberdata, CoinAPI) |
| Options | Deribit public API; options analytics vendors (e.g. Laevitas, Amberdata) |
| ETF flows / holdings | Issuer websites and filings; aggregators; SEC EDGAR |
| On-chain / exchange flows / whales | Glassnode, CryptoQuant, Coin Metrics, Santiment, Arkham, Nansen; self-hosted node / public explorers for raw data |
| Stablecoins | DefiLlama; issuer transparency pages; on-chain supply queries |
| Macro | FRED (St. Louis Fed); other official statistical releases |
| Retail / sentiment | Search-interest sources, app-ranking sources, social data vendors — terms need careful review |
| Reference data / market caps | CoinGecko, CoinMarketCap, Coin Metrics |

- [ ] For each dataset in `DATA_DICTIONARY.md` §5: pick primary + fallback provider, record evidence and terms.
- [ ] Document single-source dependencies in `DECISIONS.md`.

## Later phases — reminders captured now

- [ ] **Phase 15/16:** build a deliberate look-ahead leak into a test fixture and prove the leakage tests catch it.
- [ ] **Phase 15/16:** record the number of strategy/signal variants tried per backtest (multiple-testing control).
- [ ] **Phase 13/14:** regime and similarity models must be evaluated on periods not used to design them.
- [ ] **Phase 19:** AI validator must reject any number not present in the snapshot; add adversarial tests (prompted to invent data).
- [ ] **Phase 21:** alerts fire on signals/regimes, never on AI text alone.
- [ ] **Phase 25:** API-key storage, rate-limit abuse, prompt injection via ingested text (e.g. social data fed to Claude), dependency audit.
