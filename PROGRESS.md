# PROGRESS.md

Single source of truth for what has been done. Updated at the end of every task.

**Current phase:** 2 — Architecture → ✅ review complete, **awaiting approval** (checklist in `TODO.md`)
**Next phase:** 3 — to be defined by the user (infrastructure not yet placed)

---

## Phase overview

| Phase | Name | Status |
|---|---|---|
| 0 | Project foundation | ✅ Complete |
| 1 | Master engineering rules | ✅ Complete |
| 2 | Architecture | ✅ Review complete — awaiting approval |
| 3 | Data ingestion | ⏳ Not started |
| 4 | Market data | ⏳ Not started |
| 5 | Institutional data | ⏳ Not started |
| 6 | Whale data | ⏳ Not started |
| 7 | Derivatives | ⏳ Not started |
| 8 | Liquidity | ⏳ Not started |
| 9 | Retail | ⏳ Not started |
| 10 | Macro | ⏳ Not started |
| 11 | Market structure | ⏳ Not started |
| 12 | Divergence engine | ⏳ Not started |
| 13 | Regime engine | ⏳ Not started |
| 14 | Historical similarity | ⏳ Not started |
| 15 | Backtesting | ⏳ Not started |
| 16 | Quant red-team | ⏳ Not started |
| 17 | Anomaly engine | ⏳ Not started |
| 18 | Capital rotation | ⏳ Not started |
| 19 | Claude AI Analyst | ⏳ Not started |
| 20 | Daily intelligence | ⏳ Not started |
| 21 | Alerts | ⏳ Not started |
| 22 | Paper trading | ⏳ Not started |
| 23 | Decision journal | ⏳ Not started |
| 24 | Executive dashboard | ⏳ Not started |
| 25 | Security + AI + stress testing | ⏳ Not started |
| 26 | Production | ⏳ Not started |
| 27 | Real-time intelligence | ⏳ Not started |

---

## Log

### 2026-09-23 — Phase 0: Project foundation

**What changed**
- Inspected `E:\FINANCIAL TOOL`: folder was empty (no existing code, no Git repository).
- Created foundation documentation: `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `DATA_DICTIONARY.md`, `DECISIONS.md`, `PROGRESS.md`, `TODO.md`.
- Added `.gitignore` (secrets, Python, data, IDE files) and `.gitattributes` (LF normalisation).
- Git: initialised by the user on the Windows machine (branch `main`). Claude's file bridge cannot
  write into `.git` or run Git on that machine, so the user runs Git commands; Claude supplies them.

**Tests run:** None applicable — no code exists yet. Files were read back from `E:\FINANCIAL TOOL` and compared byte-for-byte with the originals.

**Known limitations**
- Technology stack (ADR-0008) and batch-first approach (ADR-0009) are *proposed*, not accepted.
- No data provider has been selected or verified. The dataset catalogue in `DATA_DICTIONARY.md` is a plan, not a capability statement.
- No shell on the Windows machine was available in this session, so Git could not be run there.

**Git commit:** `d59cb20` — `[A] project foundation documentation` (created by the user, 2026-09-23).
(Its message uses the old letter label `[A]`, which is Phase 0.)

### 2026-09-23 — Phase 0: follow-up

**What changed**
- Phases renumbered from letters to numbers at the user's request: A→0, B→1 … Z→25, Production→26, Real-time intelligence→27 (ADR-0012). All docs updated.
- Commit prefix changed to `[P<number>]`; branch pattern to `phase-<number>/<name>`.
- Recorded commit `d59cb20` and the Git-on-user-machine workflow (`CLAUDE.md` §7).

**Tests run:** None applicable (documentation only). Files read back from `E:\FINANCIAL TOOL` and compared byte-for-byte; no leftover letter-based phase references found by search.

**Git commit:** `7ca0345` — `[P0] renumber phases and record git workflow` (created by the user).

### 2026-09-23 — Phase 1: Master engineering rules

**What changed**
- `CLAUDE.md` restructured into Part A (context), Part B (master engineering rules R1–R13, as issued by the user), Part C (workflow).
  Earlier hard rules merged into R1–R13 without loss; phase-end report format added (C2).
- `ARCHITECTURE.md`: Hypothesis category (§2), adapter failure-mode requirements and idempotent writes (§5),
  `conflicting` quality status (§6), nine-section AI output contract with "Insufficient data." rule (§8),
  backtest cost/constraint list and survivorship handling (§10).
- `DATA_DICTIONARY.md`: new universal fields `metric`, `asset`, `original_source`, `confidence` (§2);
  `conflicting` status (§3); AI output sections (§9).
- `DECISIONS.md`: ADR-0013. `TODO.md`: section reference fixed.

**Tests run:** None applicable (documentation only, no code). Checks: every rule in the user's brief located in `CLAUDE.md`
by search; cross-references between files checked; files read back from `E:\FINANCIAL TOOL` and compared byte-for-byte.

**Known limitations:** Architecture design items (data model, point-in-time contract, adapter interface, metric registry,
snapshot/validator contract, quality checks, ADR-0008/0009) are not started and are unscheduled. Q1–Q10 in `TODO.md` remain open.

**Git commit:** `e4cca71` — `[P1] add master engineering rules` (created by the user).

**Phase 1 closed** (2026-09-23): the user confirmed Phase 1 consists only of the master engineering rules.
Phase 1 renamed from "Architecture" to "Master engineering rules" in `CLAUDE.md` and here; architecture design work moved to
"Unscheduled" in `TODO.md`. This closing update was to be committed by the user as `[P1] close phase 1` (hash not reported; verify with `git log`).

### 2026-09-23 — Phase 2: Architecture (design only, no code)

**What changed**
- `ARCHITECTURE.md` rewritten as v1.0: system containers, layer/DB-schema/role mapping, technology stack, and all 30 review areas
  (§5.1–5.30), entity classification, user layer, repository layout, deployment topology, component-to-phase map, risk register.
- `DECISIONS.md`: 31 new ADRs (0014–0044), each with decision, reason, alternatives, trade-offs, future implications; ADR-0008 superseded
  by ADR-0014; ADR-0010 cross-referenced to ADR-0044; ADR-0012 amended for the phase plan.
- `DATA_DICTIONARY.md` v0.2: series-level vs. row-level fields, new enums (`evidence_category`, `pit_reliability`, `job_status`,
  `circuit_state`, `app_role`), full logical schema for 9 DB schemas (§4), AI snapshot format (§9a).
- `TODO.md`: Architecture Approval Checklist (Parts A–D) replaces the open-questions list; infrastructure tasks listed as unscheduled.
- `CLAUDE.md` §C3: Phase 2 = Architecture; later phase numbers provisional.

**Verification:** Licence facts checked against primary sources on 2026-09-23 (Timescale License terms, Redis licences,
Lightweight Charts licence/attribution). Cross-references (ADR numbers, section numbers) checked by script.
No software tests apply (no code).

**Known issues:** All Phase 2 ADRs are *Proposed* until the user approves the checklist. Storage volumes, retention, and numeric-type
performance are estimates to be benchmarked. Provider capabilities remain unverified.

**Git commit:** pending — user to commit as `[P2] architecture review`.
