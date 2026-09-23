# Capital Flow Intelligence

**Institutional vs Retail Crypto Capital Flow Intelligence Platform**

> Where is money moving, who is moving it, and how is that behavior changing?

## Status

**Phase 5 — Market data.** Spot OHLCV (1m–1d), last trade and market capitalisation for BTC, ETH, SOL and XRP
from free public sources (Coinbase Exchange, Kraken, Binance, OKX, Bybit, CoinGecko), ingested by background
workers into TimescaleDB and shown on the **Market** page with source, freshness and missing-data warnings.
Observed data only — no signals or recommendations yet. See [`PROGRESS.md`](PROGRESS.md).

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
   - Frontend: http://localhost:3000 (Market shows charts; Settings shows live system status)
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
Third-party attributions: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Disclaimer

This software is for research and decision support. Nothing it produces is financial advice.
Historical and backtested results do not guarantee future performance. Crypto assets are highly volatile.
