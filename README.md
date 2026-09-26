# Capital Flow Intelligence

**Institutional vs Retail Crypto Capital Flow Intelligence Platform**

> Where is money moving, who is moving it, and how is that behavior changing?

## Status

**Phase 8 — Derivatives.** Open interest per venue with 24 h / 7 d change, leverage (open interest ÷ market cap),
funding (7-day annualised, per venue), Deribit futures basis and options (put/call ratios, ATM implied volatility,
skew, DVOL), OKX liquidations with event detection, long/short account ratios as context, and a transparent
**Derivatives Health Score** whose direction-neutral components are all shown — on the **Derivatives** page (BTC, ETH,
SOL, XRP; options and basis BTC, ETH). Leverage and funding are never labelled bullish or bearish.

**Phase 7 — Whale intelligence.** Exchange inflows and outflows (BTC, ETH), the 100 largest addresses with
evidence-based labels (known exchange, institution, fund, market maker, protocol, miner, government — or *unknown large
holder* from size only, never "institution"), large transfers, Bitcoin coin-age and miner activity, a transparent
**Whale Flow Score** and contradiction indicators — on the **Whales** page.

**Phase 6 — Institutional capital.** US spot ETF flows for BTC, ETH, SOL and XRP (total and per fund; daily,
weekly, monthly), listed-company bitcoin purchases and treasury holdings, and a transparent **Institutional Flow
Score** whose every component is shown — on the **Flows** page. Phase 5 added market data (spot OHLCV, last trade,
market cap) on the **Market** page. Descriptive only — no forecasts, signals or recommendations. See
[`PROGRESS.md`](PROGRESS.md).

## What it is

A decision-support platform that aggregates institutional, professional, retail, on-chain,
derivatives, liquidity, and macroeconomic data and turns it into a transparent
**market-regime dashboard**.

It is designed to help a human:

- see divergences between large/institutional capital and retail/speculative positioning;
- detect accumulation and distribution;
- identify excessive leverage;
- detect changes in liquidity;
- compare the present with similar historical periods;
- build evidence-based trade and investment **scenarios** — with the evidence, confidence, and caveats visible.

## What it is not

- **Not a price-prediction oracle.** It does not claim to know what price will do.
- **Not automatic financial advice.** It never places trades or tells a user what to buy.
  Paper trading (Phase 22) is simulation only.
- **Not a black box.** Every number on screen links back to the observed data and the calculation that produced it.

## Core principle: layered evidence

```
Observed Data          what a source reported, when, and when we could have known it
      ↓
Calculated Metrics     deterministic transformations (e.g. OI-weighted funding)
      ↓
Statistical Signals    metrics compared with their own history (z-scores, percentiles, divergences)
      ↓
Market Regime          a classification of the current state, with confidence
      ↓
AI Interpretation      Claude explains the structured evidence in plain language — clearly labelled
      ↓
User Decision          the human decides, and records it in the decision journal
```

The database and the statistical engine are the source of truth.
Claude interprets; it never invents financial data.

## Planned coverage

Institutional capital flows · ETF flows · Whale activity · Exchange flows · Derivatives ·
Open interest · Funding · Liquidations · Options · Stablecoin liquidity ·
Retail activity and sentiment · Macro conditions · Market structure · Capital rotation ·
Historical market regimes · Anomalies · Historical similarity · Backtesting ·
AI-assisted analysis (Claude)

## Repository guide

| File | Read it when you want to know… |
|---|---|
| [`README.md`](README.md) | what this project is |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | how the system is structured |
| [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) | what every field and metric means |
| [`DECISIONS.md`](DECISIONS.md) | why a design choice was made |
| [`PROGRESS.md`](PROGRESS.md) | what has been done |
| [`TODO.md`](TODO.md) | what comes next and what is undecided |
| [`CLAUDE.md`](CLAUDE.md) | the rules Claude follows when working here |

## Getting started (Windows, macOS, or Linux)

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on Windows with the WSL 2 backend) and Git.

1. Open a terminal in the project folder (e.g. `E:\FINANCIAL TOOL`).
2. Create your local settings file and set passwords (letters and digits only):
   ```
   copy .env.example .env        (Windows)     |     cp .env.example .env   (macOS/Linux)
   ```
   Edit `.env` and replace both `replace-with-a-random-value` entries. In PowerShell,
   `[guid]::NewGuid().ToString('N')` prints a suitable random value.
3. Start everything:
   ```
   docker compose up --build
   ```
   First start downloads images and builds; later starts are fast.
4. Open:
   - Frontend: http://localhost:3000 (Market shows charts; Flows shows institutional capital; Whales shows on-chain
     whale data; Settings shows live system status)
   - API docs: http://localhost:8000/api/docs
   - Readiness: http://localhost:8000/health/ready

Stop with `Ctrl+C`, or `docker compose down` (data is kept in Docker volumes;
`docker compose down -v` **deletes** the database volume).

**Run the checks inside Docker**

| Check | Command |
|---|---|
| Backend tests (incl. integration against the real DB and Redis) | `docker compose exec api pytest` |
| Backend lint / format / types | `docker compose exec api ruff check .` · `docker compose exec api ruff format --check .` · `docker compose exec api mypy` |
| Frontend | run locally with pnpm — see `frontend/README.md` |

Service layout: `db` (PostgreSQL 17 + TimescaleDB 2.30.1) · `redis` (Redis 8.8) · `migrate` (runs Alembic once) ·
`api` (FastAPI) · `worker` (Celery: latest market data) · `worker-backfill` (Celery: history) · `beat` (schedule) ·
`frontend` (Next.js). Details: `backend/README.md`, `frontend/README.md`.

Market-data providers are chosen in `.env` (`CFI_MARKET_PROVIDERS`). Several exchanges are blocked by Internet
providers in some countries (e.g. the Philippines); a blocked provider shows up as failed ingestion runs in
`http://localhost:8000/api/v1/ingestion/runs` and as warnings on the Market page — remove it from the list if needed.
Institutional data (Phase 6): ETF flows and bitcoin treasury purchases come from SoSoValue, which needs a **free API
key** — register at https://sosovalue.com/developer/dashboard, wait for approval, and put the key in `.env` as
`CFI_PROVIDER_SOSOVALUE_API_KEY` (never commit it). Without a key those jobs are skipped and the Flows page says so.
After adding the key run `docker compose up -d`: it recreates the services with the new setting, and `beat` queues
every institutional job once when it starts (no need to wait hours for the schedule).
Whale data (Phase 7) needs no key: Coin Metrics Community (licence CC BY-NC 4.0 — non-commercial use) and Blockchair
(free for personal / non-commercial use up to 1,440 requests a day). History loads over the first runs (one chunk per
run); 7-day balance changes of the largest addresses appear after a week of daily snapshots. Address labels are
imported from `backend/src/cfi/whales/seed_labels/*.csv` when the worker starts; more can be added with
`docker compose exec worker python -m cfi.whales.label_store import <file.csv>` (every row needs evidence, source and
confidence; bad rows reject the whole file).
Derivatives data (Phase 8) needs no key: Binance USDⓈ-M futures, OKX and Deribit public market data. Binance and OKX
may be unreachable from some networks (Philippine ISP blocking); failed runs are listed at
`/api/v1/ingestion/runs` and in the page's data-quality table — remove a provider from `CFI_DERIVATIVE_PROVIDERS` if
needed. Open-interest and account-ratio history reaches about a month back; Deribit snapshots and OKX liquidations
(kept about a day by OKX) accumulate from the first run, so liquidation events appear after the first day.
Third-party attributions: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Disclaimer

This software is for research and decision support. Nothing it produces is financial advice.
Historical and backtested results do not guarantee future performance. Crypto assets are highly volatile.
