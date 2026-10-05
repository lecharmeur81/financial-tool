# METHODOLOGY_DECISION_INTELLIGENCE.md

**Status:** Approved methodology (Phase 38.1, documentation only). **No implementation exists.**
**Versions:** `decision_methodology.v0` · `decision_params.v0` · `decision_templates.v0`
**Decision record:** ADR-0076 in `DECISIONS.md`. **Architecture:** `ARCHITECTURE.md` §3.1.
**Authoritative full specification:** the external Phase 38.1 methodology specification
(`claude/phase38-1-methodology-spec.md`, in the project's claude.ai Project). That specification holds
the complete rule tables, the 30 + 10 golden fixtures, the property-test specification, the full
template library and the BTC-first field contract. **Future implementation must conform to it.** If
this repository document and that specification ever disagree, stop and report the disagreement; do
not pick one silently.

> **These v0 thresholds and mappings are design-judgment parameters, not empirically validated
> market predictors.** Nothing here claims predictive validity. A stance classifies the *current
> evidence*; it is not a price forecast. Evaluating predictive validity would be a separate project.

---

## 1. Purpose and scope

The Decision Intelligence foundation turns the platform's already-computed evidence (L1–L4) into one
transparent, auditable, **general and non-personalized** assessment per asset: a stance, a
confidence, a posture, the supporting and contradicting evidence, what is missing, six risk
dimensions, and the reason IDs and source field IDs behind each statement.

It exists to make the platform's own principles executable: unavailable data is visible and never
silently repaired (R3), AI never supplies data (R6), and every value is traceable (A2).

It does **not** predict prices, execute trades, manage funds, or personalize advice (§13).

## 2. Architecture layers

```
L1 Observed → L2 Metrics → L3 Signals → L4 Regime → L4.5 Evidence Synthesis → L5 AI Narration → L6 User
```

(L0 Raw sits before L1 exactly as in `ARCHITECTURE.md` §3.)

- **L4.5 Evidence Synthesis is deterministic.** It is a pure function of one immutable evidence
  snapshot plus versioned parameters: same snapshot + same methodology version + same parameter
  version → the same assessment (INV-10).
- **Claude / AI does not determine the stance**, the confidence, the posture, any risk level, the
  evidence tally, the coverage or the conflict status. L5 may only *narrate* a finished L4.5
  assessment, citing its field IDs, and may not change it.
- L4.5 is DB-free and network-free: it reads only the snapshot payload it is given, calls no AI and
  performs no I/O.
- Each layer reads only from layers to its left (A2). L4.5 reads the L1–L4 bundle; L5 reads L4.5.

## 3. Evidence roles

| Role | Domains | Effect |
|---|---|---|
| **Directional** (vote) | institutional, whale, liquidity, macro, market structure | the only inputs to the tally |
| **Context** (never a vote) | regime, similarity, divergence, rotation, market data | displayed, referenced by reason IDs; **regime is contextual and is not an independent directional vote** |
| **Risk** (never a vote) | derivatives, retail activity, retail speculation, anomaly | feed the six risk dimensions and the caps; **risk domains do not independently create a directional stance** |

Scope: BTC first. For BTC and ETH, `D = 5`; for SOL and XRP the whale domain is not tracked, so `D = 4`.
Not-tracked domains are removed from `D` and are never negative evidence.

## 4. Evidence aggregation

Each directional reading is one of: supportive (`S`), adverse (`A`), neutral (`N`) or unavailable (`U`).
Weights are equal in v0; no weighting is invented.

```text
D = S + A + N + U
n = S + A + N

coverage = n / D
balance  = (S - A) / D
```

- **Unavailable evidence remains in `U`** and therefore stays in `D`.
- **Unavailable evidence is not neutral** (INV-1) and is not evidence against the thesis.
- **Unavailable evidence cannot strengthen the conclusion.** It may reduce coverage and confidence and
  dilutes the balance, but it never increases stance strength (INV-2).
- **Regime is contextual**, not a vote (INV-5). **Risk domains are not directional evidence** (INV-6).
- All comparisons are integer comparisons; `coverage` and `balance` are never computed in floating point.

Rule order (first match decides the raw stance):

| ID | Condition (integer form) | Raw stance |
|---|---|---|
| DS-01 | `2n < D` | Insufficient Evidence (coverage floor) |
| DS-02 | `(S ≥ 2 and A ≥ 2)` or `(Ss ≥ 1 and As ≥ 1)` | Neutral / Wait, "Sources conflict." |
| DS-03 | `5(S−A) ≥ 3D`, `A = 0`, `4n ≥ 3D`, `Ss ≥ 1` | Strongly Bullish |
| DS-09 | `5(A−S) ≥ 3D`, `S = 0`, `4n ≥ 3D`, `As ≥ 1` | Strongly Bearish |
| DS-04 | `5(S−A) ≥ 3D` | Bullish |
| DS-08 | `5(A−S) ≥ 3D` | Bearish |
| DS-05 | `10(S−A) ≥ 3D` | Cautiously Bullish |
| DS-07 | `10(A−S) ≥ 3D` | Cautiously Bearish |
| DS-06 | otherwise | Neutral / Wait |

`Ss` / `As` count supportive / adverse readings that are *strong* (a strong band that is fresh and
complete). Stale or partial readings still vote but are Weak. The cut points are judgment parameters
(`decision_params.v0`). The exact reading-derivation rules (RD-01..RD-09) and the band-to-direction
mapping are in the external specification §4–§5.

## 5. Stance

Exactly eight values; the implementation must not generate free-form stance text:

`Strongly Bullish` · `Bullish` · `Cautiously Bullish` · `Neutral / Wait` · `Cautiously Bearish` ·
`Bearish` · `Strongly Bearish` · `Insufficient Evidence`

A stance classifies the current evidence. It is never a price prediction. "Bullish" / "Bearish"
appear only as these enum labels, never in explanatory sentences.

**Stance strength** (used to decide whether a result became "more directional"): `|level|` where
Strongly = 3, plain = 2, Cautiously = 1, Neutral / Wait = 0; direction never flips; Insufficient
Evidence is outside the scale (only the coverage floor produces it).

## 6. Confidence

Vocabulary: **High · Moderate · Low · Insufficient Evidence.** Confidence describes how well the
available evidence supports the classification. It is not the probability of a price move, forecast
accuracy or expected return. **No confidence percentage is ever shown or stored.**

| ID | Rule |
|---|---|
| CN-01 | Base level from coverage: Insufficient stance → Insufficient Evidence; `100n ≥ 85D` → High; `100n ≥ 65D` → Moderate; else Low |
| CN-02 | Conflict (DS-02) → −1 level |
| CN-03 | A voting reading flagged `stale` → −1 level (once) |
| CN-04 | A voting reading `partial` / `flagged`, or snapshot `has_conflicts` → −1 level (once) |
| CN-05 | Regime unavailable → −1 level |
| CN-06 | Key confirmation layer unavailable → capped at Moderate (non-binding under CN-01 in v0; recorded) |
| CN-07 | Downgrades stop at Low |

Removing fresh, complete evidence never raises confidence (INV-3).

## 7. Caps (observed risk and regime)

Caps apply after DS-01..09, **only to bullish-family raw stances** (Cautiously Bullish, Bullish,
Strongly Bullish), and only ever lower the result.

| ID | Trigger | Effect |
|---|---|---|
| RC-01 | Derivatives band `high stress` | final stance at most Cautiously Bullish |
| RC-02 | Any anomaly entry `extreme_high` / `extreme_low` (including volatility) | at most Cautiously Bullish |
| RC-03 | Regime `euphoria` | at most Cautiously Bullish |
| RC-04 | Regime `distribution` or `capitulation` | Neutral / Wait |

Caps never create or alter a bearish stance and never change confidence.

## 8. CAP-U — missing-cap-source safety ceilings (decisions D-N, D-P)

A cap source has three states: **applies**, **evaluated and does not apply**, and **not evaluable**.
A source that cannot be read is *not* the same as a source that was read and does not apply.

**CAP-U applies to bullish-family raw stances.** When a cap source is not evaluable, CAP-U imposes the
ceiling that the *worst possible value* of that source would impose (a worst-case safety ceiling).

Authoritative fallback table (approved; do not reinterpret):

| Missing / not-evaluable cap source | Maximum final stance | Maximum posture | Directional vote? | Risk value assumed? |
|---|---|---|---|---|
| Regime | Neutral / Wait | WAIT FOR CONFIRMATION | No | No |
| Derivatives safety input | Cautiously Bullish | AVOID ADDING HIGH-RISK EXPOSURE | No | No |
| Anomaly safety input | Cautiously Bullish | AVOID ADDING HIGH-RISK EXPOSURE | No | No |
| Derivatives + anomaly | Cautiously Bullish | AVOID ADDING HIGH-RISK EXPOSURE | No | No |
| Regime + any other cap source | Neutral / Wait | WAIT FOR CONFIRMATION | No | No |
| All three | Neutral / Wait | WAIT FOR CONFIRMATION | No | No |

Implementation rules: CU-01 (regime not evaluable), CU-02 (derivatives safety input not evaluable),
CU-03 (anomaly safety input not evaluable).

Evaluability: regime — regime status `ok`; derivatives — the derivatives `score_status` is `ok`;
anomaly — the anomaly tool is available and the volatility entry is present, or an extreme entry was
observed.

Properties:

- **CAP-U is a safety ceiling, not a vote and not evidence.** Nothing enters `S`, `A`, `N`, `U` or `n`.
- **CAP-U does not assume a risk value.** The affected risk dimension stays `Not assessed`.
- **CAP-U does not create bearish evidence.** A missing source is never described as bearish, neutral,
  bullish, assumed risk or "no cap".
- **Missing cap sources cannot make the result more permissive.**
- **Multiple constraints do not compound numerically; the most restrictive applicable ceiling wins**
  (observed caps and missing-source ceilings alike). Example: raw Strongly Bullish + RC-03 +
  derivatives not evaluable → Cautiously Bullish; + regime not evaluable → Neutral / Wait.
- CAP-U never forces Insufficient Evidence (only the coverage floor does).
- The raw directional calculation is unchanged and **preserved** as `directional_stance_before_limits`.
- Bearish, Neutral and Insufficient raw stances are unaffected.

**Non-negotiable monotonicity (INV-11).** Adding information may leave the stance unchanged or make it
more permissive. Removing information must never make the final stance stronger or the posture more
permissive. Treating a missing cap source as "no cap" was rejected because it violates this.

## 9. Posture

Six postures; no others may be introduced:

`INVESTIGATE FURTHER` · `WAIT FOR CONFIRMATION` · `MONITOR CONSTRUCTIVE CONDITIONS` ·
`MONITOR WITH ELEVATED CAUTION` · `AVOID ADDING HIGH-RISK EXPOSURE` · `REASSESS / REDUCE RISK`

| ID | Condition | Posture |
|---|---|---|
| PO-01 | stance = Insufficient Evidence | INVESTIGATE FURTHER |
| PO-02 | stance = Neutral / Wait | WAIT FOR CONFIRMATION |
| PO-07 | stance ∈ {Strongly Bearish, Bearish} | REASSESS / REDUCE RISK |
| PO-08 | stance = Cautiously Bearish | AVOID ADDING HIGH-RISK EXPOSURE |
| PO-04 | bullish family and (`max_risk = High` or a key confirmation layer unavailable or CU-02 / CU-03 applies) | AVOID ADDING HIGH-RISK EXPOSURE |
| PO-05 | Bullish / Strongly Bullish, confidence High, `max_risk ≤ Moderate`, at most 2 `Not assessed` dimensions, no cap source not evaluable | MONITOR CONSTRUCTIVE CONDITIONS |
| PO-06 | any other bullish-family outcome | MONITOR WITH ELEVATED CAUTION |

**Posture permissiveness ordering (decision D-O, approved), most to least permissive:**

1. `MONITOR CONSTRUCTIVE CONDITIONS`
2. `MONITOR WITH ELEVATED CAUTION`
3. `AVOID ADDING HIGH-RISK EXPOSURE`
4. `WAIT FOR CONFIRMATION`
5. `REASSESS / REDUCE RISK`

`INVESTIGATE FURTHER` is **outside** this ordering: it is a coverage / data-quality state, not a
directional-risk posture, and no risk or cap input can change it. Stance strength and posture
permissiveness are two separate orderings and are never used interchangeably.

No posture implies position sizing or presumes a holding. The label `REASSESS / REDUCE RISK` is used
verbatim; "reduce" still presupposes that the reader holds something, which the fixed disclaimer
(§13) addresses (open wording note, external specification §10.2).

## 10. The six risk dimensions

Market, liquidity, leverage/derivatives, volatility, narrative/speculation, data quality (RK-01..RK-06).
Levels: **Low · Moderate · Elevated · High · Not assessed.** `Not assessed` means the source is
unavailable; it is never `Low`. Risk can cap a stance, constrain posture and create caution; it can
never raise a stance, create a bearish stance or act as a vote. High derivatives stress does not mean
"therefore bearish". Level mappings are judgment parameters in `decision_params.v0`.

## 11. Missing-data states (NOT_ASSESSED)

These states are distinct and are never merged:

| State | Meaning | Effect |
|---|---|---|
| `unavailable` | the source could not be read | `U` (stays in `D`); lowers coverage and confidence; risk dimension `Not assessed`; never neutral |
| `stale` | read, but older than its freshness limit | kept, Weak; −1 confidence; data-quality risk +1; never described as current |
| `partial` | read, but with missing weight or flagged points | kept, Weak; −1 confidence; data-quality risk +1 |
| `not_assessed` | the snapshot carries no source field for the attribute (v0: derivatives freshness) | **not** fresh and **not** stale; no CN-03, no staleness floor, no data-quality increment; disclosed as a limitation |
| `not_tracked` | the domain does not apply to the scope | removed from `D`; never negative evidence |

Equivalences that never hold: stale ≠ unavailable, partial ≠ unavailable, `not_assessed` ≠ stale,
unavailable ≠ neutral.

For derivatives: **`freshness = not_assessed` with an available derivatives safety band does NOT
trigger CU-02.** CU-02 fires only when the derivatives safety input itself is not evaluable.
**`not_assessed` is never turned into assumed high risk.** Derivatives freshness is a known data
limitation for Phase 38.2 (extension point FD-01): if a real freshness field is added, `stale` may
then lower confidence and raise risk through the existing stale rules, with a new parameter version if
any mapping changes.

## 12. Traceability and versioning

Every assessment records the snapshot id and `payload_hash`, scope, the three version identifiers, the
assumed domain-score versions, the fired rule IDs, and `generated_at` (excluded from equality). Every
evidence item carries its source field IDs (INV-9).

**Every CAP-U application must record:**

| Field | Meaning |
|---|---|
| `cap_source` | cap source identifier: `regime` / `derivatives` / `anomaly` |
| `source_field_id` | the snapshot field that could not be read |
| `source_status` | `not_evaluable` |
| `reason_id` | e.g. `CU-01:regime=not_evaluable` |
| `rule_id` | `CU-01` / `CU-02` / `CU-03` |
| `rule_ceiling` / `applied_ceiling` | the rule's own ceiling / the least-permissive ceiling actually applied |
| `raw_directional_stance` | the stance before all limits (`directional_stance_before_limits`) |
| `final_stance`, `final_posture` | the published assessment |
| `methodology_version` | `decision_methodology.v0` |
| `parameter_version` | `decision_params.v0` |

The engine must be able to say: *the directional evidence supported X, but the final assessment was
limited to Y because Z was unavailable.*

Change control: any threshold or mapping change needs a new `parameter_version` (and an ADR amendment
or dated note); template wording changes need a new `template_version`; an output-changing bug fix
needs a new `methodology_version` patch identifier. Old assessments are never rewritten.

**Assessment identity (D-M, resolved).** A persisted assessment is identified by
`(snapshot_id, scope, methodology_version, parameter_version)`. The parameter version is part of the
identity because any threshold or mapping change changes the assessment; the methodology version because
an output-changing fix yields a different assessment from the same snapshot. **`template_version` is not
part of the identity.** Every text field of an assessment is a fixed template ID (stance, confidence and
posture are enum identifiers), so a template wording change does not change the deterministic assessment;
the version is recorded with each assessment as provenance metadata only. Anything that changes stance,
confidence, posture, risks, readings, reason IDs or the template IDs emitted is a methodology or parameter
change, never a template change. Consequently: re-processing the same snapshot under the same versions is
idempotent (insert-or-skip, never an overwrite); a new methodology or parameter version produces a new
record; and the "current" assessment for a scope is the newest one under the running methodology and
parameter versions. The database migration that enforces this key is not created by this document.

## 13. User-facing explanation and safety boundary

Every assessment constrained by CAP-U is explained in three separate parts, using fixed templates:

1. **Directional evidence** — what the directional readings alone supported.
2. **CAP-U constraint** — that the final assessment was limited because a safety source could not be read.
3. **Missing context** — which source was unavailable.

**The explanation must never describe an unavailable source as bearish** (or as neutral, bullish or
risky). Exact platform phrases: "Insufficient data." and "Sources conflict.". Only fixed templates
(`decision_templates.v0`) may produce explanation text; templates are linted (no buy/sell/long/short
instruction, no certainty, no forecast/target, no probability, no digits or percentages, no
"bullish"/"bearish" in prose, no imperative opening).

**Safety boundary.** This system provides **general, non-personalized decision context.** It does not
know the user's goals, investment horizon, holdings or risk tolerance. Therefore it does not provide
personalized financial advice or personalized trade instructions, and it does not execute trades or
manage funds. The fixed disclaimer shown with every posture:

> The platform does not know the user's goals, horizon, holdings, risk tolerance or financial circumstances. Guidance is general and is not personalized financial advice.

## 14. Invariants (verified in the reference harness for the approved methodology)

| # | Invariant |
|---|---|
| INV-1 | Unavailable evidence is never converted into neutral evidence |
| INV-2 | Removing neutral or unavailable evidence cannot increase stance strength |
| INV-3 | For fresh, complete readings, removing evidence cannot increase confidence |
| INV-4 | Increasing a risk dimension's severity never produces a more permissive posture |
| INV-5 | Regime is never an independent directional vote |
| INV-6 | Risk domains never independently create a directional stance |
| INV-7 | Insufficient directional coverage cannot produce a directional stance |
| INV-8 | A conflict meeting the conflict rule cannot silently disappear |
| INV-9 | Every evidence item remains traceable to source field IDs |
| INV-10 | Same snapshot + methodology version + parameter version → same assessment |
| INV-11 | Removing a required safety / cap source cannot raise stance strength or make posture more permissive |

Validation recorded for approval (throwaway reference harness, not the engine): INV-11 exhaustive
cap-source removal sweep — 2,488,320 states, 13,258,080 mutations, 33,180,192 pairs, **0 violations**;
random sweep — 60,000 states, 317,852 mutations, 794,354 pairs, **0 violations**; table
conformance (PT-1), combined observed + missing ceilings (PT-2), independence from
stale / partial / `not_assessed` (PT-3) and CAP-U traceability (PT-4) all pass; regression fixtures
A–J pass; template lint 0 violations (118 templates). The same sweep on the earlier rules that treated a
missing cap source as "no cap" found 1,863,646 + 48,937 violations — which is why that alternative
was rejected.

## 15. Known limitations (carried, not hidden)

- Thresholds, band mappings and level maps are design judgment, not fitted or validated.
- Derivatives freshness is `not_assessed` in v0 (field absent from the snapshot).
- `REASSESS / REDUCE RISK` still presupposes the reader holds something (§9).
- With regime missing, market risk is computed from the remaining inputs and can read Low; CAP-U and the disclosure cover it.
- Live snapshots have not been run through any engine; no engine exists.
- Provider keys and runtime timing are unverified and outside this document's scope.

## 16. What this document does not authorize

No `cfi.decision` package, migration, route, `/decision` page, snapshot-cycle change or Claude wiring
exists or is authorized by this document. Phase 38.2 requires a separate approval gate.
