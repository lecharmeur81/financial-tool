# CLAUDE.md — Operating Instructions for Claude

This file is read at the start of **every** task in this repository.
It defines how Claude must work on the Capital Flow Intelligence platform.
If a task request conflicts with this file, stop and ask.

Structure: **Part A** project context · **Part B** master engineering rules (R1–R13) · **Part C** workflow.

---

# Part A — Project context

## A1. What this project is

A cryptocurrency **Capital Flow Intelligence** and market research platform: decision-support software that answers

> **"Where is money moving, who is moving it, and how is that behavior changing?"**

It is **not** a guaranteed prediction system and **not** an automatic financial-advice engine.
It surfaces evidence, divergences, and scenarios. The human makes the decision.

## A2. The layer rule (non-negotiable)

```
Observed Data → Calculated Metrics → Statistical Signals → Market Regime → Evidence Synthesis (L4.5, deterministic — see A3) → AI Interpretation → User Decision
```

- Each layer may only read from the layers **to its left**. Never the reverse.
- The **database and the statistical engine are the source of truth.**
- The AI layer (Claude) **reads** structured outputs and **writes only interpretations and hypotheses**.
  It never writes to observed data, metrics, signals, or regimes.
- Every value shown to a user must be traceable back to observed data (lineage).
- See `ARCHITECTURE.md` for the full layer contract.

---

## A3. Decision Intelligence boundaries (ADR-0076 — non-negotiable)

Applies to the deterministic **L4.5 Evidence Synthesis** layer and everything that consumes it. Full
methodology: `METHODOLOGY_DECISION_INTELLIGENCE.md` and the approved external Phase 38.1 specification
(`claude/phase38-1-methodology-spec.md`). **Future implementation must conform to the approved external
methodology specification**; if the two ever disagree, stop and report — do not choose silently.

```
Observed Data → Metrics → Signals → Regime → L4.5 Evidence Synthesis → AI Narration → User
```

- **L4.5 is deterministic.** A pure, DB-free, network-free function of an immutable snapshot plus
  versioned parameters. Same snapshot + methodology version + parameter version → same assessment.
- **Claude narrates but does not decide.** Claude must never determine, change or override a stance,
  confidence, posture, risk level, tally, coverage or conflict status. It may only narrate a finished
  assessment, citing field IDs (R6 still applies).
- **Unavailable ≠ neutral.** Unavailable evidence stays in `U` (and in `D`); it is never counted as
  neutral, bearish or bullish evidence.
- **Missing evidence cannot strengthen conclusions.** It may lower coverage and confidence; removing
  information must never make a result more directional, more confident or more permissive (INV-2, INV-3, INV-11).
- **CAP-U is a ceiling, never a vote.** A cap source that cannot be evaluated imposes a worst-case safety
  ceiling (regime missing → at most Neutral / Wait + WAIT FOR CONFIRMATION; derivatives or anomaly
  missing → at most Cautiously Bullish + AVOID ADDING HIGH-RISK EXPOSURE); the most restrictive applicable
  ceiling wins; it assumes no risk value and creates no bearish evidence. Never treat a missing cap source as "no cap".
- **Regime is contextual**, not an independent directional vote. **Risk is not directional evidence.**
- `not_assessed` is not stale, not fresh and not high risk; stale, partial, `not_assessed` and unavailable are distinct states.
- **No personalized financial advice.** The platform does not know the user's goals, horizon, holdings or
  risk tolerance; output is general decision context only. **No trade execution. No funds management.**
- **No arbitrary external browsing by AI** in this layer or its narration.
- **Traceability is mandatory:** every assessment records snapshot id / `payload_hash`, rule IDs, source
  field IDs, `directional_stance_before_limits` and `final_stance`, and **the methodology and parameter
  versions** (`decision_methodology.v0`, `decision_params.v0`, `decision_templates.v0`) are mandatory on every record.
- Stance, confidence and posture are closed enums; no free-form text, no confidence percentages, no
  predictive-validity claims. Thresholds are design judgment, not validated predictors.
- **Status:** methodology approved (Phase 38.1); **not implemented**. Phase 38.2+ each require a separate approval gate.

---

# Part B — Master engineering rules

These rules apply to every phase. Cite them by number (e.g. "violates R3") in reviews and reports.

## R1. Core philosophy

This is a Capital Flow Intelligence and market research platform. It is not a guaranteed prediction system.

The system helps the user understand:

- where capital is moving
- who appears to be moving it
- how strong the evidence is
- whether different market participants agree or disagree
- what historical periods looked similar
- what risks and contradictions exist

**Never present uncertain inference as fact.** Never turn uncertainty into certainty.
Never treat correlation as causation.

## R2. Evidence hierarchy

Always distinguish these seven categories. **Never collapse them.**

| Category | What it is | Example | Layer |
|---|---|---|---|
| **Observed Data** | A value a source reported, as reported | "Fund X reported +1,200 BTC net creation for 2026-03-02" | L1 |
| **Calculated Metric** | A deterministic calculation over observed data | "Aggregate ETF net flow, 7-day sum" | L2 |
| **Statistical Signal** | A metric evaluated against its own history or another metric | "7-day ETF flow is at the 96th percentile of the past 2 years" | L3 |
| **Regime Classification** | A labelled market state produced by a versioned model, with confidence | "Regime: leveraged expansion (confidence 0.62)" | L4 |
| **Synthesis Classification** | A deterministic, versioned classification (stance, confidence, posture) synthesized from L1–L4 evidence by L4.5 — never produced by AI (A3, ADR-0076); methodology approved, not yet implemented | "Stance: Cautiously Bullish; final posture limited by a missing safety source" | L4.5 |
| **AI Interpretation** | Claude's explanation of L1–L4 evidence | "Institutional demand appears to be absorbing retail selling" | L5 |
| **Hypothesis** | A proposed explanation or expectation that has **not** been tested | "If funding normalises while ETF inflows continue, spot demand may be leading" | L5 / L6 |

Every value, label, and sentence the system shows must be identifiable as exactly one of these.
The UI, the database, and AI output must keep them visually and structurally separate.

## R3. Data integrity

Never:

- fabricate data
- invent missing values
- silently replace missing data
- silently substitute one provider for another
- hide stale data
- hide conflicting sources
- assume wallet ownership without evidence
- assume institutional identity without evidence
- use future information in historical calculations

Also never fabricate sources, API endpoints, field names, or provider capabilities — verify against real
documentation or a real response. Never hide errors. Missing is a first-class state (`quality_status = missing`),
never a zero and never an unflagged interpolation.

Every important dataset preserves (field names in `DATA_DICTIONARY.md` §2):

| Required | Field(s) |
|---|---|
| source | `original_source` (who first published it) |
| timestamp | `event_time` and `available_at` |
| ingestion timestamp | `ingested_at` |
| metric | `metric` |
| asset | `asset` |
| value | `value` |
| unit | `unit` |
| provider | `source_provider` (who we fetched it from) |
| data quality | `quality_status`, `quality_note` |
| confidence where appropriate | `confidence` |

**Point-in-time rule:** every historical computation may only use rows where `available_at <= as_of`, and
only the latest revision available at that time. Revised data keeps both the original and the revision.

## R4. Quantitative research rules

All historical analysis must avoid:

- look-ahead bias
- survivorship bias (e.g. analysing only assets or exchanges that still exist today)
- data leakage
- selection bias
- overfitting
- future revisions leaking into historical signals

Backtests must account for:

- fees
- slippage
- liquidity
- execution assumptions
- turnover
- position sizing
- missing data
- unavailable historical data (a signal cannot be backtested before its inputs existed)

Backtests use walk-forward / out-of-sample evaluation by default, record how many variants were tried,
and report dispersion and drawdowns. **Never use backtest results as proof of future performance.**

## R5. Entity classification

Never automatically assume a wallet or flow belongs to:

- an institution
- an ETF
- an exchange
- a market maker
- a hedge fund
- a government
- a whale

unless there is reliable evidence.

Every classification stores: label, `evidence_class` (`direct` / `attributed` / `inferred`), `confidence`,
the rule or source that produced it, and `valid_from` / `valid_to`. Large ≠ institutional. Small ≠ retail.

## R6. AI rules

**Claude is the analyst, not the database.**

- AI analysis must be grounded in database records — specifically, an immutable snapshot of them.
- Claude may only cite numbers present in that snapshot, each referenced by its field ID.
- If data is missing, Claude must say: **"Insufficient data."**
- If sources disagree, Claude must explicitly report the disagreement (which sources, which values).
- AI interpretation is never presented as observed fact (R2).
- AI output must contain these sections, in this order:
  1. **Summary**
  2. **Evidence**
  3. **Contradicting Evidence**
  4. **Market Regime**
  5. **Key Changes**
  6. **Risks**
  7. **Scenarios**
  8. **Invalidation Conditions**
  9. **Data Quality**

## R7. Software engineering

Before modifying code:

1. Inspect relevant files.
2. Understand existing architecture.
3. Make a plan.
4. Implement the smallest robust solution.
5. Run tests.
6. Run linting/type checks.
7. Check regressions.
8. Update documentation.
9. Update `PROGRESS.md`.
10. Commit to Git.

**Never claim a task is complete if tests are failing.** Never assume code exists without opening it.
Never claim something works without testing it. If something cannot be verified, say so explicitly.

## R8. External APIs

All external data providers must use an **adapter architecture**.

Every provider integration must handle:

- authentication
- rate limits
- retries
- exponential backoff
- timeouts
- malformed responses
- provider outages
- stale data
- duplicate data
- missing data
- schema changes

**Never allow provider-specific code to contaminate the core domain model.** Provider symbols, field names,
and units are converted at the adapter/normaliser boundary and go no further.
Never make the system dependent on a single provider when an adapter can reasonably prevent it.
A fallback to another provider is always recorded, never silent (R3).

## R9. Security

Never hard-code:

- API keys
- passwords
- secrets
- tokens

Use environment variables and secure configuration. Local secrets live in `.env` (git-ignored); only
`.env.example` with placeholder values is committed. Never log secrets.

## R10. Database

- Use migrations for every schema change.
- **Never destroy production data to solve a migration problem.**
- Prefer additive schema changes (add columns/tables; deprecate before removing).

## R11. Testing

Every major feature requires:

- unit tests
- integration tests
- database tests where appropriate
- API tests
- quantitative validation where applicable

Quantitative algorithms require **historical test datasets** (versioned fixtures with known expected outputs).
Point-in-time logic requires explicit leakage tests.

## R12. AI evaluation

AI outputs must eventually be tested for:

- hallucination
- unsupported claims
- incorrect calculations
- missing evidence
- incorrect interpretation
- source conflicts
- confidence calibration

## R13. Development behavior

- Do not over-engineer.
- Do not create unnecessary abstractions.
- Do not implement features that have not been requested.
- Do not use hard-coded values to make tests pass.
- Use standard production-quality approaches.
- Before destructive operations — deleting files, dropping tables, force-pushing Git, rewriting history,
  rotating keys, or changing shared infrastructure — **ask for confirmation**.
- Update `PROGRESS.md` after meaningful work.
- **Do not automatically proceed to the next major phase without the user's instruction.**

---

# Part C — Workflow

## C1. Operating protocol (every task)

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

(R7 is the same process applied to code changes.)

## C2. Reports

**End of every task:**

- What changed
- Files changed
- Tests run
- Test results
- Known limitations
- Git commit (hash + message)

**End of every phase:**

- Completed work
- Files changed
- Tests executed
- Test results
- Known issues
- Next recommended phase

Then stop and wait for the user (R13).

## C3. Development phases

Work proceeds phase by phase. Do not start a phase until the user opens it.
Phases are **numbered** (ADR-0012). Always refer to them as "Phase <number>".

| # | Phase | # | Phase |
|---|---|---|---|
| 0 | Project foundation | 15 | Historical similarity |
| 1 | Master engineering rules | 16 | Backtesting |
| 2 | Architecture | 17 | Quant red-team |
| 3 | Foundation (infrastructure) | 18 | Anomaly engine |
| 4 | Data ingestion engine | 19 | Capital rotation |
| 5 | Market data | 20 | Claude AI Analyst |
| 6 | Institutional capital | 21 | Daily intelligence |
| 7 | Whale intelligence | 22 | Alerts |
| 8 | Derivatives | 23 | Paper trading |
| 9 | Liquidity | 24 | Decision journal |
| 10 | Retail | 25 | Executive dashboard |
| 11 | Macro | 26 | Security + AI + stress testing |
| 12 | Market structure | 27 | Production |
| 13 | Divergence engine | 28 | Real-time intelligence |
| 14 | Regime engine | | |

Phases 0–12 follow the user's guide: 0 project foundation, 1 master engineering rules (Part B), 2 architecture,
3 application foundation (infrastructure), 4 data ingestion engine, 5 market data, 6 institutional capital, 7 whale
intelligence, 8 derivatives, 9 liquidity / stablecoins, 10 retail activity intelligence, 11 macroeconomic data
layer (ADR-0054, ADR-0012 Amendment 3), 12 market structure engine (ADR-0055, ADR-0012 Amendment 4). Phase
numbers from 13 onward remain **provisional** until the user issues each phase.

**Testing rule:** integration tests that write data run only in the separate `<database>_test` database, which the test
suite creates and migrates itself. Never point data-writing tests at the development or production database.

Current phase and status: see `PROGRESS.md`.

## C4. Conventions (initial — confirm before infrastructure work starts)

- **Timezone:** all timestamps stored in UTC, ISO-8601, timezone-aware. Never naive datetimes.
- **Money:** exact decimals for prices, sizes, and flows in storage. Floats allowed only inside statistical computation.
- **Units:** every numeric field has an explicit unit in `DATA_DICTIONARY.md` (USD, BTC, contracts, %, bps, ratio).
- **Naming:** `snake_case` for tables, columns, metric IDs. Metric IDs are stable and versioned (`funding_rate_oi_weighted.v1`).
- **Identifiers:** assets use a canonical internal symbol (e.g. `BTC`), mapped per provider; never assume two providers use the same symbol.
- **Commits:** small, one logical change, imperative subject line, prefixed with the phase number, e.g. `[P3] add provider base interface`. (The very first commit, `d59cb20`, used the old `[A]` label = Phase 0.)
- **Branches:** `main` is always green. Feature work on `phase-<number>/<short-name>`, e.g. `phase-3/provider-interface`.

## C5. Environment notes

- Development machine: Windows (x64). Project root: `E:\FINANCIAL TOOL`.
  The path contains a space — always quote it in shell commands and scripts.
- Line endings are normalised to LF by `.gitattributes`.
- **Git runs on the user's machine.** When Claude works through the remote file bridge, it cannot write
  into `.git` or run Git there. In that case, step 5 (Git status) and step 15 (commit) are done by giving
  the user the exact commands to run and recording the resulting hash in `PROGRESS.md`.
- After copying files to the user's machine, Claude reads them back and compares them before reporting success.
- Tooling commands (Phase 3). Backend from `backend/` with uv; frontend from `frontend/` with pnpm 10.28:

```
# run everything:   docker compose up --build            (needs .env from .env.example)
# backend test:     uv run pytest                        (integration tests need CFI_DATABASE_URL, CFI_REDIS_URL)
# backend lint:     uv run ruff check .   &&   uv run ruff format --check .
# backend types:    uv run mypy                          (strict; src, tests, migrations)
# migrations:       uv run alembic upgrade head          (new: uv run alembic revision -m "...")
# frontend test:    pnpm test
# frontend lint:    pnpm lint   &&   pnpm format:check
# frontend types:   pnpm typecheck                       (next typegen && tsc --noEmit)
# frontend build:   pnpm build
# in Docker:        docker compose exec api pytest | ruff check . | mypy
```

- This Next.js version (16.x) differs from older versions: read `frontend/node_modules/next/dist/docs/`
  before changing frontend code (see `frontend/AGENTS.md`).
- Pytest treats warnings as errors; only explicitly documented third-party warnings are ignored (`backend/pyproject.toml`).

## C6. Documentation map

| File | Purpose |
|---|---|
| `CLAUDE.md` | How Claude must work here (this file) |
| `README.md` | What the project is, for humans |
| `ARCHITECTURE.md` | Layers, components, data flow, contracts |
| `DATA_DICTIONARY.md` | Every entity, field, unit, metric definition |
| `DECISIONS.md` | Architecture Decision Records (why things are the way they are) |
| `METHODOLOGY_DECISION_INTELLIGENCE.md` | Approved methodology for L4.5 Evidence Synthesis (stance, confidence, posture, CAP-U); ADR-0076 |
| `PROGRESS.md` | What is done, what is in progress, per phase |
| `TODO.md` | Upcoming work and open questions |
