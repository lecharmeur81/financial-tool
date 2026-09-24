# TODO.md

Upcoming work and open questions. Items move to `PROGRESS.md` when done.
Nothing here is started until the user opens the corresponding phase.

---

## Immediate

- [x] **User:** Architecture Approval Checklist Part A approved; B1–B3 answered (2026-09-23).
- [x] **User (Windows machine):** initialise Git — done 2026-09-23, commit `d59cb20`.
- [ ] **User:** decide whether to connect a remote (GitHub/GitLab, private) — nothing has been pushed anywhere.

---

## ARCHITECTURE APPROVAL CHECKLIST (Phase 2)

Implementation does not start until the items in **Part A** are answered. Each row gives the recommended default;
reply "approve A1–A12 as recommended" or name the changes. Details: `ARCHITECTURE.md` section and ADR shown.

### Part A — ✅ approved by the user on 2026-09-23 (all as recommended)

| # | Decision | Recommended default | Ref | Approved? |
|---|---|---|---|---|
| A1 | Technology stack: Next.js/React/TypeScript · Python 3.12+/FastAPI · PostgreSQL+TimescaleDB · Redis · Celery · Claude API · Docker Compose | Approve as proposed | ADR-0014 | [x] |
| A2 | One repository (`backend/`, `frontend/`, `infra/`); FastAPI is the only data gateway; Next.js presentation-only | Approve | ADR-0015 | [x] |
| A3 | Self-hosted TimescaleDB under the Timescale License (free for our own application; cannot resell the database as a service) | Approve; managed Timescale considered at production time | ADR-0016 | [x] |
| A4 | Hybrid storage: series registry + typed tables for market data + one generic table for scalar series; providers side by side, never blended | Approve | ADR-0017 | [x] |
| A5 | Bitemporal model: `available_at` (publicly knowable) + `ingested_at` (when we knew) + revisions; `pit_reliability` tag on history | Approve | ADR-0018, 0032 | [x] |
| A6 | Raw payload archive: local folder in development, S3-compatible object storage in production | Approve | ADR-0019 | [x] |
| A7 | Queue: **Celery** with Redis broker (alternatives: Dramatiq, Arq, Temporal) | Celery | ADR-0023 | [x] |
| A8 | Cache/broker product: **Redis 8** (RSAL/SSPL/AGPL licences) or **Valkey** (BSD, drop-in compatible) | Redis 8 (unmodified, internal use); switch to Valkey if you prefer a permissive licence | ADR-0024 | [x] |
| A9 | Authentication: own accounts in FastAPI, Argon2id, mandatory 2FA (TOTP) for owner, server-side session cookies; single user now, multi-user capable | Approve | ADR-0026 | [x] |
| A10 | Authorization: roles `owner`/`analyst`/`viewer` + separate database roles per service enforcing the layer rule | Approve | ADR-0027 | [x] |
| A11 | AI: Claude called only by background workers; snapshot grounding; strict validator (reject unsupported numbers); no action tools; model tiering by config | Approve | ADR-0034 | [x] |
| A12 | Charts: Lightweight Charts (requires a visible TradingView link/attribution) + ECharts for analytics | Approve both | ADR-0043 | [x] |

### Part B — business inputs (B1–B3 answered 2026-09-23; B4–B8 use the defaults unless changed)

| # | Question | Default if not answered | Ref | Answer |
|---|---|---|---|---|
| B1 | Asset scope for v1 | BTC and ETH only | — | **BTC, ETH + major altcoins** (exact list to confirm when data work starts; examples discussed: SOL, XRP, BNB) |
| B2 | Monthly data-provider budget (USD) | 0 — free/public sources only at first | ADR-0038 | **$0 — free sources first** |
| B3 | Monthly Claude API budget (USD) and hard ceiling behaviour | Small fixed ceiling; AI pauses (with notice) when reached | ADR-0034, 0038 | **$20/month hard ceiling; AI pauses with a notice** |
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
| D1 | ~~What is Phase 3?~~ Answered: Phase 3 = application foundation (done). **Open:** where does the data ingestion framework go? It must precede the dataset phases (4+). |

---

## Phase 3 — Foundation (done 2026-09-23; see PROGRESS.md)

- [x] Project skeleton (`backend/`, `frontend/`), dependency management (uv, pnpm), lockfiles.
- [x] Docker Compose: TimescaleDB, Redis, migrate, API, frontend; named volumes; health checks.
- [x] Alembic baseline: TimescaleDB extension + schemas `ref`, `raw`, `obs`, `calc`, `sig`, `regime`, `ai`, `usr`, `ops`.
- [x] Config and secret handling (`.env.example`, `CFI_` settings, secrets never logged).
- [x] Structured logging, error taxonomy, problem-details API errors, health checks.
- [x] Test, lint, format, type-check commands wired and documented in `CLAUDE.md` §C5.
- [x] CI workflow (`.github/workflows/ci.yml`) — runs once a Git remote exists.
- [x] Provider interface + stub (no real providers).
- [x] **User:** `ci.yml` placed in `.github\workflows\` (2026-09-23).
- [x] **User:** `docker compose up --build` on Windows — all services healthy; `docker compose exec api pytest` 56 passed (2026-09-23).

## Phase 4 — Data ingestion engine (done 2026-09-23; see PROGRESS.md)

- [x] Provider adapter interface, shared HTTP client (auth, timeouts, retries/backoff, rate limit, circuit breaker, pagination).
- [x] Response validation, normalisation (timestamps, time zones, units), provenance on every record.
- [x] Duplicate, revision, missing, gap, stale, conflict, rejection detection; quality findings; job runs; request log.
- [x] Raw payload archive; migration `0002` (registry, job runs, requests, payloads, series, observations, findings).
- [x] Mock providers + tests (unit and integration); provider-health and ingestion-runs API.

## Phase 5 — Market data (done 2026-09-23; see PROGRESS.md)

- [x] Adapters: Coinbase Exchange, Kraken, Binance, OKX, Bybit (OHLCV), Coinbase last trade, CoinGecko market cap.
- [x] `obs.market_bar`, backfill checkpoints, Celery workers + beat, market API, Market page with charts.
- [ ] **User:** run `docker compose up --build` on Windows and check the Market page with real data.

### Decisions needed from the user (Phase 5)

- [ ] **CoinGecko storage.** Its terms discourage storing data and ask that stored data be refreshed at least every
      24 h. Options: (a) keep storing (current: refreshed every 6 h / 5 min, history kept); (b) keep only the latest
      value; (c) drop market cap until a licensed source is chosen.
- [ ] **Exchange terms.** Coinbase, Kraken, Binance, OKX, Bybit terms of use not reviewed (`terms_verified = false`).
- [ ] **History depth / retention (B4, C1).** Defaults: 1m 7 d, 5m 30 d, 15m 90 d, 1h 2 y, 4h 4 y, 1d 10 y
      (`CFI_MARKET_BACKFILL_DAYS`). Raw payload files grow with every request (about 7k small files/day per provider).
- [ ] **Blocked providers.** Binance, OKX, Bybit, Kraken are blocked by Philippine ISPs; keep them enabled (visible
      failures) or remove them from `CFI_MARKET_PROVIDERS`? Hosting location (B6) decides this in production.
- [ ] **Display time zone (B8).** The Market page shows UTC; Asia/Manila display not built yet.

## Phase 6 — Institutional capital (built 2026-09-24; see PROGRESS.md)

- [x] `obs.institutional_flow`, SoSoValue + CoinGecko treasury adapters, jobs, aggregation, score, API, Flows page.
- [x] US spot ETF flows for BTC, ETH, **SOL and XRP** (added at the user's request, 2026-09-24).
- [x] **User:** register a free SoSoValue API key and set `CFI_PROVIDER_SOSOVALUE_API_KEY` in `.env` (done 2026-09-24).
- [x] **User:** run the tests and `docker compose up --build` on Windows (228 passed, commit `ef852b6`).
- [x] **User:** after the pacing fix, per-fund flows (12 BTC funds, reconciling) and treasury purchases (521) loaded.
- [ ] Ask SoSoValue what `avg_btc_cost` means (documented as USD per BTC; real values are not) — not stored until known.
- [ ] Farside Investors as a second ETF source: **not usable** (bot-check page for automated clients; "All rights
      reserved", no data terms). HYPE ETF flows deferred until a usable source exists (user decision 2026-09-24).
- [ ] After the first real run: copy one real SoSoValue payload from the raw archive into the test fixtures (with its
      capture date) and confirm the documented shapes (date format of `start_date`/`end_date`, number formats).

### Decisions needed from the user (Phase 6)

- [ ] **SoSoValue terms.** No API terms, licence or attribution rules are published in its documentation
      (`terms_verified = false`). Options: (a) use it for personal decision support as now; (b) ask SoSoValue for
      written terms; (c) disable it (`CFI_INSTITUTIONAL_PROVIDERS=coingecko`).
- [ ] **Score parameters (v1).** Weights 0.35 / 0.30 / 0.15 / 0.20, reference scales 1 % / 3 % / — / 2 %, band edges
      ±15 / ±50, minimum coverage 90 %, minimum weight 0.5 are judgment parameters. Approve, or name changes (a change
      creates v2).
- [ ] **Single source for ETF flows.** SoSoValue only; no second free source verified. Accept, or evaluate issuer
      files / a paid source later (B2 budget is $0).
- [ ] **Not tracked yet:** CoinShares weekly fund flows (no API), 13F holdings, Hong Kong ETFs (available from
      SoSoValue — enable?), ETH/SOL/XRP treasury purchases (no free source).
- [ ] **Availability estimates.** ETF: next US trading day 18:00 New York; purchases: date + 7 days. Review once native
      receipt times show when the data really appears.

## Phase 7 — Whale intelligence (built 2026-09-24; see PROGRESS.md)

- [x] Address validation, `ref.entity` / `ref.entity_label` / `obs.large_transfer`, Coin Metrics + Blockchair adapters,
      label import, classification, Whale Flow Score, contradiction indicators, API, Whales page.
- [ ] **User:** run the tests and `docker compose up --build` on Windows; check `/api/v1/ingestion/runs` for
      `coinmetrics` and `blockchair` (neither host is reachable from Claude's workspace, so no live response has been
      seen for Blockchair; Coin Metrics was checked with real responses).
- [ ] After the first real run: copy one real Blockchair payload per endpoint from the raw archive into the test
      fixtures and confirm the documented shapes (aggregation keys, `context.total_rows`, ETH `value` strings).
- [ ] Watch Blockchair's request cost (`context.request_cost` in archived payloads) against the 1,440/day free limit.

### Decisions needed from the user (Phase 7)

- [ ] **Licences.** Coin Metrics Community is CC BY-NC 4.0 (non-commercial only); Blockchair's free tier is for
      personal / non-commercial use. Fine for personal decision support; a commercial use needs paid licences.
- [ ] **BitInfoCharts labels.** 27 Bitcoin address labels copied once (2026-09-24) as attributed evidence, confidence
      0.6. Their terms for reuse were not found. Keep, replace with another source, or remove the seed file.
- [ ] **Judgment parameters (v1).** Large transfer ≥ 500 BTC / ≥ 5,000 ETH; unknown large holder ≥ 1,000 BTC /
      ≥ 10,000 ETH (confidence 0.5); score weights 0.35 / 0.15 / 0.25 / 0.25, scales 1 % / 3 % / 1 % / 1.0, band edges
      ±15 / ±50, contradiction thresholds ±0.25 sub-score, ±15 points, ±0.5 %. Approve or name changes (creates v2).
- [ ] **Not available free (recorded in the UI):** dormant / long-term-holder supply stock, miner → exchange flows,
      SOL and XRP whale data, labelled Ethereum addresses, balance bands, real-time transfer alerts (Whale Alert: paid).

## Deferred (to the phase that needs them)

- [x] Scheduling: Celery workers/beat (ADR-0023) — implemented in Phase 5. `dataset_updated` events still to do.
- [ ] Freshness/quality findings are written on every run (thousands of rows/day) — add retention or summarise.
- [ ] Compression policy for `obs.market_bar` (ADR-0020) once data volume is measured.
- [ ] OpenAPI-generated TypeScript client (ADR-0025); types are hand-written for now.
- [ ] Shared (Redis-backed) rate limiter and circuit breaker — needed once several workers ingest in parallel.
- [ ] Job types `backfill`, `reconcile`, `gap_fill`; `ops.coverage_daily`; per-dataset retention.
- [ ] Database roles and grants per service (ADR-0027, approved) — when API and workers run as separate services.
- [x] First real provider adapters (Phase 5). Access from the final hosting location still to verify (B6).
- [ ] Authentication (ADR-0026, approved) — before any user-layer feature or remote hosting.
- [x] Benchmark `NUMERIC` vs `double precision` (ADR-0044) — done in Phase 5: keep `NUMERIC`.
- [ ] Pre-commit hooks (optional convenience; CI already enforces the same checks).
- [ ] Observability stack (Prometheus/Grafana) — decision C3.

## Data ingestion: provider research (phase to be set by the user)

Names below are **candidates to evaluate only**. Their current endpoints, coverage, history depth, pricing,
rate limits, and terms of use (including storage/redistribution) are **not verified** and must be checked
against official documentation before any adapter is written.

| Category | Candidates to evaluate |
|---|---|
| Spot / perps / funding / OI / liquidations | Exchange public APIs (e.g. Binance, Bybit, OKX, Coinbase, Kraken, Deribit); aggregators (e.g. Coinglass, Kaiko, Amberdata, CoinAPI) |
| Options | Deribit public API; options analytics vendors (e.g. Laevitas, Amberdata) |
| ETF flows / holdings | **Implemented (Phase 6): SoSoValue OpenAPI.** Still candidates: issuer websites and filings; SEC EDGAR |
| On-chain / exchange flows / whales | **Implemented (Phase 7): Coin Metrics Community, Blockchair; BitInfoCharts labels.** Still candidates: Glassnode, CryptoQuant, Santiment, Arkham, Nansen (paid); self-hosted node |
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
