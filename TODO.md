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

## Phase 8 — Derivatives (built 2026-09-26; see PROGRESS.md)

- [x] `obs.derivative_quote`, Binance USDⓈ-M / OKX / Deribit adapters, shared scheduled-source runner, derivatives
      calculations, Derivatives Health Score, API, Derivatives page.
- [x] **User:** tests and `docker compose up --build` on Windows — 418 passed, commit `ea124b5` (2026-09-26).
- [ ] **User:** check `/api/v1/ingestion/runs` for `binance_futures`, `okx_derivatives` and `deribit` (Binance was
      not reachable from Claude's workspace — HTTP 451 — so no live Binance response has been seen).
- [ ] After the first real run: copy one real Binance payload per endpoint from the raw archive into the test fixtures
      and confirm the documented shapes (timestamps on the hour for 1 h statistics).
- [ ] Watch the option-chain job duration (hundreds of instruments every 4 h on the `backfill` queue).

### Decisions needed from the user (Phase 8)

- [ ] **Terms of use** of Binance, OKX and Deribit public market data (not reviewed; `terms_verified = false`).
- [x] **Judgment parameters (v1 methodology / initial parameters) — approved by the user (2026-09-26)** after
      reviewing the exact component/threshold/band breakdown. OI expansion ±5 % / 24 h, ±15 % / 7 d; leverage change
      ±10 % / 7 d; funding extreme |30 %| a year; basis extreme ≥ +20 % / ≤ −5 % (headline ≈ 90 days, ≥ 14 d);
      liquidation event 5 × median and ≥ 0.05 % of OI; skew at 0.9 / 1.1 × forward (± 3 %), expiry ≈ 30 d; score
      weights 0.25 / 0.15 / 0.20 / 0.20 / 0.20 (funding / basis / leverage / liquidations / volatility), each a
      fixed-threshold ratio (metric ÷ reference scale, clipped 0–1) — explicitly not percentile- or z-score-
      normalised; bands 75 / 50 / 25 (health, not stress). Never to be described as empirically validated. Any
      future change publishes a new version id (`derivatives_health_v2`, …) rather than editing `derivatives_health_v1`
      — see the addendum below.
- [x] **Score parameter storage — externalised (2026-09-26 addendum, ADR-0051).** Weights/scales/bands moved from
      hard-coded constants in `score.py` into a versioned registry, `backend/src/cfi/derivatives/score_parameters.py`
      (`PARAMETER_SETS`, current version `derivatives_health_v1`). A future change adds a new entry rather than
      editing this one, so past scores stay reproducible. Deliberately a plain Python module, not a database table
      (no runtime editing is needed yet) — promoting it to a table later would not require touching any caller.
      Condition thresholds in `metrics.py` (separate from the score) were left as-is; not requested.
- [ ] **Coverage gaps** (recorded in the UI): Binance liquidations (websocket only — would need the real-time phase),
      SOL / XRP options and basis, top-trader positioning, venues beyond Binance / OKX / Deribit (paid aggregators).
- [ ] **Open scope question (ADR-0051):** should computed Derivatives Health Scores be snapshotted into a database
      table over time (e.g. for "the score as it stood each day", independent of recomputation), rather than relying
      on recomputation from stored point-in-time observations + a named parameter version? Not built — flagged as a
      deliberate scope call, not assumed either way.

## Phase 9 — Liquidity / stablecoins (built 2026-09-26; see PROGRESS.md)

- [x] DefiLlama stablecoins adapter, generalised scheduled-source runner (reused unchanged, no new migration),
      liquidity calculations, versioned Liquidity Score (`liquidity_score_v1`, versioned from the start), API
      (`/api/v1/liquidity/{catalog,overview,history}`).
- [ ] **User:** tests and `docker compose up --build` on Windows — see PROGRESS.md for the exact commands and the
      expected test count (505 passed in Claude's scratch environment).
- [ ] **User:** check `/api/v1/ingestion/runs` for `defillama` (its host is not reachable from Claude's workspace —
      egress-proxy denied, like Blockchair in Phase 7 — so no live response has been seen from a network that can
      actually reach it).
- [ ] After the first real run: copy one real DefiLlama `/stablecoincharts/all` payload into the test fixtures and
      confirm the documented shape (digit-string `date`, nested `totalCirculating.peggedUSD`).

### Decisions needed from the user (Phase 9)

- [ ] **Terms of use** of DefiLlama's public API (not reviewed; `terms_verified = false`).
- [ ] **Judgment parameters (v1 methodology / initial parameters) — not yet reviewed by the user.** Liquidity Score
      weights 0.30 / 0.30 / 0.25 / 0.15 (USDT growth / USDC growth / total growth / growth acceleration), reference
      scales 5 % / 5 % / 4 % / 3 pp, bands ±50 / ±15 (see DATA_DICTIONARY.md §5e, ADR-0052). Chosen by design, not
      fitted to data — same review invitation as Phase 8's Derivatives Health Score: if the user wants a different
      breakdown, send it and a new version id (`liquidity_score_v2`) is published rather than editing v1.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the user
      asks for it, following the `HealthScoreCard` pattern from Phase 8.
- [ ] **Coverage gap, permanent (not a "to do"):** exchange stablecoin balances and flows are not calculable from
      any free source found (checked DefiLlama, Coin Metrics, Blockchair) — would need paid, labelled on-chain
      address attribution (Nansen, Arkham, CryptoQuant). `exchange_liquidity_change()` always reports
      `"unavailable"`, shown as a named gap in the UI/API rather than omitted.

## Phase 10 — Retail Activity Intelligence (built 2026-09-26; see PROGRESS.md)

- [x] CoinGecko `/search/trending` and Blockchair small-output-count provider extensions (no new adapters), retail
      derivatives-positioning cross-module read (Phase 8's funding rate / account ratio, Binance venue only, not
      re-ingested), retail calculations (`percentile_rank`, `derivatives_proxy`, `meme_coin_activity`,
      `small_transaction_activity`), two versioned scores (`retail_activity_score_v1`,
      `retail_speculation_score_v1`), retail sentiment (a deterministic rule, not AI interpretation), API
      (`/api/v1/retail/{catalog,overview,history}`).
- [ ] **User:** tests and `docker compose up --build` on Windows — see PROGRESS.md for the exact commands and the
      expected test count (577 passed in Claude's scratch environment).
- [ ] **User:** check `/api/v1/ingestion/runs` for `coingecko` (trending) and `blockchair` (small-output-count) —
      no live response for either new endpoint has been captured from a network that can actually reach them from
      Claude's workspace, so the user's first real run is the real verification, same pattern as Phases 7–9.
- [ ] After the first real run: capture one real CoinGecko `/search/trending` response and one real Blockchair
      small-output-count response into the test fixtures and confirm the documented shapes.

### Decisions needed from the user (Phase 10)

- [ ] **Business/licensing decisions — three sources deliberately not integrated, not technical dead ends:**
      - **Google Trends:** no official public API (the supported route needs a paid Google Cloud BigQuery
        account); the commonly used unofficial scrape of `trends.google.com` is not authorised by Google's terms
        of service for sustained automated use. If the user wants Google Trends data, the choice is between
        paying for BigQuery access or accepting an unauthorised scrape (not built here either way without an
        explicit decision).
      - **Reddit activity** (post/comment volume, sentiment): Reddit's API has been metered/paid beyond a small
        non-commercial free allowance since 2023. Integrating it commercially at meaningful volume needs a paid
        licensing decision from the user.
      - **Social activity (Twitter/X and similar):** no free tier supports search or aggregate content retrieval
        on X; meaningful read access needs a paid API tier. Same posture as Reddit.
- [ ] **Judgment parameters (v1 methodology / initial parameters) — not yet reviewed by the user.**
      - Retail Activity Score weights 0.35 / 0.30 / 0.35 (small-tx percentile / meme-trending percentile /
        derivatives-turnover percentile), `min_available_weight` 0.5, bands ±80/±60/±40/±20.
      - Retail Speculation Score weights 0.40 / 0.40 / 0.20 (funding-rate bias / account-ratio skew /
        meme-trending), reference scales 0.0005 / 0.5 / 2, `min_available_weight` 0.4, bands ±50/±15.
      - See DATA_DICTIONARY.md §5f, ADR-0053. Chosen by design, not fitted to data — same review invitation as
        every prior phase's score: if the user wants a different breakdown, send it and a new version id
        (`retail_activity_score_v2` / `retail_speculation_score_v2`) is published rather than editing v1.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the
      user asks for it.
- [ ] **Coverage/methodology gap, permanent (not a "to do"):** small-output-count is not filtered for change
      outputs from large transactions, exchange-internal batching, or dust — a noisy proxy, stated plainly
      wherever the metric is shown, never smoothed over. If the user wants a cleaner signal, that needs either a
      paid provider with UTXO-level classification or an accepted false-positive rate.

## Phase 11 — Macroeconomic Data Layer (built 2026-09-27; see PROGRESS.md)

- [x] FRED provider adapter (official keyed JSON API), 18 datasets across daily/weekly/monthly/event cadence,
      macro calculations (`yield_curve_slope`, `real_policy_rate`, `cpi_year_over_year`, `vix_condition`,
      generic `trend`, `us_net_liquidity`, `net_liquidity_trend`), one versioned score
      (`macro_environment_score_v1`, 7 direction-annotated components), API
      (`/api/v1/macro/{catalog,overview,history}`).
- [ ] **User:** register a free FRED API key (https://fred.stlouisfed.org/docs/api/api_key.html) and set
      `CFI_PROVIDER_FRED_API_KEY` in `.env` — required, not optional, same as SoSoValue in Phase 6. No data can
      be ingested from a live environment without it.
- [ ] **User:** tests and `docker compose up --build` on Windows — see PROGRESS.md for the exact commands and
      the expected test count (630 passed in Claude's scratch environment).
- [ ] **User:** check `/api/v1/ingestion/runs` for `fred` — its host is not reachable from Claude's workspace
      (egress-proxy denied, like Blockchair/DefiLlama in earlier phases), so no live response has been seen from
      a network that can actually reach it; the user's first real run, after setting the API key, is the real
      verification.
- [ ] After the first real run: copy one real FRED `/fred/series/observations` payload per series (or a
      representative subset) into the test fixtures and confirm the documented shape (`realtime_start`/
      `realtime_end`, `"."` missing-value marker).

### Decisions needed from the user (Phase 11)

- [ ] **DXY substitute.** The real ICE US Dollar Index (DXY) is proprietary/licensed and not freely available;
      the Fed's own trade-weighted Broad Dollar Index (`DTWEXBGS`) is tracked instead and labelled "DXY
      substitute" everywhere it appears. Accept the substitute, or evaluate a paid DXY source later.
- [ ] **US-only net liquidity, not a true global aggregate.** "Global liquidity proxies" was requested, but no
      free source aggregates non-US central-bank balance sheets. `us_net_liquidity` (Fed balance sheet − TGA −
      reverse repo) is explicitly labelled a US-only proxy. Accept as the working proxy, or scope in
      China/EU/Japan balance-sheet sources later (all currently unverified for free access).
- [ ] **Gold not tracked.** FRED's only free daily gold series was discontinued by ICE Benchmark Administration
      in January 2022; no other verified free/keyless source was found. Accept the gap, or evaluate a paid gold
      data source later.
- [ ] **Point-in-time integrity for revised series (CPI, PCE, unemployment, M2).** Conservative documented
      release-delay estimates are used for `available_at`, not full FRED vintage
      (`realtime_start`/`realtime_end`/`vintage_dates`) tracking — deliberately out of scope this phase (not
      requested; R13). Full vintage tracking can be built later if point-in-time backtests need the value *as
      first published* rather than today's most-revised figure.
- [ ] **Judgment parameters (v1 methodology / initial parameters) — not yet reviewed by the user.** Macro
      Environment Score weights 0.20 / 0.20 / 0.15 / 0.15 / 0.10 / 0.15 / 0.05 (yield curve / real policy rate /
      VIX / equity trend / dollar trend / net-liquidity trend / oil trend), reference scales 1.00pp / 2.00pp /
      10 / 10% / 5% / 5% / 15%, `min_available_weight` 0.5, bands ±50/±15. See DATA_DICTIONARY.md §5g, ADR-0054.
      Chosen by design, not fitted to data — same review invitation as every prior phase's score: if the user
      wants a different breakdown, send it and a new version id (`macro_environment_score_v2`) is published
      rather than editing v1.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the
      user asks for it.
- [ ] **Terms of use** of FRED's public API not separately reviewed (`terms_verified` unchanged from the
      existing adapter capabilities default) — FRED data is US federal government work and is generally public
      domain, but this has not been formally verified against FRED's own terms page.

## Phase 12 — Market Structure Engine (built 2026-09-27; see PROGRESS.md)

- [x] One new dataset (`market_structure.total_market_cap.usd`, CoinGecko `/global`), everything else
      calculated from already-tracked data: moving averages, trend, RSI, ATR, realized volatility, volume
      trend, rolling VWAP, relative strength vs. BTC, support/resistance, market breadth, BTC/ETH dominance,
      TOTAL2/TOTAL3, ETH/BTC, one versioned score (`market_structure_score_v1`, 5 direction-annotated
      components), API (`/api/v1/market-structure/{catalog,overview,history}`).
- [ ] **User:** tests and `docker compose up --build` on Windows — see PROGRESS.md for the exact commands and
      the expected test count.
- [ ] **User:** check `/api/v1/ingestion/runs` for `coingecko`'s `/global` calls — CoinGecko's host is not
      reachable from Claude's workspace (egress-proxy denied, like every other provider's raw endpoints in
      earlier phases), so no live response has been seen from a network that can actually reach it; the user's
      first real run is the real verification.
- [ ] After the first real run: copy one real CoinGecko `/global` payload into the test fixtures and confirm
      the documented shape (`data.total_market_cap.usd`, `data.updated_at`) still matches.

### Decisions needed from the user (Phase 12)

- [ ] **Market breadth is a four-asset proxy, not full-market breadth.** No free source publishes an
      advance/decline line across the whole crypto market. `market_breadth` is the fraction of this platform's
      own four tracked assets (BTC, ETH, SOL, XRP) trading above their own 50-day SMA — accept as the working
      proxy, or scope in a broader universe later if a suitable free source is found.
- [ ] **BTC/ETH dominance calculated, not CoinGecko's own `market_cap_percentage`.** Dominance is derived from
      the new TOTAL dataset and the per-asset market caps already tracked (Phase 5/6), to keep every dominance
      figure point-in-time consistent with its own inputs, rather than storing CoinGecko's own percentage
      (computed at CoinGecko's own snapshot time). Accept this approach, or ask for CoinGecko's own figure to
      be stored alongside it for comparison.
- [ ] **One venue (Coinbase), one benchmark (BTC), for every technical calculation.** Every indicator is
      computed from Coinbase Exchange's daily bars (Phase 5's priority-10 default venue) rather than blending
      venues; relative strength, ETH/BTC and dominance are always benchmarked against BTC. Accept these
      defaults, or specify a different venue/benchmark.
- [ ] **VWAP is a rolling 20-day window, not a session-anchored intraday VWAP.** Daily bars have no intraday
      session to anchor to; every VWAP field/label says "rolling-window approximation". Accept this, or request
      intraday bars for a true session VWAP later (a larger scope change).
- [ ] **Judgment parameters (v1 methodology / initial parameters) — not yet reviewed by the user.** Market
      Structure Score weights 0.25 / 0.20 / 0.20 / 0.20 / 0.15 (price trend / momentum / market breadth /
      altcoin relative strength / volatility regime), reference scales 0.20 / 50 / 0.50 / 0.15 / 50,
      `min_available_weight` 0.5, bands ±50/±15. See DATA_DICTIONARY.md §5h, ADR-0055. Chosen by design, not
      fitted to data — same review invitation as every prior phase's score: if the user wants a different
      breakdown, send it and a new version id (`market_structure_score_v2`) is published rather than editing
      v1.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the
      user asks for it.
- [ ] **Terms of use** of CoinGecko's public API for `/global` not separately reviewed beyond the existing
      adapter's attribution requirement (already tracked from Phase 5/6/10).

## Phase 13 — Capital Flow Divergence Engine (built 2026-09-27; see PROGRESS.md)

- [x] No new ingestion; pure computation over Phases 5–12's already-ingested/already-calculated data via each
      domain's own already-tested service methods. 10 standardized comparisons (institutional vs. retail,
      institutional vs. price, whale vs. retail, whale vs. price, liquidity vs. price, open interest vs. price,
      funding vs. price, stablecoin supply vs. price, leverage vs. price, macro vs. market structure), the
      4-cell quadrant matrix (with the two explicit whale/retail cross-cells), duration/historical-episode
      scanning (new methodology), deterministic rule-based evidence text, and the 12-node Capital Flow Map with
      hedged OBSERVED FLOW vs. INFERRED ROTATION edges. API: `/api/v1/divergence/{catalog,pair,matrix,
      capital-flow-map}`. See DATA_DICTIONARY.md §5i, DECISIONS.md ADR-0056.
- [ ] **User:** run the full test/lint/mypy suite and `docker compose up --build` on Windows — see PROGRESS.md
      for the exact commands and expected counts. The integration suite (`test_divergence_api.py`) needs
      `CFI_DATABASE_URL`/`CFI_REDIS_URL`, unavailable in Claude's own sandbox; only the unit suite (fully
      synthetic, no DB) has been run and verified in this environment.

### Decisions needed from the user (Phase 13)

- [ ] **Comparison #5 (liquidity vs. price) uses combined USDT+USDC supply; #8 (stablecoin supply vs. price)
      uses USDT alone.** These look similar but are deliberately distinct metrics (a broad dry-powder proxy vs.
      a single-issuer view) — accept as scoped, or ask for a different pairing.
- [ ] **Comparison #6 (open interest vs. price) uses the raw OI level; #9 (leverage vs. price) uses a
      leverage-skew proxy** (mean `|long/short account ratio − 1|` across venues — a directional-crowding
      measure, not a level). Accept as scoped, or ask for a different leverage definition.
- [ ] **Comparison #10 (macro vs. market structure) substitutes TOTAL crypto market cap for the Market
      Structure Score**, because the score has no ranged/historical series in this platform (a Phase 12 gap).
      Accept this substitution, or ask for the score to gain a persisted history in a later phase so #10 can
      use it directly.
- [ ] **Capital Flow Map: Mid Caps, DeFi and AI-related asset categories are marked `unavailable`** — no
      asset-category taxonomy exists anywhere in the platform yet. "Large Caps" uses XRP as a proxy; "Meme
      assets" uses retail's meme-trending-count as an explicitly-labelled attention proxy, never an observed
      flow. Accept these gaps as documented, or specify which additional assets/categories to track so real
      data can populate these nodes in a later phase.
- [ ] **Percentile/duration/episode thresholds (judgment parameters, not fitted to data):**
      `MIN_PERCENTILE_SAMPLE=20`, `EPISODE_PERCENTILE_THRESHOLD=70`, `MAX_DURATION_LOOKBACK_DAYS=180`,
      `MAX_HISTORICAL_EXAMPLES=3`, default `window_days=30` (range 3–180). See `cfi/divergence/universe.py`.
      Chosen by design — send different values if the user wants a different sensitivity.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the
      user asks for it.

## Phase 14 — Market Regime Engine (built 2026-09-27; see PROGRESS.md)

- [x] No new ingestion; pure computation over the seven existing domain scores (institutional, whale, retail
      activity/speculation, liquidity, derivatives health, macro, market structure) plus BTC trend/RSI/
      volatility-percentile/market-breadth/liquidation-event readings, via `cfi.divergence.adapters.Adapters`
      as a service factory. Seven regimes (Accumulation, Recovery, Expansion, Euphoria, Distribution,
      Capitulation, Mixed/Unclear); confidence = matched/available condition weight, explicitly NOT a
      price-direction probability; contributing/contradicting metrics; regime start date/duration (daily
      backward walk) and historical examples (weekly sample). API: `/api/v1/regime/{catalog,current}`. See
      DATA_DICTIONARY.md §5j, DECISIONS.md ADR-0057.
- [ ] **User:** run the full test/lint/mypy suite and `docker compose up --build` on Windows — see PROGRESS.md
      for the exact commands and expected counts. The integration suite (`test_regime_api.py`) needs
      `CFI_DATABASE_URL`/`CFI_REDIS_URL`, unavailable in Claude's own sandbox; only the unit suite (fully
      synthetic, no DB) has been run and verified in this environment.

### Decisions needed from the user (Phase 14)

- [ ] **The seven regime definitions (which conditions, which weights, which thresholds) are v1 judgment
      parameters** — anchored to each domain score's own already-published bands where possible, but not
      fitted to data or empirically validated. See `cfi/regime/parameters.py`, DATA_DICTIONARY.md §5j,
      ADR-0057. Send different weights/thresholds, or a different condition set per regime, if these don't
      match the user's own intuition for what each regime should require.
- [ ] **Assignment thresholds** (`min_available_weight=0.5`, `min_confidence_assign=0.55`, `tie_margin=0.08`)
      decide how readily the classifier commits to a regime vs. reporting "Mixed/Unclear." Accept these
      defaults, or request a different sensitivity (e.g. a lower confidence floor for a more decisive but
      less certain classifier).
- [ ] **Regime duration walks daily (capped at 120 days); historical examples sample weekly (over 365 days)**
      — two deliberately different, documented performance trade-offs (see ADR-0057), since re-running the
      full seven-domain classification at every past day would be far more expensive over a long lookback.
      Accept this approach, or ask for a persisted regime-history table in a later phase so both could work
      from stored history instead of live re-classification.
- [ ] **Regime conditions are evaluated only for BTC** (`cfi.regime.universe.BENCHMARK_ASSET`), the same
      "one benchmark" convention as Phases 12/13. A regime here describes BTC's own conditions, not
      necessarily every altcoin's. Accept this scope, or ask for a per-asset regime classification later.
- [ ] **Frontend page** — not built this phase (not requested; see PROGRESS.md). A natural next step once the
      user asks for it.

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
| Stablecoins | **Implemented (Phase 9): DefiLlama stablecoins API.** Still candidates: issuer transparency pages; on-chain supply queries; exchange-balance/flow data (paid: Nansen, Arkham, CryptoQuant) |
| Macro | **Implemented (Phase 11): FRED (St. Louis Fed) official keyed JSON API.** Still candidates: other official statistical releases (BLS, BEA direct, ECB, PBoC) for series FRED does not carry |
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
