# PROGRESS.md

Single source of truth for what has been done. Updated at the end of every task.

**Current phase:** 0 — Project foundation → ✅ complete, awaiting user sign-off
**Next phase:** 1 — Architecture (not started; waits for the user to open it)

---

## Phase overview

| Phase | Name | Status |
|---|---|---|
| 0 | Project foundation | ✅ Complete (pending review) |
| 1 | Architecture | ⏳ Not started |
| 2 | Infrastructure | ⏳ Not started |
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

**Git commit:** pending — user to commit as `[P0] renumber phases and record git workflow`.
