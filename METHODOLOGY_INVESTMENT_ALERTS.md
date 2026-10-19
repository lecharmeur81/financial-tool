# METHODOLOGY_INVESTMENT_ALERTS.md

**Status:** Draft specification, revision 6, for review (Phase 51 Step 1, documentation only). **No implementation exists.**
**Current status (2026-10-12).** The two sentences above are the historical Step 1 status (2026-10-11) and are kept as written. The specification
has since been implemented in Stages 1 to 6 with persistence disabled (the gate is a hard-coded `False`; no writer exists). Revision 6 was not
re-issued, no design rule was changed by implementation, and Phase 51 is **not** declared complete: see `PROGRESS.md`, "Phase 51 readiness record
(2026-10-12)".
**Amendment (2026-10-19).** Fixture G49's diff clause is amended by owner decision for four named reliability changes (§14). The amendment changes the acceptance criterion; it does not mean G49 has passed (G49 remains OPEN / NOT PASSED). Revision 6 is not re-issued. Record: ADR-0087 in `DECISIONS.md`. *Status update (later 2026-10-19): G49 is closed under the amended criterion; see §14 item 8.*
**Persistence of investment alerts into `usr.alert_event` is DISABLED in Phase 51** (gate: §4.1). Revision 5 applied the final-review corrections M-1, M-2, M-3 and m-1 to m-6.
**Revision 6** records the user's decisions K-1 to K-4 (2026-10-11) and a final contradiction check; it changes no design rule.
**Versions (proposed):** `investment_alert_methodology.v0` · `investment_alert_params.v0` (experimental)
**Decision record:** ADR-0087 in `DECISIONS.md`. **Input:** `investment_decision.v0` (Phase 49, ADR-0086) built from the
cycle's stored snapshot. **Lifecycle reused:** Phase 23 (`alert_event.v1`,
`alert_cooldown.v1`; ADR-0035, ADR-0071). **Isolated from:** Phase 35 (`cfi.realtime`).
**Separate artifact:** `PHASE51_SCHEMA_VERIFICATION_PROCEDURE.md` (proposed read-only procedure; not approved, not executed).

> **This alert methodology is experimental and has not been validated against historical outcomes.** Phase 50
> (historical validation) has not been implemented and remains a required future phase. Nothing here claims
> predictive validity. An alert reports that an asset's Phase 49 decision state changed. It is not a signal, a
> recommendation, a probability, a target or a safety rating.

**Legend.** Every rule carries one tag.
- **[E]** established by existing code or an accepted ADR (source named).
- **[D]** *approved design direction*: the user's decision of 2026-10-11 (A-n). The direction is approved; its details are
  provisional until the specification review is complete.
- **[R]** *provisional rule*: a proposal that existing code does not determine. Not final until the review is complete.
- **[U]** *unresolved*: deliberately not decided. No value is assumed.
- **[X]** a named, additive *extension* of existing code. The direction is [D]; nothing is applied.

---

## 0. Decision status at a glance

| Item | Status | Where |
|---|---|---|
| A-1 additive extension of `AlertService.evaluate`; existing Phase 23 behavior unchanged | **Approved direction** (contract support verified) | §4 |
| A-12 dedicated Phase 51 adapter using the existing snapshot repository and public builders | **Provisionally accepted** (2026-10-11), on condition that Phase 49 behavior is unchanged | §4 |
| A-2 explicit, validated per-candidate detection-method field; existing mappings preserved | **Approved direction** | §11 |
| A-3 no Phase 35 events or AI analysis from investment alerts in Phase 51 | **Approved direction**; proving tests are **required** | §11 |
| A-4 five alertable states at uniform `notable` | **Provisionally retained**; each state verified against the classifier | §6, §6.1 |
| A-5 resolution | **Decided for v0: no investment alert is automatically resolved.** The clearance condition is preserved as a future consideration only, not approved, not implemented | §8 |
| A-6 `insufficient_evidence` never clears; expiry and any new status deferred to Phase 52 | **Approved** | §8 |
| A-7 freshness | **Approved**: upstream evidence-freshness requirement and fail-closed behavior; no age threshold; the evaluation timestamp is never evidence freshness. Any threshold is **unresolved** | §5 |
| A-8 one-hour cooldown as experimental starting point; post-resolution interval deferred | **Approved** (value not data-derived) | §9 |
| A-9 existing fields and version markers; no column or migration | **Approved direction**; sufficiency argued, not proven for future consumers | §10 |
| A-10 read-only schema verification | **Procedure prepared as a separate artifact; not approved, not executed** | §19 |
| A-11 Phase 49 wording discrepancy recorded; Phase 49 untouched | **Approved**; recorded | §3 |
| M-1 exposure policy: Option 3, persistence disabled until Phase 52 and its review | **Decided** (2026-10-11); explicit, testable, default-off gate | §4.1, §18.1 |
| M-2 no automatic resolve or expire | **Accepted as a v0 limitation (K-1)**; not a permanent design requirement; Phase 52 must revisit it | §8.1.1, §18.1 P3 |
| M-3 time limits and isolation | **Decided**: bounded work, signals propagate; residual hard-termination risk **accepted (K-2)**, not eliminated, no guarantee claimed | §11 |
| K-3 evaluate while persistence is disabled | **Accepted**: evaluator and adapter may run, bounded, confined to `EvaluationResult.investment` and the cycle log | §4.1 |
| K-4 hard-coded persistence gate | **Accepted**: constant `False`, no override; enabling needs §18.1, a separately approved and passed §19, and written approval | §4.1, §18.1 |

---

## 1. Purpose and scope

Phase 51 adds backend evaluation of investment alerts: when the Phase 49 decision state of an asset moves into a state
that merits a human's attention, the existing alert infrastructure would record one alert, once, with full provenance (only once persistence is enabled, §4.1). It
covers evaluation, eligibility, the specified persistence design for the existing alert infrastructure, deduplication, cooldown and re-arm,
and explicitly no automatic resolve or expire. **Persistence is disabled in Phase 51 (§4.1):** the design is specified and tested on
fakes, and may be enabled only in Phase 52 after the prerequisites of §18.1.

Out of scope (Phase 52 and later, §18): delivery channels, notification routing, user-facing alert management,
monitoring, any visible "cannot be evaluated" marker, age-based expiry, frontend work. Out of scope for ever in this
layer: prices, targets, probabilities, position sizing, buy/sell language.

## 2. What exists today (verified in code, read-only)

- **[E]** `build_investment_decision` (`cfi/intelligence/investment.py`) is pure and deterministic. Per asset scope (`BTC`,
  `ETH`, `SOL`, `XRP`; `SCOPE_DOMAINS`) it returns one `decision_state`, `decision_reasons`, the Phase 46 `status` and
  `reasons`, `evidence` (supporting, contradicting, other eligible, missing or unusable; each with `freshness_verified`),
  `risk_assessment`, and `risk_findings` and `invalidation` (both `null` when not assessed). It does **not** carry the Phase 46
  `basis` (coverage, agreement, families) or the freshness records.
- **[E]** It raises `InvestmentInputError` for unsupported, malformed or mismatched input, including a Phase 46 `blocked`
  status without a triggered gate. The Phase 49 route answers 503 with no partial result.
- **[E]** The route builds its input chain inline from one stored snapshot row: `build_unified_snapshot(payload,
  snapshot_ref)` → `build_confirmation` → `build_opportunities` → `build_ranking` → `build_risk_view(payload, snapshot_ref)` →
  `build_risk_invalidation(opportunities, ranking, view)` → `build_investment_decision(opportunities, ranking, risk, view)`.
  All are public functions of `cfi.intelligence`. `SnapshotRef` takes the row id, uuid, payload hash and `created_at`.
- **[E]** `AlertService.evaluate(as_of, knowledge_time, now)`: builds a snapshot, inserts it (`insert_snapshot` returns the row
  id and uuid), runs `evaluate_all(snapshot)` (the 11 evaluators), loops `decide` / `insert_alert` / `supersede`, then
  `_auto_resolve_cleared` (visits only the prefixes in `_FLAGGED_STATE_TYPES`: `divergence`, `anomaly`, `capital_rotation`),
  and returns a frozen `EvaluationResult` whose later fields (`decisions`, `snapshot_id`, `snapshot`) are defaulted. The only
  construction of `EvaluationResult` in `src` and `tests` is in `alerts/service.py`; `AlertService` is constructed only by
  `RealtimeIntelligenceService`.
- **[E]** `lifecycle.decide` returns `create`, `skip_unchanged`, `skip_cooldown` or `rearm`, comparing `observed_value` only. The
  existing alert is the latest `active` or `acknowledged` row of the dedup key and its timestamp is that row's `created_at`. A
  rearm inserts a new row and marks the prior one `expired` with `superseded_by`. Statuses: `active`, `acknowledged`,
  `resolved`, `expired`.
- **[E]** `usr.alert_event` CHECKs cover `severity` (`info`, `notable`, `elevated`, `critical`) and `status` only; `alert_type`
  is free text. `sig.intelligence_event` likewise (migration `20261004_0012`). This is read from migration sources and
  `tables.py`; the live schema was **not** inspected (§19).
- **[E]** `usr.alert_event` is read by more than the alerts repository and route (found in the final review; revision 4 was wrong to
  say otherwise): (a) the frontend `AlertsSection` (dashboard) and the `/alerts` page through `GET /api/v1/alerts` (limit 50, newest
  first; type, severity, status, trigger and observed value are shown, with no experimental label and no Phase 49 notice); (b) Phase 28
  `journal/service.py` and Phase 29 `paper/service.py`, each calling `list_alerts(status="active", limit=RELEVANT_ALERTS_LIMIT)`
  (50) to fill `relevant_alert_ids`. The route passes `alert_type`, `source_tool_id`, `component_status` and `evidence_field_ids`
  through as strings. A persisted `investment_state` row would reach all three consumers, none designed for it. This is why persistence
  is gated (§4.1).
- **[E]** A by-id read of a stored snapshot already exists: `DecisionAssessmentRepository.get_snapshot(snapshot_id)` returns the
  row "exactly as the Phase 39 read path sees it (after the JSONB round trip)": id, uuid, payload hash, `created_at`, `as_of`,
  `knowledge_time`, payload. Phase 40 builds decision assessments from this stored row, not from the in-memory snapshot.
- **[E]** The worker task passes `as_of = knowledge_time = now = utc_now()` to `RealtimeIntelligenceService.process_cycle`,
  every 15 minutes and after data arrival, under a Redis cycle lock.

## 3. Findings of this review (recorded; no completed phase is changed)

1. **[E] Event provenance.** `detection_method_for(alert_type)` returns `cfi.alerts.rules.evaluate_{alert_type}` for any string.
   For `investment_state` that is `cfi.alerts.rules.evaluate_investment_state`, a function that does not exist, and it would
   imply the Phase 23 rules engine produced the event. Existing tests pin the strings for existing types.
2. **[E] The event layer consumes `EvaluationResult.decisions` only.** `_record_events` iterates `result.decisions`, and
   `significant_decisions` (the AI trigger input) reads the same tuple. `AI_TRIGGER_SEVERITIES = {elevated, critical}`.
3. **[E] `no_opportunity` is not a clean state.** Phase 46 `_classify` yields `no_candidate` for four reasons:
   `OD-UNCONFIRMED` (Phase 45 `unconfirmed`, which requires the coverage floor to be met), `OD-NO-ASSET-SPECIFIC-CONFIRMER`,
   `OD-ADVERSE-CONFIRMATION` (Phase 45 `confirmed_adverse`) and `OD-UNVERIFIED-SUPPORT`. Phase 49 maps all of them to
   `no_opportunity`.
4. **[E] The Phase 45 coverage floor is 1/2.** An asset can reach `unconfirmed` (hence `OD-UNCONFIRMED`) with up to half of its
   expected evidence missing, stale or unavailable (`coverage.eligible` / `coverage.expected`; absent members appear in
   `excluded_members`). A candidate can therefore stop being a candidate *because evidence became unavailable*.
5. **[E] Phase 49 wording discrepancy (A-11, recorded).**
   - The `contradicted_evidence` text reads "or adverse evidence is confirmed (Phase 46)". The code maps only Phase 46
     `conflicting_evidence` (Phase 45 `mixed`) to it. Confirmed adverse evidence becomes `no_opportunity`.
   - The `no_opportunity` text reads "no candidate and no conflict or gap". That is accurate for `OD-UNCONFIRMED` and
     `OD-NO-ASSET-SPECIFIC-CONFIRMER` only; it does not describe `OD-ADVERSE-CONFIRMATION` or `OD-UNVERIFIED-SUPPORT`.
   - The `withheld_integrity_gate` text names the look-ahead and producer-hash gates; the classifier also returns it for a
     candidate whose finding result is `withheld`.
   - **Consequences for Phase 51.** (a) An asset with confirmed adverse evidence is `no_opportunity`: not alertable and not
     clearing, so a prior alert stays unchanged while adverse evidence is confirmed. (b) No clearance rule may rely on the
     vocabulary text; it must read the Phase 46 reasons. (c) The specification follows the code. (d) Phase 49 code and text are
     not changed here; a corrective note is a separate, optional documentation action.
6. **[E] The cycle's `as_of` equals `now`.** A snapshot age measured from `as_of` is zero on the current path. It cannot measure
   data freshness (§5).
7. **[E] Derivatives freshness is not assessed in v0.** The derivatives tool result carries no freshness node
   (`decision/context.py`), so derivatives evidence is never freshness-verified.
8. **[E] Consumers of stored alerts (M-1).** See §2: the dashboard, the `/alerts` page, journal and paper read `usr.alert_event`; none
   filters by type or shows an experimental label.
9. **[E] Time budget (M-3).** The Celery task `alerts.evaluate` has `time_limit=120` and `soft_time_limit=100`; the Redis cycle lock TTL
   is 150 s. `RealtimeIntelligenceService.process_cycle` runs `AlertService.evaluate` first and `_record_events` after it returns, so
   the 11 types' alerts are persisted before their Phase 35 events are recorded. A hard termination between the two loses those events
   for good (later cycles see `skip_unchanged`). That window exists today; any work added inside `evaluate` lengthens it.

## 4. Integration boundary (A-1, A-12) — the smallest safe extension (adapter provisionally accepted)

**Verified:** the existing contract supports an additive extension without changing Phase 23 behavior: `EvaluationResult`
already takes defaulted additional fields, nothing else constructs it, `AlertService` has one caller, `insert_snapshot` already
returns the row id and uuid, and the repository methods the layer needs already exist.

**[D] Direction.** Extend `AlertService.evaluate` additively. **[R] Details**, listed as one boundary:

1. **New module(s) in the alerts package** hold everything new: the pure evaluator, the `InvestmentAlertCandidate` type, the
   closed vocabulary and parameters (§13), and the adapter. `alerts/universe.py`, `alerts/rules.py`, `alerts/lifecycle.py`,
   `alerts/repository.py`, `AlertCandidate`, `ALERT_TYPE_TOOL_IDS`, `evaluate_all`, `_FLAGGED_STATE_TYPES` and all of
   `cfi.realtime` are **not modified**.
2. **[X] One additive block in `AlertService.evaluate`**, placed after the existing `_auto_resolve_cleared` call and before the
   result is built. It runs only after the 11 existing types are fully processed, so their *outcomes* cannot depend on it. It does
   **not** run for free: it adds bounded synchronous work before `evaluate` returns, hence before `_record_events` and
   `_consider_ai_analysis`, inside the task time limits (§11, M-3). The revision-4 claim that it can never delay the cycle is withdrawn.
3. **[X] One defaulted field on `EvaluationResult`**: `investment: InvestmentCycleResult | None = None`. The existing counters
   (`created`, `rearmed`, `resolved`, `skipped_*`, `candidates_evaluated`) keep counting the 11 types only. Investment counts live
   in `investment`.
4. **[R] Failure isolation, time limits and cancellation (M-3).** The block catches `Exception` (never `BaseException`, never a bare
   `except`) from the investment evaluation, records `investment_internal_error` (logged with the exception) in `investment`, and
   returns normally, so an ordinary investment failure does not change or fail the 11 types' outcomes. A time-limit or cancellation
   signal is **not** an ordinary failure: it is re-raised before the broad catch and is never swallowed or recorded as
   `investment_internal_error` (§11). Work inside the block is bounded (§11). The residual hard-termination risk is stated in §11 and
   is not claimed eliminated.
5. **[R] Dedicated adapter (A-12).** A function in the new module builds the decision from the cycle's snapshot: it receives the stored row
   by id through an **injected `SnapshotReader` protocol** whose single method, `async get_snapshot(snapshot_id)`, has the signature of
   `DecisionAssessmentRepository.get_snapshot` (the JSONB round trip, as Phase 40 does); the real repository is wired in Stage 6, not
   in the adapter module. The adapter module imports no repository, database, `cfi.decision_store` (its package import loads SQLAlchemy),
   service, realtime or API module. `async read_and_build(reader, snapshot_id)` performs exactly one read and delegates to the
   synchronous, pure `build_decision_from_row`, which validates the row, builds a `SnapshotRef` from it, and calls the seven public
   builders in the order of §2. The stored row is used, not the in-memory `Snapshot.payload()`, because
   `tool_results` can carry `datetime` objects that the engine's JSON serializer converts on write (`db/engine.py`, Phase 30 finding F-1), so the two can differ. It contains no logic of its own. A shared builder extracted from
   the Phase 49 route was considered and **not** proposed: it edits Phase 49 code, and behavior preservation cannot be shown
   without running its tests, which this step may not do. Extraction remains a later option, with the Phase 49 tests green and a
   separate approval. To avoid duplicated undocumented logic, the order is documented here and in the route's docstring, and the
   adapter's output must equal the route's chain on the same payload (fixture G38).
6. **[R] Input of the pure evaluator:** the `investment_decision.v0` only. With no automatic resolution in v0 (§8.1) the Phase 46 `basis`
   that the decision does not expose is not needed. The evaluator refuses if the decision's `snapshot` identity (row id, uuid, payload
   hash) differs from the stored row the adapter read.
7. **[D] Phase 49 behavior stays unchanged.** No Phase 49 file (`investment.py`, `investment_universe.py`, the route, their tests) is
   edited. The adapter uses only public `cfi.intelligence` builders and the existing snapshot repository read; it adds no logic of its
   own and no parameter. If any Phase 49 change ever appears necessary, work stops and the user is asked (fixture G38 guards parity).

### 4.1 Persistence gate (M-1) [D] — investment-alert persistence is DISABLED in Phase 51

**Gate wording (normative):**

> Investment-alert persistence is DISABLED in Phase 51. The investment block may evaluate and may record outcomes only in
> `EvaluationResult.investment` and in one structured log record per cycle. It must not insert, supersede, resolve, acknowledge or
> otherwise write any `usr.alert_event` row with `alert_type = 'investment_state'`, and must not read `usr.alert_event` for an
> investment dedup key. The gate is the module constant `INVESTMENT_ALERT_PERSISTENCE_ENABLED`, fixed at `False`. It has no
> environment, configuration, database, request or runtime override. It is read through a single accessor that returns true only for
> the boolean `True`; any other value (absent, `None`, a string, a number) means disabled. Changing the constant is a code change that
> is not permitted until Phase 52 is implemented, the prerequisites of §18.1 are complete and reviewed, and the user has approved the
> change in writing.

1. **[R] One guard.** The only code that can write an investment alert sits behind one check of the accessor; the pure evaluator has no
   path to the repository. The default production wiring (`AlertService` as built by `RealtimeIntelligenceService`) passes nothing and
   therefore gets the constant.
2. **[R] Test seam.** The block function takes a `persistence_enabled` parameter defaulting to the accessor. Only tests inject `True`,
   and only against in-memory fakes, never a database. Lifecycle fixtures (§14) use this seam; no production path does. *(Deviation recorded 2026-10-19: the block-level parameter was not implemented; see the exception note in §14.)*
3. **[R] Disposition while disabled.** An asset in class A (§8.2) is recorded in `investment` with disposition
   `not_persisted_gate_disabled`. `lifecycle.decide` is **not** called and no stored investment alert is read, because none can exist; so
   deduplication, cooldown and re-arm are **not simulated** while the gate is off. They are specified (§8.3, §9), fixture-tested on fakes,
   and become operative only when the gate is enabled. Classes B and C are recorded as in §8.2.
4. **[D] Untouched.** Phase 23 code beyond the block and field of §4, the alerts API, the dashboard and `/alerts` page, journal, paper,
   and `cfi.realtime`. With the gate off, none of their inputs or outputs can differ from the same code without the investment block.
5. **Evaluation while gated (K-3, accepted).** Phase 51 may run the adapter and evaluator while the gate is off, provided the work is bounded
   (§11) and the result stays confined to `EvaluationResult.investment` and the one structured cycle log record. While gated off, no read or
   write of `usr.alert_event` for an investment alert is permitted. The adapter's single read of the stored `ai.snapshot` row (the existing
   snapshot repository) is not an investment-alert read and is allowed. **Two kinds of validation are kept apart:** *evaluator validation*
   (pure decision-to-candidate logic, adapter parity, isolation, gate behavior; achievable in Phase 51 on fakes) and *end-to-end persistence
   validation* (real writes, real schema, real consumers; **not** achievable in Phase 51 and not claimed).
6. **Gate is a hard-coded constant (K-4, accepted).** `INVESTMENT_ALERT_PERSISTENCE_ENABLED` stays `False`, with no runtime or configuration
   override. Enabling it needs all of: the §18.1 prerequisites completed and reviewed; the §19 procedure separately approved and passed; and the
   user's explicit written approval.
7. **Effect on decision D2.** D2 listed persistence under Phase 51. Under M-1 the persistence design stays in Phase 51 as a specification
   and fakes-tested code, but is not active until Phase 52 (trade-off T-1, §20). Schema verification (§19) no longer blocks Phase 51 code
   on fakes; it blocks enabling the gate.

## 5. Evidence freshness (A-7)

**[D]** No snapshot-age threshold is invented. **[U]** Whether the alert layer needs any evidence-age threshold of its own is
unresolved.

1. **[E] Where freshness lives.** Evidence freshness is a property of each source, not of the snapshot. Each source carries a
   freshness record in the stored payload (`tool_results.<tool>.data….freshness`) with `status`, `latest` (the source's own
   newest-observation time), `expected_latest`, `age_seconds`, `rule` and `note` (`decision/context.py::SourceFreshness`). Phase
   45 admits a member as eligible only if its top-level freshness is `fresh`, it has no quality flag, and **every** record has
   status exactly `fresh`; Phase 48 repeats that test (`freshness_verified`).
2. **Timestamp needed to measure freshness: [E/R]** the per-source `freshness.latest`, read against `expected_latest` and the
   record's `status` and `rule`. The snapshot's `as_of`, `knowledge_time` and `created_at` describe when the snapshot was taken,
   not how old the evidence is, and are **not** freshness measures; they must never be used as a substitute for them (the evaluation timestamp is not evidence freshness). The reference time of `age_seconds` was not traced and is
   not relied on here **[U]**.
3. **[R] Freshness requirement.** An alert for state S is admissible only if the evidence that justifies S is freshness-verified:
   for states 2, 6, 7 and 8 every `evidence.supporting` reference has `freshness_verified == true` and the list is non-empty; for
   state 3 every `supporting` and `contradicting` reference does and both lists are non-empty. Upstream guarantees this by
   construction (only eligible members are listed); the check is a fail-closed consistency guard, not a new threshold.
4. **[R] Fail-closed.** If the freshness requirement is not met for an asset, that asset is class B (§8) with reason
   `evidence_freshness_unverified`. If it cannot be established for the cycle, the **whole new investment evaluation is refused**:
   no alert is created, rearmed, resolved or expired, and every existing alert is left exactly as stored. A refusal is recorded
   with its reason; it is never silent and never a clearance. Cycle-level refusals: the stored snapshot row cannot be read;
   `as_of` or `knowledge_time` is missing or timezone-naive; either is later than `now`; any Phase 44 to 49 contract is refused
   (`InvestmentInputError` and its upstream equivalents); the decision's snapshot identity differs from the stored row.
   *Stage 5 definitions (the adapter's three closed reasons, kept separate from the evaluator's four).*
   - `snapshot_not_found`: the injected reader returned no row for the cycle's snapshot id.
   - `snapshot_row_invalid`: a row came back but is unusable, checked before any builder runs: `row_id` is not a plain integer or is not the
     requested id; `uuid` or `payload_hash` is not a clean non-empty string; `created_at`, `as_of` or `knowledge_time` is not a `datetime`;
     or `payload` is not a mapping. Timezone awareness and a time later than `now` remain the evaluator's refusals
     (`snapshot_time_invalid`, `snapshot_time_in_future`).
   - `decision_inputs_refused`: a builder raised exactly one of the six known input-refusal types (`InvalidSnapshotError`,
     `ConfirmationInputError`, `OpportunityInputError`, `RankingInputError`, `RiskInputError`, `InvestmentInputError`). Only the
     exception class name is recorded as detail, never a message or payload content.
   - **Not refusals.** "The stored snapshot row cannot be read" means no row or an unusable row. A reader or database failure, a plain
     `ValueError`, any other programming error, `SoftTimeLimitExceeded`/`TimeLimitExceeded` and `asyncio.CancelledError` are not converted
     into an ordinary refusal: they propagate to the cycle block, which records `investment_internal_error` for ordinary exceptions and
     re-raises the signals (§4 item 4, §11). A refusal never carries a decision.
   - **Producer-hash integrity (existing behavior, unchanged).** A `producer_hash_check` of `mismatch` is **not** an adapter refusal. The
     existing Phase 46 gate (`OD-SNAPSHOT-INTEGRITY`, repeated by Phase 48 and Phase 49 as `DI-GATE-INTEGRITY`) already withholds every
     asset (`assessment.performed` false), which the evaluator records as class B `request_gated`; no alert is created and every stored
     alert stays as stored. The adapter always supplies the stored hash, so the check it produces is `verified` or `mismatch`, never
     `unverified`. This section makes **no claim that real database snapshots verify**; the evidence for that lives in the Phase 38.3
     and Phase 40 integration tests, which Phase 51 does not run.
5. **[U] Threshold.** If an alert-layer evidence-age limit is later wanted, it must be measured on `freshness.latest`, not on
   `as_of`; it is not part of `investment_alert_params.v0`. What would be needed to decide: the distribution of `age_seconds`,
   `rule` and `status` across stored snapshots (a read-only analysis needing its own approval), and a decision about derivatives
   evidence, which has no freshness node (§3.7). Until then the only freshness authority is the upstream `fresh` status, and the
   absence of a threshold is not a refusal condition.
6. **Honest limit.** The upstream `fresh` status uses rules owned by the domain services; this layer neither reproduces nor
   validates them.

## 6. Decision-state mapping (all eight states, checked against the classifier) — provisional

The classifier order is: `invalidation == triggered` → `withheld` finding → detected risk → unresolved → none. A request-wide
gate (`assessment.performed` false) overrides it for every asset. Non-candidates take the Phase 46 status map. "Existing
contract" is [E]; the last columns are [R] (A-4). **These rules are provisional until the specification review is complete.**

| # | State | Existing contract [E] | Alertable | Severity | If an alert already exists and this is the verified state |
|---|---|---|---|---|---|
| 1 | `withheld_integrity_gate` | Request-wide gate, or a candidate with a `withheld` finding. Phase 46 `blocked` without a gate is refused. | No | n/a | Unchanged (class B). |
| 2 | `candidate_invalidation_triggered` | Phase 48 invalidation summary `triggered`; first in the classifier. Not reachable for any input Phase 48 accepts. | Yes | `notable` | Same value: `skip_unchanged`. Other alertable value: cooldown then `rearm`. |
| 3 | `contradicted_evidence` | Phase 46 `conflicting_evidence` only (§3.5). `risk_findings` and `invalidation` null. | Yes | `notable` | As row 2. |
| 4 | `insufficient_evidence` | Phase 46 `insufficient_evidence` (coverage below the floor). Not adverse evidence. | No | n/a | **Never clears.** Unchanged (class C). |
| 5 | `no_opportunity` | Phase 46 `no_candidate`, four reasons (§3.3). | No | n/a | Unchanged. No alert is resolved in v0 (§8.1). |
| 6 | `candidate_risk_findings_detected` | Candidate, at least one detected Phase 48 finding other than the evidence limitations. | Yes | `notable` | As row 2. |
| 7 | `candidate_unresolved` | Candidate, no detected finding, but unverified, unavailable, not-applicable, limitation or non-evaluable checks. | Yes | `notable` | As row 2. |
| 8 | `candidate_no_findings_detected` | Candidate, no finding among the evaluated checks. Not a thesis, not safe. Not reachable on live data. | Yes | `notable` | As row 2. |

Severity rationale [R]. `notable` is Phase 23's uniform default (`alerts/universe.py`); other severities are assigned there only
where an existing closed vocabulary or threshold supports them, and no Phase 49 contract ranks states by significance (the
precedence is restrictiveness). `critical` has no basis in the existing methodology and state 2 is unreachable. `elevated` would
also make an alert eligible for the Phase 35 AI trigger (§3.2) and is not used. `info` has no existing basis for these states.

**[E]** On live data today the states are `insufficient_evidence` or `no_opportunity`; the layer would create no alert.
**[R]** The state id is the alert's `observed_value`. Alerts at states 7 and 8 always carry `DI-CANDIDATE-IS-NOT-A-THESIS` and
`DI-DECLARED-CHECKS-NOT-EVALUATED` in their provenance.

### 6.1 Evidence and eligibility requirements per state

Verified by reading `_classify_candidate`, `build_investment_decision`, Phase 46 `_classify` and Phase 45 `_assess`, **not** by running
tests. Candidate states 2, 6, 7 and 8 share this upstream [E] basis: Phase 45 reached `confirmed_supportive` only when no eligible
adverse family exists, the coverage floor was met and the parameterized minimum of supportive families (with the key layer, when
required) was present; Phase 46 made the asset a `candidate` only if every supporting member is eligible with verified freshness
(otherwise `OD-UNVERIFIED-SUPPORT`) and the parameterized minimum of asset-specific families confirms with the key layer supportive
(otherwise `OD-NO-ASSET-SPECIFIC-CONFIRMER`). "Eligible" means status ok, fresh, no quality flag, every freshness record `fresh`.

| State | Classifier path [E] | Evidence required upstream [E] | Additional check in this layer [R] | Not established |
|---|---|---|---|---|
| 2 `candidate_invalidation_triggered` | Candidate; `invalidation.summary == "triggered"`; tested first, before withheld, detected and unresolved. | The common candidate basis; at least one Phase 48 invalidation condition triggered. Not reachable for any input Phase 48 accepts. | `invalidation` and `risk_assessment.state` present; `supporting` non-empty and freshness-verified. | That the thesis failed or the candidate is unsafe; only that Phase 48 reports a triggered condition. |
| 3 `contradicted_evidence` | Non-candidate; Phase 46 `conflicting_evidence` (Phase 45 `mixed`); no gate. | At least one eligible supportive and one eligible adverse family; reported even with low coverage. | `supporting` and `contradicting` both non-empty and freshness-verified; `risk_assessment.state` present (risk blocks are null). | Confirmed adverse evidence alone is `no_opportunity`, not this state (§3.5). No weighing of the two sides. |
| 6 `candidate_risk_findings_detected` | Candidate; not triggered; no `withheld` finding; at least one finding with result `detected` whose check is not `RI-EVD-03/04/05`. | The common candidate basis; findings across the integrity, market-wide and asset blocks. | `risk_findings` and `invalidation` non-null; `supporting` verified. | That a finding is an invalidation; the findings are not ranked. A detected finding can rest on risk-role evidence whose freshness is unverified (Phase 48 reports it flagged). |
| 7 `candidate_unresolved` | Candidate; not triggered; no `withheld`; no detected risk finding; at least one unresolved item (unverified, unavailable, not applicable, a detected evidence limitation `RI-EVD-03/04/05`, or a `cannot_evaluate` invalidation condition). | The common candidate basis. | As state 6; the `why_not_conclusive` reason ids are carried. | Absence of risk: unresolved means not evaluated, not clean. |
| 8 `candidate_no_findings_detected` | Candidate; none of the above; every evaluated check passed. | The common candidate basis. | As state 6; the notice reason ids are carried. | A confirmed thesis or safety; declared-unavailable checks are never evaluated; not reachable on live data (`RI-DQ-01` always unverified). |
| 1 `withheld_integrity_gate` | Request-wide gate for every asset; or a candidate with a `withheld` finding (after the triggered test). | None assessed. | Not alertable. | Anything about the asset. |
| 4 `insufficient_evidence` | Phase 46 `insufficient_evidence` (Phase 45 coverage below the floor, not `mixed`). | Eligible coverage below the floor. | Not alertable. | Adverse evidence; it is a lack of evidence. |
| 5 `no_opportunity` | Phase 46 `no_candidate`: `OD-UNCONFIRMED`, `OD-NO-ASSET-SPECIFIC-CONFIRMER`, `OD-ADVERSE-CONFIRMATION` or `OD-UNVERIFIED-SUPPORT`. | Varies by reason (§3.3). | Not alertable. | A clean or clear state (§3.5). |

Cross-state notes [E]: the triggered test precedes the `withheld` test, which precedes detected risk, so a triggered invalidation is
reported even when a finding is withheld; the request-wide gate overrides everything. Nothing here ranks the states by significance.

## 7. Eligibility [R]

An asset yields an alert candidate only if **all** hold: (1) the cycle is not refused (§5.4) and the decision was built; (2)
`assessment.performed` is true; (3) `decision_state` is one of the five alertable states; (4) the freshness requirement of §5.3
holds; (5) the fields the state requires are present: `risk_assessment.state`, and for states 2, 6, 7 and 8 non-null
`risk_findings` and `invalidation` (a missing field is `suppressed: incomplete_decision`, never an alert and never a clearance);
(6) the scope is one of the Phase 49 scopes.

## 8. Lifecycle behavior

### 8.1 Phase 51 v0 decision: no automatic resolution [D]

For v0 **no investment alert is automatically resolved or expired by this layer.**
- The investment block never calls `AlertRepository.resolve` and never writes the status `resolved`. The status `expired` appears only
  through the existing Phase 23 rearm, when a new alert supersedes the prior row.
- `no_opportunity`, `insufficient_evidence`, a gate, a refusal, stale or unverified evidence, and any other unevaluable condition leave
  every existing alert exactly as stored.
- The existing user-driven transitions remain [E] and unchanged: acknowledge and resolve through the alerts API. This layer neither
  changes nor automates them.
- **Consequence, stated plainly.** An alert whose state has ended stays `active` or `acknowledged` until a user resolves it or a different
  alertable state replaces it. The row carries no marker. An investment alert is a record that a state **was observed** in snapshot
  `snapshot_id` at `created_at`; it does not assert that the state still holds. Visible markers, expiry and any automatic clearance are
  deferred (A-6; Phase 52 or a future approved version).

### 8.1.1 Known v0 limitation (M-2) — **accepted for v0 by the user (K-1, 2026-10-11)**; not a permanent design requirement; Phase 52 must revisit it

The lifecycle policy is not silently changed: v0 has no automatic resolve and no automatic expire. Once persistence is enabled
(Phase 52), the consequences are:
1. **No new alert for a later episode.** If a state ends and the same state value recurs while the earlier alert is still `active` or
   `acknowledged`, `decide()` gives `skip_unchanged` and no new alert appears. Only a user resolve, or a different alertable state after
   the cooldown, produces a new row.
2. **Stale timestamps and snapshot references.** `skip_unchanged` writes nothing, so a long-lived alert keeps the `created_at` and
   `snapshot_id` of its first observation; the evidence it points to ages without any marker.
3. **Cooldown measured from that stale `created_at`.** After a long-lived alert, a different alertable state re-arms at once, because the
   cooldown elapsed long ago.
4. **No marker** says the state ended or cannot currently be evaluated. A reader must treat an alert as "observed at `created_at`",
   never as a current state (§15).

While the gate is off (§4.1) no investment row exists, so these consequences are dormant. Mitigations (visible markers, age-based expiry,
a new status, clearance, a post-resolution interval) are deferred to Phase 52 (§18.1, P3). The user accepted this limitation for v0 (K-1). Phase 52 must revisit it (§18.1, P3).

**Phase 52 status note (2026-10-19, owner-approved, marker only).** Consequence 4 is now addressed by a read-time marker, `cfi/alerts/lifecycle_marker.py` (ADR-0090), shown on the alerts API as `lifecycle_marker`: `still_holds`, `state_ended`, `cannot_be_evaluated`, `not_evaluated` or `closed`. It is derived, stored nowhere, and never changes a status; "cannot be evaluated" is not "ended" or "invalidated". Consequences 1 to 3 and the other mitigations (age-based expiry, a new status, clearance, a post-resolution interval) remain deferred and unapproved. Persistence stays disabled, so no investment alert exists to carry the marker.

### 8.2 Outcome classes [R]

Per asset, per cycle, exactly one class (a partition: fixture G55). **Every class is recorded** in `investment` with its reason; none
is silent. Classes B and C never touch an existing alert, whether or not one exists.

| Class | Meaning | Effect |
|---|---|---|
| **A. Eligible and alertable** | All of §7 hold and the state is one of the five alertable states. | Gate enabled (fakes, Phase 52): `decide()` gives `create`, `skip_unchanged`, `skip_cooldown` or `rearm`. Gate disabled (Phase 51 production): disposition `not_persisted_gate_disabled`, `decide()` not called (§4.1). |
| **B. Not evaluable or withheld** | A precondition of §7 fails: cycle refusal; request-wide gate (`assessment.performed` false); state 1; unverified or empty required evidence; a missing required field; scope not supported. | **Nothing.** No create, rearm, resolve or expire. |
| **C. Evaluated, not alertable** | §7 (1), (2) and (6) hold, and the state is `insufficient_evidence` or `no_opportunity` (states 4 and 5). | **Nothing.** Counted. |

Neither B nor C is ever a clearance.

### 8.3 Required situations [R]

These rules are specified and fakes-tested; they are operative only when the gate is enabled (§4.1). While it is off, an alertable state is recorded as `not_persisted_gate_disabled` and nothing else happens.

| Situation | Behavior |
|---|---|
| **Verified qualifying state change** | Class A. No alert → `create`. Different alertable state inside the cooldown → `skip_cooldown`. After the cooldown → `rearm` (new row; prior row `expired`, `superseded_by` set). |
| **Verified `no_opportunity`** | Class C. Unchanged, for every Phase 46 reason. No alert is created. Never a resolution. |
| **Missing, stale, gated, refused or otherwise unavailable evidence** | Class B, or a refused cycle (§5.4). Existing alerts untouched. |
| **Existing active alert whose condition cannot currently be evaluated** | Stays as stored: no field changes, `updated_at` untouched. The key is listed in `investment.indeterminate` with the reason. When evaluation resumes, `decide()` compares it with the first verified result. |
| **Repeated qualifying states** | Same value → `skip_unchanged` every cycle (no write). Different value inside the cooldown → `skip_cooldown`, deferred not discarded (the stored value is unchanged, so each later cycle compares again). If the state returns to the stored value before the cooldown ends → `skip_unchanged` and the intermediate state is **never recorded**. A state that leaves and returns to the stored value → `skip_unchanged`. |
| **`insufficient_evidence`** | Class C. Never clears (A-6). |

### 8.4 Future consideration only: a clearance condition — not approved, not implemented, not v0 behavior

Preserved for a possible later version; **nothing in v0 depends on it** and no code path implements it. Adopting it would need a new
methodology and parameter version, resolution of the open points below, and a separate approval. The earlier proposal required all of:
1. state `no_opportunity`, assessment performed, cycle not refused;
2. the asset's Phase 46 `reasons` exactly `["OD-UNCONFIRMED"]` or exactly `["OD-NO-ASSET-SPECIFIC-CONFIRMER"]` (a closed whitelist);
3. `basis.coverage.eligible == basis.coverage.expected` and `excluded_members` empty (no expected evidence missing, stale, partial,
   not assessed or unavailable; needed because the Phase 45 floor is 1/2, §3.4);
4. every `evidence_refs` entry freshness-verified;
5. `basis.adverse_families` empty.
`OD-UNVERIFIED-SUPPORT`, `OD-ADVERSE-CONFIRMATION`, gated and unavailable cases would be excluded outright.

Open points, which are why this is not adopted [U]: (a) whether a complete, fresh, non-adverse `unconfirmed` reading means the alert's own
condition has ended is a methodology judgment, not a measured fact; (b) `coverage.expected` was read from `confirmation.py`, not exercised;
(c) whether `OD-NO-ASSET-SPECIFIC-CONFIRMER` belongs on the whitelist; (d) on current live data condition 3 would not hold, so it could not
be exercised against real data; (e) it should be validated (Phase 50) before it governs a lifecycle.

### 8.5 Extensions and deferrals

- **[X] Cycle-result detail** in `investment` (suppressed, indeterminate and refused outcomes): additive and defaulted. The only
  extension to Phase 23 code beyond the block and field of §4. There is no scoped-clearance step in v0.
- The Phase 23 `_auto_resolve_cleared` pass is not modified and does not visit `investment_state:` keys (§2).
- **Deferred (A-6):** age-based expiry, any new status, any visible marker, any automatic clearance (the consequences of this absence are in §8.1.1).

## 9. Deduplication, cooldown and re-arm

*Operative only when the persistence gate is enabled (§4.1); while it is off nothing is read or compared, and these rules are exercised on fakes only.*

- **[E] Reused unchanged:** `lifecycle.decide`, `AlertRepository.latest_active_for_key`, `insert_alert` and `supersede`. This
  layer supplies only a candidate (`observed_value` = state id). Dedup key `investment_state:{asset}` (follows
  `{alert_type}:{asset}`). Acknowledged alerts are compared like active ones.
- **[E]** The cooldown runs from the `created_at` of the existing active alert, not from the last evaluation.
- **[D/R] Cooldown (A-8):** `investment_alert_params.v0.cooldown_seconds`, starting at 3600, the value of `alert_cooldown.v1`.
  It is an experimental policy constant, **not data-derived**: Step 0 executed no alert-cadence or alert-table query (they were
  only EXPLAINed). It is not fitted (R4) and is versioned, so a change is a new version.
- **[U] Post-resolution minimum interval:** deferred. It matters only after a user resolves an alert through the existing API: a later
  alertable state then finds no active alert and creates at once, as for the flagged-state types. This layer resolves nothing.

## 10. Alert record, provenance and coexistence with the 11 types

| Column | Value | Basis |
|---|---|---|
| `alert_type` | `investment_state` | [R]; free text, no CHECK [E] |
| `severity` | `notable` | [R]; within the CHECK vocabulary [E] |
| `domain` | the asset scope (for example `BTC`) | [E] convention |
| `dedup_key` | `investment_state:{asset}` | [R] |
| `trigger_condition` | fixed template `investment decision state for {asset}` | [R] |
| `observed_value` | the state id | [R] |
| `reference_value` | `null` | [R] |
| `evidence_field_ids` | provenance markers, then decision reason ids, then upstream `field_ids` of the evidence and findings the decision lists | [R] |
| `snapshot_id` | the cycle's snapshot id | [E] |
| `source_tool_id` | `investment_decision.v0` (a contract id, not an analyst tool) | [R] |
| `component_status` | the asset's `risk_assessment.state` copied verbatim | [R]; no new vocabulary |
| `data_quality_state` | the snapshot's `data_quality_state` | [E] |
| `status` | `active` on insert | [E] |

**Coexistence [D/R].** `investment_state` is **not** added to `ALERT_TYPE_TOOL_IDS` (the existing test asserts 11; it has no
analyst tool). It is declared in the new module only. `evaluate_all` and the 11 evaluators are unchanged. The alerts read API
passes stored rows through unchanged; with the gate off no `investment_state` row exists, so the API, the dashboard, journal and paper see
exactly what they see today (§4.1, G46 to G49).

**Provenance without a new column (A-9).** The requirement is that an alert be traceable to: the producing contract and
versions; the snapshot; the source and component; the detection method; and the parameters in force. Existing fields cover
each: `snapshot_id` (joins to `ai.snapshot` for uuid, payload hash, `created_at`, `as_of`, `knowledge_time`; the Phase 44 to 49
chain is pure, so the decision can be re-derived from the stored payload); `source_tool_id` for the contract; `component_status`
for the Phase 48 assessment state; the upstream `field_ids` for the source components (same `tool_id + path` form as the rules);
and markers for the rest. **Markers** are entries of `evidence_field_ids` in a reserved namespace so they cannot be mistaken for
field ids: each begins with `@` (real field ids begin with a tool id), in this fixed order, e.g. `@contract=investment_decision.v0`,
`@states=investment_states.v0`, `@params=investment_params.v0`, `@methodology=investment_alert_methodology.v0`,
`@alert_params=investment_alert_params.v0`, `@cooldown_seconds=<effective>`, `@detection=<method>` and the Phase 44 to 48 contract
and parameter versions from the decision's `source_contracts`. A fixture asserts that no real field id begins with `@`.

**Sufficiency.** No demonstration that the existing contract is insufficient has been found, so no column and no migration is
proposed. The revision-4 argument from "the only readers" was wrong (§2): the dashboard, the `/alerts` page, journal and paper also read these
rows and none was designed for `@`-entries or for an experimental type. Sufficiency is therefore **not argued for those consumers**; while the
gate is off no row exists and the question is dormant, and Phase 52 must settle it (§18.1, P2 and P4). It is not a proof for
future consumers: Phase 52 must treat `@`-entries as metadata, and if a consumer later needs structured provenance, that is the
point at which a column would have to be justified **[U]**. No claim is made that a migration is unnecessary in general: the live
schema is unverified (§19).

## 11. Detection-method provenance and Phase 35 isolation (A-2, A-3)

**Isolation [D]: investment alerts produce no Phase 35 intelligence events and no AI analysis during Phase 51.** Smallest safe
boundary [R], by construction and with no change to Phase 35 code:
1. Investment outcomes are held only in `EvaluationResult.investment`. They are **never** appended to
   `EvaluationResult.decisions`. `RealtimeIntelligenceService._record_events` and `significant_decisions` read only
   `decisions` (§3.2), so no `sig.intelligence_event` row and no AI request can arise from an investment alert.
2. `InvestmentAlertCandidate` is a distinct type, not an `AlertCandidate`, so it cannot be placed in a `CandidateDecision` (whose
   `candidate` field is typed `AlertCandidate`) without a type error.
3. The existing worker counters are unchanged; investment counts are not added to them.
4. Existing types retain current behavior: the 11 evaluators, `detection_method_for`, the event schema and the AI policy are not
   modified. `detection_method_for` keeps its exact outputs for the 11 rule types.

**Detection method [D].** Each `InvestmentAlertCandidate` carries an explicit `detection_method`, required and **validated** in its
constructor against a closed set that contains only the investment evaluator (proposed value, final name fixed at
implementation: `cfi.alerts.investment_alerts.evaluate_investment_alerts`). An unknown or empty value raises. It is persisted as the
`@detection=` marker (§10), because `usr.alert_event` has no such column. It is never derived from the alert type string.

**Optional hardening [U].** A guard in `cfi.realtime` that rejects an alert type it cannot attribute would be defense in depth, but
it edits Phase 35 code; it is not proposed unless the isolation above proves insufficient. Surfacing investment alerts as
intelligence events, or enabling any AI analysis for them, is a later, separately approved decision.

**Required tests (A-3) — acceptance-blocking for Phase 51.** These must exist and pass before Phase 51 can be accepted. They run against the
real `_record_events`, `significant_decisions` and `_consider_ai_analysis` code paths with fakes only for I/O, and they must fail if an
investment outcome is ever placed in `EvaluationResult.decisions`:
1. **Events (G34):** after a cycle that creates and rearms investment alerts, no `sig.intelligence_event` is written for them, `decisions`
   holds none of them, `significant_decisions` returns none of them, and the worker counters are unchanged.
2. **AI analysis (G44):** with an Anthropic credential configured and investment alerts present, no interpretation is queued and no task
   is sent for them (`create_queued_interpretation` and `send_task` are not called on their account).
3. **Existing types unchanged (G35):** for the 11 existing types, the existing `EvaluationResult` fields (`created`, `rearmed`, `resolved`, `skipped_*`, `candidates_evaluated`, `decisions`), the repository rows and the Phase 35 inputs are identical with the investment block present and absent. The new `investment` field is excluded from this comparison by definition.
4. **Exception isolation (G36):** an ordinary exception inside the investment block leaves the 11 types' outcomes unchanged, does not raise, and is recorded as `investment_internal_error`.
5. **Type boundary (G37):** `InvestmentAlertCandidate` cannot be wrapped in `CandidateDecision`; an unknown `detection_method` raises.
6. **Existing mappings (G39):** `detection_method_for` outputs for the 11 types and `len(ALERT_TYPE_TOOL_IDS) == 11` are unchanged.
7. **Time-limit and cancellation propagation (G53, M-3):** such signals raised inside the block escape `evaluate`; they are neither swallowed nor recorded as `investment_internal_error`.
8. **Bounded work (G54, M-3):** the block's reads, loops and calls stay within the bounds below.
9. **Persistence gate and leakage (G45 to G50, M-1):** the gate is off by default and fail-closed, and with it off no investment alert reaches any existing consumer.

### Time budget, bounded work and residual risk (M-3)

- **Corrected claim.** The block runs after the 11 types are persisted, so it cannot change their outcomes. It adds synchronous work before
  `evaluate` returns, therefore before `_record_events` and `_consider_ai_analysis`, inside the task limits (soft 100 s, hard 120 s) and
  the 150 s cycle-lock TTL. The statement that it can never delay the cycle is withdrawn.
- **[R] Bounded work.** The block loops over the four Phase 49 scopes only. With the gate off it performs one stored-row read
  (`get_snapshot`) plus pure CPU builders: no network, no file access, no other database read, no retry, sleep or polling, no loop over
  unbounded data. With the gate enabled (Phase 52) it may add at most one `latest_active_for_key` read per scope and the writes of §9,
  counted in G54. **[U]** A wall-clock budget value is not invented here; the builders' run time on a stored payload is to be measured
  offline at implementation and recorded, and any budget would need your approval.
- **[R] Signals propagate.** The broad catch is `except Exception` only. Before it, the block re-raises the time-limit and cancellation
  signals: Celery's `SoftTimeLimitExceeded` (confirmed in the isolated test environment, Stage 5, to derive from `Exception`, as does `TimeLimitExceeded`; so it must be re-raised before the broad catch),
  `asyncio.CancelledError`, and, for completeness, `KeyboardInterrupt` and `SystemExit` (`BaseException`s that the catch never reaches).
  A signal is never recorded as `investment_internal_error` and never turns into a normal return.
- **Residual risk, not eliminated.** A hard termination (the 120 s task limit, or a process kill) after the 11 types' alerts are persisted
  but before Phase 35 records their events loses those events permanently, because later cycles see `skip_unchanged`. This window exists
  today and is not created by this layer, but the block lengthens it by the block's run time. Nothing in this specification removes it; a
  hard kill cannot be reproduced by an offline fixture (G36 to G54 cover only what can be raised in-process). The user accepted this risk (K-2, 2026-10-11).
- **Implementation duties (K-2).** No wall-clock budget is invented. During implementation: inspect the actual task, time-limit and cancellation
  behavior (the base class of `SoftTimeLimitExceeded` is confirmed as `Exception`; how the cycle lock and task limits interact is still to be inspected); propagate time-limit and
  cancellation signals; bound the work; **measure** evaluation duration and record the measurement; document any remaining risk accurately.
  Hard-termination safety is not guaranteed and must not be claimed.
- **K-2 offline measurement recorded (2026-10-12).** Full-block medians of 7.4 to 8.9 ms and p99 of 12.8 to 17.6 ms on fixture payloads, with the
  seven builders dominating, are recorded in `PROGRESS.md` ("Stage 6 addendum — K-2 offline evaluation-duration benchmark recorded"), including an
  estimated 1.3 to 1.5 ms of instrumentation overhead. They are indicative CPU-time figures, not production latency, and no budget is set; the
  database read and the rest of the cycle are not measured, and P7 still requires a re-measurement before persistence is enabled.

### Stage 6 implementation record (additive; no decided rule changed)

- **Placement.** `cfi.alerts.investment_block.run_investment_cycle` is called once from `AlertService.evaluate`, after `_auto_resolve_cleared` and
  before the return. Its result is `EvaluationResult.investment` (a trailing optional field). Nothing is appended to `decisions`.
- **Statuses.** `evaluated`, `refused`, `internal_error`. With the gate off, `indeterminate` is empty by construction, so no
  `indeterminate_count` is logged. Only class A assets carry the disposition `not_persisted_gate_disabled`; class B and C assets have none.
- **Log event `investment_alert_cycle` (field whitelist).** evaluated: `snapshot_id, status, class_a, class_b, class_c,
  incomplete_decision_assets, integrity_gates, persistence_enabled, duration_ms`. refused: `snapshot_id, status, refusal_reason,
  refusal_detail, persistence_enabled, duration_ms`. internal_error: `snapshot_id, status, error_class, duration_ms` plus the traceback.
  Levels: refusals `snapshot_not_found`, `snapshot_row_invalid`, `snapshot_identity_mismatch`, `decision_contract_invalid`,
  `snapshot_time_invalid`, `snapshot_time_in_future` at error; `decision_inputs_refused` at warning; evaluated at error when the
  `producer_hash` gate fired, at warning when another gate fired or any asset is `incomplete_decision`, otherwise info; internal_error at
  error. Refusal events carry no exception message, payload, identity UUID or hash.
- **Signals.** `SoftTimeLimitExceeded`, `TimeLimitExceeded` (imported by name from `celery.exceptions`), `asyncio.CancelledError` and
  `KeyboardInterrupt` are re-raised before `except Exception`, unrecorded and unlogged. There is no `BaseException` handler and no bare `except`.
- **Residual exposures (documented, not removed).** (1) The logging redactor works by key name and runs before traceback formatting, so
  traceback text of an `internal_error` is not redacted and may contain exception-message text. (2) `persist_assessments_safely`
  (`decision_store/repository.py`) caught `Exception` and could swallow a soft time limit raised inside it; it was not modified in Stage 6 (historical
  record, kept as written). *Update (2026-10-19):* the change in commit `c42b075` now re-raises `SoftTimeLimitExceeded` and `TimeLimitExceeded` before the
  ordinary `except Exception` handler, so this exposure is no longer left unaddressed; ordinary persistence failures remain best-effort (logged, returning `0`).
  It is retained under the separate owner ruling of 2026-10-19 in ADR-0087. Its tests are offline and use fakes; they were not run as part of recording this
  note. No real soft-time-limit interrupt has been demonstrated on Linux or a live stack, and no post-change fixture G38 parity result is recorded.
  (3) The database-backed test (`test_investment_alert_snapshot_path.py`) was written first and not executed; it is skipped unless the
  connection-free gate (`evaluate_gate`: exact confirmation `p51_scratch_test`, host `127.0.0.1` or `localhost`, port `55432`, database
  `p51_scratch`, no runtime URL) passes, and it required separate authorization after the target was verified disposable. It has since been run
  on the Windows host against a disposable container: 7 passed in 3.04 s, exit code 0, none skipped (2026-10-12; details in the `PROGRESS.md`
  entry "Stage 6 addendum — database-backed integration verification passed"). Passing I-01 to I-07 does not satisfy all Phase 51 criteria:
  persistence stays disabled and the A-10 schema verification is not executed.

## 12. Timestamps

`created_at` is the cycle's `now`. `as_of` and `knowledge_time` are the snapshot's, read from the stored row and reached through
`snapshot_id`. The three are never copied over each other or substituted, in the evaluator, the row, tests or any presentation.
They are used only for sanity (§5.4); freshness is measured on `freshness.latest` (§5.2).

## 13. Parameters (`investment_alert_params.v0`, experimental, declared, not fitted, not validated)

| Parameter | Value | Status |
|---|---|---|
| `cooldown_seconds` | 3600 (the `alert_cooldown.v1` value) | starting point, **not data-derived** (A-8) |
| `alertable_states` / `severity_by_state` | the five states of §6 at `notable` | **provisional** (A-4) |
| `INVESTMENT_ALERT_PERSISTENCE_ENABLED` | `False`, constant, no override (§4.1) | **decided** (M-1); changed only per §18.1 |
| automatic resolution | none | **decided for v0**: no automatic resolution; §8.4 is a future consideration only |
| evidence-age threshold | none | **unresolved** (A-7) |
| post-resolution minimum interval | none | **deferred** (A-8) |

A parameter change creates a new version string; stored alerts keep the markers they were created with.

## 14. Golden fixtures (to be built at implementation, not now)

*Status note (2026-10-12): the heading is the Step 1 wording and is kept. Fixtures were built during Stages 1 to 6 in the Phase 51 test files and
numbered on after G67 for the block and service tests (see the Stage 6 implementation record at the end of §11). They validate the evaluator and
the block on fakes only; this note does not re-audit the mapping of every G-number to a test.*

Hand-built inputs (`investment_decision.v0`; for G19 and G38 a stored snapshot payload; and the stored-alert starting point) with outcomes
fixed in advance; none from live data. Fixtures for states 2 and 8 cannot be produced from live data. **Mode:** G01 to G33 exercise the
lifecycle on an in-memory fake repository with the gate injected as enabled (§4.1, item 2); the production gate is off (G45). G34 and G44
run in both modes.

**State coverage (all eight) — G01 to G08.** For each state n of §6 (G0n), four cases: (a) no prior alert; (b) a prior alert with the same state id;
(c) a prior alert with a different alertable state id; (d) a prior `acknowledged` alert with a different state id. Expected, alertable states
2, 3, 6, 7, 8: (a) `create` at `notable` with `observed_value` = the state id; (b) `skip_unchanged`; (c) `skip_cooldown` inside the
cooldown, `rearm` after it; (d) as (c), acknowledgement not reset. States 1, 4, 5: (a) nothing created, counted as not alertable or
suppressed; (b) to (d) the prior alert unchanged (no resolve, no rearm, no expire). State 1 is run through both code paths (request-wide
gate; candidate with a `withheld` finding). Each alertable state is built from the upstream basis of §6.1 and fails closed when a required
field of §6.1 is removed.

**Lifecycle transitions and repeats**
- G09 Three consecutive cycles with an unchanged state: `skip_unchanged` each time, no write.
- G10 Alertable A → alertable B after the cooldown: `rearm`; A `expired`, `superseded_by` = B's id; one active row remains.
- G11 Acknowledged alert, unchanged: `skip_unchanged`; changed after the cooldown: `rearm`; acknowledgement not reset.
- G12 Two assets in different states: independent keys and outcomes.

**Cooldown and re-arm**
- G13 Different state inside the cooldown: `skip_cooldown`, no row; the next cycle after the cooldown: `rearm`.
- G14 Different state inside the cooldown, then the stored value again before it ends: `skip_unchanged`; the intermediate state is never stored.
- G15 Elapsed exactly equal to `cooldown_seconds` follows `decide` (`rearm`); one second less: `skip_cooldown`.
- G16 The cooldown is measured from the prior alert's `created_at`, not from the last evaluation.

**No automatic resolution (A-5, A-6)**
- G17 For each of the eight states as the current verified state, with a prior `active` or `acknowledged` alert: a spy on the repository shows the investment block never calls `resolve`; no row gets status `resolved`; `expired` appears only through rearm.
- G18 `no_opportunity` with a prior alert, for each Phase 46 reason (`OD-UNCONFIRMED`, `OD-NO-ASSET-SPECIFIC-CONFIRMER`, `OD-ADVERSE-CONFIRMATION`, `OD-UNVERIFIED-SUPPORT`, an unknown id): the alert is unchanged.
- G19 Adapter/cycle level: a stored payload that yields `no_opportunity` with `OD-UNCONFIRMED`, complete coverage, no excluded member, verified evidence and no adverse family (every condition of §8.4), with a prior alert: unchanged. The evaluator's input is the decision only (§4 item 6), so the Phase 46 basis is read nowhere; this pins that the future condition is not active.
- G20 The same for a prior `acknowledged` alert.
- G21 `insufficient_evidence` with a prior alert: unchanged; the original state returns: `skip_unchanged`.
- G22 Request-wide gate, and a candidate-level `withheld` finding, with a prior alert: unchanged.
- G23 Alert A, then `no_opportunity` for many cycles, then A again: `skip_unchanged` throughout, one row, status still `active` meanwhile.
- G24 Alert A, then `no_opportunity`, then alertable B after the cooldown (measured from A's `created_at`): `rearm`, A `expired` with `superseded_by`.
- G25 A prior alert that a user resolved through the existing API, then an alertable state: `create` at once.
- G26 The Phase 23 `_auto_resolve_cleared` pass never touches `investment_state:` keys, and the investment block never touches the keys of the 11 types.

**Freshness refusal and unavailable evidence (A-7)**
- G27 `evidence.supporting` entry with `freshness_verified == false` for a candidate state: asset class B `evidence_freshness_unverified`; no alert, no change.
- G28 Empty `supporting` (or empty `contradicting` for state 3): class B.
- G29 `as_of` or `knowledge_time` missing, timezone-naive, or later than `now`: whole evaluation refused; existing alerts byte-identical.
- G30 Stored snapshot row not readable; the decision's snapshot identity differs from the stored row; any upstream refusal (including Phase 46 `blocked` without a gate): refused, nothing changes.
- G31 `null` `risk_findings` or `invalidation` on a candidate state: `suppressed: incomplete_decision`.
- G32 Resolved (Stage 2 correction). The original G32, "derivatives-only supporting evidence", is NOT CONSTRUCTIBLE under the current Phase 45 to 49 contracts: derivatives is `Role.RISK`, has `independent_vote=False`, is in no evidence family and has freshness `NOT_ASSESSED`, so it can never be Phase 45 eligible or Phase 49 `supporting`; it is not tested. The constructible risk-role variant IS pinned (`test_risk_finding_with_unverified_freshness_stays_admissible_and_adds_no_marker`): state 6 with a risk finding whose `freshness_verified` is false stays admissible, because §5.3 guards `supporting` only. The unverified risk-finding freshness flag is NOT carried into the candidate: the candidate holds only the finding's field ids, and no new marker is added. The decision can be re-derived through the snapshot reference (`snapshot_id`). No new provenance semantics are introduced.
- G33 A snapshot older than any number of seconds, with `fresh` upstream status, is not refused by age: no alert-layer age threshold exists (fixture pins the absence).

**Phase 35 and AI isolation (A-3)**
- G34 **(required, §11; both modes)** After a cycle that creates and rearms investment alerts, `EvaluationResult.decisions` contains none of them; `_record_events` writes no event for them; `significant_decisions` returns none of them; the worker counters are unchanged.
- G35 **(required, §11)** For the 11 existing types, the existing `EvaluationResult` fields, the repository rows and the Phase 35 inputs are identical with the investment block present and absent. The new `investment` field is excluded from the comparison.
- G36 **(required, §11)** Exception isolation. An ordinary exception raised (a) in the adapter, (b) in the pure evaluator, (c) after a partial result, leaves the 11 types' outcomes and rows unchanged, does not raise out of `evaluate`, and is recorded as `investment_internal_error`; the 11 types' alerts were persisted before the block ran.
- G37 **(required, §11)** `InvestmentAlertCandidate` cannot be wrapped in `CandidateDecision` (type check); an unknown `detection_method` raises.
- G44 **(required, §11; both modes)** AI isolation: with an Anthropic credential configured and investment alerts present at every severity in use, no interpretation is queued and no task is sent on their account, and the AI minimum-interval state is unchanged.

**Persistence gate and consumer leakage (M-1) — required, acceptance-blocking**
- G45 **(required)** Gate default and fail-closed: `INVESTMENT_ALERT_PERSISTENCE_ENABLED` is `False`; the accessor returns true only for the boolean `True` (`None`, `"true"`, `1`, absent: disabled); no environment, configuration or request value changes it; the default `AlertService` wiring used by `RealtimeIntelligenceService` yields disabled.
- G46 **(required)** With the gate off and every alertable state present: a repository spy records zero `insert_alert`, `supersede`, `resolve` and acknowledge calls and zero `usr.alert_event` reads for an investment key (the single `ai.snapshot` read of G54 is allowed); the store holds no row with `alert_type = 'investment_state'`.
- G47 **(required)** With the gate off, `list_alerts` for each existing filter combination (including `status="active", limit=50`) and the `GET /api/v1/alerts` response body are identical with the investment block present and absent.
- G48 **(required)** With the gate off, journal and paper `relevant_alert_ids` are identical with the block present and absent.
- G49 **(required)** With the gate off, the dashboard and `/alerts` data contain no investment item; an acceptance diff check shows none of the Phase 23, route, frontend, journal, paper or realtime files is modified beyond the §4 block and field.
- G50 **(required)** Disposition: with the gate off, class A assets carry `not_persisted_gate_disabled`, `lifecycle.decide` is never called, and no cooldown or dedup state is created or read.

**Amendment to G49 (2026-10-19), owner decision.** *This amendment changes the acceptance criterion. It does not establish that G49 has passed, and G49 remains OPEN / NOT PASSED.* The G49 text above is kept as written. Revision 6 is not re-issued (as for the 2026-10-12 status note).

1. **Diff clause as amended.** The acceptance diff check (baseline `5193c38`) must show that none of the Phase 23, route, frontend, journal, paper or realtime files is modified beyond (a) the §4 block, field and injected reader (§4 items 2, 3 and 5) and (b) the four retained reliability changes named in item 2, limited to the files and regions named there. The retained changes are an owner-authorized extension of the §4 boundary for those named regions only; the text of §4 and §4.1 is unchanged. Any other modification of any such file fails the check, including any further change to a listed file outside its named regions.
2. **The four retained changes** (reference state: commit `9962980`; blob ids in parentheses):
   - *Finding 1, stage-timing instrumentation.* `backend/src/cfi/alerts/service.py` (`396e6a0d75c9`): the five `timed_stage` wrappers around the existing stages `build_snapshot`, `persist_snapshot`, `evaluate_rules`, `process_candidates` and `auto_resolve`, the `stage["candidates"]` assignment, the `timed_stage` import, and the mechanical re-indentation and line wrapping those wrappers entail. The new module `backend/src/cfi/alerts/stage_timing.py` (`a6ec0a9fd6f5`) is a new module in the alerts package (§4 item 1). **Not permitted:** any wrapper around the Stage 6 investment block, which reports its own duration in its `investment_alert_cycle` event.
   - *Finding 3, dedicated queue for the manual trigger.* `backend/src/cfi/api/routes/alerts.py` (`d326f3cc8c14`): line 86 only, the queue argument of the `alerts.evaluate` publication, changed from `"ingest"` to `"alerts"`.
   - *Finding 4, realtime expiry, lock ownership and cycle timing.* `backend/src/cfi/realtime/service.py` (`fce8618dec53`): (a) the data-arrival trigger `trigger_cycle_if_due` publishing to the `alerts` queue with the `DATA_ARRIVAL_ALERT_EXPIRES_SECONDS` expiry; (b) the cycle-lock owner token with compare-and-delete release (`_RELEASE_IF_OWNER_LUA`, `_acquire_lock`, `_release_lock` and their use in `process_cycle`); (c) the `realtime_cycle_timing` logging in `process_cycle` and the `status_for` import it uses.
   - *Finding 5, cancellation and draining.* `backend/src/cfi/worker/app.py` (`8302eeb6c8dd`): in `alerts_evaluate_task` only, `rt.run(go())` replaced by `rt.run_guarded(go())`, with its two comment lines.

   Associated changes outside the files G49 names, recorded for traceability and needing no amendment under the assessment convention agreed for G49 (the "Phase 23 files" are those changed by commit `096f789`): `backend/src/cfi/worker/client.py` (the optional `expires` argument), `backend/src/cfi/worker/runtime.py` (`run_guarded` and its drain handling), the `worker-alerts` service in `compose.yaml`, and the tests for these changes.
3. **Not covered.** Any other change in the named categories; `backend/src/cfi/decision_store/repository.py`, whose time-limit propagation safeguard is retained under a separate owner ruling dated 2026-10-19 in ADR-0087 (a §4 item 7 ruling); that ruling is not part of the four-change amendment and does not waive, expand or otherwise alter any G49 acceptance criterion; the point-in-time performance change (the separate scope note in ADR-0087); and documentation files (outside the violation count by the earlier ruling). This is not a blanket exception.
4. **Evidence and testing requirements preserved.** Each retained change keeps its tests: `tests/unit/test_alert_evaluate_stage_timing.py`, `tests/unit/test_alerts_queue_routing.py`, `tests/unit/test_alert_data_arrival_expiry.py`, `tests/unit/test_realtime_cycle_lock.py`, `tests/unit/test_worker_runtime_cancellation.py` and the opt-in `tests/integration/test_alert_reliability_isolated.py`. Nothing here claims the safeguards verified beyond the recorded evidence: nine POSIX interval-timer tests skip on Windows, and cancel-and-drain and lock ownership under a real soft-time-limit interrupt have not been executed on Linux or a live stack. Truthful status reporting continues; any later change to a listed region needs its own review.
5. **Runtime clause: unchanged and separate.** With the gate off, the dashboard and `/alerts` data contain no investment item. Evidence so far: the `/alerts` API listing on real PostgreSQL and the real HTTP stack (`backend/tests/integration/test_alert_listing_gate_off_http.py`, user-run, 1 passed in 7.39 s, 2026-10-19) and the in-memory G47 and G48 tests. No test or inspection yet shows the live dashboard or frontend rendering after a gate-off cycle (hand-fed component tests exist; see item 7); that evidence remains required.
6. **Closing G49 under the amended criterion** needs both a recorded diff check against the reference state of item 2 and the runtime-clause evidence of item 5. Persistence stays disabled, A-10 stays proposed, not approved and not executed, Phase 51 is not complete, Phase 52 is not authorized, and Phase 50 remains a separate outstanding milestone.
7. **Frontend regression tests (ruling of 2026-10-19, ADR-0087).** The three existing `AlertsSection` tests and their associated fixtures in `frontend/src/components/dashboard/dashboard-components.test.tsx`, as reviewed in the 2026-10-19 audit, are ruled test-only additions outside the restricted production-code categories of the diff clause. The ruling covers only those tests and fixtures; it authorizes no other change to the file, and any subsequent modification needs a fresh scope check. Any other file in the named categories remains subject to the check. The tests do not show that the persistence gate is off, are not live-dashboard evidence, and waive neither the recorded diff check nor the runtime and reliability evidence above. G49 remains OPEN / NOT PASSED.
8. **Status update (later 2026-10-19).** The two closing conditions of item 6 now have records: the user accepted the diff audit recorded in `PROGRESS.md` against reference `9962980` as the required diff check (scope: the named source files and categories, not the whole working tree), and live runtime observations were reported (dashboard and `GET /api/v1/alerts/?limit=200` showed no `investment_state` item; user-reported, point-in-time, running build not recorded). G49 is therefore **closed under the amended criterion**; it was not satisfied under the original literal wording, which is unchanged. The "OPEN / NOT PASSED" statements in items above and in the header are accurate as of their writing and are superseded by this item. This does not complete Phase 51, does not validate signal quality, and does not change persistence (disabled), A-10 (proposed, not approved, not executed), P1 to P8 (open), Phase 52 (not authorized) or Phase 50 (outstanding). Record: `PROGRESS.md` and ADR-0087.

**Exception to G34, G44 and G54 (2026-10-19), owner decision.** *This is an exception to acceptance-blocking criteria. It is not a claim that the clauses passed.* The G34, G44 and G54 text above is kept as written. The owner approved deferring to Phase 52, alongside P8 (§18.1), these clauses only: the **enabled-mode** clause of G34 and of G44 ("both modes", with the gate injected as enabled per the §14 Mode paragraph and §4.1 item 2) and the **gate-enabled** clause of G54 (at most four `latest_active_for_key` reads plus the §9 writes; §11 already places the gate-enabled behavior in Phase 52). Status of those clauses: **NOT PASSED - DEFERRED BY OWNER EXCEPTION.** The gate-off clauses are unchanged and rest on the tests already recorded: G34 `test_s02_g34_the_real_event_path_writes_nothing_for_investment_alerts`, G44 `test_s03_g44_no_ai_analysis_is_queued_for_investment_alerts` (with its control), G54 `test_b13_work_is_bounded_one_read_and_two_clock_calls`, `test_s07_...` and `test_s10_g54_...`.
*Why the clauses cannot be exercised now.* The Stage 4 persistence writer was deliberately not built. The block-level `persistence_enabled` parameter specified by §4.1 item 2 was **not implemented**: `run_investment_cycle` takes no gate parameter and calls the planner with fixed arguments (`test_b12_...` asserts this), and `InvestmentCycleResult` rejects any plan with persistence enabled. The only seam is the planner-level `persistence=` argument of `plan_investment_lifecycle`, which the lifecycle fixtures use. It cannot satisfy G34 or G44, whose assertions concern `EvaluationResult.decisions`, `_record_events`, `significant_decisions`, the worker counters and the AI queue, none of which the planner reaches.
*Deviation recorded.* The missing block-level seam is a deviation from the [R] rule in §4.1 item 2 that was not recorded earlier; the header statement that no design rule was changed by implementation did not mention it. That history is not rewritten. *Phase 52 obligation:* the deferred clauses are re-run with P8 in the gate-on configuration, once a writer and an enabled-mode seam exist. *Not changed:* the gate (`False`), the `InvestmentCycleResult` guard, the writer, A-10, P1 to P8, the closure of G49, and every other fixture status. This does not complete Phase 51. Record: ADR-0087 and `PROGRESS.md`.

**Known v0 limitation (M-2) — pins the documented behavior**
- G51 An alert stays `active` across many unchanged cycles: `skip_unchanged`, its `created_at` and `snapshot_id` are not refreshed (the stale-reference consequence, §8.1.1 item 2).
- G52 State A alert still `active`, state ends (class B or C), state A recurs: `skip_unchanged`, no new row (item 1); after a user resolve through the existing API the recurrence creates (G25).

**Time limit and cancellation (M-3) — required**
- G53 **(required)** `SoftTimeLimitExceeded`, `asyncio.CancelledError`, `KeyboardInterrupt` and `SystemExit` raised inside the block escape `evaluate`; none is recorded as `investment_internal_error`; the 11 types' rows already persisted are unchanged.
- G54 **(required)** Bounded work: with the gate off, at most one stored-row read and no other I/O; the loop visits exactly the four scopes; with the gate enabled on fakes, at most four `latest_active_for_key` reads plus the §9 writes; no sleep, retry or polling.
- G55 Class partition (m-2): every combination of the eight states, refusals, gate, freshness and missing-field cases falls into exactly one of A, B and C.

**Adapter (Stage 5, `tests/unit/test_investment_adapter.py`; fakes and hand-built data only)**
- G56 A valid row gives a decision and the stored identity (the three timestamps distinct); the Stage 2 evaluator accepts it.
- G57 The injected reader is read exactly once; no row gives `snapshot_not_found`; a non-integer `snapshot_id` is a caller error and reads nothing.
- G58 Row validation: every unusable identity, time or payload type gives `snapshot_row_invalid` and no builder runs; something that is not a row likewise.
- G59 Each of the six known builder refusals (injected at its step, and a real unsupported `snapshot_version`) gives `decision_inputs_refused` with only the class name as detail; a subclass is reported under the known name.
- G60 A plain `ValueError`, `KeyError`, `TypeError`, `AttributeError`, `RuntimeError`, `RecursionError`, `SoftTimeLimitExceeded`, `TimeLimitExceeded`, `asyncio.CancelledError` and `KeyboardInterrupt` raised from any builder or from the reader propagate unchanged.
- G61 Hash policy: a stored hash that matches gives `verified`; one that differs gives `mismatch`, which the Phase 46 gate turns into all-assets class B `request_gated`, no candidate, and (with a stored alert on a fake view) `indeterminate` with that reason; `unverified` never comes from the adapter.
- G62 The payload is not mutated, the result is deterministic, and the returned decision does not alias the stored payload.
- G63 `AdapterOutcome` invariants: a success has a decision and an identity; a refusal has neither; the detail is a known class name only and only with `decision_inputs_refused`.
- G64 Vocabulary: the three adapter reasons and the four evaluator reasons are closed, disjoint and unioned; the evaluator never emits an adapter reason; all pass `BANNED_PATTERNS`; every adapter refusal leaves stored alerts indeterminate in the planner and cannot become a usable evaluation.
- G65 Import boundary: an allow-list of imports, a fresh-interpreter check that no I/O library, repository, `cfi.decision_store` or service module is loaded, a source scan with no clock, I/O, writer or orchestration call, one unguarded `await`, and one `except` naming only the six known refusals. mypy checks (statically) that the real repository and row type satisfy the protocols.
- G66 The seven builders run once each, in the order of the Phase 49 route.
- G67 `build_decision_from_row` is synchronous; `read_and_build` is the only coroutine.

**Coexistence, provenance, wording**
- G38 Adapter parity: for the same stored payload the adapter's `investment_decision.v0` equals the Phase 49 route's chain (tested by calling the route function with an in-memory source, so no database is involved).
- G39 **(required, §11)** `len(ALERT_TYPE_TOOL_IDS) == 11`; `detection_method_for` outputs for the 11 types unchanged; `EvaluationResult()` still constructs without `investment`.
- G40 Markers present, in order, with effective parameter values; `@detection=` present; no real field id begins with `@`.
- G41 `created_at`, `as_of` and `knowledge_time` all different; none substituted.
- G42 Every produced string passes `BANNED_PATTERNS` and §15. Identical inputs and parameters give identical candidates.
- G43 Phase 45 `confirmed_adverse` → `no_opportunity`, not alertable, not clearing (§3.5).

**Fixture constructibility (final review).** Reliably constructible by hand-built inputs and fakes: G01 to G31, G33 to G37, G38 (needs one realistic
stored payload), G39 to G46, G47 and G48 (against an in-memory store), G50 to G52, G53 (raising the four signal types directly), G54, G55, G56 to G67.
Not reliably constructible or not a runtime test: states 2 and 8 only by hand (not reachable on live data); G32 (original: not constructible under the Phase 45 to 49 contracts; the risk-role variant is pinned); the SoftTimeLimitExceeded
case of G53 (and G60) needs the Celery exception class importable in the test environment (it is, in the isolated environment; the adapter test falls back to a stand-in `Exception` subclass if it is not); G45's "no override" and G49's file-diff check are static or
acceptance checks (a source scan and a diff), not behavior tests, and prove absence only for the code as scanned; a hard kill (M-3) cannot be
reproduced offline. All fixtures validate the *evaluator* and the gate; none validates end-to-end persistence (§4.1, item 5).

**Stage 6 fixtures (numbered after G67).** G68 onward are the block and service tests (`test_investment_block.py`, `test_alert_service_investment.py`):
class A/B/C dispositions, the seven refusal reasons and their log levels, the hash-mismatch path (four class B `request_gated`, no dispositions),
gate and `incomplete_decision` levels, log-field whitelist and absence of identity or payload, contained ordinary errors at four stages, signals
propagating from four stages, AST handler and source scans, bounded work, import boundary, `decisions` isolation and parity with and without
the block. They validate the evaluator and the block on fakes only; none validates end-to-end persistence.

## 15. Wording restrictions

[E] `BANNED_PATTERNS` applies to every produced string. [R] Additionally banned: buy/sell/long/short/enter/exit/hold language,
price targets or levels, probability or expected return, "signal", "opportunity to", "safe", "confirmed thesis", "validated",
"predicts", "will". Produced strings are fixed templates plus closed-vocabulary ids; no generated free text. Any presentation must
carry the Phase 49 `NOTICE` and the experimental/unvalidated label (Phase 52).

[R] An alert is a record of an observation at its creation time ("state X was observed in snapshot N"); no produced or presented wording may assert that the state currently holds.

## 16. What is and is not validated

| Validated | Not validated |
|---|---|
| The Phase 49 contract and states are implemented and tested (ADR-0086). | That a state change, or any alert, carries information about later outcomes. |
| The Phase 23 lifecycle is implemented and tested (ADR-0071). | Any threshold, cooldown, whitelist, condition or severity mapping (declared, none fitted). |
| Phase 51 Step 0 verified data availability for the October 1 to 9 window. | Historical alert frequency, noise and flapping (no alert-table or cadence query was executed). |
| | End-to-end persistence against the live schema and the existing consumers (disabled in Phase 51; fakes only). |
| | Any claim of predictive validity. Phase 50 is the required future validation. |

## 17. Known limitations (carried, not hidden)

- Step 0: Q6 and census consistency is aggregate only (per-snapshot equivalence not established); census focus series are
  replay-derived and not exhaustive; the Pass 2 wrapper version that ran is not recorded; the Pass 2 report was not opened by the assistant.
- Phase 49: the strongest and invalidation states are not reachable on live data; live states are `insufficient_evidence` or
  `no_opportunity`, so no investment alert would currently be created.
- No investment alert is resolved or expired automatically in v0 (a rearm supersede excepted). An alert whose state has ended, or whose condition cannot be evaluated, stays active until a user resolves it or another alertable state replaces it; the row carries no marker and records an observation at its creation time, not a current state. Markers, expiry and clearance are deferred (Phase 52 or a future approved version).
- **Persistence is disabled in Phase 51 (M-1).** The persistence, dedup, cooldown and re-arm design is verified only on in-memory fakes; its behavior against the live schema and the existing consumers is unverified until Phase 52 enables it.
- **M-2 consequences** (§8.1.1): no new alert for a later episode of an unchanged state; stale `created_at` and `snapshot_id` on long-lived alerts; cooldown measured from the stale `created_at`; no marker. Accepted for v0 by the user (K-1); Phase 52 must revisit it.
- **M-3 residual risk** (§11): a hard termination after the 11 types persist and before Phase 35 records events loses those events; not eliminated, lengthened by the block's run time; accepted by the user (K-2); hard-termination safety is not claimed.
- Freshness is the upstream `fresh` status; this layer does not validate those rules, and derivatives evidence is never verified.
- The inputs are views of one snapshot and not independent confirmations.
- No formal Phase 51 acceptance specification was found; the criteria are those of the Step 1 approval.

## 18. Phase boundaries

- **Phase 50 (historical validation)** is not started and not a prerequisite (D1); it remains a required future phase. Nothing in Phase
  51 may be described as validated until it is done.
- **Phase 52** owns delivery, notification channels, user-facing alert management and monitoring beyond the lifecycle functionality
  here (D2): including visible markers, age-based expiry, any new status, any automatic clearance (§8.4) and the presentation of the notice.
- Phase 35 integration of investment alerts (events, AI) is not part of Phase 51 (A-3).
- Enabling investment-alert persistence is not part of Phase 51 (M-1); it belongs to Phase 52 under §18.1.
- No earlier phase (15, 23, 35, 43 to 49) is reopened; every [X] item is additive and leaves existing outputs unchanged (G26, G35, G39).

### 18.1 Required before persistence can be enabled in Phase 52 (documented, not decided)

All of the following must be complete, reviewed and approved in writing before `INVESTMENT_ALERT_PERSISTENCE_ENABLED` changes:
- **P1 Presentation.** The dashboard `AlertsSection` and the `/alerts` page show the experimental/unvalidated label and the Phase 49
  `NOTICE` for investment alerts, and word an alert as an observation at its creation time, not a current state.
- **P2 Consumer exposure.** An explicit decision for each consumer of stored alerts: the alerts API (filter or label), journal and paper
  `relevant_alert_ids` (include, exclude or label; the 50-row `list_alerts` window must not be crowded out by a new type).
- **P3 Lifecycle review.** The M-2 limitation re-examined with the user: visible "cannot be evaluated" marker, age-based expiry, a new
  status if wanted, any clearance (§8.4) and a post-resolution interval, each with its own approval.
- **P4 Provenance.** `source_tool_id = investment_decision.v0`, `component_status` and the `@`-markers confirmed acceptable to every
  consumer, or structured provenance justified.
- **P5 Schema verification (§19)** approved, executed and passed.
- **P6 Phase 35 stance** re-confirmed (events and AI stay isolated) or changed by a separate decision.
- **P7 Time budget (M-3)** measured and the residual risk re-accepted.
- **P8 The change itself** is a separate, reviewable change; the G45 to G54 leakage fixtures are re-run in the gate-on configuration with the
  consumer changes of P1 and P2, and the user approves the flip explicitly.

## 19. Read-only schema verification (A-10) — prepared as a separate artifact, not approved, not executed

The procedure is in **`PHASE51_SCHEMA_VERIFICATION_PROCEDURE.md`**, kept separate so that approving this specification does not approve
running anything. It would confirm, by catalog reads only, that the live `usr.alert_event`, `sig.intelligence_event` and `ai.snapshot` match the
migration sources and `tables.py`. It needs three separate approvals (the procedure, a reviewed and offline-tested runner, and the execution).
Until it passes, enabling persistence against the live database is blocked (§18.1, P5); with the gate off Phase 51 writes nothing to these tables, and fixture-level implementation on fakes does not depend on it. No database
connection has been made and no SQL has been run.

## 20. Decisions and what remains

- **Decided by the user (2026-10-11):**
  - **K-1** M-2 limitation accepted for v0 (§8.1.1): no automatic resolve or expire; a recurrence of an unchanged state may not create a new alert;
    stored timestamps and snapshot references may become stale. Not a permanent design requirement; Phase 52 must revisit it.
  - **K-2** Residual hard-termination risk accepted (§11). No wall-clock budget invented; at implementation: inspect task and cancellation
    behavior, propagate signals, bound the work, measure duration, document the remaining risk; no safety guarantee claimed.
  - **K-3** Evaluator and adapter may run while persistence is off (§4.1, item 5), bounded and confined to `EvaluationResult.investment` and the cycle
    log; no investment-alert database read or write while gated off; evaluator validation is distinguished from end-to-end persistence validation.
  - **K-4** The gate stays a hard-coded `False` constant with no override; enabling needs §18.1, a separately approved and passed §19, and written approval.
  - Earlier: M-1 Option 3; the adapter (provisional); the five states at `notable` (provisional); no automatic resolution; upstream freshness
    with fail-closed behavior and no threshold; Phase 35 isolation.
- **Trade-offs recorded.** T-1: persistence leaves Phase 51's active behavior (D2), so Phase 51 acceptance cannot show alerts on the live stack.
  T-2: running the evaluator while gated adds synchronous time and a failure surface (accepted, K-3). T-3: lifecycle fixtures run on fakes and
  cannot prove live behavior. T-4: a constant means enabling is a code change and a deploy (accepted, K-4).
- **Still open, none blocking the specification:** `SoftTimeLimitExceeded` base class (confirmed as `Exception` in the isolated environment, Stage 5; the cycle-block propagation test is Stage 6); G32 resolved (original not constructible; risk-role variant pinned); measured evaluation duration (offline measurement recorded 2026-10-12, see §11; production and gate-on measurement remain open); the Phase 52 items of §18.1.
- **Blocking before enabling persistence (Phase 52):** §18.1 and §19 (approval of the procedure, of its runner, and its execution).
- **Blocking before implementation starts:** your review of this revision and a separate, explicit implementation approval. *(Historical; the
  implementation has since been approved and carried out in Stages 1 to 6, 2026-10-11 to 2026-10-12.)*
- **Not blocking, not in v0:** a clearance condition (§8.4); an alert-layer evidence-age threshold; a post-resolution interval; an optional
  realtime guard; a corrective note for the Phase 49 text; the final name of the detection-method string; structured provenance for future
  consumers.

## 21. What this document does not authorize

No code, test, migration, DDL, route, worker or schedule change, no enabling of investment-alert persistence, no alert delivery, no frontend work, no database access, and no
Phase 50 or Phase 52 work is authorized by this document. No commit is authorized.

**R13 approval gate.** Phase 51 implementation does not begin until the user has reviewed this specification, resolved or accepted
the items in §20 and separately approved the implementation. Stop and wait for the user.
*(Historical wording: that approval was later given stage by stage. The rest of this section still holds: this document does not authorize enabling
investment-alert persistence, delivery, frontend work, A-10 execution, or Phase 50 or Phase 52 work.)*
