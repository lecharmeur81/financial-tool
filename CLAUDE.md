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

Phases are **numbered** (ADR-0012). Always refer to them as "Phase <number>".

| # | Phase | # | Phase |
|---|---|---|---|
| 0 | Project foundation | 14 | Historical similarity |
| 1 | Architecture | 15 | Backtesting |
| 2 | Infrastructure | 16 | Quant red-team |
| 3 | Data ingestion framework | 17 | Anomaly engine |
| 4 | Market data | 18 | Capital rotation |
| 5 | Institutional data | 19 | Claude AI Analyst |
| 6 | Whale data | 20 | Daily intelligence |
| 7 | Derivatives | 21 | Alerts |
| 8 | Liquidity | 22 | Paper trading |
| 9 | Retail | 23 | Decision journal |
| 10 | Macro | 24 | Executive dashboard |
| 11 | Market structure | 25 | Security + AI + stress testing |
| 12 | Divergence engine | 26 | Production |
| 13 | Regime engine | 27 | Real-time intelligence |

Current phase and status: see `PROGRESS.md`.

## 6. Conventions (initial — confirm in Phase 1/2)

- **Timezone:** all timestamps stored in UTC, ISO-8601, timezone-aware. Never naive datetimes.
- **Money:** exact decimals for prices, sizes, and flows in storage. Floats allowed only inside statistical computation.
- **Units:** every numeric field has an explicit unit in `DATA_DICTIONARY.md` (USD, BTC, contracts, %, bps, ratio).
- **Naming:** `snake_case` for tables, columns, metric IDs. Metric IDs are stable and versioned (`funding_rate_oi_weighted.v1`).
- **Identifiers:** assets use a canonical internal symbol (e.g. `BTC`), mapped per provider; never assume two providers use the same symbol.
- **Commits:** small, one logical change, imperative subject line, prefixed with the phase number, e.g. `[P3] add provider base interface`. (The very first commit, `d59cb20`, used the old `[A]` label = Phase 0.)
- **Branches:** `main` is always green. Feature work on `phase-<number>/<short-name>`, e.g. `phase-3/provider-interface`.

## 7. Environment notes

- Development machine: Windows (x64). Project root: `E:\FINANCIAL TOOL`.
  The path contains a space — always quote it in shell commands and scripts.
- Line endings are normalised to LF by `.gitattributes`.
- **Git runs on the user's machine.** When Claude works through the remote file bridge, it cannot write
  into `.git` or run Git there. In that case, step 5 (Git status) and step 15 (commit) are done by giving
  the user the exact commands to run and recording the resulting hash in `PROGRESS.md`.
- Tooling commands (test, lint, type check, run) will be listed here once chosen in Phase 2:

```
# test:        (to be defined in Phase 2)
# lint:        (to be defined in Phase 2)
# type check:  (to be defined in Phase 2)
# run:         (to be defined in Phase 2)
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
