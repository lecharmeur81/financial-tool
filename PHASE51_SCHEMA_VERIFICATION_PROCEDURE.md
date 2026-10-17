# PHASE51_SCHEMA_VERIFICATION_PROCEDURE.md

**Status: PROPOSED. NOT APPROVED. NOT EXECUTED.** Documentation only (Phase 51 Step 1, specification revision 6). No database connection has been made
and no SQL has been run to produce this document. It belongs to `METHODOLOGY_INVESTMENT_ALERTS.md` §19 (decision A-10) and ADR-0087.
Approving the specification does **not** approve anything in this file.

## 1. Purpose

Investment-alert persistence is disabled in Phase 51 (methodology §4.1, hard-coded gate). Enabling it in Phase 52 would write `usr.alert_event` rows with a new free-text `alert_type` (`investment_state`) and to read stored `ai.snapshot` rows.
Those plans rest on the **migration sources and `tables.py`**, not on the live database. Phase 51 itself reads only stored `ai.snapshot` rows. This procedure would confirm, by catalog reads only,
that the live objects match what the sources say, before enabling persistence relies on it. Passing this procedure is one of the conditions (not the only one) for changing the gate (methodology §18.1, P5, and decision K-4). It does not examine data, volumes or cadence.

## 2. Approvals required (three, each separate)

1. This procedure (the questions, the allow-listed statements, the pass criteria).
2. A reviewed runner that implements it, with offline tests (same discipline as the Step 0 runners; the earlier runners are not reused blindly).
3. The execution, naming the environment and the person running it.

## 3. Safety envelope

- One connection, one transaction opened `READ ONLY`, always ended with `ROLLBACK`. Session settings, inside the transaction only:
  `SET LOCAL statement_timeout = '10s'`, `SET LOCAL lock_timeout = '2s'`, `SET LOCAL idle_in_transaction_session_timeout = '30s'`.
- **Allow-list.** The runner executes only the statements in §4, matched as exact text. Anything else is refused before it is sent. No DDL, no
  DML, no `COPY`, no function with side effects, no statement against a business table.
- **Credentials.** The connection string is supplied by the environment the user already uses; it is never read from `.env` by the assistant, never
  placed in arguments, never printed, never written to the report or logs. The report records the environment label and the server version only.
- **Data.** No row of `usr.alert_event`, `sig.intelligence_event` or `ai.snapshot` is read; no `payload`. The single non-catalog read is the migration
  version table (S7b), one value of metadata.
- **Output.** A plain-text report plus its SHA-256, in a new directory, recorded in `PROGRESS.md` as Step 0's were. No raw dump of rows.
- **Failure.** Any error, timeout or refusal ends the run with the transaction rolled back and the failure reported. A failed run is never retried
  automatically and never interpreted as a pass.

## 4. Allow-listed statements (proposed text)

Objects in scope: `usr.alert_event`, `sig.intelligence_event`, `ai.snapshot`.

```sql
-- S0 session
SELECT current_setting('transaction_read_only') AS read_only, current_setting('server_version') AS server_version;

-- S1 columns
SELECT table_schema, table_name, ordinal_position, column_name, data_type, udt_name, is_nullable
FROM information_schema.columns
WHERE (table_schema, table_name) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY table_schema, table_name, ordinal_position;

-- S2 constraints (CHECK, PK, UNIQUE, FK)
SELECT n.nspname AS schema_name, c.relname AS table_name, con.conname, con.contype,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE (n.nspname, c.relname) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY n.nspname, c.relname, con.conname;

-- S3 indexes
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE (schemaname, tablename) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY schemaname, tablename, indexname;

-- S4 triggers (non-internal)
SELECT n.nspname AS schema_name, c.relname AS table_name, t.tgname, pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal
  AND (n.nspname, c.relname) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY n.nspname, c.relname, t.tgname;

-- S5 relation kind and row-level security
SELECT n.nspname AS schema_name, c.relname AS table_name, c.relkind, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE (n.nspname, c.relname) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY n.nspname, c.relname;

-- S6 rules
SELECT schemaname, tablename, rulename
FROM pg_rules
WHERE (schemaname, tablename) IN (('usr','alert_event'),('sig','intelligence_event'),('ai','snapshot'))
ORDER BY schemaname, tablename, rulename;

-- S7a locate the migration version table
SELECT n.nspname AS schema_name, c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname = 'alembic_version' AND c.relkind = 'r';

-- S7b migration head (the runner builds this with the schema found in S7a, quoted as an identifier)
SELECT version_num FROM <schema_from_S7a>.alembic_version;
```

**Privilege-visibility caveat (m-6).** `information_schema.columns` lists only columns the connecting role owns or has a privilege on. A missing column in S1 can therefore mean a privilege gap, not a schema mismatch. Before reading a missing column as drift, confirm the role's privileges, or read `pg_catalog.pg_attribute` (joined to `pg_class` and `pg_namespace`, `attnum > 0`, `NOT attisdropped`), which does not hide columns. Any switch of S1 to `pg_attribute` is a change to this procedure and needs its own approval; none is made here.

## 5. Expected results (from the migration sources, to be compared with the live result)

| Statement | Expected |
|---|---|
| S0 | `read_only = on`. |
| S1 `usr.alert_event` | The columns of migration 0009 and `tables.py`: `id` bigint, `uuid` uuid, `created_at` and `updated_at` timestamptz, `alert_type`, `severity`, `domain`, `dedup_key`, `trigger_condition`, `observed_value`, `reference_value`, `source_tool_id`, `component_status`, `data_quality_state`, `status` text, `evidence_field_ids` jsonb, `snapshot_id` and `superseded_by` bigint, `acknowledged_at` and `resolved_at` timestamptz. `alert_type` has `data_type = text` (not a user-defined enum). |
| S1 `sig.intelligence_event` | The columns of migration 0012, with `event_type` of type text. |
| S1 `ai.snapshot` | `id`, `uuid`, `created_at`, `as_of`, `knowledge_time`, `snapshot_version`, `payload` (jsonb), `payload_hash` (migration 0007). |
| S2 | `usr.alert_event`: CHECK on `severity` in (`info`,`notable`,`elevated`,`critical`) and on `status` in (`active`,`acknowledged`,`resolved`,`expired`); **no CHECK mentioning `alert_type`**; PK; UNIQUE `uuid`; FKs `snapshot_id` → `ai.snapshot`, `superseded_by` → `usr.alert_event`. `sig.intelligence_event`: CHECK on `severity` and on `status` in (`new`,`ai_requested`); **no CHECK mentioning `event_type`**; UNIQUE `alert_id`. |
| S3 | `alert_event_dedup_key_idx` on (`dedup_key`, `created_at` DESC) and `alert_event_status_idx` on (`status`, `created_at` DESC); the four `intelligence_event_*_idx`. |
| S4, S6 | No non-internal trigger and no rule on these tables (none is created by the migrations). |
| S5 | `relkind = r` for all; `relrowsecurity` and `relforcerowsecurity` false (none is created by the migrations). |
| S7b | `0013` as the migration head recorded in the sources (latest file `20261006_0013_decision_assessment.py`). |

Note: a comment in `db/engine.py` mentions a column `usr.alert_event.details`. Neither migration 0009 nor `tables.py` defines it and no later migration alters
the table; S1 would show whether the live table has any column beyond the sources.

## 6. Pass criteria and what a result means

- **Pass:** every row of §5 matches. Then the persistence assumptions in the methodology (free-text `alert_type`, the severity and status CHECK
  vocabularies, the column set, the snapshot read) hold on the verified database.
- **Fail or difference:** the difference is reported verbatim. No assumption in the methodology is relied on until the user decides. A difference never
  triggers an automatic change.
- **A pass proves only** that those catalog objects match at that moment on that database. It says nothing about volumes, alert cadence, data
  quality, freshness distributions, behavior under load or any other environment.

## 7. Not covered

Alert volumes and cadence (Step 0 only EXPLAINed those queries); the distribution of source freshness ages (which any future evidence-age
threshold, methodology §5.5, would need); migration application on other environments; permissions and roles; performance.

## 8. Approval gate

This procedure is a proposal. No runner exists, nothing was run, and no connection was made. Stop and wait for the user's review (R13).

## 9. Isolated environment for the Stage 6 database-backed integration test (added 2026-10-12; requirements only)

This section is separate from the read-only schema verification above. It records what the database-backed Phase 51 Stage 6 test
(`backend/tests/integration/test_investment_alert_snapshot_path.py`, tests I-01 to I-07) requires of its target. **At the time this section was
written no such environment had been created and no connection had been made; see the execution record at the end of this section.** The shared fixture (`tests/integration/conftest.py`) drops and
recreates `<configured database>_test` with `DROP DATABASE ... WITH (FORCE)`, migrates it to head and truncates 22 data tables before every
test, so the target must be a disposable server and never the existing development stack.

Required target (the only one the test accepts):
- A separate TimescaleDB container of the same image as the stack (`timescale/timescaledb:2.30.1-pg17`), with its own named volume (not
  `pgdata`), test-only credentials, no shared volumes and no application, worker, beat or frontend service attached.
- Host `127.0.0.1` or `localhost`, port `55432`, configured database `p51_scratch`, derived test database `p51_scratch_test`.
- `CFI_DATABASE_URL_RUNTIME` unset or blank, and a `CFI_DATABASE_URL` without query parameters (libpq lets `?host=` or `?port=` override the
  authority that is checked).
- `CFI_P51_DB_TEST_CONFIRM` exactly `p51_scratch_test`, set only after separate explicit authorization.
- Redis is not used by I-01 to I-07. `CFI_REDIS_URL` must still be set and well formed because the shared skip condition and `Settings`
  require it; it should point at no live Redis.

Gate. `evaluate_gate` in the test module checks every condition above on the environment mapping, without connecting, and the module is skipped
unless it passes. Because a `skipif` mark is evaluated before any fixture of the test is set up, the session fixture that drops and recreates
the database is never created for a skipped test. A connection-free unit file (`backend/tests/unit/test_p51_integration_gate.py`) covers the
valid case, wrong host, port, database or confirmation, malformed URLs, query parameters, a non-blank runtime URL, credential non-disclosure,
and the skip-before-fixture ordering on a throwaway project. The gate cannot prove the server is disposable; that remains a human
verification.

Unrelated integration modules use the same destructive fixture whenever the service variables are set, so only this file may be run, with
`-m integration`, and never an unfiltered `pytest` while those variables are set.

### Execution record (2026-10-12, reported by the user from the Windows run; not executed by the assistant)

The test was later run against a disposable container that meets the requirements above: container `p51-test-db`, database `p51_scratch`
(derived test database `p51_scratch_test`) on `127.0.0.1:55432`, dedicated volume `p51_test_pgdata`, no shared volume and no application
service attached. Command, from `E:\FINANCIAL TOOL\backend`:
`python -m pytest tests/integration/test_investment_alert_snapshot_path.py -m integration -p no:cacheprovider -q`.
Result: 7 passed in 3.04 s, exit code 0, none skipped (so the gate passed). The existing application containers and the persistent database
volume were not touched. Afterwards the temporary environment variables, including the confirmation variable and the test password, were
removed from the session. No credentials are recorded here.

This is not the read-only schema verification of sections 1 to 8. That procedure remains proposed, not approved and not executed; the run
above migrated a fresh disposable database and says nothing about the development or live schema.
