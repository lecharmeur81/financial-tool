# DECISIONS.md — Architecture Decision Records

Each decision records **context → decision → consequences**. Decisions are never deleted;
a changed decision gets a new ADR that supersedes the old one.

Status values: `Proposed` (awaiting the user's confirmation) · `Accepted` · `Superseded by ADR-xxxx` · `Rejected`.

| ADR | Title | Status | Date |
|---|---|---|---|
| 0001 | Strict one-way layer architecture | Accepted | 2026-09-23 |
| 0002 | Database and statistical engine are the source of truth; AI never supplies data | Accepted | 2026-09-23 |
| 0003 | Point-in-time (bitemporal) data model | Accepted | 2026-09-23 |
| 0004 | Missing data is an explicit state | Accepted | 2026-09-23 |
| 0005 | Provider abstraction per dataset | Accepted | 2026-09-23 |
| 0006 | Entity classification requires evidence class and confidence | Accepted | 2026-09-23 |
| 0007 | Decision-support, not advice or prediction | Accepted | 2026-09-23 |
| 0008 | Core technology stack | **Proposed** | 2026-09-23 |
| 0009 | Batch first, real-time last | **Proposed** | 2026-09-23 |
| 0010 | UTC timestamps and exact decimals in storage | Accepted | 2026-09-23 |
| 0011 | Git workflow and LF line endings | Accepted | 2026-09-23 |
| 0012 | Numbered phases (0–27) instead of letters | Accepted | 2026-09-23 |

---

## ADR-0001 — Strict one-way layer architecture
**Status:** Accepted (user requirement, Phase 0)

**Context.** Financial dashboards often blur what was observed, what was calculated, and what was opined. That makes errors invisible and interpretations look like facts.

**Decision.** Data flows one way: Observed → Metrics → Signals → Regime → AI Interpretation → User Decision (plus an immutable raw layer beneath Observed). A layer reads only from layers to its left and never writes to them.

**Consequences.** Every derived value is rebuildable and auditable. Slightly more storage and plumbing. Features that "shortcut" layers (e.g. AI writing a metric) are forbidden.

---

## ADR-0002 — Source of truth; AI never supplies data
**Status:** Accepted (user requirement)

**Context.** Language models can produce plausible but false numbers.

**Decision.** The database and statistical engine are the only sources of numbers. Claude receives an immutable snapshot, must cite snapshot field IDs for every number, and its output passes a deterministic validator before storage/display. AI output is always labelled as interpretation.

**Consequences.** Requires a snapshot builder and validator (Phase 19). Claude cannot answer questions whose data is not in the snapshot — it must say the data is missing.

---

## ADR-0003 — Point-in-time (bitemporal) data model
**Status:** Accepted

**Context.** Many sources publish with delay (ETF flows, filings, macro releases) or revise past values; entity labels change over time. Using present knowledge in historical calculations inflates backtests (look-ahead bias).

**Decision.** Every observation stores `event_time`, `available_at`, `ingested_at`, and a `revision` number. All historical computations query with `available_at <= as_of`. Where the source gives no publication time, a documented availability rule sets a conservative `available_at` and flags it as estimated. Entity labels are time-versioned (`valid_from`/`valid_to`).

**Consequences.** More complex queries and storage; needs dedicated leakage tests. In exchange, backtests and historical similarity are honest.

---

## ADR-0004 — Missing data is an explicit state
**Status:** Accepted

**Decision.** Missing values are `NULL` + `quality_status = missing`, never zero. Filling is allowed only when a metric's definition explicitly permits it, and the result is flagged `estimated`. Metrics inherit the worst quality of their inputs. Quality status is shown in the UI and in AI snapshots.

**Consequences.** Some signals will be unavailable on some days; that is correct behaviour.

---

## ADR-0005 — Provider abstraction per dataset
**Status:** Accepted

**Decision.** One adapter per provider behind a common interface; each dataset lists eligible providers with priority. Provider symbols/units never leak past normalisation. No silent blending: a fallback is recorded as a source change. Abstraction is built only where ≥2 realistic providers exist; single-source datasets are wrapped simply and the dependency is documented here.

**Consequences.** Avoids lock-in to one vendor; some duplicated mapping work.

---

## ADR-0006 — Entity classification requires evidence
**Status:** Accepted

**Decision.** Every actor label (institutional, whale, retail, exchange…) records `evidence_class` (`direct` / `attributed` / `inferred`), confidence, rule or source, and validity period. The UI distinguishes direct from inferred evidence.

**Consequences.** "Institutional vs retail" becomes a spectrum of evidence strength rather than a binary claim. Some popular dashboard labels will be shown as low-confidence proxies.

---

## ADR-0007 — Decision-support, not advice or prediction
**Status:** Accepted (user requirement)

**Decision.** The platform presents evidence, divergences, regimes, historical analogues, and scenarios with confidence and invalidation conditions. It does not issue buy/sell instructions or price targets presented as certain. Paper trading is simulation only; no live order execution is in scope.

---

## ADR-0008 — Core technology stack
**Status:** Proposed — to be confirmed at the start of Phase 1/2

**Proposal.** Python 3.12+; PostgreSQL with TimescaleDB; SQLAlchemy + Alembic; Pydantic; Polars/pandas, NumPy, SciPy, statsmodels; FastAPI; a simple scheduler first; Docker Compose (Docker Desktop + WSL2 on Windows); pytest, ruff, mypy, pre-commit. Dashboard technology deferred to Phase 24.

**Alternatives considered.**
- DuckDB/Parquet only: excellent for research, weaker for a multi-user service with concurrent writes. Could still be used for offline research/backtests.
- ClickHouse: very fast analytics, more operational overhead than needed at this stage.
- Node/TypeScript backend: weaker statistics/backtesting ecosystem.

**Open questions.** Whether Docker Desktop is acceptable on the development machine; hosting target for production.

---

## ADR-0009 — Batch first, real-time last
**Status:** Proposed

**Decision.** Build all phases on scheduled batch ingestion (hourly/daily). Streaming (websocket) ingestion is added only in the final "Real-time intelligence" stage, and only for datasets where latency demonstrably matters (liquidations, funding, order book).

**Consequences.** Faster, simpler development; intraday alerting is limited until the real-time stage.

---

## ADR-0010 — UTC timestamps and exact decimals
**Status:** Accepted

**Decision.** All timestamps are timezone-aware UTC. Prices, sizes, and flows are stored as exact decimals; floats are used only inside statistical computations. Every numeric field has an explicit unit; rates state their period.

---

## ADR-0011 — Git workflow and LF line endings
**Status:** Accepted

**Decision.** `main` is always green; feature work on `phase-<number>/<name>` branches; small commits prefixed with the phase number (e.g. `[P3] add provider interface`) — amended by ADR-0012. `.gitattributes` normalises text files to LF so the repo behaves identically on Windows and Linux. Secrets are never committed (`.env` is git-ignored).

---

## ADR-0012 — Numbered phases instead of letters
**Status:** Accepted (user requirement)

**Context.** Phases were originally labelled A–Z. The user prefers numbers.

**Decision.** Phases are numbered from 0: A→0 (Project foundation), B→1 (Architecture) … Z→25 (Security + AI + stress testing), then 26 (Production) and 27 (Real-time intelligence). Commit prefix is `[P<number>]`; branches are `phase-<number>/<name>`.

**Consequences.** The first commit (`d59cb20`) keeps its original `[A]` label; `[A]` = Phase 0. No other history is affected.
