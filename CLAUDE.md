# CLAUDE.md — Operating Instructions for Claude

This file is read at the start of **every** task in this repository.
It defines how Claude must work on the Capital Flow Intelligence platform.
If anything in a task request conflicts with this file, stop and ask.

---

## 1. What this project is

A cryptocurrency **Capital Flow Intelligence** platform: decision-support software that answers

> **"Where is money moving, who is moving it, and how is that behavior changing?"**

It is **not** a prediction oracle and **not** an automatic financial-advice engine.
It surfaces evidence, divergences, and scenarios. The human makes the decision.

## 2. The layer rule (non-negotiable)

```
Observed Data → Calculated Metrics → Statistical Signals → Market Regime → AI Interpretation → User Decision
```

- Each layer may only read from the layers **to its left**. Never the reverse.
- The **database and the statistical engine are the source of truth.**
- The AI layer (Claude) **reads** structured outputs and **writes only interpretations**.
  It never writes to observed data, metrics, signals, or regimes.
- Every value shown to a user must be traceable back to observed data (lineage).
- See `ARCHITECTURE.md` for the full layer contract.

## 3. Operating protocol (every task)

1. Read `CLAUDE.md`.
2. Read `PROGRESS.md`.
3. Read `ARCHITECTURE.md` when relevant.
4. Read `DECISIONS.md` when relevant.
5. Inspect the current Git status.
6. Inspect the relevant existing code.
7. Understand before modifying.
8. Create a short implementation plan.
9. Implement **only** the requested scope.
10. Run relevant tests.
11. Run linting and type checks.
12. Review the implementation for regressions.
13. Update documentation (`DATA_DICTIONARY.md` for any new field/metric, `DECISIONS.md` for any architectural choice).
14. Update `PROGRESS.md`.
15. Commit the work.

When a task is complete, report:

- What changed
- Files changed
- Tests run
- Test results
- Known limitations
- Git commit (hash + message)

If something cannot be verified, **say so explicitly**.

## 4. Hard rules

**Truthfulness**
- Never assume code exists without opening it.
- Never claim something works without testing it.
- Never fabricate data. Never fabricate sources. Never fabricate API endpoints, field names, or provider capabilities — verify against real documentation or a real response.
- Never hide errors. Never hide missing data. Missing is a first-class state (`status = missing`), not a zero and not an interpolation.
- Never turn uncertainty into certainty. Every signal and interpretation carries confidence and caveats.

**Time and history**
- Never silently use future information.
- Never use future information in historical calculations.
- Every historical computation must be **point-in-time**: it may only use rows where `available_at <= as_of` (see `DATA_DICTIONARY.md` §2).
- Revised data (e.g. restated ETF flows, re-labelled wallets) must preserve the original value and the revision.
- Never use backtest results as proof of future performance.

**Interpretation**
- Never classify an entity (institution, whale, exchange, fund, retail) without recorded evidence and a confidence level.
- Never treat correlation as causation.
- Never treat an AI interpretation as observed fact. AI output is always labelled as interpretation.
- Claude, inside the product, may only cite numbers that exist in the structured input it was given.

**Engineering**
- Never make the system dependent on a single external data provider when a provider abstraction can reasonably prevent it.
- Prefer simple, maintainable solutions over unnecessary abstraction.
- Before destructive or irreversible actions (dropping tables, deleting data, rewriting Git history, force-push, rotating keys), **ask for confirmation**.
- Never commit secrets. API keys live in `.env` (git-ignored) or a secret manager.

## 5. Development phases

Work proceeds phase by phase. Do not start a phase until the user opens it.

| Phase | Name | Phase | Name |
|---|---|---|---|
| A | Project foundation | N | Regime engine |
| B | Architecture | O | Historical similarity |
| C | Infrastructure | P | Backtesting |
| D | Data ingestion framework | Q | Quant red-team |
| E | Market data | R | Anomaly engine |
| F | Institutional data | S | Capital rotation |
| G | Whale data | T | Claude AI Analyst |
| H | Derivatives | U | Daily intelligence |
| I | Liquidity | V | Alerts |
| J | Retail | W | Paper trading |
| K | Macro | X | Decision journal |
| L | Market structure | Y | Executive dashboard |
| M | Divergence engine | Z | Security + AI + stress testing |

Then: **Production → Real-time intelligence.**

Current phase and status: see `PROGRESS.md`.

## 6. Conventions (initial — confirm in Phase B/C)

- **Timezone:** all timestamps stored in UTC, ISO-8601, timezone-aware. Never naive datetimes.
- **Money:** exact decimals for prices, sizes, and flows in storage. Floats allowed only inside statistical computation.
- **Units:** every numeric field has an explicit unit in `DATA_DICTIONARY.md` (USD, BTC, contracts, %, bps, ratio).
- **Naming:** `snake_case` for tables, columns, metric IDs. Metric IDs are stable and versioned (`funding_rate_oi_weighted.v1`).
- **Identifiers:** assets use a canonical internal symbol (e.g. `BTC`), mapped per provider; never assume two providers use the same symbol.
- **Commits:** small, one logical change, imperative subject line, prefixed with the phase letter, e.g. `[D] add provider base interface`.
- **Branches:** `main` is always green. Feature work on `phase-<letter>/<short-name>`.

## 7. Environment notes

- Development machine: Windows (x64). Project root: `E:\FINANCIAL TOOL`.
  The path contains a space — always quote it in shell commands and scripts.
- Line endings are normalised to LF by `.gitattributes`.
- Tooling commands (test, lint, type check, run) will be listed here once chosen in Phase C:

```
# test:        (to be defined in Phase C)
# lint:        (to be defined in Phase C)
# type check:  (to be defined in Phase C)
# run:         (to be defined in Phase C)
```

## 8. Documentation map

| File | Purpose |
|---|---|
| `CLAUDE.md` | How Claude must work here (this file) |
| `README.md` | What the project is, for humans |
| `ARCHITECTURE.md` | Layers, components, data flow, contracts |
| `DATA_DICTIONARY.md` | Every entity, field, unit, metric definition |
| `DECISIONS.md` | Architecture Decision Records (why things are the way they are) |
| `PROGRESS.md` | What is done, what is in progress, per phase |
| `TODO.md` | Upcoming work and open questions |
