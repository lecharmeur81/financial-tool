# TODO.md

Upcoming work and open questions. Items move to `PROGRESS.md` when done.
Nothing here is started until the user opens the corresponding phase.

---

## 0. Immediate (end of Phase A)

- [ ] **User:** review the seven foundation documents and confirm or amend.
- [ ] **User (Windows machine):** initialise Git — open a terminal in `E:\FINANCIAL TOOL` and run:
      ```
      git init -b main
      git add -A
      git commit -m "[A] project foundation documentation"
      ```
      - If Git reports *"detected dubious ownership"* (common on external/exFAT/FAT32 drives), run:
        `git config --global --add safe.directory "E:/FINANCIAL TOOL"` and retry.
      - Then update the "Git commit" line in `PROGRESS.md` with the hash from `git log --oneline -1`.
- [ ] **User:** decide whether to connect a remote (GitHub/GitLab, private) — nothing has been pushed anywhere.

---

## 1. Open questions for the user (block Phase B/C)

| # | Question | Why it matters |
|---|---|---|
| Q1 | Accept the proposed stack in ADR-0008 (Python, PostgreSQL + TimescaleDB, FastAPI, Docker)? | Shapes all of Phase C |
| Q2 | Is Docker Desktop (with WSL2) acceptable on your Windows machine? Alternative: native PostgreSQL install. | Local infrastructure |
| Q3 | Asset scope for v1: BTC + ETH only, or also a defined alt/sector basket? | Data volume, provider cost, rotation analysis (Phase S) |
| Q4 | Data budget: free/public sources only at first, or paid APIs allowed? Monthly ceiling? | Many on-chain, entity-label, and options datasets are paid |
| Q5 | Historical depth required for regimes/backtests (e.g. since 2017, 2020, ETF era only)? | Some datasets only exist for recent years; affects regime validity |
| Q6 | Primary granularity for v1: daily, 4h, or 1h? | Storage, cost, rate limits |
| Q7 | Where will ingestion run in production (your PC, a VPS, cloud)? Which country/region? | Several exchange APIs restrict access by jurisdiction/IP; must be verified |
| Q8 | Single user (you) or multi-user? | Auth, permissions, hosting (Phase Z) |
| Q9 | Dashboard preference: web app (React/Next.js) vs. quick internal tool (e.g. Streamlit) first? | Phase Y, may affect API design |
| Q10 | Which Claude model/tier and monthly AI budget for the in-product analyst? | Phase T cost and latency |

---

## 2. Phase B — Architecture (next)

- [ ] Resolve Q1–Q10 (or record defaults in `DECISIONS.md`).
- [ ] Finalise the logical data model: raw, observation, reference entities, metric/signal/regime/interpretation tables.
- [ ] Specify the point-in-time query contract and the leakage-test strategy.
- [ ] Specify the provider adapter interface (fetch, paginate, rate limit, retry, map, record terms).
- [ ] Specify the metric registry (IDs, versions, dependencies, recomputation).
- [ ] Specify the snapshot format and AI output validator contract (design only).
- [ ] Define data-quality checks and freshness limits per dataset category.
- [ ] Move ADR-0008 / ADR-0009 to Accepted or revise.

## 3. Phase C — Infrastructure

- [ ] Project skeleton (`src/`, `tests/`, `migrations/`), dependency management, pre-commit.
- [ ] Local database (containerised or native per Q2), migrations baseline.
- [ ] Config and secret handling (`.env.example`, no real keys in Git).
- [ ] Logging, error handling, job-run audit table.
- [ ] Test, lint, type-check commands wired and documented in `CLAUDE.md` §7.
- [ ] CI (optional, if a remote is added).

## 4. Phase D — Data ingestion: provider research

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

## 5. Later phases — reminders captured now

- [ ] **P/Q:** build a deliberate look-ahead leak into a test fixture and prove the leakage tests catch it.
- [ ] **P/Q:** record the number of strategy/signal variants tried per backtest (multiple-testing control).
- [ ] **N/O:** regime and similarity models must be evaluated on periods not used to design them.
- [ ] **T:** AI validator must reject any number not present in the snapshot; add adversarial tests (prompted to invent data).
- [ ] **V:** alerts fire on signals/regimes, never on AI text alone.
- [ ] **Z:** API-key storage, rate-limit abuse, prompt injection via ingested text (e.g. social data fed to Claude), dependency audit.
