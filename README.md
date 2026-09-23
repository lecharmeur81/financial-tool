# Capital Flow Intelligence

**Institutional vs Retail Crypto Capital Flow Intelligence Platform**

> Where is money moving, who is moving it, and how is that behavior changing?

## Status

**Phase A — Project foundation.** Documentation and repository setup only.
No application code exists yet. See [`PROGRESS.md`](PROGRESS.md).

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
  Paper trading (Phase W) is simulation only.
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

## Getting started

Not applicable yet. Setup, installation, and run instructions will be added in **Phase C (Infrastructure)**.

## Disclaimer

This software is for research and decision support. Nothing it produces is financial advice.
Historical and backtested results do not guarantee future performance. Crypto assets are highly volatile.
