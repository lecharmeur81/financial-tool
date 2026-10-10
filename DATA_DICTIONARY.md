# DATA_DICTIONARY.md

**Status:** v0.2 (Phase 2 — architecture). Defines conventions, shared fields, the **logical schema** (§4), and the planned
dataset/metric catalogue. **Nothing here is implemented.** Tables and columns are logical designs; exact types, indexes, and
constraints are finalised in migrations when each phase is implemented, and this file is updated in the same commit.
Design rationale: `ARCHITECTURE.md` §5 and `DECISIONS.md` (ADR-0016 – ADR-0018).

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Timestamps | UTC, timezone-aware, ISO-8601. Stored as `timestamptz` (or equivalent). |
| Dates | A "day" is the UTC calendar day unless the dataset declares otherwise (e.g. US trading day for ETFs — declared per dataset). |
| Money | Exact decimal in storage. Unit always explicit (`usd`, `btc`, `eth`, `usdt`…). |
| Percentages | Stored as a **ratio** (0.0125 = 1.25%). Field name suffix `_pct` is **not** used, to avoid ambiguity; unit column states `ratio`. |
| Basis points | Only where the source uses them; unit `bps`. |
| Rates over time | Always state the period: `per_8h`, `per_1h`, `annualized`. Never store an unlabeled "funding rate". |
| Assets | Canonical internal symbol (`BTC`, `ETH`, `SOL`, `USDT`, `USDC`…). Provider symbols map via `asset_symbol_map`. |
| Instruments | Canonical instrument ID encodes venue, type, base, quote, expiry/strike where relevant. |
| Venues | Canonical venue ID (`binance`, `cme`, `deribit`, `coinbase`…), mapped per provider. |
| Missing | `NULL` value **plus** `quality_status = missing`. Never 0. |
| Naming | `snake_case`. Metric IDs are stable and versioned: `<name>.v<major>`. |

---

## 2. Universal fields

Observed data is split between the **series** (what is being measured — constant for the series) and the **row**
(one value at one time from one provider — ADR-0017). Together they satisfy the required fields of `CLAUDE.md` R3.

### 2a. Series-level fields (`obs.series`)

| Field | Type | Description |
|---|---|---|
| `series_id` | bigint | Primary key |
| `dataset_id` | text | Dataset in the registry (`ops.dataset`) |
| `metric` | text | What is measured, e.g. `perp_funding_rate`, `etf_net_flow` (canonical name) |
| `asset` | text, nullable | Canonical asset symbol, e.g. `BTC`; `NULL` only for non-asset series (e.g. macro) |
| `subject_type` | enum | `asset` · `instrument` · `venue` · `etf` · `entity` · `address_cluster` · `macro_series` · `market` |
| `subject_ref` | text | Canonical ID of the subject (e.g. instrument ID, ETF ticker, macro series code) |
| `venue` | text, nullable | Canonical venue ID where relevant |
| `period` | text | Granularity: `event`, `tick`, `1m`, `5m`, `1h`, `8h`, `1d`, `1w`, `1mo`, `1q` |
| `unit` | text | Unit of the value (DATA_DICTIONARY §1 conventions) |
| `revisable` | bool | Whether the source may revise published values (drives aggregation and compression rules) |
| `created_at` | timestamptz | When the series was registered |

### 2b. Row-level provenance fields (every L1 row, scalar or typed table)

| Field | Type | Description |
|---|---|---|
| `series_id` | bigint | The series this value belongs to |
| `event_time` | timestamptz | When the event happened / start of the period described (bar open) |
| `available_at` | timestamptz | Earliest time the value was publicly knowable (point-in-time key) |
| `available_at_estimated` | bool | `true` if `available_at` comes from a documented availability rule rather than the source |
| `ingested_at` | timestamptz | When our system stored it (knowledge-time key) |
| `value` / typed columns | numeric | The observed value(s) (scalar table: `value`; typed tables: e.g. `open`, `high`, `low`, `close`, `volume`) |
| `source_provider` | text | Provider we fetched it from (e.g. an aggregator or API vendor) |
| `original_source` | text | Who first published it (e.g. the ETF issuer, the exchange); `unknown` if the provider does not say |
| `raw_ref` | bigint | Pointer to `raw.payload` (L0) |
| `revision` | int | 0 = first publication; increments on each revision |
| `pit_reliability` | enum | `native` · `vendor_pit` · `backfilled_latest` (§3) |
| `quality_status` | enum | See §3 |
| `quality_note` | text | Human-readable reason when status is not `ok` |
| `confidence` | decimal 0–1, nullable | Where appropriate: for estimated, attributed, or inferred values. `NULL` for values reported directly by the source |

Natural key (uniqueness): (`series_id`, `event_time`, `source_provider`, `revision`).

**`as_of` / `knowledge_time` query-parameter resolution** (every point-in-time API route,
`cfi.api.params.resolve_query_times`, Phase 18 ADR-0060): `available_at <= as_of` gates *what was publicly
knowable*; `ingested_at <= knowledge_time` gates *what this system had stored*. When `as_of` is supplied and
`knowledge_time` is not, `knowledge_time` now defaults to `as_of` (not independently to `now()`) — only what
was knowable by that same date is visible unless a later `knowledge_time` is explicitly requested. When both
are omitted, both default to `now()`. Both resolved values are capped at the real `now()` (R3), including an
explicitly supplied `as_of`.

---

## 3. Enumerations

### `quality_status`
| Value | Meaning |
|---|---|
| `ok` | Received, validated, within expected ranges |
| `missing` | Expected but not received |
| `stale` | Last value older than the dataset's freshness limit |
| `partial` | Only some components present (e.g. OI from 4 of 6 venues) |
| `estimated` | Filled/derived under an explicitly permitted rule |
| `revised` | Superseded by a later revision (kept for history) |
| `suspect` | Failed a range/consistency check; retained, excluded from signals by default |
| `conflicting` | Two or more providers disagree beyond tolerance; all values kept and shown |
| `provider_error` | Provider returned an error or malformed payload |

### `evidence_category` (R2 — attached to every value the API or AI returns)
`observed` · `metric` · `signal` · `regime` · `ai_interpretation` · `hypothesis` · `user_decision`

### `pit_reliability`
| Value | Meaning |
|---|---|
| `native` | Recorded live by this system; `available_at` and vintage are real |
| `vendor_pit` | Provider supplies historical vintages / publication times |
| `backfilled_latest` | Historical values as the provider shows them today; may include later revisions or re-labelling (look-ahead risk) |

### `job_status`
`queued` · `running` · `succeeded` · `partial` · `failed` · `cancelled`

### `circuit_state`
`closed` · `open` · `half_open`

### `app_role`
`owner` · `analyst` · `viewer`

### `evidence_class` (entity classification)
| Value | Meaning |
|---|---|
| `direct` | The source itself identifies the actor (issuer reports, filings, exchange-published data) |
| `attributed` | A named third party labels the actor (e.g. analytics provider cluster label) |
| `inferred` | Heuristic proxy (size band, venue mix, cross-venue premium) |

### `actor_class`
Planned general set: `institutional` · `professional` · `whale` · `retail` · `exchange` · `miner` · `market_maker` · `fund` · `treasury_company` · `unknown`

**Implemented for on-chain addresses (Phase 7, `ref.entity_label.actor_class`):** known classes `exchange`,
`institution`, `fund`, `market_maker`, `protocol`, `miner`, `government`, `other` (each names an entity in `ref.entity`
and needs a label from a named source), and `unknown_large_holder` (no entity; `inferred` from size only). Read-time
classification adds `unlabelled` (no label, balance unknown or below the size threshold). Database checks: `inferred`
⇒ `unknown_large_holder`; `institution` / `fund` / `market_maker` ⇒ `direct` or `attributed`; known class ⇔ entity set.

Every non-`unknown` assignment requires an `evidence_class`, `confidence` (0–1), `rule_or_source`, `valid_from`, `valid_to`.

---

## 4. Logical schema (planned — Phase 2 design)

Tables are grouped by PostgreSQL schema (one per layer, ADR-0016). **Implemented in Phase 4 (migration `0002`):** `ops.provider`, `ops.dataset`,
`ops.dataset_provider`, `ops.job_run`, `ops.provider_request` (replaces the planned `provider_health_event` and
`request_ledger`: one row per HTTP attempt with its outcome), `ops.quality_check_result` (column `check_name`), `raw.payload`,
`obs.series`, `obs.observation` (plus `transformations text[]` — empty means the value was stored exactly as reported).
**Implemented in Phase 5 (migration `0003`):** `obs.market_bar` (below), `ops.backfill_state` (resumable history
checkpoint: `dataset_id`, `provider_id`, `subject`, `covered_from`, `covered_to`, `target_start`, `complete`,
`empty_chunks`, `note`, `updated_at`), `ops.dataset.kind` (`scalar` | `bar`), `ops.job_run.subject` (asset the run
covered), `ops.job_run.skipped` (records not final yet — skipped, fetched later), `ops.job_run.suspect`
(records failing a consistency check), `ops.job_run.job_type` ∈ {`ingest`, `backfill`}.
**Implemented in Phase 7 (migration `0005`):** `ref.entity`, `ref.entity_label` (below), `obs.large_transfer`,
`ops.dataset.kind` also `transfer`.
**Implemented in Phase 8 (migration `0006`):** `obs.derivative_quote` (below; replaces the planned `option_quote` for
venue snapshots of futures, perpetuals and options), `ops.dataset.kind` also `quote`. Open interest, funding,
account ratios and hourly liquidation totals are scalar series in `obs.observation` (the planned `open_interest` and
`liquidation_event` tables were not needed).
Still planned: the other typed market tables, `ref.*`, `calc`/`sig`/`regime`/`ai`/`usr` tables, `ops.coverage_daily`.
**Implemented in Phase 3 (migration `0001`):** the nine
schemas exist and are empty; no tables have been created yet. **HT** = TimescaleDB hypertable (time column in brackets).
"Provenance" = the row-level fields of §2b. Write access per schema follows the DB roles in `ARCHITECTURE.md` §5.9.

### `ref` — reference data (bitemporal: `valid_from`/`valid_to` + `recorded_at`)

| Table | Purpose | Key columns |
|---|---|---|
| `asset` | Canonical assets | `asset_id`, `symbol`, `name`, `asset_type` (coin, stablecoin, token), `chain`, `launched_at`, `retired_at` |
| `asset_symbol_map` | Provider symbol → canonical asset | `provider_id`, `provider_symbol`, `asset_id`, `valid_from`, `valid_to` |
| `venue` | Exchanges, CME, ETF issuers, DEXs | `venue_id`, `name`, `venue_type` (cex, dex, cme, etf_issuer, otc), `jurisdiction`, `opened_at`, `closed_at` |
| `instrument` | Tradable instruments | `instrument_id`, `venue_id`, `type` (spot, perp, future, option, etf), `base`, `quote`, `expiry`, `strike`, `option_type`, `contract_size`, `contract_unit`, `listed_at`, `delisted_at` |
| `instrument_map` | Provider instrument code → canonical | `provider_id`, `provider_code`, `instrument_id`, `valid_from`, `valid_to` |
| `instrument_status_history` | Listing/suspension/delisting events (survivorship) | `instrument_id`, `status`, `effective_at`, `available_at` |
| `etf_fund` | Spot crypto ETFs/ETPs | `fund_id`, `ticker`, `issuer`, `underlying_asset`, `listing_venue`, `launched_at`, `closed_at` |
| `entity` (**implemented** Phase 7) | Real-world actors (exchanges, institutions, funds, market makers, protocols, miners, governments, other) | `entity_id`, `name`, `actor_class` (a known class), `description`, `created_at` |
| `address` | On-chain addresses | `chain`, `address`, `first_seen_at` |
| `entity_label` (**implemented** Phase 7 for addresses) | Label of an on-chain address (R5); append-only | `label_id`, `chain` (`bitcoin`/`ethereum`), `address` (checksum-validated canonical form), `actor_class`, `entity_id`, `evidence_class`, `confidence` (0–1), `evidence` (text, required), `source` (required), `source_url`, `valid_from`, `valid_to` (NULL = open), `available_at` (when the label was published), `recorded_at` (when stored). Unique (chain, address, actor_class, entity_id, source, available_at) |
| `calendar` | Trading/release calendars | `calendar_id`, `date`, `is_open`, `open_at_utc`, `close_at_utc` |
| `universe_membership` | As-of universes (survivorship) | `universe_id`, `member_ref`, `valid_from`, `valid_to`, `rule_version` |

### `raw` — L0

| Table | Purpose | Key columns |
|---|---|---|
| `payload` (HT [`received_at`]) | Index of archived provider responses | `payload_id`, `provider_id`, `endpoint`, `request_params` (redacted), `http_status`, `received_at`, `content_hash`, `archive_uri`, `bytes`, `schema_version`, `schema_check` (pass/fail + details), `job_run_id` |

### `obs` — L1 observed data

| Table | Purpose | Key columns (plus provenance) |
|---|---|---|
| `series` | Series registry (§2a) | see §2a |
| `institutional_flow` (HT [`event_time`], **implemented** Phase 6) | Flows and holdings of identified institutional vehicles/entities (§5b) | `entity_type` (`etf_group`, `etf_fund`, `public_company`, `public_company_group`), `evidence_class` (`direct` or `attributed` — `inferred` is rejected), `entity_name`, `flow_usd` / `flow_native` (positive = capital entering the entity), `holdings_usd` / `holdings_native`, `cum_flow_usd`, `value_traded_usd`, `premium_discount` (ratio), `unit_cost_usd`. USD columns in the series unit (`usd`); `*_native` in units of the asset. Any field not reported is NULL; a missing row has no flow and no holdings with `quality_status = missing` |
| `observation` (HT [`event_time`]) | Generic scalar series: ETF flows/holdings, stablecoin supply, exchange reserves, macro, sentiment, on-chain aggregates | `value` |
| `market_bar` (HT [`event_time`], **implemented**) | OHLCV bars; `event_time` = bar open | `open`, `high`, `low`, `close` (unit = series unit, the quote currency), `volume_base` (base asset), `volume_quote` (quote currency; NULL when the venue does not report it), `trade_count` (NULL when not reported). A missing bar has all prices and volumes NULL with `quality_status = missing` |
| `funding_rate` (HT) | Perpetual funding | `rate`, `interval_hours`, `rate_per_8h`, `mark_price`, `index_price`, `is_predicted` |
| `open_interest` (HT) | Open interest | `oi_contracts`, `oi_base`, `oi_usd` |
| `liquidation_event` (HT) | Liquidations (event or aggregated) | `side` (long/short), `quantity_base`, `notional_usd`, `price`, `is_aggregated` |
| `orderbook_depth` (HT) | Depth bands around mid | `mid_price`, `band_bps`, `bid_notional_usd`, `ask_notional_usd` |
| `derivative_quote` (HT [`event_time`], 7-day chunks, **implemented** Phase 8; planned as `option_quote`) | One futures / perpetual / option instrument per venue snapshot, one series per instrument (`subject_ref` = `DERIBIT:<instrument>`); `event_time` = the venue's response time | `instrument`, `instrument_kind` (`future` / `perpetual` / `option`), `expiry` (NULL only for perpetuals; Deribit 08:00 UTC), `strike`, `option_type` (`call` / `put`; both set exactly for options), `mark_price`, `bid_price`, `ask_price` (series unit: `usd` for inverse futures, the coin for options), `mark_iv` (ratio), `underlying_price` (forward, USD), `index_price` (USD), `open_interest_native` (coins), `open_interest_usd` (USD, inverse futures), `volume_native` (24 h, coins), `volume_usd`. Missing ⇔ `mark_price` NULL. Checks: non-negative values, strike > 0, bid ≤ ask, expiry after the snapshot — violations are kept and flagged `suspect` |
| `large_transfer` (HT [`event_time`], **implemented** Phase 7; planned as `onchain_transfer`) | Individual large transfers, one series per transfer (`subject_ref` = `chain:tx_hash[:output_index]`) | `chain`, `tx_hash`, `output_index` (Bitcoin output; NULL for Ethereum), `block_height`, `sender` (NULL for Bitcoin outputs), `recipient`, `value_native` (asset units), `value_usd` (provider value at block time; NULL if not reported). `event_time` = block time. An address failing validation is kept as reported and the row is `suspect` |
| `selected_observation` (view) | Preferred-provider value per point in time with provider used and conflict flag | derived |

### `calc` — L2 metrics

| Table | Purpose | Key columns |
|---|---|---|
| `metric_definition` | Registered metric versions (template §6) | `metric_id` (`name.vN`), `formula_ref`, `inputs`, `unit`, `missing_policy`, `fill_policy`, `status` |
| `metric_value` (HT [`as_of`]) | Computed metric values | `metric_id`, `subject_ref`, `as_of`, `knowledge_time`, `value`, `quality_status`, `coverage`, `input_fingerprint`, `code_version`, `computed_at`, `pit_reliability_min` |

### `sig` — L3 signals and research

| Table | Purpose | Key columns |
|---|---|---|
| `signal_definition` | Signal versions | `signal_id`, `method`, `lookback`, `thresholds`, `inputs` |
| `signal_value` (HT [`as_of`]) | Signal outputs (§8) | `signal_id`, `subject_ref`, `as_of`, `statistic`, `value`, `state`, `confidence`, `quality_status`, `input_fingerprint`, `code_version` |
| `divergence_value` (HT [`as_of`]) | Institutional vs. retail (and other) divergences | `divergence_id`, `as_of`, `left_composite`, `right_composite`, `spread`, `state`, `evidence_mix`, `confidence` |
| `anomaly_event` | Unusual observations/metrics | `ref`, `as_of`, `method`, `score`, `is_data_error_candidate` |
| `experiment` | Backtest/research registry | `experiment_id`, `spec` (JSON), `code_version`, `knowledge_time`, `accepted_pit_levels`, `trial_count`, `created_by` |
| `experiment_result` | Backtest outputs | `experiment_id`, `split`, `metrics` (JSON), `equity_curve_ref`, `drawdowns`, `turnover`, `costs` |

### `regime` — L4

| Table | Purpose | Key columns |
|---|---|---|
| `regime_model` | Versioned regime models | `model_id`, `method`, `features`, `labels`, `filtered_only` (must be true) |
| `regime_state` (HT [`as_of`]) | Classified state | `model_id`, `as_of`, `label`, `probabilities` (JSON), `confidence`, `component_signals`, `quality_status` |
| `similarity_result` | Historical analogues | `as_of`, `method`, `matches` (periods, distance), `excluded_windows` |

### `ai` — L5

| Table | Purpose | Key columns |
|---|---|---|
| `snapshot` | Immutable evidence pack (§9a) | `snapshot_id`, `as_of`, `knowledge_time`, `content` (JSON), `content_hash`, `builder_version`, `created_at` |
| `interpretation` | Claude output (§9) | see §9 |
| `usage` | Token/cost accounting | `interpretation_id`, `model_id`, `input_tokens`, `output_tokens`, `cached_tokens`, `cost_usd`, `batch` |
| `eval_run` | AI evaluation results (R12) | `eval_id`, `prompt_version`, `model_id`, `suite`, `results` (JSON), `run_at` |

### `usr` — L6 user layer

| Table | Purpose | Key columns |
|---|---|---|
| `app_user` | Accounts | `user_id` (uuid), `email`, `password_hash` (Argon2id), `role`, `totp_secret` (encrypted), `display_timezone`, `created_at`, `disabled_at` |
| `api_token` | Personal API tokens | `token_id`, `user_id`, `token_hash`, `scopes`, `expires_at`, `last_used_at` |
| `journal_entry` | Decision journal (versioned, append-only) | `entry_id`, `version`, `user_id`, `decision`, `rationale`, `hypotheses`, `invalidation_conditions`, `snapshot_id`, `interpretation_id`, `created_at`, `outcome_review` |
| `paper_account` / `paper_order` / `paper_fill` / `paper_position` | Paper trading | `account_id`, `user_id`; orders: `instrument_id`, `side`, `qty`, `order_type`, `submitted_at`, `journal_entry_id`; fills: `price`, `fee`, `slippage`, `filled_at`, `cost_model_version` |
| `alert_rule` | User-defined rules (versioned) — **not built**; Phase 23 (§5o) implemented 11 code-defined rule types instead of a user-authored rule table, since the spec asked for fixed monitoring across named domains, not user-authored rules | `rule_id`, `version`, `user_id`, `rule_type`, `definition` (JSON), `min_quality`, `cooldown`, `channels`, `enabled` |
| `alert_event` | Fired alerts — **implemented in Phase 23** (§5o) with a different column set than planned here (no `rule_id`/`rule_version`, since there is no `alert_rule` table; `delivered` replaced by the `status` lifecycle) | see §5o for the real, implemented shape |

### `ops` — operations

| Table | Purpose | Key columns |
|---|---|---|
| `provider` | Provider catalogue | `provider_id`, `name`, `auth_type`, `terms_notes`, `storage_allowed`, `redistribution_allowed`, `status` |
| `provider_endpoint` | Endpoint limits | `provider_id`, `endpoint`, `rate_limit`, `weight`, `cost_class` |
| `dataset` | Dataset registry | `dataset_id`, `category`, `schedule`, `freshness_limit`, `availability_rule`, `history_start`, `conflict_tolerance`, `retention_policy`, `revisable` |
| `dataset_provider` | Eligible providers per dataset | `dataset_id`, `provider_id`, `priority`, `enabled` |
| `provider_health_event` (HT) | Circuit/outage history | `provider_id`, `endpoint`, `at`, `circuit_state`, `error_class`, `latency_ms` |
| `request_ledger` (HT) | Every provider request (cost/limits) | `provider_id`, `endpoint`, `at`, `weight`, `status`, `job_run_id` |
| `job_run` | Job history of record | `job_run_id`, `job_type`, `queue`, `dataset_id`, `window_start`, `window_end`, `status`, `rows_written`, `error_code`, `error_detail`, `code_version`, `started_at`, `finished_at`, `checkpoint` |
| `quality_check_result` (HT) | Data-quality check history | `dataset_id`, `series_id`, `check`, `at`, `status`, `details` |
| `coverage_daily` | Coverage per dataset/day | `dataset_id`, `day`, `expected_points`, `present_points` |
| `audit_log` | Security/admin audit (append-only) | `at`, `user_id`, `action`, `target`, `details`, `ip` |
| `data_version` | Version counters for cache invalidation | `scope`, `version`, `updated_at` |

---

## 5. Planned dataset catalogue (L1)

Evidence class indicates how directly the dataset tells us *who* is acting.

| Category | Dataset (planned) | Typical period | Evidence of actor | Phase |
|---|---|---|---|---|
| Market | Spot OHLCV per venue — **implemented (Phase 5)** | 1m–1d | n/a | 5 |
| Market | Last trade price, market capitalisation — **implemented (Phase 5)** | event, 1d | n/a | 5 |
| Market | Spot volume by venue (venue share metric) | 1h–1d | inferred (venue mix) | later (L2) |
| Institutional | Spot ETF daily net flows, holdings, AUM — **implemented (Phase 6)**: US, BTC/ETH/SOL/XRP, total and per fund | 1d | direct | 6 |
| Institutional | CME futures OI & volume | 1d | inferred (regulated venue) | 5 |
| Institutional | Regulatory position filings (e.g. quarterly holdings) | 1q, lagged | direct, heavily lagged | 5 |
| Institutional | Public company / treasury holdings — **implemented (Phase 6)**: BTC purchases per company; BTC/ETH/SOL totals | event | attributed (disclosures compiled by a provider) | 6 |
| Institutional | Cross-venue premium (e.g. US-regulated vs offshore spot) | 1m–1h | inferred | 5 |
| Whale | Large on-chain transfers — **implemented (Phase 7)**: BTC outputs ≥ 500 BTC, ETH transactions ≥ 5,000 ETH | event | labels (attributed) or size (inferred) | 7 |
| Whale | Balances by holder-size band — not available free; top-100 address balances **implemented (Phase 7)** instead | 1d | inferred / attributed | 7 |
| Exchange flows | Exchange net inflow/outflow, reserves — **implemented (Phase 7)**: BTC, ETH daily (Coin Metrics) | 1d | attributed (exchange address labels) | 7 |
| Coin age | Coin days destroyed, revived ≥ 1 y, ≥ 155 d spent, coinbase-origin spent — **implemented (Phase 7)**: BTC daily | 1d | n/a | 7 |
| Derivatives | Perpetual funding rates per venue | 1h–8h | n/a | 7 |
| Derivatives | Open interest per venue/instrument | 5m–1d | n/a | 7 |
| Derivatives | Liquidations (long/short) | event–1h | n/a | 7 |
| Derivatives | Futures basis / term structure | 1h–1d | n/a | 7 |
| Derivatives | Long/short account & position ratios (where venues publish) | 5m–1h | inferred | 7/9 |
| Options | Options OI, volume, IV, skew, term structure, put/call | 1h–1d | n/a | 7 |
| Liquidity | Stablecoin supply per chain/issuer | 1d | direct (issuer) / attributed | 8 |
| Liquidity | Stablecoin exchange balances & flows | 1d | attributed | 8 |
| Liquidity | Order-book depth (±x% from mid) | 1m–1h | n/a | 8 |
| Retail | Search interest, app ranking, social volume/sentiment | 1d | inferred | 9 |
| Retail | Small-transfer / small-holder activity | 1d | inferred | 9 |
| Macro | Rates, yields, dollar index, liquidity aggregates, inflation, equities, volatility indices | 1d–1m | n/a | 10 |
| Market structure | Dominance, correlations, volatility, realized cap-style aggregates | 1d | n/a | 11 |

Candidate providers for each dataset are **not yet selected**; see `TODO.md` (Phase 3 research).
No provider capability is assumed until verified against its documentation and a real response.

---

## 5a. Market datasets (implemented in Phase 5)

| Dataset ID | Metric | Unit | Period | Providers (venue · instrument) | Availability rule | Freshness limit |
|---|---|---|---|---|---|---|
| `market.ohlcv.usd.<tf>` | `spot_ohlcv` | `usd` | 1m, 5m, 15m, 1h, 4h, 1d | Coinbase Exchange `coinbase:spot:<A>-USD` (no 4h: rolled up from 1h at read time); Kraken `kraken:spot:<A>-USD` (720 most recent bars only) | bar close + 60 s | 5 min, 15 min, 45 min, 3 h, 10 h, 50 h |
| `market.ohlcv.usdt.<tf>` | `spot_ohlcv` | `usdt` | 1m, 5m, 15m, 1h, 4h, 1d | Binance `binance:spot:<A>-USDT`; OKX `okx:spot:<A>-USDT` (4h/1d = UTC-aligned bars); Bybit `bybit:spot:<A>-USDT` | bar close + 60 s | as above |
| `market.spot_price.usd` | `spot_price` | `usd` | event | Coinbase Exchange last trade (`event_time` = trade time) | provider time | 5 min |
| `market.market_cap.usd` | `market_cap` | `usd` | event | CoinGecko (`event_time` = its last update) | provider time | 30 min |
| `market.market_cap.usd.1d` | `market_cap` | `usd` | 1d | CoinGecko daily snapshot at 00:00 UTC (history ≤ 365 days on the free tier) | 00:00 + 10 min | 50 h |

`<A>` ∈ {BTC, ETH, SOL, XRP}. Each venue is its own series (`obs.series.venue`); USD and USDT are different units and
are never combined. `pit_reliability` is `native` when a value was stored within its freshness limit after it became
knowable, otherwise `backfilled_latest`. `transformations` records every conversion (epoch → UTC, field re-ordering,
time truncation, alignment to the daily grid).

## 5b. Institutional datasets (implemented in Phase 6)

All rows live in `obs.institutional_flow`. Availability rules are conservative estimates; a value received earlier is
dated by its receipt time (`known_when_received`), and `available_at_estimated = true` in both cases.

| Dataset ID | Subject (`subject_ref`) | Entity / evidence | Values | Provider | `available_at` | Freshness |
|---|---|---|---|---|---|---|
| `institutional.etf_flow.us_spot.1d` | `US-SPOT-ETF:<A>` | `etf_group` / direct | `flow_usd` (net inflow), `holdings_usd` (total net assets), `cum_flow_usd`, `value_traded_usd` | SoSoValue `/etfs/summary-history` | next US trading day 18:00 New York | calendar-aware (read); engine limit 5 d |
| `institutional.etf_fund_flow.us_spot.1d` | `ETF:<TICKER>` | `etf_fund` / direct | as above per fund, plus `premium_discount` | SoSoValue `/etfs`, `/etfs/{ticker}/history` | same | same |
| `institutional.treasury_purchase.btc` | `COMPANY:<TICKER>` | `public_company` / attributed | `flow_native` (BTC acquired, negative = sold), `flow_usd` (cost, signed like the coins), `holdings_native` (holdings after). `unit_cost_usd` stays NULL: SoSoValue's `avg_btc_cost` is not a USD price (see below) | SoSoValue BTC Treasuries | purchase date + 7 days | last successful sweep ≤ 36 h (no engine check) |
| `institutional.treasury_holdings.public_companies` | `PUBLIC-COMPANIES:<A>` | `public_company_group` / attributed | `holdings_native`, `holdings_usd` | CoinGecko `/companies/public_treasury/{coin}` | receipt time (no timestamp in the response) | 26 h |

`<A>` ∈ {BTC, ETH, SOL, XRP} for ETF data; {BTC, ETH, SOL} for holdings totals; BTC only for purchases.
`event_time`: ETF rows and purchases = the date (US trading date for ETFs) as a 00:00 UTC label; holdings = receipt
time. ETF figures settle T+1: the current day's row without figures is skipped as not final; an older row without
figures is stored as explicit missing. Consistency checks mark rows `suspect` (kept): negative holdings or value
traded, flow in USD and coins with opposite signs, a reported unit cost differing from cost ÷ coins by more than
2 %, and — for BTC — an implied price (|cost ÷ coins|) outside 1,000 to 1,000,000 USD (e.g. a cost reported in another
currency). SoSoValue's `avg_btc_cost` is documented as "per-unit cost (USD)" but real values (2026-09-24) are small
company-specific numbers (MSTR 0.09 while cost ÷ BTC ≈ 79,700 USD); it is not stored. The API shows a calculated
`implied_cost_per_btc_usd` = |cost ÷ BTC| instead.

### Read-time aggregations (Phase 6)

| Metric ID | Definition | Evidence category |
|---|---|---|
| `etf_net_flow.us_spot.1d.v1` | Reported daily total net flow (USD) | observed |
| `etf_net_flow.us_spot.1w.v1` | Σ daily net flow over the trading days (Mon–Sun week) with data; net assets = last day with data | metric |
| `etf_net_flow.us_spot.1mo.v1` | same per calendar month | metric |
| `treasury_net_acquisitions.btc.{1w,1mo}.v1` | Σ BTC acquired (net) and Σ reported cost of purchases dated in the bucket | metric |
| `treasury_reported_holdings.btc.v1` | Σ each tracked company's holdings after its latest reported purchase | metric |

Per bucket every US trading day is counted once as **present**, **missing** (due, within stored history, no value),
**not loaded** (before stored history) or **not due** (not public yet). Bucket status: `complete`, `partial`,
`in_progress`, `not_due`, `not_loaded`, `no_data`.

### Institutional Flow Score v1 (`institutional_flow_score.v1`, calculated metric — ADR-0048)

```
metric_id:        etf_net_flow_5d_pct_aum.v1   (weight 0.35, reference scale 1.0 %)
formula:          Σ daily net flow (USD) over the last 5 US trading days ÷ total ETF net assets (USD)
                  on the last day with data in the window × 100
metric_id:        etf_net_flow_20d_pct_aum.v1  (weight 0.30, reference scale 3.0 %)
formula:          same over 20 US trading days
metric_id:        etf_flow_day_balance_10d.v1  (weight 0.15, no scale — already −1 … +1)
formula:          (days with net inflow − days with net outflow) ÷ days with data, last 10 US trading days
metric_id:        treasury_net_acquisitions_30d_pct.v1 (weight 0.20, reference scale 2.0 %; BTC only)
formula:          Σ BTC acquired (net) in purchases dated within the last 30 days and public by as_of
                  ÷ Σ each tracked company's latest reported BTC holdings × 100
window end:       the later of the latest trading day due by as_of and the latest day already received
sub_score:        clip(metric ÷ reference scale, −1, +1), 4 decimals
score:            100 × Σ(weight × sub_score) ÷ Σ(weights of available components), 1 decimal
missing_policy:   a component with < 90 % of its window present is excluded (never filled); if the available
                  weight is < 0.5 the result is "Insufficient data"
point_in_time:    inputs with available_at <= as_of and ingested_at <= knowledge_time
bands:            ≥ +50 strong net inflow · ≥ +15 net inflow · ≥ −15 balanced · ≥ −50 net outflow · below:
                  strong net outflow (descriptive only)
caveats:          ETF flows are fund flows, not proof of institutional buyers; parameters are judgments,
                  published and versioned, not fitted
owner_phase:      6
status:           implemented
```

## 5c. Whale datasets (implemented in Phase 7)

`<a>` ∈ {btc, eth}; `<chain>` ∈ {bitcoin, ethereum}. Units are the asset's coins (`btc`, `eth`) unless stated.

| Dataset ID | Subject | Values | Provider | `available_at` | Evidence of actor |
|---|---|---|---|---|---|
| `whale.exchange_inflow.<a>.1d` / `exchange_outflow` / `exchange_supply` | `EXCHANGES:<A>` | coins into / out of / held by exchange addresses per UTC day | Coin Metrics Community (`FlowInExNtv`, `FlowOutExNtv`, `SplyExNtv`) | the value's status time (publication); `flash` values stored as `estimated` | attributed (Coin Metrics' exchange attribution) |
| `whale.supply.<a>.1d` / `whale.issuance.<a>.1d` | `NETWORK:<A>` | current supply / new issuance per UTC day | Coin Metrics (`SplyCur`, `IssTotNtv`) | day start + 30 h (estimated; receipt time if earlier) | n/a |
| `whale.coin_days_destroyed.btc.1d` | `NETWORK:BTC` | Σ coin days destroyed (unit `coin_days`) | Blockchair `/bitcoin/blocks?a=date,sum(cdd_total)` | day end + 2 h | n/a |
| `whale.revived_supply_1y.btc.1d` / `lth_spent_155d` / `miner_origin_spent` | `NETWORK:BTC` | BTC spent that day from outputs ≥ 365 d old / ≥ 155 d old / coinbase outputs | Blockchair `/bitcoin/outputs?a=spending_date,sum(value)` + `lifespan` / `is_from_coinbase` filter | day end + 2 h | n/a (coin age / origin, not owners) |
| `whale.address_balance.<chain>` | `<chain>:<address>` | balance of each of the 100 largest addresses (ETH: accounts, contracts excluded) | Blockchair `/{chain}/addresses` | receipt time (list has no timestamp, estimated) | classified at read time (labels, else size) |
| `whale.large_transfer.<chain>` | `<chain>:<tx>[:<output>]` | `obs.large_transfer` row | Blockchair `/bitcoin/outputs`, `/ethereum/transactions` | block time + 10 min (receipt time if earlier) | classified at read time (labels, else size from the latest snapshot) |

Only complete UTC days are requested; the current day is skipped as not final. History: Coin Metrics 730 days,
Blockchair aggregates 120 days, transfers 7 days — one chunk per run (`ops.backfill_state`). Rich lists have no history:
7-day changes need a week of daily snapshots.

### Whale Flow Score v1 (`whale_flow_score.v1`, calculated metric — ADR-0049)

```
sign:             positive = accumulation, negative = distribution (on-chain behaviour; not price)
metric_id:        exchange_netflow_7d_pct_exchange_supply.v1 (weight 0.35, scale 1.0 %)
formula:          Σ (inflow − outflow) over the last 7 complete UTC days ÷ exchange supply on the last day × 100;
                  sub_score = clip(−value ÷ scale)
metric_id:        exchange_supply_change_30d_pct.v1 (weight 0.15, scale 3.0 %)
formula:          (supply on day D − supply on D−30) ÷ supply on D−30 × 100; sub_score = clip(−value ÷ scale)
metric_id:        unknown_large_holder_balance_change_7d_pct.v1 (weight 0.25, scale 1.0 %)
formula:          addresses classed unknown large holder in the top-100 snapshot 7 days (± 1 day) before the
                  latest one and still listed: Σ(balance now − then) ÷ Σ balance then × 100; ≥ 80 % still listed
metric_id:        revived_supply_1y_7d_vs_90d.v1 (weight 0.25, scale 1.0; BTC only)
formula:          (Σ ≥ 1 y coins moved over 7 days ÷ 7) ÷ (Σ over the 90 days before ÷ days with data);
                  sub_score = clip(−(ratio − 1) ÷ scale)
window end:       the later of the last day due (day end + 12 h Coin Metrics, + 16 h Blockchair) and the last
                  complete day received
score:            100 × Σ(weight × sub_score) ÷ Σ(available weights), 1 decimal
missing_policy:   component excluded below 90 % coverage (never filled); "Insufficient data" below weight 0.5
bands:            ≥ +50 strong accumulation · ≥ +15 accumulation · ≥ −15 neutral · ≥ −50 distribution · below: strong
                  distribution
owner_phase:      7
status:           implemented
```

Not in the score (shown next to it): `miner_origin_spent_vs_issuance_7d.v1` = Σ coinbase-origin BTC moved ÷ Σ BTC
issued over the same 7 days (≥ 90 % coverage).

**Contradiction indicators** (read-time, per asset): exchange flows vs old coins moving; exchange flows vs unknown large
holders; Whale Flow Score vs Institutional Flow Score (Phase 6); labelled top-100 exchange balances (7 days) vs Coin
Metrics exchange supply (the days before the two snapshots). Direction thresholds: sub-score ±0.25, score ±15 points,
balance change ±0.5 %. Status: `contradiction` (opposite directions), `consistent`, `no_clear_direction`,
`insufficient_data`.

**Transfer-date balance snapshots** (Phase 18, RED_TEAM_REPORT.md finding #13 / ADR-0064,
`cfi.whales.service._balances_as_of`): each large transfer's sender/recipient size-rule classification
(`unknown_large_holder`) now uses the top-100 balance snapshot in effect **at that transfer's own
`event_time`** — the latest snapshot at-or-before it — never the latest snapshot regardless of when the
transfer happened. A transfer predating every stored snapshot gets no balance (classification by labels
alone) rather than borrowing a later, unrelated one. Previously, an address that only grew large *after* a
given historical transfer would be retroactively classified as a large holder for that transfer using
today's balance (and the reverse for an address that has since drawn down).

## 5d. Derivatives datasets (implemented in Phase 8)

`<a>` ∈ {btc, eth, sol, xrp} for perpetual data; {btc, eth} for Deribit. Perpetuals are the USDT-margined ones
(`<A>USDT`, `<A>-USDT-SWAP`). Each venue is its own series (`obs.series.venue` ∈ {`binance`, `okx`, `deribit`}).

| Dataset ID | Subject | Values (unit) | Providers | `available_at` |
|---|---|---|---|---|
| `deriv.open_interest.<a>.1h` | `PERP:<A>-USDT` | open interest in coins (`<a>`), hourly snapshot on the hour | Binance `openInterestHist` (`sumOpenInterest`), OKX `open-interest-history` (`oiCcy`) | snapshot + 5 min (receipt time if earlier) |
| `deriv.funding_rate` | `PERP:<A>-USDT` | funding rate per settlement interval (`ratio`; positive = longs pay shorts) | Binance `fundingRate`, OKX `funding-rate-history` (`fundingRate`) | settlement + 1 min (receipt time if earlier) |
| `deriv.long_short_account_ratio.1h` | Binance `PERP:<A>-USDT`; OKX `CONTRACTS:<A>` | accounts net long ÷ accounts net short (`ratio`) — different populations per venue, never combined | Binance `globalLongShortAccountRatio`, OKX `long-short-account-ratio` | snapshot + 5 min (receipt time if earlier) |
| `deriv.liquidations.<a>.1h` | `PERP:<A>-USDT:long` / `:short` | coins liquidated in the hour (Σ contracts × `ctVal`); 0 = no orders in a fully read hour | OKX `liquidation-orders` (+ `instruments` for `ctVal`) | hour end + 2 min |
| `deriv.volatility_index.1h` | `DVOL:<A>` | Deribit DVOL close of the hour (`ratio`; percent ÷ 100); `event_time` = hour start | Deribit `get_volatility_index_data` | hour end + 2 min |
| `deriv.futures_curve.<a>` | `DERIBIT:<instrument>` | `obs.derivative_quote` rows for dated futures and the perpetual (unit `usd`) | Deribit `get_book_summary_by_currency?kind=future` | Deribit response time (`usOut`; receipt time if Deribit's clock is ahead) |
| `deriv.option_chain.<a>` | `DERIBIT:<instrument>` | `obs.derivative_quote` rows for every option (mark in coins; `mark_iv` ratio) | Deribit `…?kind=option` | as above |

History loaded once, one chunk per run: open interest and account ratios ~1 month (Binance 29 d, OKX 28 d), funding
365 d (Binance) / 90 d (OKX), DVOL 365 d. Deribit snapshots (futures hourly, options every 4 h) and OKX liquidations
(~1 day retained) accumulate from the first run. USD amounts are calculated at read time: coins × the Coinbase USD
close of the hour ending at the snapshot (`market.ohlcv.usd.1h`).

### Derivatives calculated metrics (read time, point-in-time — ADR-0050)

```
oi_change_24h / oi_change_7d:  Σ OI (coins) of the venues with a value now AND 24 h / 7 d earlier (± 1 h)
                               ÷ the same venues' earlier sum − 1; "now" = newest snapshot ≤ 3 h old
oi_expansion / contraction:    change_24h ≥ +5 % or change_7d ≥ +15 % / ≤ −5 % or ≤ −15 % (both: "mixed")
leverage_ratio:                Σ OI coins × Coinbase USD close ÷ market cap (CoinGecko daily, ≤ 2 days old)
leverage_change_7d:            ratio now ÷ ratio 7 d earlier − 1 (same venues); expansion ≥ +10 %, reduction ≤ −10 %
funding_annualised_7d:         Σ rates settled in (as_of − 7 d, as_of] × 365 ÷ 7, per venue; only when no gap
                               between settlements (or window edges) exceeds 9 h; venues OI-weighted
funding_extreme:               |funding_annualised_7d| ≥ 30 %
basis_annualised:              (future mark ÷ index − 1) × 365 ÷ days to expiry (≥ 1 day)
basis_headline:                dated future closest to 90 days to expiry, at least 14 days; extreme ≥ +20 % or ≤ −5 %
perpetual_premium:             perpetual mark ÷ index − 1 (context)
liquidations_24h:              Σ long + short over the last 24 complete hours (all 24 present); ÷ OKX OI (coins)
liquidation_event:             hour total ≥ 5 × median of the earlier hours in the 7-day window (≥ 24 of them) and
                               ≥ 0.05 % of OKX OI
put_call_oi / put_call_volume: Σ put ÷ Σ call open interest / 24 h volume (contracts = coins), whole chain
atm_iv:                        mean mark IV of call and put at the strike nearest the forward (median underlying of
                               the expiry closest to 30 days, ≥ 7 d)
skew_10pct:                    IV(put nearest 0.9 F) − IV(call nearest 1.1 F), strikes within ± 3 % of the targets
price_oi_context:              Coinbase price 24 h change vs OI 24 h change (± 1 %): a plain sentence, no direction call
```

### Derivatives Health Score (`derivatives_health_score`, calculated metric — ADR-0050, ADR-0051)

```
version:          derivatives_health_v1 (versioned, immutable parameter set — see
                  cfi/derivatives/score_parameters.py; a future revision publishes a new version id rather
                  than editing this one, so a past score stays reproducible against the parameters that
                  produced it)
range:            0 … 100, 100 = no sign of stress; derivatives_stress = 100 − health
components:       direction-neutral stress = clip(metric ÷ scale, 0, 1)
  funding_annualised_7d_abs.v1            weight 0.25   |funding_annualised_7d| ÷ 30 %
  futures_basis_annualised_outside_band.v1 weight 0.15  distance of the headline basis outside 0 … 10 % ÷ 15 %
  leverage_ratio_change_7d_abs.v1         weight 0.20   |leverage_change_7d| ÷ 20 %
  liquidations_24h_pct_oi.v1              weight 0.20   liquidations_24h ÷ OKX OI ÷ 1 %
  dvol_level.v1                           weight 0.20   (DVOL − calm) ÷ (stressed − calm); BTC 30 → 80 %, ETH 40 → 100 %
health:           100 × (1 − Σ weight × stress ÷ Σ available weights), 1 decimal
missing_policy:   component excluded without complete inputs (never filled); basis and DVOL "not applicable" for
                  SOL and XRP; "Insufficient data" below weight 0.5 (min_available_weight, itself a versioned
                  parameter)
bands:            ≥ 75 low stress · ≥ 50 moderate stress · ≥ 25 elevated stress · below: high stress (band
                  boundaries are also a versioned parameter)
context:          direction shown per component (who pays funding, contango/backwardation, long vs short
                  liquidations, leverage building/unwinding) — never scored, never bullish/bearish
reproducibility:  every result records `parameter_version` (the version actually used) and `calculated_at`
                  (wall-clock computation time, distinct from `as_of`, the point-in-time market snapshot the
                  inputs describe) alongside every component's value, stress, effective weight, contribution,
                  calculation string and inputs — sufficient to audit or recompute the result later
semantic_note:    fixed API/UI text: "Higher Derivatives Health Score means lower measured derivatives stress
                  across the available components. It is not a probability of price increase and does not
                  indicate market direction."
parameters_note:  v1 methodology / initial parameters, chosen by design and not fitted to data or empirically
                  validated — never described as "validated"; to be reviewed against stored history once
                  enough accumulates (Phases 15-16)
shared_input_note: (Phase 18, RED_TEAM_REPORT.md finding #7 / ADR-0064) always-present string field:
                  `liquidations_24h_pct_oi.v1` is sourced from a single venue (OKX), see single_venue_caveat
                  below; separately, this score's own funding component and `cfi.retail`'s Retail Speculation
                  Score's `funding_rate_bias` component (0.40 weight there) derive from the same underlying
                  funding-rate series — disclosed here and reciprocally on that score, so neither reads as
                  independent evidence of the other
single_venue_caveat: (Phase 18, RED_TEAM_REPORT.md finding #9 / ADR-0064) the `liquidations_24h_pct_oi.v1`
                  component's `context` field always includes a caveat that its liquidation data is OKX-only,
                  understating true cross-venue liquidation stress during venue-specific events
owner_phase:      8 (addendum: 2026-09-26, parameter externalisation and reproducibility fields);
                  18 (2026-09-27, disclosure notes — no methodology change)
status:           implemented
```

---

## 5e. Liquidity / stablecoin datasets (implemented in Phase 9)

Sole provider: **DefiLlama** (`stablecoins.llama.fi`, free, keyless). Sole dataset, three subjects.

| Dataset ID | Subject | Values (unit) | Provider | `available_at` |
|---|---|---|---|---|
| `liquidity.stablecoin_supply.1d` | `STABLECOIN:USDT` / `STABLECOIN:USDC` / `STABLECOIN:TOTAL` | circulating supply, one value per calendar day, aggregated across every chain (`usd`) | DefiLlama `/stablecoincharts/all` (`?stablecoin=1` USDT, `?stablecoin=2` USDC, no param = every stablecoin tracked = TOTAL) | `event_time` (UTC midnight of the day) + 36 h (receipt time if earlier) |

`TOTAL` is every stablecoin DefiLlama tracks (USDT, USDC and every other one), not the sum of the two tracked
individually. DefiLlama's chart endpoint takes no date-range parameters — every call returns its **entire**
history in one response; the adapter (`cfi/providers/defillama.py`) fetches it every time and filters client-side
to the requested window (`parse_page`). History loaded once, one 180-day chunk per run, back to a generous depth
(DefiLlama's stablecoin charts start November 2017).

**Not tracked** (`NOT_TRACKED`, `cfi/liquidity/universe.py`) — no free source found for any of these:

- Exchange stablecoin balances and stablecoin exchange flows (would need labelled on-chain address attribution;
  paid providers only: Nansen, Arkham, CryptoQuant). The "exchange liquidity change" calculation this phase was
  asked for is defined (`liquidity/metrics.py:exchange_liquidity_change`) but always reports `unavailable` — a
  named, visible gap, never a silently omitted field, and never folded into the Liquidity Score.
- Individual mint/burn transactions: day-over-day change in stored circulating supply is used as the observable
  proxy for net minting/burning instead (stated plainly wherever shown, never presented as an exact event count).
- Stablecoins beyond USDT and USDC tracked individually (DAI, USDe, USDS, … count only inside `TOTAL`).

### Liquidity calculated metrics (read time, point-in-time — `cfi/liquidity/metrics.py`)

```
supply_growth (24h/7d/30d):  supply now ÷ supply N days earlier − 1, per subject ("now" ≤ 36 h old)
growth / contraction:        24 h ≥ +1 % or 7 d ≥ +3 % or 30 d ≥ +8 % (and the negatives; disagreement: "mixed")
market_share:                subject circulating supply ÷ TOTAL circulating supply, same stored snapshot time
growth_acceleration:         7-day growth rate ending now − 7-day growth rate ending 7 days earlier, for TOTAL
acceleration / deceleration: |change in the 7-day rate| ≥ 2 percentage points, either direction
exchange_liquidity_change:   always "unavailable" (see Not tracked, above) — never a scored component
```

### Liquidity Score (`liquidity_score`, calculated metric — ADR-0052)

```
version:          liquidity_score_v1 (versioned, immutable parameter set from the start — see
                  cfi/liquidity/score_parameters.py, following the Derivatives Health Score addendum's pattern;
                  a future revision publishes a new version id rather than editing this one)
range:            −100 … +100, signed (unlike the direction-neutral Derivatives Health Score): higher = stronger
                  measured growth in the tracked stablecoin supply
components:       sub-score = clip(7-day change (or acceleration change) ÷ scale, −1, +1)
  usdt_growth_7d        weight 0.30   USDT 7-day supply growth ÷ 5 %
  usdc_growth_7d        weight 0.30   USDC 7-day supply growth ÷ 5 %
  total_growth_7d       weight 0.25   TOTAL 7-day supply growth ÷ 4 %
  growth_acceleration   weight 0.15   change in TOTAL's 7-day growth rate ÷ 3 percentage points
score:            100 × Σ(weight × sub-score) ÷ Σ(weights of available components), 1 decimal
missing_policy:   component excluded without a complete 7-day (or acceleration) window (never filled);
                  "Insufficient data" below available weight 0.5 (min_available_weight, versioned parameter)
bands:            ≥ 50 strong liquidity expansion · ≥ 15 liquidity expansion · ≥ −15 stable ·
                  ≥ −50 liquidity contraction · below: strong liquidity contraction (versioned parameter)
reproducibility:  every result records `parameter_version` and `calculated_at` alongside every component's
                  value, sub-score, effective weight, contribution and calculation string
semantic_note:    fixed API/UI text: "Higher Liquidity Score means stronger measured growth in the stablecoin
                  supply this platform tracks (USDT, USDC, and DefiLlama's total). It is not a probability of
                  price increase and does not indicate market direction."
parameters_note:  v1 methodology / initial parameters, chosen by design and not fitted to data or empirically
                  validated — never described as "validated"
measurement_class: (Phase 18, RED_TEAM_REPORT.md finding #8 / ADR-0064) always `"proxy"` — an always-present
                  field, mirroring `cfi.retail.metrics`'s existing convention
proxy_caveat:     (Phase 18, ADR-0064) always-present string field disclosing at read time (not just in this
                  document) that this score measures stablecoin *supply growth*, not market liquidity or peg
                  stability directly (the proxy relationship itself was already documented — ADR-0052 — but
                  was not previously visible in the API response)
owner_phase:      9 (2026-09-26); 18 (2026-09-27, proxy disclosure fields — no methodology change)
status:           implemented
```

---

## 5f. Retail activity datasets (implemented in Phase 10)

**Every metric in this section carries `measurement_class = "proxy"` — never `"direct"`.** No source found
publishes data identified by its provider as retail-only (no exchange or vendor segments its public data by
account type), so nothing here is DIRECT RETAIL DATA (`cfi/retail/universe.py`, `cfi/retail/metrics.py`).

| Dataset ID | Subject | Values (unit) | Provider | `available_at` |
|---|---|---|---|---|
| `retail.trending_coin_rank` | dynamic — every coin CoinGecko returns each poll (asset = its ticker symbol) | position in the top ~15 trending-by-search list, 0 = most trending that poll (`rank`) | CoinGecko `/search/trending` (free, keyless) | receipt time (the endpoint carries no timestamp of its own) |
| `retail.small_output_count.btc.1d` | `BTC` | count of Bitcoin transaction outputs valued under $1,000 (Blockchair's `value_usd`), per UTC day (`count`) | Blockchair `/bitcoin/outputs` aggregation (already used for whale intelligence, Phase 7) | day end + 2 h |

Two further datasets are **read, not re-ingested** — owned and already ingested by the Derivatives module
(Phase 8), read here as a deliberate cross-module read (R2's layer rule restricts which *layers* a module reads,
not which module's job wrote a given L1 row): `deriv.funding_rate` and `deriv.long_short_account_ratio.1h`,
filtered to `venue = "binance"` only (Binance and OKX publish the ratio for different account populations that
are never blended — see `cfi.derivatives.universe.LONG_SHORT_RATIO`'s docstring, and `cfi/retail/queries.py`).

**Not tracked** (`NOT_TRACKED`, `cfi/retail/universe.py`) — each a business/licensing decision, not a technical
dead end, restated in `TODO.md` for the user's review:

- **Google Trends** — no official public API; the supported route (Google Cloud BigQuery public dataset) needs a
  paid billing account, and the commonly used unofficial scrape of `trends.google.com` is not authorised by
  Google's terms of service for sustained automated use.
- **Reddit activity** (post/comment volume, sentiment) — Reddit's API is metered/paid beyond a small
  non-commercial free allowance (since 2023, confirmed still in effect 2026).
- **Social activity (Twitter/X and similar)** — no free tier supports search or aggregate content retrieval;
  meaningful read access needs a paid API tier.

### Retail calculated metrics / statistical signals (read time, point-in-time — `cfi/retail/metrics.py`)

```
percentile_rank:              nearest-rank percentile (0-100) of a current value against its own trailing
                               history; "insufficient_history" below a 20-point sample (L3 Statistical Signal)
derivatives_proxy:             average, across every tracked perp with a fresh (≤ 6 h) reading, of Binance's
                               funding rate and "global" long/short account ratio — RETAIL PROXY
meme_coin_activity:            presence and rank of a curated, non-exhaustive meme-coin list (DOGE, SHIB, PEPE,
                               WIF, BONK, FLOKI) within the latest trending-coin snapshot (≤ 8 h old) — RETAIL PROXY
small_transaction_activity:    latest small-output-count day (≤ 3 days old), its trailing 7-day average, and the
                               percent change between them — RETAIL PROXY, not filtered for change outputs,
                               exchange-internal batching, or dust
```

### Retail Activity Score (`retail_activity_score`, calculated metric — ADR-0053)

```
version:          retail_activity_score_v1 (versioned, immutable parameter set — cfi/retail/score_parameters.py)
range:            0 … 100, unsigned: "how elevated is retail-proxy activity right now, relative to its own
                  recent history" — a level/intensity reading, not a direction
components:       each component is already a 0-100 historical percentile; weighted average, no reference scale
  small_tx_percentile              weight 0.35   small-output-count historical percentile
  meme_trending_percentile         weight 0.30   meme-coin trending-count historical percentile
  derivatives_turnover_percentile  weight 0.35   |account ratio − 1| historical percentile
score:            100 × Σ(weight × percentile/100) ÷ Σ(weights of available components), 1 decimal
missing_policy:   component excluded when its percentile is "insufficient_history" (never filled);
                  "Insufficient data" below available weight 0.5 (min_available_weight, versioned parameter)
bands:            ≥ 80 elevated · ≥ 60 above-normal · ≥ 40 typical · ≥ 20 below-normal · below: quiet
                  retail-proxy activity (versioned parameter)
owner_phase:      10 (2026-09-26)
status:           implemented
```

### Retail Speculation Score (`retail_speculation_score`, calculated metric — ADR-0053)

```
version:          retail_speculation_score_v1 (versioned, immutable parameter set)
range:            −100 … +100, signed: does the tracked proxy data lean toward crowded, long-biased leveraged
                  positioning, short-biased, or balanced
components:       sub-score = clip(value ÷ scale, −1, +1); the meme-trending component is UNSIGNED (always ≥ 0
                  — a count can only push the score up, never down; documented via `ComponentDef.directional`)
  funding_rate_bias      weight 0.40   avg funding rate ÷ 0.0005
  account_ratio_skew     weight 0.40   (avg account ratio − 1) ÷ 0.5
  meme_trending          weight 0.20   meme coins currently trending ÷ 2 (unsigned)
score:            100 × Σ(weight × sub-score) ÷ Σ(weights of available components), 1 decimal
missing_policy:   component excluded when its underlying proxy is "unavailable"; "Insufficient data" below
                  available weight 0.4 (min_available_weight, versioned parameter)
bands:            ≥ 50 strong long-biased · ≥ 15 long-biased · ≥ −15 balanced · ≥ −50 short-biased ·
                  below: strong short-biased speculative skew (versioned parameter)
reproducibility:  every result (both scores) records `parameter_version` and `calculated_at` alongside every
                  component's value, sub-score, effective weight, contribution and calculation string
semantic_note:    fixed API text for both scores states plainly that every input is a proxy, never data
                  identified by its source as retail-only, and neither score is a probability or prediction
parameters_note:  v1 methodology / initial parameters, chosen by design and not fitted to data or empirically
                  validated — never described as "validated"
shared_input_note: (Phase 18, RED_TEAM_REPORT.md finding #7 / ADR-0064) Speculation score only (Activity
                  carries no such field — its `shared_input_note` is always `null`): an always-present string
                  disclosing that `funding_rate_bias` (0.40 weight here) derives from the same underlying
                  series as the Derivatives Health Score's own funding component, so the two scores must not
                  be read as independent evidence of the same thing
owner_phase:      10 (2026-09-26); 18 (2026-09-27, shared-input disclosure — no methodology change)
status:           implemented
```

---

## 5g. Macroeconomic datasets (implemented in Phase 11)

All 18 datasets in this section come from a single provider, the **official FRED (Federal Reserve Economic
Data) keyed JSON API** (`cfi/providers/fred.py`, `cfi/macro/universe.py`) — chosen over FRED's undocumented
keyless `fredgraph.csv` download endpoint because only the JSON API is documented and versioned. Requires
`CFI_PROVIDER_FRED_API_KEY` (free, user-obtained; not optional — same pattern as SoSoValue, Phase 6).
`subject` is always `US` — every series in this phase is a US macro series.

| Dataset ID | Cadence | FRED series | Values (unit) | `available_at` |
|---|---|---|---|---|
| `macro.dxy_broad_proxy.1d` | daily | `DTWEXBGS` | Fed Broad Dollar Index (index, **DXY SUBSTITUTE** — see note below) | day end + 1 day |
| `macro.ust_yield_2y.1d` | daily | `DGS2` | US 2-year Treasury yield (%) | day end + 1 day |
| `macro.ust_yield_10y.1d` | daily | `DGS10` | US 10-year Treasury yield (%) | day end + 1 day |
| `macro.fed_funds_effective.1d` | daily | `DFF` | Effective federal funds rate (%) | day end + 1 day |
| `macro.vix.1d` | daily | `VIXCLS` | CBOE Volatility Index (index) | day end + 1 day |
| `macro.sp500.1d` | daily | `SP500` | S&P 500 close (index) | day end + 1 day |
| `macro.nasdaq_composite.1d` | daily | `NASDAQCOM` | Nasdaq Composite close (index) | day end + 1 day |
| `macro.oil_wti.1d` | daily | `DCOILWTICO` | WTI crude spot price (USD/barrel) | day end + 1 day |
| `macro.reverse_repo.1d` | daily | `RRPONTSYD` | Overnight reverse repo, Treasury securities (USD billions) | day end + 1 day |
| `macro.fed_balance_sheet.1w` | weekly | `WALCL` | Fed total assets, weekly (USD millions) | week end + 3 days |
| `macro.treasury_general_account.1w` | weekly | `WTREGEN` | Treasury General Account balance, weekly (USD millions) | week end + 3 days |
| `macro.m2_money_stock.1w` | weekly | `WM2NS` | M2 money stock, weekly, not seasonally adjusted (USD billions) | week end + 3 days |
| `macro.cpi.1mo` | monthly | `CPIAUCSL` | CPI, all urban consumers, seasonally adjusted (index) | published (event) + 45 days (est., `known_when_received`) |
| `macro.pce_price_index.1mo` | monthly | `PCEPI` | PCE price index (index) | published (event) + 60 days (est., `known_when_received`) |
| `macro.unemployment_rate.1mo` | monthly | `UNRATE` | Civilian unemployment rate (%) | published (event) + 38 days (est., `known_when_received`) |
| `macro.m2_money_stock.1mo` | monthly | `M2SL` | M2 money stock, monthly, seasonally adjusted (USD billions) | published (event) + 52 days (est., `known_when_received`) |
| `macro.fed_funds_target_upper.event` | event | `DFEDTARU` | FOMC target rate, upper bound (%) | event + 1 day (est., `known_when_received`) |
| `macro.fed_funds_target_lower.event` | event | `DFEDTARL` | FOMC target rate, lower bound (%) | event + 1 day (est., `known_when_received`) |

**Point-in-time note (revised series):** CPI, PCE, unemployment and M2 are subject to later revision by their
publisher. FRED's default API returns only the current (most-revised) vintage, not the value as first
published; true vintage tracking is available via FRED's own `realtime_start`/`realtime_end`/`vintage_dates`
parameters but was deliberately not built this phase (CLAUDE.md R13 — not requested). Instead, conservative
documented release-schedule delays are used (`event_time_plus` + `known_when_received=True`), which is the
same conservative-estimate pattern as Phase 9's DefiLlama 36h-estimated-availability rule.

**Not tracked** (`NOT_TRACKED`, `cfi/macro/universe.py`) — each a verified sourcing gap or scope decision, not
a technical dead end, restated in `TODO.md` for the user's review:

- **Gold spot price** — FRED's only free daily gold series (`GOLDAMGBD228NLBM` / `GOLDPMGBD228NLBM`, the LBMA
  fixing) was discontinued in January 2022 at ICE Benchmark Administration's own request (verified via FRED's
  own removal notice). No other verified $0/keyless replacement was found.
- **True global liquidity aggregate** — `us_net_liquidity` (below) is explicitly a **US-only proxy**
  (Fed balance sheet − TGA − reverse repo), never presented as a true global aggregate, which would need
  China, EU, Japan and other central-bank balance sheets this phase does not source.

**DXY note:** `DTWEXBGS` (the Fed's trade-weighted Broad Dollar Index) is used as a substitute for the real
ICE US Dollar Index (DXY), which is proprietary/licensed and not freely available. Every field and label
referencing it says "DXY substitute", never "DXY".

### Macro calculated metrics / statistical signals (read time, point-in-time — `cfi/macro/metrics.py`)

```
yield_curve_slope:      10-year Treasury yield − 2-year Treasury yield (pp); condition: inverted (≤ −0.10pp),
                         steep (≥ 1.00pp), normal otherwise
real_policy_rate:        effective federal funds rate − trailing 12-month CPI inflation (pp) — an
                         approximation, not the Fed's own preferred real-rate measure
cpi_year_over_year:      CPI now ÷ CPI 12 months earlier − 1 (%)
vix_condition:           latest VIX level; condition: elevated (≥ 25), calm (≤ 15), normal otherwise
trend (generic):         ratio change of a series over a window (default 90 days); condition: up/down (±3%
                         threshold) / flat — used for equities, dollar, oil, and net-liquidity trend
us_net_liquidity:        (Fed balance sheet − Treasury General Account) ÷ 1000 − overnight reverse repo, in
                         USD billions — US-ONLY PROXY, NOT A TRUE GLOBAL AGGREGATE
tolerance windows:       DAILY_TOLERANCE = 7 days, WEEKLY_TOLERANCE = 18 days, MONTHLY_TOLERANCE = 95 days —
                         each sized to a series' worst-case staleness (period length + publication delay)
                         before its next point becomes available, so normal operation never reads as
                         "unavailable"
```

### Macro Environment Score (`macro_environment_score`, calculated metric — ADR-0054)

```
version:          macro_environment_score_v1 (versioned, immutable parameter set — cfi/macro/score_parameters.py)
range:            −100 … +100, signed: how accommodative (positive) or restrictive (negative) the current US
                  macro backdrop looks — NOT a crypto price prediction and NOT a directional trading signal
components:       sub-score = clip(value ÷ scale, −1, +1), each with a documented direction_note explaining
                  which way is accommodative vs. restrictive
  yield_curve_slope        weight 0.20   10y − 2y slope ÷ 1.00pp
  real_policy_rate         weight 0.20   real policy rate ÷ 2.00pp, INVERTED (lower real rate = more accommodative)
  vix_level                weight 0.15   (VIX − 20 reference) ÷ 10, INVERTED (higher VIX = more risk-off)
  equity_trend              weight 0.15   S&P 500 90-day change ÷ 10%
  dollar_trend               weight 0.10   DXY-substitute 90-day change ÷ 5%, INVERTED (stronger dollar = more
                            restrictive for risk assets)
  net_liquidity_trend       weight 0.15   US net-liquidity composite 90-day change ÷ 5%
  oil_trend                 weight 0.05   WTI 90-day change ÷ 15%, INVERTED (rising oil = inflationary pressure)
score:            100 × Σ(weight × sub-score) ÷ Σ(weights of available components), 1 decimal
missing_policy:   component excluded when its underlying metric is "unavailable" (never filled with a
                  default), with automatic renormalisation over the remaining weight; "Insufficient data"
                  below available weight 0.5 (min_available_weight, versioned parameter)
bands:            ≥ 50 broadly accommodative macro backdrop · ≥ 15 leaning accommodative · ≥ −15 neutral ·
                  ≥ −50 leaning restrictive · below: broadly restrictive macro backdrop (versioned parameter)
reproducibility:  every result records `parameter_version` and `calculated_at` alongside every component's
                  value, sub-score, effective weight, contribution and calculation string
semantic_note:    fixed API text states plainly this score does not convert macro data into a deterministic
                  crypto prediction
parameters_note:  v1 methodology / initial parameters, chosen by design and not fitted to data or empirically
                  validated — never described as "validated"
vintage_risk_note: (Phase 18, RED_TEAM_REPORT.md finding #2 / already-accepted limitation, ADR-0054) an
                  always-present string field (present on both `"ok"` and `"insufficient_data"` results,
                  identical either way) disclosing that FRED series carry no point-in-time ("ALFRED") vintage
                  in this platform — every historical reading uses the latest revision, so a past `as_of`
                  query may reflect data that was not actually publicly known at that date. This does not
                  introduce a new limitation; it makes the existing, already-documented ADR-0054 limitation
                  visible at read time rather than only in this document.
owner_phase:      11 (2026-09-27); 18 (2026-09-27, vintage-risk disclosure — no methodology change)
status:           implemented
```

## 5h. Market structure datasets (implemented in Phase 12)

Only **one** dataset is directly ingested this phase — everything else is a **Calculated Metric** (R2) derived
at read time from datasets Phase 5/6 already ingest (daily OHLCV bars, per-asset market caps), never
re-ingested.

| Dataset ID | Cadence | Provider | Values (unit) | `available_at` |
|---|---|---|---|---|
| `market_structure.total_market_cap.usd` | ~5 min (event) | CoinGecko `/global` | Total market capitalisation across every cryptocurrency CoinGecko tracks (USD) | provider (event time = provider's last update time) |

`asset` and `subject_ref` are both the sentinel `GLOBAL` (`cfi.market_structure.universe.GLOBAL_SUBJECT`) —
one global reading, no per-asset dimension (same pattern as Phase 9's `TOTAL_SUBJECT` and Phase 10's
`TRENDING_SUBJECT`).

**Reused, not re-ingested:** daily OHLCV bars (`market.ohlcv.usd.1d`, Coinbase Exchange — Phase 5's
priority-10 default venue, so all four tracked assets are compared on the same venue/timeframe) and per-asset
market capitalisation (`market.market_cap.usd`, Phase 5/6).

**Not tracked** (`NOT_TRACKED`, `cfi/market_structure/universe.py`):

- **Full-market breadth** — no free source publishes an advance/decline line across the whole crypto market
  (thousands of listed assets). Market breadth here is a proxy limited to the four assets this platform
  already tracks (BTC, ETH, SOL, XRP) — the fraction of them trading above their own 50-day moving average —
  never presented as full-market breadth.
- **Full market-cap-weighted TOTAL/TOTAL2/TOTAL3 constituent breakdown** — TOTAL2/TOTAL3 are calculated (TOTAL
  minus BTC's, then BTC+ETH's, market cap), matching the common charting convention (e.g. TradingView's
  CRYPTOCAP:TOTAL2/TOTAL3), never a directly observed value from any provider.

### Market-structure calculated metrics (read time, point-in-time — `cfi/market_structure/metrics.py`)

```
moving_averages:         simple moving average (SMA) over 20/50/200 daily bars
trend:                   uptrend: close > SMA50 > SMA200; downtrend: close < SMA50 < SMA200; mixed otherwise
rsi:                     Wilder's 14-day relative strength index; overbought ≥ 70, oversold ≤ 30, neutral
                         otherwise
atr:                     Wilder's 14-day average true range, as a percentage of price, ranked as a nearest-
                         rank percentile of its own trailing 365-day history (minimum 20 readings); elevated
                         ≥ 80th percentile, low ≤ 20th, normal otherwise
volatility:              annualized standard deviation of 30-day rolling daily log returns (std × √365), ranked
                         the same way as ATR
volume_trend:            latest daily volume vs. the trailing 20-day average (excluding the latest bar);
                         elevated ≥ 1.5x, low ≤ 0.5x, normal otherwise
vwap:                    rolling 20-day volume-weighted average price (Σ(typical price × volume) ÷ Σvolume) —
                         a rolling-window approximation, NOT a session-anchored intraday VWAP
relative_strength:       trailing 30-day return minus BTC's trailing 30-day return; outperforming ≥ +5pp,
                         underperforming ≤ −5pp, in_line otherwise — always benchmarked against BTC
support_resistance:      naive rolling 20-day and 50-day high (resistance) / low (support) — a Donchian-
                         channel-style method, never fitted or clustered
market_breadth:          fraction of the tracked universe (BTC, ETH, SOL, XRP) trading above its own 50-day
                         SMA; broad_advance ≥ 75%, broad_decline ≤ 25%, mixed otherwise
dominance_total_family:  BTC/ETH dominance = asset market cap ÷ TOTAL × 100; TOTAL2 = TOTAL − BTC market cap;
                         TOTAL3 = TOTAL2 − ETH market cap
eth_btc:                 ETH close ÷ BTC close (same venue/quote), plus its own 90-day trend (±3pp threshold)
```

### Market Structure Score (`market_structure_score`, calculated metric — ADR-0055)

```
version:          market_structure_score_v1 (versioned, immutable parameter set —
                  cfi/market_structure/score_parameters.py)
range:            −100 … +100, signed: how constructive (positive) or deteriorated (negative) the current
                  technical structure looks — NOT a trading recommendation and NOT a directional signal
components:       sub-score = clip(value ÷ scale, −1, +1)
  price_trend                  weight 0.25   BTC (close ÷ SMA200 − 1) ÷ 0.20
  momentum                     weight 0.20   BTC (RSI(14) − 50) ÷ 50
  market_breadth                weight 0.20   (tracked-universe fraction above 50-day SMA − 0.5) ÷ 0.50
  altcoin_relative_strength     weight 0.20   average ETH/SOL/XRP 30-day spread vs. BTC ÷ 0.15
  volatility_regime             weight 0.15   (BTC realized-volatility percentile − 50) ÷ 50, INVERTED (calmer
                                than usual = more constructive)
score:            100 × Σ(weight × sub-score) ÷ Σ(weights of available components), 1 decimal
missing_policy:   component excluded when its underlying metric is "unavailable" (never filled with a
                  default; altcoin_relative_strength averages whichever of ETH/SOL/XRP are available, subject
                  to `MIN_ALTCOIN_COUNT` below), with automatic renormalisation over the remaining
                  weight; "Insufficient data" below available weight 0.5 (min_available_weight, versioned
                  parameter)
altcoin_floor:    (Phase 18, RED_TEAM_REPORT.md finding #6 / ADR-0063) `MIN_ALTCOIN_COUNT = 2` — the
                  altcoin_relative_strength component is `"unavailable"` (not just averaged over fewer
                  inputs) whenever fewer than 2 of the 3 tracked altcoins (ETH/SOL/XRP) have a reading, not
                  only when all 3 are missing. A single idiosyncratic altcoin move can no longer stand in for
                  the whole 20%-weighted component.
bands:            ≥ 50 broadly constructive technical structure · ≥ 15 improving · ≥ −15 neutral/mixed · ≥ −50
                  deteriorating · below: broadly weak technical structure (versioned parameter)
reproducibility:  every result records `parameter_version` and `calculated_at` alongside every component's
                  value, sub-score, effective weight, contribution and calculation string
semantic_note:    fixed API text states plainly this score does not convert these metrics into an automatic
                  trading recommendation
parameters_note:  v1 methodology / initial parameters, chosen by design and not fitted to data or empirically
                  validated — never described as "validated"
owner_phase:      12 (2026-09-27); 18 (2026-09-27, altcoin-count floor — no other methodology change)
status:           implemented
```

## 5i. Capital Flow Divergence Engine (implemented in Phase 13)

**No datasets ingested.** `cfi/divergence/` reads nothing from any provider and writes nothing new to the
database — it is pure computation, at read time, over data Phases 5–12 already ingested or already calculate
(reused via each domain's own already-tested public service methods, never raw queries, except macro's
net-liquidity recompute and price bars — see ADR-0056). Every value it produces is either a Calculated Metric
(L2) or a Statistical Signal (L3); it never classifies a Regime (L4) and it is not an AI Interpretation (L5) —
`evidence_note` on every response states this plainly.

### "As-of style" window reading (`cfi/divergence/metrics.py::window_reading`)

```
method:           direction/magnitude = (latest known value at-or-before as_of) minus (latest known value
                  at-or-before as_of − window_days) — carries the last known reading forward for series that
                  update less than daily (e.g. weekly macro releases); never an invented interpolation
window_days:      3–180, default 30 (cfi.divergence.universe)
direction:        up / down / flat (delta == 0) / unavailable (missing endpoint)
status:           ok · insufficient_data (with a reason: no point at-or-before as_of, or none before the
                  window start)
```

### Historical percentile (reused, not reimplemented)

`cfi.divergence.metrics.magnitude_and_percentile` reuses `cfi.retail.metrics.percentile_rank` unchanged
(nearest-rank, tie-tolerant, 0–100; `status = insufficient_history` below `MIN_PERCENTILE_SAMPLE = 20` rolling
daily deltas over a 400-day load span).

### Duration and historical examples (new methodology — genuine gap, no prior helper existed)

```
duration:           backward walk counting consecutive days sharing today's (direction_a, direction_b)
                    combination; capped at MAX_DURATION_LOOKBACK_DAYS = 180 (flagged capped=true)
historical_examples: scans the loaded lookback (excluding the current streak) for prior runs sharing today's
                    direction combination; ranks each by the peak historical percentile of |delta_a| reached
                    during that run; reports only runs at EPISODE_PERCENTILE_THRESHOLD = 70 or above, most
                    recent first, capped at MAX_HISTORICAL_EXAMPLES = 3
```

### Deterministic evidence rules (`cfi.divergence.metrics.evidence`)

Rule-based, not AI-generated — every bullet cites a number already computed elsewhere in the same response
(an L3 Statistical Signal fact, never an L5 AI Interpretation): percentile ≥ 80 → top-quintile supporting;
percentile 40–60 → near-median contradicting; `insufficient_history` → contradicting; duration ≥ `window_days`
→ supporting; duration ≤ 1 day → contradicting; both legs' data quality `ok` → supporting, otherwise
contradicting per leg.

### The 10 standardized comparisons (`cfi/divergence/comparisons.py`)

| # | `comparison_id` | Leg A | Leg B | Scope note |
|---|---|---|---|---|
| 1 | `institutional_vs_retail` | Institutional net flow (ETF) | Retail small-tx count | shared asset |
| 2 | `institutional_vs_price` | Institutional net flow (ETF) | Price close | leg A asset-scoped |
| 3 | `whale_vs_retail` | Whale net flow | Retail small-tx count | shared asset |
| 4 | `whale_vs_price` | Whale net flow | Price close | shared asset |
| 5 | `liquidity_vs_price` | Combined USDT+USDC supply (TOTAL) | Price close | no asset scope on leg A |
| 6 | `open_interest_vs_price` | Raw OI aggregate level | Price close | shared asset |
| 7 | `funding_vs_price` | Funding rate | Price close | shared asset |
| 8 | `stablecoin_supply_vs_price` | USDT supply alone (single-issuer) | Price close | distinct from #5 by design |
| 9 | `leverage_vs_price` | Leverage-skew proxy: mean \|long/short account ratio − 1\| across venues | Price close | distinct from #6 by design |
| 10 | `macro_vs_market_structure` | US net liquidity (recomputed) | TOTAL crypto market cap | substitutes for the Market Structure Score, which has no ranged history (Phase 12 gap, `NOT_TRACKED`) |

Comparisons #5/#8 and #6/#9 look redundant at a glance; each pair is deliberately built from a genuinely
distinct underlying metric (documented in each `ComparisonDef.notes`) rather than merged, so neither is
silently narrowed.

`standard_matrix(short_a, short_b)` always emits the same 4 named cells in the user's specified order
(`↑/↑`, `↑/↓`, `↓/↑`, `↓/↓`); `whale_vs_retail`'s matrix — built from the same generic function — naturally
includes the two explicitly requested cross-cells (`Whale ↑ / Retail ↓`, `Whale ↓ / Retail ↑`).
`is_divergent()` is `true` only for a strict opposite up/down pair, never for flat/unavailable legs.

### The Capital Flow Map (`cfi/divergence/capital_flow_map.py`)

A versioned 12-node chain, in the user's specified order:

```
institutions → whales → liquidity → btc → eth → sol → large_caps → mid_caps → defi → ai_related
→ meme_assets → retail
```

| Node | `measurement_class` | Note |
|---|---|---|
| institutions, whales, liquidity, btc, eth, sol, retail | `observed` | directly computed from tracked data |
| large_caps | `proxy` | XRP price stands in for "large caps" — the only additional tracked large-cap asset beyond BTC/ETH/SOL |
| mid_caps, defi, ai_related | `unavailable` | `fetch_key=None` — no asset-category taxonomy for these exists anywhere in the platform; honestly marked rather than populated with fabricated or loosely-related data |
| meme_assets | `proxy` | retail's meme-trending-count — an explicitly-labelled retail **attention** proxy, NOT an observed capital flow |

**OBSERVED FLOW vs. INFERRED ROTATION (`classify_edge`, R1/R3):** an edge between two adjacent nodes only ever
emits a `possible_rotation` hypothesis, `evidence_class = "inferred"`, when the two nodes move in strictly
opposite directions over the same window — worded as "consistent with (but not proof of) ...; no transfer
between these nodes is directly observed." Same-direction pairs get `no_rotation_signal`; any node with an
unknown or unavailable direction gets `status = "unavailable"` and no hypothesis is emitted at all. The engine
never states that money moved between assets.

```
owner_phase:      13 (2026-09-27)
status:           implemented
```

## 5j. Market Regime Engine (implemented in Phase 14)

**No datasets ingested.** `cfi/regime/` reads nothing from any provider — pure computation, the same posture as
`cfi/divergence/` (Phase 13). Every underlying value is a Calculated Metric or Statistical Signal already
published by its own domain module (institutional, whale, retail, liquidity, derivatives, macro, market
structure); the regime label and confidence produced here are this platform's first **Regime Classification
(L4)**: "a labelled market state produced by a versioned model, with confidence" (R2). It is never an AI
Interpretation (L5) and never a price forecast.

**Confidence semantics (the user's explicit instruction, restated everywhere this value appears):** confidence
measures how well *current, already-observed conditions* satisfy a regime's own definition. It is **NOT** a
probability that price will rise or fall, and it is not a trading recommendation.

### The seven regimes (`cfi/regime/parameters.py`)

| Regime | Definition (summary) |
|---|---|
| Accumulation | Smart money (whale/institutional) building positions quietly while price is flat/declining and retail is disinterested |
| Recovery | An early uptrend forming, confirmed by whale and institutional flow, retail still modest |
| Expansion | A broad-based uptrend: price, breadth and institutional flow all confirming, leverage building but healthy |
| Euphoria | Parabolic price action, retail chasing, speculative leverage extreme, structure overheated |
| Distribution | Smart money exiting while retail remains enthusiastic, momentum quietly weakening |
| Capitulation | Sharp forced selling: extreme derivatives stress, elevated volatility, confirmed downtrend, risk-off macro |
| Mixed / Unclear | The classifier's own fallback — never itself a defined regime (see below) |

### Classification method (`cfi/regime/classifier.py`)

```
inputs:           institutional_score, whale_score, retail_activity_score, retail_speculation_score,
                  liquidity_score, derivatives_health, macro_score, market_structure_score, btc_trend,
                  btc_rsi, btc_volatility_percentile, market_breadth, derivatives_liquidation_event —
                  each read via the owning domain's own already-tested public service method
                  (InstitutionalService.score(), WhaleService.score(), RetailService.overview(),
                  LiquidityService.overview(), DerivativesService.asset(), MacroService.overview(),
                  MarketStructureService.overview()) — never a raw query
benchmark_asset:  BTC (cfi.regime.universe.BENCHMARK_ASSET) — the same "one benchmark" convention as
                  Phases 12/13; a regime describes BTC's own conditions, not necessarily every altcoin's
condition:        one single-metric test (comparator: gte / lte / between / categorical) with a weight;
                  weights within one regime sum to 1; thresholds are anchored, wherever sensible, to the
                  same numeric bands each underlying domain score already publishes (e.g. the +-15/+-50
                  net-inflow bands, the 70/30 RSI levels, the 75%/25% breadth levels) — not fabricated
per-regime score: confidence = matched weight / available weight, restricted to conditions whose
                  underlying metric was "ok"; "insufficient_data" (no confidence) below
                  min_available_weight (0.5, versioned parameter)
decision:         the highest-confidence regime is assigned outright when its confidence is at or above
                  min_confidence_assign (0.55) AND it leads the second-best regime by at least
                  tie_margin (0.08); otherwise the result is "mixed_unclear", with the closest
                  candidate(s) and the specific reason (below threshold, or a close tie) reported
missing_policy:   a regime with too little available data is skipped entirely (never scored as if its
                  missing conditions failed); if every regime is skipped, the result is "mixed_unclear"
                  with status "insufficient_data"
reproducibility:  every classification records its parameter version (regime_classifier_v1 or v2 — see
                  hysteresis below) and the full set of every regime's own candidate score, for transparency
hysteresis:       (Phase 18, RED_TEAM_REPORT.md finding #4 / ADR-0062) `classify()` takes an optional
                  `previous_regime_id`; when the challenger regime's confidence beats the previous regime's
                  own confidence by less than `hysteresis_margin` — while the previous regime still
                  independently clears `min_confidence_assign` — the PREVIOUS regime's result is returned
                  instead, marked `held_by_hysteresis: true` with an explanatory `reason`. Damps single-day
                  boundary flip-flopping without persisting any new state: `RegimeService.current()` supplies
                  `previous_regime_id` via one extra lookback classification call
                  (`as_of - timedelta(days=1)`), and the existing historical backward-walk
                  (`regime_duration`/`historical_examples`) threads each anchor day's own regime_id through
                  the walk at no extra query cost. `regime_classifier_v1`'s `hysteresis_margin = 0` is a
                  no-op (byte-for-byte reproducible); `regime_classifier_v2` (current default) uses `0.05`.
parameters_note:  v1 methodology / initial parameters, chosen by design and anchored to each domain
                  score's own already-published bands where possible — not fitted to data or
                  empirically validated (same posture as every score in this platform)
owner_phase:      14 (2026-09-27); 18 (2026-09-27, hysteresis — regime_classifier_v2)
status:           implemented
```

### Regime start date, duration and historical examples (`cfi/regime/history.py`)

No domain score has a persisted, ranged history of its own (the Market Structure Score gap already documented
in Phase 12/13) — there is no stored regime-history table either. Both of the following work by **re-running
the classifier** at past `as_of` values, two deliberately different, documented performance trade-offs:

```
regime_duration:      walks backward from as_of ONE DAY AT A TIME, re-classifying each day (knowledge_time
                      pinned to that same day, deliberately excluding any later-ingested revision — R4),
                      stopping as soon as the label changes or MAX_DURATION_LOOKBACK_DAYS (120) is reached
historical_examples:  SAMPLES weekly (HISTORICAL_STEP_DAYS=7) further back than the current streak, over
                      HISTORICAL_LOOKBACK_DAYS (365) — a coarser but far cheaper method than the daily
                      duration walk; reports runs of the same regime spanning at least
                      MIN_EPISODE_SAMPLES (2) consecutive weekly samples, most recent first, capped at
                      MAX_HISTORICAL_EXAMPLES (3)
performance_note:     when the current classification itself is "insufficient_data" (no regime could be
                      evaluated at all), both of the above are skipped rather than repeating hundreds of
                      redundant re-classifications on a known-empty result — duration is reported as 0 with
                      no start date, examples as an empty list
```

---

## 5k. Historical Similarity Engine (implemented in Phase 15)

**No datasets ingested.** `cfi/similarity/` reads nothing from any provider — pure computation, the same
posture as `cfi/regime/` (Phase 14) and `cfi/divergence/` (Phase 13). The similarity score is a **Statistical
Signal (L3)**: a documented, fixed-normalization distance between the current 9-feature market state and a
sampled historical date's own state, each read from already-published Calculated Metrics. It is never a
Regime Classification of its own — each analogue's regime label simply cites Phase 14's already-computed
classification for that date — and never an AI Interpretation (L5) or a price forecast.

### The 9 features (`cfi/similarity/parameters.py`, version `similarity_v1`)

| Feature | Weight | Source field | Normalization |
|---|---|---|---|
| Institutional flow score | 0.15 | `InstitutionalService.score()` | shift -100..100 -> 0..100 |
| Whale flow score | 0.15 | `WhaleService.score()` | shift -100..100 -> 0..100 |
| Retail activity score | 0.10 | `RetailService.overview()['activity_score']` | identity (already 0..100) |
| Liquidity score | 0.10 | `LiquidityService.overview()['score']` | shift -100..100 -> 0..100 |
| Perp funding rate (annualised, 7d) | 0.10 | `DerivativesService.asset()['funding']['annualised_7d_pct']` | clamp to [-100, 100]%, linear -> 0..100 |
| Open interest, 7-day change | 0.10 | `DerivativesService.asset()['open_interest']['change_7d_pct']` | clamp to [-50, 50]%, linear -> 0..100 |
| Realized volatility percentile | 0.10 | `MarketStructureService.overview()['assets']['BTC']['volatility']['percentile']` | identity (already a percentile) |
| Market structure score | 0.10 | `MarketStructureService.overview()['score']` | shift -100..100 -> 0..100 |
| Macro score | 0.10 | `MacroService.overview()['score']` | shift -100..100 -> 0..100 |

Weights sum to exactly 1.00. Normalization bounds are **fixed constants, decided once, independent of any
date's own data** (ADR-0058) — never a trailing percentile or a batch min/max, specifically so that no
candidate's similarity score can ever be influenced by data from another date (including a later one).

### Similarity methodology (`cfi/similarity/scorer.py`)

```
inputs:           the 9 features above, gathered for the query date and for each candidate date via
                  cfi.similarity.snapshot.gather_snapshot — each read through the owning domain's own
                  already-tested public service method, never a raw query
comparison:       only features where BOTH dates are "ok" are compared; each contributes
                  weight * (normalized_query - normalized_candidate)^2 to a weighted mean-squared
                  difference over the compared features' combined weight
similarity_score: 100 - sqrt(weighted mean squared difference) — 0..100, 100 = identical normalized
                  profile across every compared feature
missing_policy:   a pair is not scored ("insufficient_data") if the compared features' combined weight is
                  below min_available_weight (0.5) — never a misleadingly precise score from too little
                  evidence (same discipline as cfi.regime.classifier's confidence)
evidence_category: Statistical Signal (L3) — NOT a Regime Classification, NOT a probability, NOT a
                  prediction
owner_phase:      15 (2026-09-27)
status:           implemented
```

### Candidate search and selection (`cfi/similarity/search.py`, `cfi/similarity/universe.py`)

```
sampling:         weekly (STEP_DAYS=7) over a 2-year lookback (LOOKBACK_DAYS=730) — a documented
                  cost/precision trade-off mirroring cfi.regime.history.historical_examples (Phase 14);
                  candidates must be at least MIN_CANDIDATE_AGE_DAYS (14) before the query's own as_of
selection:        candidates ranked by similarity score, highest first; greedily selected only if at
                  least MIN_GAP_DAYS (30) from every already-selected date — so results span genuinely
                  different episodes rather than several consecutive weeks of the same one
detailed_rows:    TOP_N_ANALOGUES (5) — date, similarity score, regime, forward returns, drawdown,
                  volatility, and the per-feature comparison breakdown
distribution_set: a larger, equally de-duplicated superset (MAX_DISTRIBUTION_SAMPLE=15, a superset of
                  the detailed rows) whose forward returns feed the distribution section only — never
                  used to produce a single predicted value
```

### Forward returns, maximum drawdown and volatility (`cfi/similarity/outcomes.py`)

```
forward_return:   % change in BTC close price from the analogue date to analogue_date + horizon_days,
                  for horizons (7, 30, 90) — reported ONLY once that target date is at or before the
                  query's own as_of ("not_yet_known" otherwise, R3: missing is a first-class state);
                  gated structurally, never by what happens to be present in the fetched bar range
                  (proven by a deliberate look-ahead-leak test, per TODO.md's own Phase 15/16 suggestion)
max_drawdown:     largest peak-to-trough decline in BTC close price within [analogue_date,
                  analogue_date + 90 days], truncated to whatever of that window has already elapsed by
                  as_of (marked "partial" when not yet complete — real, observed data, never a
                  projection of the remaining window)
volatility:       the same analogue date's own realized volatility (annualized %, market_structure's
                  volatility.annualized_pct) already fetched as part of its 9-feature snapshot — not a
                  forward-looking measure, no separate recomputation
no_prediction:    the API never produces a single expected/forecast return — only each analogue's own
                  realized outcome, plus a distribution (count, min, p25, median, p75, max) across the
                  broader analogue set per horizon, reported "insufficient_data" below
                  MIN_DISTRIBUTION_SAMPLE (3) analogues rather than a range built from too few points
owner_phase:      15 (2026-09-27)
status:           implemented
```

---

### Backtest performance metrics (`cfi/backtest/metrics.py::BacktestMetrics`, ADR-0059)

```
total_return_pct:          % change in equity from the first to the last EquityPoint
annualized_return_pct:     total growth compounded to a 365-day year (TRADING_DAYS_PER_YEAR — crypto
                           trades every calendar day, unlike equities' 252)
volatility_annualized_pct: population stdev of daily equity returns, annualized (× sqrt(365) × 100)
max_drawdown_pct:          largest peak-to-trough decline in the equity curve (negative, or 0 if the
                           curve never fell below a prior peak)
sharpe:                    (mean daily return − daily risk-free rate) / stdev of daily returns × sqrt(365)
sortino:                   same, but the denominator uses only downside deviation (returns below the
                           daily risk-free rate) — None below 2 downside observations
win_rate_pct:              % of closed trades with pnl > 0
expectancy:                win_rate × avg_win − loss_rate × avg_loss (currency units, not %)
turnover:                  total traded notional (entry + exit) / average equity over the run
avg_exposure_pct:          mean of each day's (position notional / equity × 100), 0 while flat
num_trades:                count of closed trades (int, never None — 0 is a valid, real count)
avg_trade_pct:             mean of each closed trade's own return_pct
best_trade_pct / worst_trade_pct: max / min of each closed trade's own return_pct
missing_policy:            every metric above is None, never a fabricated 0 or empty distribution, when
                           there is not enough data to compute it honestly (R3) — e.g. total_return_pct
                           needs >= 2 equity points, sharpe needs a nonzero return stdev, turnover needs
                           both trades and an equity curve; num_trades alone is always a real int
owner_phase:               16 (2026-09-27)
status:                    implemented (in-memory result only — not yet persisted; see ADR-0059)
```

### Reproducibility record (`cfi/backtest/versioning.py::RunVersions` / `Assumptions`, ADR-0059)

```
strategy_version / parameter_version: the exact StrategyDefinition.version and CostParameterSet.version
                                       used for the run (both from append-only, versioned registries)
dataset_version:   SHA-256 fingerprint (first 16 hex chars) of asset|start|end|as_of|knowledge_time|
                   provider_id — identical inputs always fingerprint identically, without re-storing bars
code_version:      the installed cfi package version (importlib.metadata), the closest honest stand-in
                   for a git commit hash available from inside the running process
assumptions:       every cost/sizing/execution-lag assumption restated in full on every result (fee_bps,
                   slippage_bps, max_participation_pct, risk_free_rate_annual, initial_capital, the
                   execution-lag and liquidity-sizing conventions in plain English) — nothing implicit.
                   (Phase 18, RED_TEAM_REPORT.md finding #11 / ADR-0061) two new always-present fields,
                   `sizing_price_gap_note` and `slippage_participation_note`, restate the corrected
                   intrabar-gap and size-dependent-slippage conventions below in the same plain-English style.
owner_phase:       16 (2026-09-27); 18 (2026-09-27, assumption-disclosure fields — see cost model below)
status:            implemented (in-memory result only — not yet persisted; see ADR-0059)
```

### Cost model corrections (Phase 18, RED_TEAM_REPORT.md findings #3/#5/#12/#14, ADR-0061)

```
version:           cost_model_v1 (unchanged, byte-for-byte reproducible — participation_impact_coefficient
                   defaults to 0, so v1 slippage stays flat regardless of trade size) /
                   cost_model_v2 (current default — participation_impact_coefficient = 1)
intrabar_stops:    (finding #3) `_intrabar_stop_fill()` checks the day's own `open` against the stop-
                   loss/take-profit level first: if the open already gapped through it, the fill is the
                   open itself, not the stop/take-profit price — the sole exception to the execution-lag
                   convention (ADR-0059), since a stop reacts to the realized bar rather than deciding a
                   future one. Falls back to an intrabar high/low pierce check otherwise. Stop-loss is
                   checked before take-profit when a bar's range spans both.
participation_slippage: (finding #5) `_participation_fraction()` = trade notional ÷ that day's own traded
                   volume (None, i.e. flat slippage, when volume is unknown). `slipped_price()` scales the
                   base slippage bps by (1 + participation_impact_coefficient × clamped fraction) when both
                   the coefficient and the fraction are available and nonzero.
warmup_disclosure: (finding #14) `_warmup_shortfall_warning()` appends a descriptive string to the existing
                   `warnings` list whenever a strategy's `WARMUP_DAYS` requirement exceeds the bars actually
                   available before `start` — previously silent.
exact_value_tests: (finding #12) a dedicated integration test now asserts exact Decimal fill prices, fees,
                   P&L and return_pct against independently hand-derived formulas, using an always-on test
                   strategy and NULL-volume synthetic bars (eliminating participation-fraction complexity
                   from the hand computation) — not just trade counts and statuses as before.
owner_phase:       18 (2026-09-27)
status:            implemented
```

---

## 5l. Market Anomaly Engine (implemented in Phase 19)

**No datasets ingested.** `cfi/anomaly/` reads nothing from any provider — pure computation over
`cfi.divergence.adapters.Adapters`, reused unchanged, the same posture as `cfi/divergence/` (Phase 13),
`cfi/regime/` (Phase 14) and `cfi/similarity/` (Phase 15). Every reading is a **Calculated Metric (L2)** or
**Statistical Signal (L3)** — never a Regime Classification, an AI Interpretation (L5), or an automatic trading
recommendation.

### The 13 tracked categories (`cfi/anomaly/universe.py::ANOMALY_METRICS`)

| metric_id | category | unit | source (adapter) | evidence_class |
|---|---|---|---|---|
| `etf_flows` | ETF flows | usd/day | `institutional_net_flow` | direct |
| `institutional_flows` | institutional flows | usd/day | `treasury_net_acquisitions` (new, Phase 19) | attributed |
| `whale_flows` | whale flows | native units/day | `whale_net_flow` | direct |
| `exchange_flows` | exchange flows | native units/day | `whale_net_flow` (same series as `whale_flows`) | direct |
| `funding` | funding | ratio per interval | `funding_rate` | direct |
| `oi` | OI | native units | `open_interest` | direct |
| `liquidations` | liquidations | native units/day | `liquidations_total` (new, Phase 19) | direct |
| `stablecoin_supply` | stablecoin supply | usd | `stablecoin_supply` (subject=`TOTAL`) | direct |
| `retail_activity` | retail activity | count/day | `retail_small_tx_count` | direct |
| `social_activity` | social activity | count | `retail_meme_trending_count` | direct |
| `volume` | volume | native units/day | `daily_volume` (new, Phase 19; base-asset volume — Coinbase reports no quote volume) | direct |
| `volatility` | volatility | annualized ratio | `realized_volatility` (new, Phase 19; reuses `cfi.market_structure.metrics.realized_volatility_series`) | direct |
| `market_structure` | market structure | usd | `total_market_cap` | direct |

`whale_flows` and `exchange_flows` read the SAME underlying series (this platform has no aggregate
exchange-wallet flow independent of the whale on-chain dataset) — disclosed in `NOT_TRACKED`, never presented
as two independently observed feeds.

### Percentile bands (`cfi/anomaly/universe.py::ANOMALY_BANDS_V1`, versioned parameter set)

| Band | Cut-point |
|---|---|
| `extreme_high` | percentile >= 97.5 |
| `notable_high` | percentile >= 90 |
| `normal` | otherwise |
| `notable_low` | percentile <= 10 |
| `extreme_low` | percentile <= 2.5 |
| `unavailable` | percentile not computable (fewer than `MIN_PERCENTILE_SAMPLE` = 20 historical readings) |

Every metric is judged by the same symmetric, disclosed cut-points — never fitted to any metric's own
distribution (R13) — applied to that metric's own percentile rank (`cfi.retail.metrics.percentile_rank`,
reused unchanged), never to a raw hard-coded value.

### Magnitude (`cfi/anomaly/metrics.py::robust_magnitude`, `magnitude_method = "modified_zscore_mad_v1"`)

A robust (median/MAD-based) modified z-score: `(current − median) / (1.4826 × MAD)` over the same historical
window used for the percentile (current excluded). `1.4826` is the standard constant that makes MAD a
consistent estimator of the standard deviation under normality. Chosen over a mean/stdev z-score because a
handful of already-extreme historical readings — exactly what an anomaly detector's own history accumulates —
would otherwise inflate the standard deviation and mechanically shrink the z-score of a genuinely new extreme.
`None` (never a fabricated 0) when the history is empty or has zero spread.

### Duration

The number of consecutive trailing days (walking backward from `as_of`) the metric's OWN band has matched
today's — each day's band is recomputed against only the history strictly before that day's own reading, never
the full lookback window every day would otherwise share (R3/R4: no look-ahead bias). Capped at
`MAX_DURATION_LOOKBACK_DAYS` = 180 (never an unbounded scan; the cap is reported, not silently truncated).

### Possible interpretations and contradicting evidence

`possible_interpretations` is a **fixed, versioned, non-AI-generated registry** (one hedged, mechanism-level
candidate reading per metric/band combination) — still L3 territory, never an L5 AI Interpretation (R2/R6).
Phase 20's Claude AI Analyst is the only future place an L5 interpretation belongs. A dedicated test bans
"bullish"/"bearish"/"buy"/"sell" language from every interpretation string, enforcing the Phase 19
instruction structurally, not just by convention.

`contradicting_evidence` compares each metric's band against a curated list of counterpart metrics
(`AnomalyMetricDef.counterparts`, e.g. funding vs. OI vs. liquidations; volume vs. volatility) using the same
four-way vocabulary already established by `cfi.whales.score`'s contradiction indicators — `"consistent"` /
`"contradiction"` / `"no_clear_direction"` / `"insufficient_data"` — a purely mechanical percentile-band-sign
comparison, never an economic or directional judgment call.

### NOT_TRACKED (`cfi/anomaly/universe.py::NOT_TRACKED`)

Whale/exchange flows share one feed; treasury purchases are BTC-only accumulation events (disposals are not
tracked); liquidations are single-venue (OKX); volume is single-venue (Coinbase, base-asset units — Coinbase
reports no quote volume); social/retail activity are attention/activity proxies, never capital-flow measures;
market structure is TOTAL crypto market capitalization only (the pre-existing Phase 12 ranged-history gap);
mid-cap/DeFi/AI/meme assets have no tracked anomaly feed (tracked universe: BTC/ETH/SOL/XRP; whale/exchange
flows: BTC/ETH only).

```
metric:            Market Anomaly Engine (13 categories)
owner_phase:       19 (2026-09-28)
status:            implemented
```

---

## 5m. Capital Rotation Engine (implemented in Phase 20)

**No datasets ingested for the rotation logic itself; one new adapter reads an already-registered dataset.**
`cfi/rotation/` reads through `cfi.divergence.adapters.Adapters` (reused unchanged, plus one new method —
`asset_market_cap`, below), the same posture as `cfi/divergence/`, `cfi/anomaly/`, `cfi/regime/` and
`cfi/similarity/`. Every node's own market-share reading is OBSERVED CAPITAL FLOW (a **Calculated Metric,
L2**, over Observed Data); an edge between two nodes is always INFERRED CAPITAL ROTATION (a hedged hypothesis,
never a stated fact — R1/R2/R5) — never a Regime Classification, an AI Interpretation (L5), or an automatic
trading recommendation.

### The 10 requested categories -> tracked nodes (`cfi/rotation/universe.py::NODES`)

| Requested category | node_id(s) | measurement_class | fetch_key |
|---|---|---|---|
| BTC | `btc` | observed | `asset_share` |
| ETH | `eth` | observed | `asset_share` |
| SOL | `sol` | observed | `asset_share` |
| major assets | `btc`, `eth`, `sol`, plus `xrp` | observed | `asset_share` |
| large caps | `large_caps` | observed | `large_caps_share` |
| mid caps | `mid_caps` | **unavailable** | none (no tracked mid-cap universe) |
| DeFi | `defi` | **unavailable** | none (no tracked DeFi-token universe) |
| AI-related assets | `ai_related` | **unavailable** | none (no tracked AI-token universe) |
| meme assets | `meme_assets` | proxy | `retail_meme_trending` (attention proxy only; informational, never a rotation leg) |
| stablecoins | `stablecoins_total`, `stablecoin_usdt`, `stablecoin_usdc` | observed | `stablecoin_growth` / `stablecoin_share` |

"Major assets"/"large caps" both map onto this platform's own tracked 4-asset universe (BTC/ETH/SOL/XRP) — a
scope decision, disclosed in `NOT_TRACKED`, not a claim that no other large-cap assets exist.

### Market-share denominator: the genuine global TOTAL, never the platform's own 4-asset sum

`asset_share` and `large_caps_share` both divide by `Adapters.total_market_cap` — the genuine CoinGecko global
TOTAL crypto market capitalization, the same denominator Phase 12's own BTC/ETH dominance figures use — never
by the sum of BTC+ETH+SOL+XRP. Using the platform's own 4-asset sum as the denominator would make
`large_caps_share` a circular, always-100% figure, since `large_caps` IS defined as that same sum (caught and
corrected before the service layer was written — see ADR-0067 point 2). The residual share of the global TOTAL
not held by BTC/ETH/SOL/XRP is reported once as `untracked_share_pct`, never decomposed into mid-cap/DeFi/
AI/meme sub-shares (no data exists to do so — R3).

### New adapter: `Adapters.asset_market_cap` (Phase 20)

The first RANGED (not single-snapshot) per-asset market-cap history in this platform — CoinGecko's
`/coins/{id}/market_chart` (dataset `market.market_cap.usd.1d`, i.e. `MARKET_CAP_USD_1D`), distinct from the
live-snapshot-only `MARKET_CAP_USD` Phase 12 already used for `total_market_cap`/dominance. Read directly via
`DerivativesQueries.observations()` (bypassing `MarketStructureService.history()`'s `series` parameter, which
only accepts `"total_market_cap"` — an API-facing restriction, not a query-layer limitation, the same
precedent as Phase 19's `liquidations_total` and Phase 7's whale-transfer reads).

| Field | Value |
|---|---|
| dataset_id | `market.market_cap.usd.1d` |
| unit | usd |
| period | 1d |
| availability | event_time + 10 minutes |
| tracked assets | BTC, ETH, SOL, XRP |

### `share_series` / `sum_series` (`cfi/rotation/metrics.py`, pure functions)

`share_series(numerator, denominator)`: an as-of join expressing one raw series as a percent of another,
carrying the denominator's last known reading forward (never an interpolation, R3); a timestamp whose
denominator is unavailable or exactly zero emits `value=None` (`quality_status='insufficient_data'`), never a
silently shortened series. `sum_series(components)`: the same as-of-join discipline, adding several raw series
together (used to build `large_caps`'s own numerator from BTC+ETH+SOL+XRP). Everything downstream — window
direction, magnitude, historical percentile, duration, historical examples — reuses
`cfi.divergence.metrics` **unchanged**.

### OBSERVED vs. INFERRED (`cfi.divergence.capital_flow_map.classify_edge`, reused unchanged)

An edge between two nodes is classified `"possible_rotation"` (only when the two nodes' own share directions
are opposite, always `evidence_class: "inferred"`, always hedged wording — "consistent with, but not proof
of"), `"no_rotation_signal"` (same direction), or `"unavailable"` (either direction unknown). This system never
claims capital moved from Asset A to Asset B solely because Asset B's share increased while Asset A's
decreased (the user's explicit Phase 20 constraint) — enforced structurally by reusing Phase 13's own
never-upgraded hedge wording, not by convention.

### `flow_corroboration` — the evidence supporting each inferred rotation (`cfi/rotation/metrics.py`, new)

For a `"possible_rotation"` edge, each node's own OBSERVED institutional ETF net flow (`institutional_net_flow`,
BTC/ETH/SOL/XRP) and/or whale exchange net flow (`whale_net_flow`, BTC/ETH only) over the same window is
compared against that node's own share direction:

| flow direction vs. share direction | result |
|---|---|
| same | supporting evidence (flow data is directionally consistent with the share move) |
| opposite (neither `flat`) | contradicting evidence (the share move is not corroborated by this flow data) |
| no flow data tracked for either node | `not_applicable` (never a fabricated check) |

Still not proof the flow *caused* the share move (R1) — flow and share direction can each have independent
causes — but a second, independently observed data point the hypothesis can be checked against, never
upgrading `classify_edge`'s hedged wording to a stated fact.

### `EXCLUDED_PAIRS` (`cfi/rotation/universe.py`)

Pairs where one node is a strict aggregate of the other — `large_caps` vs. each of BTC/ETH/SOL/XRP,
`stablecoins_total` vs. each of USDT/USDC — are excluded from `/matrix` and rejected (404) by `/pair`.
Comparing a whole to its own part would manufacture a "rotation" out of arithmetic identity, never an
independent observation (a stronger violation of R1 than an ordinary spurious correlation).

### NOT_TRACKED (`cfi/rotation/universe.py::NOT_TRACKED`)

Mid-cap/DeFi/AI-related assets have no tracked universe at all (BTC/ETH/SOL/XRP only); meme assets get a
retail-attention proxy only, never a capital-flow or market-share measure, and are excluded from the pairwise
matrix; "large caps" means only this platform's own 4-asset universe, not a broad large-cap index; the
untracked residual share of the global TOTAL is reported once, never decomposed further; stablecoin exchange
balances/flows remain outside this platform's scope (`cfi.liquidity.universe`'s own pre-existing limit).

```
metric:            Capital Rotation Engine (10 requested categories -> 12 tracked nodes)
owner_phase:       20 (2026-09-28)
status:            implemented
```

---

## 5n. AI Analyst (implemented in Phase 21)

Realizes and supersedes the "planned" fields in §9/§9a below for the `ai` schema. The AI Analyst is L5
(CLAUDE.md R2): it interprets L1-L4 evidence and never writes to observed data, metrics, signals, or regimes.

### `ai.snapshot` (`cfi/db/tables.py::ai_snapshot`, migration `0007`)

One immutable, hashed evidence bundle per analysis — never updated after insert.

| Field | Description |
|---|---|
| `id` (bigint, PK) / `uuid` (unique) | Internal identity / stable external identifier |
| `created_at`, `as_of`, `knowledge_time` | Point-in-time coordinates the snapshot was built with |
| `snapshot_version` | `cfi.analyst.universe.SNAPSHOT_VERSION` (`analyst_snapshot.v1`) |
| `payload` (jsonb) | The exact JSON given to Claude: `snapshot_version`, `as_of`, `knowledge_time`, `question`, `tools_called`, `not_tracked` (known platform limitations), `data_quality_state`, `has_conflicts`, `fields` (field_id → `{display, evidence_category, quality_status, unit, source}`), `tool_results` (raw, per-tool) |
| `payload_hash` | sha256 of a canonical JSON encoding of the pre-flattening tool results — same inputs always produce the same hash (ADR-0041) |

### `ai.interpretation` (`cfi/db/tables.py::ai_interpretation`, migration `0007`)

One row per analysis request; created `queued` by the API before the Celery worker task runs (its `uuid` is
returned immediately as the stable `analysis_id`), then updated in place: `queued → running → completed/failed`.

| Field | Description |
|---|---|
| `id` (bigint, PK) / `uuid` (unique) | Internal identity / the `analysis_id` returned to callers |
| `created_at`, `updated_at` | Lifecycle timestamps |
| `snapshot_id` | FK to `ai.snapshot.id` — the exact evidence Claude used |
| `status` | `queued` \| `running` \| `completed` \| `failed` |
| `question` | The user's own question, if any (else `null` — a general analysis) |
| `prompt_version` | `cfi.analyst.universe.PROMPT_VERSION` (`analyst_prompt.v1`) |
| `model` | `Settings.anthropic_model` at the time of the call |
| `response` (jsonb) | The validated `cfi.analyst.schema.AnalystResponse`, in its 12-section canonical order |
| `validation_status` | `ok` \| `failed` (the deterministic validator's own verdict) |
| `validation_errors` (jsonb) | The validator's own error strings, if any (on the final attempt) |
| `attempt_count` | 1 or 2 (`cfi.analyst.universe.MAX_VALIDATION_ATTEMPTS`) — one call, at most one retry |
| `tools_called` (jsonb) | The 14 tool IDs called for this analysis (always all 14 in this phase) |
| `data_quality_state` | `ok` \| `degraded` \| `insufficient`, rolled up by `check_data_quality` |
| `error` | Set only when `status = failed`: budget-ceiling refusal, malformed Claude output after the retry, or a provider error |

### `ai.usage` (`cfi/db/tables.py::ai_usage`, migration `0007`)

One row per Claude API call attempt (the first call, and the one retry, are each their own row) — the basis
of the monthly budget ceiling (`Settings.ai_monthly_budget_usd`, TODO.md B3), enforced by summing this table
for the current calendar month, never by a separate counter.

| Field | Description |
|---|---|
| `id` (bigint, PK) / `uuid` (unique) | Internal identity / external identifier |
| `created_at` | When this attempt was recorded |
| `interpretation_id` | FK to `ai.interpretation.id` — nullable since migration `0008` (a brief-generated row has no interpretation; see `brief_id` below) |
| `brief_id` | FK to `ai.brief.id`, added in migration `0008` — nullable; exactly one of `interpretation_id`/`brief_id` is set (CHECK `usage_exactly_one_owner`), never both and never neither |
| `model` | Model that answered this attempt |
| `input_tokens`, `output_tokens` | From the Messages API's own `usage` block |
| `latency_ms` | Wall-clock time for this one call |
| `cost_usd` | Estimated cost (`Settings.anthropic_{input,output}_cost_per_mtok_usd` × tokens) — Anthropic's own billing is the source of truth for actual charges |
| `attempt` | 1 or 2 |

### `ai.brief` (`cfi/db/tables.py::ai_brief`, migration `0008`) — Phase 22

One row per generated Daily Market Brief; same `queued → running → completed/failed` job-record
shape as `ai.interpretation`, reusing the Phase 21 Claude-call machinery
(`cfi.analyst.client.ClaudeClient`) and the shared `ai.usage` budget ceiling rather than a parallel
logging system (ARCHITECTURE.md §5.18a).

| Field | Description |
|---|---|
| `id` (bigint, PK) / `uuid` (unique) | Internal identity / the `brief_id` returned to callers |
| `created_at`, `updated_at` | Lifecycle timestamps |
| `reporting_period_start`, `reporting_period_end` | The 24-hour window this brief covers |
| `snapshot_id` | FK to `ai.snapshot.id` — the exact evidence Claude used (the same `ai.snapshot` table Phase 21 writes to; not a separate snapshot store) |
| `previous_brief_id` | FK to `ai.brief.id` — the previous `completed` brief used as the change-detection comparison basis (`null` means none existed yet) |
| `status` | `queued` \| `running` \| `completed` \| `failed` |
| `prompt_version` | `cfi.brief.universe.BRIEF_PROMPT_VERSION` (`brief_prompt.v1`) |
| `analyst_version` | `cfi.brief.universe.BRIEF_ANALYST_VERSION` (`brief_analyst.v1`) — this layer's own version id, independent of Phase 21's own `PROMPT_VERSION`/`RESPONSE_SCHEMA_VERSION` |
| `model` | `Settings.anthropic_model` at the time of the call |
| `response` (jsonb) | The validated `cfi.brief.schema.BriefResponse`, in its 15-section canonical order |
| `validation_status` | `ok` \| `failed` (the deterministic validator's own verdict) |
| `validation_errors` (jsonb) | The validator's own error strings, if any (on the final attempt) |
| `attempt_count` | 1 or 2 (`cfi.brief.universe.MAX_VALIDATION_ATTEMPTS`) |
| `tools_called` (jsonb) | The 14 analyst tool IDs called for this brief's snapshot (the same snapshot builder Phase 21 uses) |
| `data_quality_state` | `ok` \| `degraded` \| `insufficient`, rolled up by `check_data_quality` |
| `changes` (jsonb) | The computed `cfi.brief.changes.ChangeSet`: `comparison_basis` (`previous_brief` \| `none`) and every `FieldChange` (`change_id`, `field_id`, `previous_display`, `current_display`, `delta`) — recorded for auditability even though it is also implicit in `response` |
| `error` | Set only when `status = failed`: budget-ceiling refusal, malformed Claude output after the retry, or a provider error |

### The 14 analyst tools (`cfi/analyst/universe.py::TOOLS`, `cfi/analyst/tools.py`)

Read-only wrappers over already-tested domain services — Claude never gets a database connection or calls
these directly; `cfi.analyst.snapshot.build_snapshot` calls all 14 once per analysis, before Claude is invoked.

| tool_id | Wraps |
|---|---|
| `get_market_data` | `cfi.divergence.adapters.Adapters` (price/volume/volatility) + `window_reading` |
| `get_institutional_flows` | `cfi.institutional.service.InstitutionalService.overview` |
| `get_whale_activity` | `cfi.whales.service.WhaleService.overview` |
| `get_retail_activity` | `cfi.retail.service.RetailService.overview` |
| `get_derivatives` | `cfi.derivatives.service.DerivativesService.overview` |
| `get_liquidity` | `cfi.liquidity.service.LiquidityService.overview` |
| `get_macro` | `cfi.macro.service.MacroService.overview` |
| `get_market_structure` | `cfi.market_structure.service.MarketStructureService.overview` |
| `calculate_divergence` | `cfi.divergence.service.DivergenceService.matrix` (Phase 13) |
| `get_market_regime` | `cfi.regime.service.RegimeService.current` (Phase 14) |
| `find_historical_similar_periods` | `cfi.similarity.service.SimilarityService.current` (Phase 15) |
| `get_anomalies` | `cfi.anomaly.service.AnomalyService.scan` (Phase 19) |
| `get_capital_rotation` | `cfi.rotation.service.RotationService.matrix` (Phase 20) |
| `check_data_quality` | Pure function over the other 13 tools' own results — not a new database read |

### Response schema (`cfi/analyst/schema.py::AnalystResponse`) and grounding (`cfi/analyst/validator.py`)

The 12 required sections, in this fixed order (enforced by the schema's own field order, not by asking Claude
for ordered JSON keys): Summary, Evidence, Contradicting Evidence, Market Regime, Key Changes,
Capital/Participant Behavior, Derivatives & Liquidity Context, Historical Context, Risks/Uncertainties,
Scenarios, Invalidation Conditions, Data Quality. `evidence`/`contradicting_evidence`/`key_changes`/
`capital_participant_behavior`/`derivatives_liquidity_context`/`historical_context` are lists of
`{text, field_ids}`; every number in `text` must equal the exact `display` value of one of its cited
`field_ids` (checked by `cfi.analyst.validator.validate`, a pure function with no model call). `scenarios` are
non-predictive: `{label, description, supporting_evidence, contradicting_evidence, strengthening_conditions,
invalidation_conditions}` — no probability field exists on the schema at all.

```
metric:            AI Analyst (14 tools, 12-section grounded response, ai.snapshot/interpretation/usage)
owner_phase:       21 (2026-09-28)
status:            implemented
```

---

## 5o. Alerts (implemented in Phase 23)

A deterministic rule engine with no AI/Claude component — reads the same 14-tool evidence snapshot
Phases 21/22 already build and decides, by code, whether one of 11 alert types' trigger condition
is satisfied (ARCHITECTURE.md §5.19a). Implements ADR-0035's "Alert architecture" decision rather
than redesigning it.

### `usr.alert_event` (`cfi/db/tables.py::alert_event`, migration `0009`)

One row per generated alert; never updated after insert except for its lifecycle fields
(`status`/`acknowledged_at`/`resolved_at`/`superseded_by`/`updated_at`).

| Field | Description |
|---|---|
| `id` (bigint, PK) / `uuid` (unique) | Internal identity / the `alert_id` returned to callers |
| `created_at`, `updated_at` | Lifecycle timestamps |
| `alert_type` | One of the 11 types in `cfi.alerts.universe.ALERT_TYPE_TOOL_IDS`: `institutional_flow`, `whale_activity` (covers "Whale activity" and "Exchange flows"), `retail_activity`, `derivatives`, `liquidity`, `macro`, `market_structure`, `divergence`, `anomaly`, `capital_rotation`, `regime_change` |
| `severity` | `info` \| `notable` \| `elevated` \| `critical` — significance of the detected market event, never a trading recommendation |
| `domain` | The asset symbol (e.g. `BTC`), a node pair (`btc->eth`), a score name (`activity_score`), or `GLOBAL` for a platform-wide domain |
| `dedup_key` | Stable identity of "this particular condition" (e.g. `institutional_flow:BTC`, `anomaly:funding_rate_oi_weighted.v1`) — the key `cfi.alerts.lifecycle.decide` dedups/cools-down against |
| `trigger_condition` | Human-readable description of what was evaluated |
| `observed_value` | The current state as reported by the underlying tool (a band label, a regime id, `possible_rotation`, etc.) — never fabricated |
| `reference_value` | The threshold/reference compared against, where applicable (`null` for a purely categorical state) |
| `evidence_field_ids` (jsonb array) | The snapshot field id(s) this alert is grounded in (reproducible from `ai.snapshot.payload`) |
| `snapshot_id` | FK to `ai.snapshot.id` — the exact evidence this alert was computed from (reproducibility) |
| `source_tool_id` | Which of the 14 analyst tools this alert's domain data came from |
| `component_status` | The specific field/component's own reported status (`ok` unless otherwise noted) |
| `data_quality_state` | The overall snapshot data-quality state (`ok` \| `degraded` \| `insufficient`) at evaluation time — passed through, never fabricated, when sources conflict or data is stale |
| `status` | `active` \| `acknowledged` \| `resolved` \| `expired` (lifecycle) |
| `superseded_by` | FK to `usr.alert_event.id` — set when this alert was re-armed by a later one (`status` becomes `expired`) |
| `acknowledged_at`, `resolved_at` | Set by the corresponding user-driven API action |

### Deduplication / cooldown (`cfi/alerts/lifecycle.py::decide`)

Pure, database-free: given the most recent non-terminal alert for a dedup key and a freshly
evaluated candidate, returns `create` (no prior alert) / `skip_unchanged` (same observed value) /
`skip_cooldown` (changed, but within `cfi.alerts.universe.cooldown_period()`, one hour) / `rearm`
(changed, past cooldown — a new alert is created and the prior one marked `expired`).

```
metric:            Alerts (11 types, deterministic rule engine, usr.alert_event, in-app delivery)
owner_phase:       23 (2026-10-03)
status:            implemented (periodic-sweep evaluation only; event-driven evaluation and the
                    email/Telegram channels ADR-0035 allows remain proposed, not built)
```

---

## 5p. Paper trading (implemented in Phase 24)

Simulation only — no exchange connection, no order-routing, no trading credential anywhere in this
code. One consolidated table rather than ADR-0036's original four-table account/order/fill/position
sketch (ADR-0072; ARCHITECTURE.md §7a). Simulated performance is never evidence of future results.

### `usr.paper_trade` (`cfi/db/tables.py::paper_trade`, migration `0010`)

One row per simulated trade; the entry fields are set once at creation and never altered
afterward (historical integrity — "Do not allow later information to alter the original decision
context"); only the exit/closing fields and `status`/`updated_at` are written by a later close or
cancel.

| Field | Unit | Description |
|---|---|---|
| `id` (bigint, PK) / `uuid` (unique) | — | Internal identity / the `trade_id` returned to callers |
| `created_at`, `updated_at` | — | Lifecycle timestamps |
| `asset` | — | One of `cfi.market.universe.ASSET_SYMBOLS` (`BTC`/`ETH`/`SOL`/`XRP`) — the platform's only priced assets |
| `direction` | — | `long` \| `short` |
| `status` | — | `open` \| `closed` \| `cancelled` (lifecycle; `open → closed`/`cancelled`, both terminal) |
| `entry_time` | timestamptz | Always the trade's creation time — there is no backdated entry (no look-ahead by construction) |
| `entry_price_observed` | USD | The observed market price at entry (`cfi.divergence.adapters.Adapters.price_close`, via `window_reading(window_days=0)`) — never a real exchange fill |
| `entry_price_execution` | USD | The simulated execution price after slippage (`cfi.backtest.costs.slipped_price`) — always worse than `entry_price_observed` (long buys pay more; short sells receive less) |
| `entry_price_source` | — | Free-text description of the price source (Coinbase daily close via the reused adapter) |
| `notional` | USD | The simulated position's exposure/size — what quantity/P&L are actually computed from (never confused with margin or leverage) |
| `leverage` | ratio | Defaults to 1 (no leverage) if not supplied |
| `margin` | USD | `notional / leverage` — the capital actually at risk; `return_pct` is computed on this, not on `notional` |
| `stop_loss`, `take_profit` | USD | As specified by the user; informational only — nothing in this phase automatically triggers a close from these (no autonomous trading, per spec) |
| `exit_time` | timestamptz | Set only on close; `null` for `open`/`cancelled` |
| `exit_price_observed`, `exit_price_execution` | USD | Analogous to the entry fields, computed at close time; `null` until then; `null` forever for a `cancelled` trade (a cancellation is not a market exit) |
| `exit_price_source` | — | Analogous to `entry_price_source` |
| `cost_model_version` | — | Which `cfi.backtest.costs.PARAMETER_SETS` version priced this trade's slippage/fees — reproducible from this field alone |
| `gross_pnl` | USD | Price-move result from the two *observed* prices, before any cost |
| `slippage_cost` | USD | Dollar cost of execution slippage on both legs — always ≥ 0 |
| `fees_total` | USD | Proportional fee on both legs (`cfi.backtest.costs.apply_fee`) |
| `realized_pnl` | USD | Net P&L: `gross_pnl - slippage_cost - fees_total` |
| `return_pct` | % | `realized_pnl / margin * 100` |
| `max_favorable_move_pct`, `max_adverse_move_pct` | % | Largest favorable/adverse price excursion over the holding period, relative to `entry_price_observed`, where the price history to compute it was available (`null` otherwise — missing is first-class, R3) |
| `strategy_tag`, `notes` | — | Free-text user context; never read by this service to make a decision |
| `decision_snapshot_id` | — | FK to `ai.snapshot.id` — the SAME immutable 14-tool snapshot Phases 21-23 already build, captured at creation time (market state, institutional/whale/retail/derivatives/liquidity/macro/market-structure/divergence/anomaly/rotation/regime/data-quality) |
| `market_brief_id` | — | FK to `ai.brief.id` — the latest *completed* Daily Market Brief at decision time, if any (`BriefRepository.latest_completed_brief`) |
| `relevant_alert_ids` (jsonb array) | — | UUIDs of every `usr.alert_event` row `active` at decision time (capped at `cfi.paper.universe.RELEVANT_ALERTS_LIMIT`) — contextual evidence only; never auto-converted into a trade |

**No user/account reference:** no `usr.app_user` or equivalent table exists anywhere in this
schema (no authentication phase has been built through Phase 23) — omitted rather than invented,
per the Phase 24 spec's own instruction not to require fields the existing architecture does not
support.

### P&L methodology (`cfi/paper/pnl.py`, pure functions)

`Observed market price → simulated execution price → calculated P&L`, exactly in that order. See
ARCHITECTURE.md §7a for the full pipeline diagram and `cfi/paper/pnl.py`'s own module docstring for
the complete derivation. No participation-scaled slippage is applied (flat `slippage_bps` only) —
a documented limitation, not an oversight: modelling liquidity impact meaningfully needs the
backtest engine's own position-sizing context (ADR-0061), which does not naturally apply to an
arbitrary user-specified notional.

### Performance statistics (`cfi/paper/stats.py::performance_stats`, pure function)

`total_trades`, `open_trades`, `closed_trades`, `cancelled_trades`, `winning_trades`,
`losing_trades`, `win_rate`, `gross_pnl`, `net_pnl`, `average_win`, `average_loss`,
`profit_factor`, `expectancy`, `max_drawdown` (largest peak-to-trough decline of the cumulative
realized-P&L curve, trades ordered by `exit_time`) — computed live over current rows every call,
never a separately maintained counter that could drift (R3). The API response for this endpoint
carries a disclaimer string: simulated performance is never evidence of future profitability.

```
metric:            Paper trading (usr.paper_trade, simulation only, no worker task)
owner_phase:       24 (2026-10-03)
status:            implemented (Decision journal half of ADR-0036 also implemented, Phase 25)
```

---

## 5q. Decision journal (implemented in Phase 25)

The remaining half of ADR-0036. One consolidated table, same rationale as §5p's
`usr.paper_trade` (ADR-0073; ARCHITECTURE.md §7b). Hindsight protection — "Never silently modify
the original decision record based on the outcome" — is enforced by the repository's own API
shape: the decision-time columns and the outcome columns are disjoint, written by different
methods, and no method ever writes to both.

### `usr.decision_journal` (`cfi/db/tables.py::decision_journal`, migration `0011`)

One row per journaled decision. The decision-time columns are set once at creation by
`insert_decision` and never written again by any other method; the outcome columns are set once,
later, by `record_outcome`. `notes` is the one freely mutable field; `paper_trade_id` is a
genuinely mutable cross-reference (a relationship, not evidence).

| Field | Unit | Description |
|---|---|---|
| `id` (bigint, PK) / `uuid` (unique) | — | Internal identity / the `decision_id` returned to callers |
| `created_at`, `updated_at` | — | Lifecycle timestamps |
| `decision_time` | timestamptz | Always the entry's creation time — there is no backdated decision (no look-ahead by construction, same convention as `usr.paper_trade.entry_time`) |
| `asset` | — | Free text — not restricted to `cfi.market.universe.ASSET_SYMBOLS`; only the optional auto-captured `observed_price_at_decision` requires a tracked asset |
| `decision_type` | — | Free text, user-supplied (e.g. `long_spot`, `watch`) — grouped by exact string in review, never inferred |
| `thesis` | — | The user's own reasoning, required, verbatim, never rewritten after the outcome is known |
| `expected_scenario`, `alternative_scenario` | — | User-supplied; `null` if not provided — never invented |
| `time_horizon` | — | Free text, user-supplied |
| `entry_price` | USD | Purely user-stated; never conflated with `observed_price_at_decision` below |
| `observed_price_at_decision` | USD | Auto-captured from the SAME decision-time snapshot's own already-fetched `get_market_data` result (`cfi.journal.context.observed_price`) — zero new adapter calls; `null` if `asset` is not one of the platform's 4 tracked symbols or the price was itself unavailable (missing is first-class, R3) |
| `invalidation_condition` | — | User-supplied; grouped by exact string in review |
| `key_risks` | — | User-supplied free text |
| `confidence` | ratio (0-1) | User-stated only; `null` if not provided — "Do not invent user decisions or confidence levels" |
| `notes` | — | The one field mutable at any time, via its own `update_notes` method |
| `status` | — | `open` \| `resolved` \| `invalidated` \| `cancelled` (lifecycle; `open` → any of the three terminal states) |
| `outcome` | — | User-supplied label (`as_expected` \| `partially_as_expected` \| `not_as_expected`), set once by `record_outcome`; `null` until then |
| `thesis_supported`, `thesis_contradicted`, `invalidation_occurred` | — | User's own self-assessment booleans, never system-inferred ("Do not automatically judge") |
| `evidence_changed_notes` | — | User-supplied free text: what evidence changed after the decision |
| `actual_market_movement_text` | — | User-supplied free text description of what actually happened |
| `actual_price_at_outcome` | USD | A fresh, lightweight `Adapters.price_close` lookup at outcome time — computed only when `asset` is tracked; `null` otherwise |
| `actual_market_movement_pct` | % | `(actual_price_at_outcome - decision_price) / decision_price * 100`, where `decision_price` is `observed_price_at_decision` or, failing that, `entry_price` — pure arithmetic from two observed/stated prices, computed only when both are available, never invented |
| `lessons_notes` | — | User-supplied free text |
| `outcome_timestamp` | timestamptz | Set only by `record_outcome`; `null` for `open`/`cancelled` |
| `decision_snapshot_id` | — | FK to `ai.snapshot.id` — the SAME immutable 14-tool snapshot Phases 21-24 already build, captured at creation time — the decision's one true evidence record |
| `market_brief_id` | — | FK to `ai.brief.id` — the latest *completed* Daily Market Brief at decision time, if any |
| `relevant_alert_ids` (jsonb array) | — | UUIDs of every `usr.alert_event` row `active` at decision time (capped at `cfi.paper.universe.RELEVANT_ALERTS_LIMIT`, reused unchanged) — contextual evidence only; never auto-converted into a decision |
| `market_regime_label` | — | Denormalized copy of the snapshot's own `get_market_regime` label at decision time (`cfi.journal.context.regime_label`) — kept only because grouping by a plain column is cheaper than a jsonb path; the snapshot remains the source of truth |
| `paper_trade_id` | — | FK to `usr.paper_trade.id` — a genuinely mutable cross-reference, set/cleared by `link_paper_trade`/`unlink_paper_trade`; never created automatically in either direction |

**No user/account reference:** same genuine, disclosed limitation as §5p — no `usr.app_user` or
equivalent table exists anywhere in this schema.

### Decision review and statistics (`cfi/journal/stats.py`, pure functions)

`decision_stats`: `total_decisions`, `open_decisions`, `resolved_decisions`,
`invalidated_decisions`, `cancelled_decisions`, `thesis_supported_count`,
`thesis_contradicted_count`, `invalidation_occurred_count`, `average_time_to_resolution_hours`.

`decision_review`: `decisions_by_type`, `decisions_by_regime`, `decisions_by_invalidation_condition`,
`decisions_by_outcome` — exact-string groupings only, computed live over current rows, never a
separately maintained counter (R3). No clustering or semantic matching of free-text fields is
attempted (a documented limitation: two differently worded but equivalent invalidation conditions
are counted as two separate groups). Both API responses carry a disclaimer string: these are
descriptive statistics, not recommendations, and never a ranking of the user's own decisions.

```
metric:            Decision journal (usr.decision_journal, no worker task)
owner_phase:       25 (2026-10-03)
status:            implemented (completes ADR-0036; paper trading half already implemented Phase 24)
```

---

## 5r. Decision assessments (implemented in Phase 40)

### `sig.decision_assessment` (`cfi/db/tables.py::decision_assessment`, migration `0013`)

One immutable row per stored snapshot, scope and methodology/parameter version: the deterministic
Phase 38.2/38.3 assessment of that snapshot, written by `cfi.decision_store` from the engine's own
`DecisionContext.deterministic_dict()`. Written right after every `ai.snapshot` insert (the single
`AnalystRepository.insert_snapshot` boundary used by the alerts cycle, analyst, brief, journal and
paper services), best-effort: a failure to assess never affects the snapshot. Never updated.

| Field | Unit | Description |
|---|---|---|
| `id` (bigint, PK) / `uuid` (unique) | — | Internal identity / external-safe reference |
| `created_at` | timestamptz | The snapshot's own `created_at` (no wall clock is read by persistence) |
| `snapshot_id` | — | FK to `ai.snapshot(id)` (the D-M `snapshot_id`) |
| `scope` | — | `BTC`, `ETH`, `SOL` or `XRP` |
| `methodology_version`, `parameter_version` | — | With `snapshot_id` and `scope`: the UNIQUE assessment identity (ADR-0076, D-M) |
| `template_version` | — | Provenance only; deliberately NOT part of the identity |
| `snapshot_version`, `snapshot_as_of`, `knowledge_time` | — / timestamptz | The snapshot's own provenance |
| `producer_payload_hash` | — | `ai.snapshot.payload_hash` exactly as stored (Phase 21 producer hash) |
| `producer_hash_check` | — | `verified`, `mismatch` or `unverified` (re-verification result). A `mismatch` is recorded, never repaired and never a completeness signal |
| `decision_input_hash` | — | The Phase 38.2 hash over the payload the engine received (a different value from the producer hash) |
| `stance`, `confidence`, `posture` | — | Copies of the engine's final stance / confidence / posture (closed vocabularies, CHECK-enforced). `Insufficient Evidence` is a valid value |
| `coverage_available`, `expected_domains` | count | Directional domains with usable evidence / defined for the scope |
| `conflict` | — | The engine's own conflict flag (not the producer's `has_conflicts`) |
| `assessment` | jsonb | The full `deterministic_dict()` of the context, `generated_at` excluded |

The producer's `data_quality_state` and `has_conflicts` are intentionally not stored: they are not a
completeness signal (Phase 39). Retention is not defined (out of scope for Phase 40).

```
metric:            Decision assessment (sig.decision_assessment, no worker task of its own)
owner_phase:       40 (2026-10-06)
status:            implemented (ADR-0077); read by the Phase 41 history view (§5s); the Phase 39 API still computes on read
```

---

## 5s. Decision history (implemented in Phase 41)

`GET /api/v1/decision/history?asset=BTC|ETH|SOL|XRP&limit=1..100` (`cfi/api/routes/decision_history.py`,
contract `decision_history.v0`). Derived on read from `sig.decision_assessment` (§5r); nothing is stored
and nothing is recalculated. Entries are ordered newest first by `snapshot_id`; each is compared with the
row recorded immediately before it for the same scope. 404 when the scope has no persisted assessment, 422
for an unsupported asset or limit.

| Field | Description |
|---|---|
| `contract_version`, `asset`, `ordering` (`snapshot_id`), `limit`, `returned` | Envelope |
| `running_versions` | The methodology / parameter / template versions the running code produces |
| `current` | The newest entry (equal to `history[0]`) |
| `history[]` | Entries, newest first |

Entry fields: `snapshot_id`, `snapshot_as_of` (as stored, never altered), `recorded_at` (the row's
`created_at`), `stance`, `confidence`, `posture`, `decision_input_hash`, `producer_hash_check`,
`methodology_version`, `parameter_version`, `template_version`, `previous_snapshot_id`,
`previous_methodology_version` / `previous_parameter_version` (set only for a version change),
`out_of_order_as_of`, `state`, `change`.

`state`: `Compared`, `No Previous Assessment` (no earlier row; `change` is `null`), or `Not Comparable
(version change)` (the earlier row has a different methodology or parameter version; `change` is `null`).
`out_of_order_as_of` is true when `snapshot_as_of` is earlier than the previous entry's; ordering is never
changed by it.

`change` (state `Compared`): `classification` (`NO_CHANGE`, `STANCE_CHANGED`, `CONFIDENCE_CHANGED`,
`POSTURE_CHANGED`, `EVIDENCE_CHANGED`, `COVERAGE_CHANGED`, `RISK_CHANGED` or `MULTIPLE_CHANGES`),
`changed_dimensions` (fixed order), `same_decision_input`, and one block per dimension:

| Block | Content | `direction` values |
|---|---|---|
| `stance`, `confidence`, `posture` | `previous`, `current`, `changed`, `direction` | stance/confidence: `strengthened`, `weakened`, `changed`, `unchanged`, `insufficient evidence`; posture: `changed`, `unchanged` |
| `evidence` | per-domain `items` (`side` supportive/adverse/neutral; `added`/`removed`/`changed` with the changed fields and `strength_direction`), the conflict flag and contradictions added/removed | `changed`, `unchanged` |
| `coverage` | available/expected counts, directional and context sources that became available/unavailable, per-component status/freshness/flag changes, limitations added/removed | `improved`, `deteriorated`, `changed`, `unchanged` |
| `risk` | per-dimension level changes and `max` | `improved`, `deteriorated`, `changed`, `unchanged` |

```
metric:            Decision history / change intelligence (derived view, no table, no worker task)
owner_phase:       41 (2026-10-06)
status:            implemented (ADR-0078)
```

---

## 5t. Unified intelligence snapshot (implemented in Phase 44)

`GET /api/v1/intelligence/snapshot` (`cfi/api/routes/intelligence_snapshot.py`, contract
`unified_snapshot.v0`). Derived on read from the latest stored `ai.snapshot` row; nothing is stored,
recalculated or fetched. 404 when no snapshot is stored; 503 when the stored payload is unsupported or
malformed.

| Field | Description |
|---|---|
| `contract_version` | `unified_snapshot.v0` |
| `snapshot` | `row_id`, `uuid`, `row_created_at`, `as_of`, `knowledge_time`, `snapshot_version`, `producer_payload_hash`, `producer_hash_check` (`verified` / `mismatch` / `unverified`), `decision_input_hash`, `snapshot_data_quality_state`, `source_conflicts` |
| `global_domains[]` | Evidence that does not depend on the asset, each once: liquidity, macro, market_structure, regime, anomaly, retail (activity, speculation), similarity, divergence, rotation, market_data |
| `assets.<BTC\|ETH\|SOL\|XRP>` | `domains[]` (institutional, whale where tracked, derivatives) and `not_tracked_domains` (whale for SOL, XRP) |
| `coverage` | `entries`, `available`, `insufficient`, `by_evidence_state` |
| `data_quality` | `unavailable_tools`, `degraded_tools`, `conflicting_tools`, `look_ahead_violations`, `platform_limits` |

Entry fields (the Decision Context's own values, unchanged): `domain`, `component`, `role` (`Directional`,
`Risk`, `Context`), `independent_vote` (true only for `Directional`; regime is never a vote), `status`
(`ok`, `unavailable`, `insufficient_data`, `not_applicable`, `not_tracked`), `freshness` (`fresh`, `stale`,
`no_data`, `not_assessed`), `evidence_state` (as in `decision_view.v0`), `insufficient_data` (`status != ok`),
`quality_flags` (`stale`, `partial`, `flagged`), `direction`, `strength`, `band`, `source_ids`, `field_ids` and
`freshness_records[]` (`path`, `status`, `latest`, `expected_latest`, `age_seconds`, `rule`, `note`,
`after_knowledge_time`). Unavailable is never neutral; there is no stance, score or recommendation field.

```
metric:            Unified intelligence snapshot (derived view, no table, no worker task)
owner_phase:       44 (2026-10-10)
status:            implemented (ADR-0081)
```

---

## 5u. Cross-domain confirmation (implemented in Phase 45)

`GET /api/v1/intelligence/confirmation` (`cfi/api/routes/intelligence_confirmation.py`, contract
`cross_domain_confirmation.v0`). Derived on read from `unified_snapshot.v0` (§5t); nothing is stored. 404 when no
snapshot is stored; 503 when the stored payload is unsupported or malformed. No recommendation, score or stance.

| Field | Description |
|---|---|
| `contract_version`, `source_contract` | `cross_domain_confirmation.v0`, `unified_snapshot.v0` |
| `snapshot`, `data_quality` | Copied unchanged from the unified snapshot (identity, hashes, look-ahead violations, platform limits) |
| `parameters` | `confirmation_params.v0`: `min_families` 2, `require_key_layer` true, `coverage_floor` [1, 2]; `families_version` `evidence_families.v0`. Experimental engineering parameters, not validated predictors |
| `families` | Directional domain -> `family` and `lineage` (institutional_flows, onchain_large_holders, stablecoin_liquidity, macro_backdrop, price_structure) |
| `assets.<BTC\|ETH\|SOL\|XRP>` | `agreement`, `reasons`, `supportive_families`, `adverse_families`, `key_layer`, `coverage`, `counts_by_state`, `members[]` |
| `excluded[]` | Entries that never vote (regime, risk, context): `scope` (`global` or asset), `domain`, `component`, `role`, `reason` `not_a_directional_vote` |
| `limitations[]` | `id` and `text`: lineage-only independence, price lineage overlap, economic overlap not modelled, market-wide evidence shared, experimental parameters |

`agreement`: `confirmed_supportive`, `confirmed_adverse`, `mixed`, `unconfirmed`, `insufficient_evidence`.
`reasons`: `CF-CONFIRMED`, `CF-MIXED`, `CF-MIXED-LOW-COVERAGE`, `CF-DECISION-CONFLICT-DEFINITION-MET`,
`CF-LOW-COVERAGE`, `CF-TOO-FEW-FAMILIES`, `CF-NO-KEY-LAYER`, `CF-NO-DIRECTIONAL-EVIDENCE`.

Member fields: `family`, `domain`, `component`, `scope_basis` (`asset` / `market_wide`), `shared_across_assets`,
`state` (`supportive`, `adverse`, `neutral` when eligible; otherwise `unavailable`, `stale`, `partial`,
`not_assessed`, `not_tracked`, `unmapped`), `eligible`, `exclusion_reason`, `direction`, `strength` (preserved,
never weighted), `freshness`, `evidence_state`, `quality_flags`, `source_ids`, `field_ids`, `freshness_records[]`.

Eligibility: Directional vote, status `ok`, freshness `fresh` **and verified** (`freshness_records` non-empty and
every record's `status` exactly `fresh`), no quality flag, direction S / A / N, family mapped. The top-level
`freshness` label alone is not enough: missing, empty, `None`, `no_data` or unknown freshness records give state
`not_assessed` with `exclusion_reason` `freshness_unverified`, and the member cannot vote or be the key-layer
confirmer. Records and labels are output unchanged. Partial readings are visible but never counted. A family counts at most once per asset and direction.
`mixed` is reported whenever eligible families exist on both sides, even below the coverage floor. The result may
differ from the Decision Center stance (`GET /api/v1/decision/current`) by design.

```
metric:            Cross-domain confirmation (derived view, no table, no worker task)
owner_phase:       45 (2026-10-10)
status:            implemented (ADR-0082)
```

---

## 5v. Opportunity discovery (implemented in Phase 46)

`GET /api/v1/intelligence/opportunities` (`cfi/api/routes/intelligence_opportunities.py`, contract
`opportunity_discovery.v0`). Derived on read from `unified_snapshot.v0` (§5t) and `cross_domain_confirmation.v0`
(§5u) of the latest stored snapshot; nothing is stored. 404 when no snapshot is stored; 503 when the payload or
the inputs are unusable (unsupported contract versions, or the two inputs describing different snapshots).
Research context only: no score, ranking, recommendation, target price or position size.

| Field | Description |
|---|---|
| `contract_version`, `source_contracts` | `opportunity_discovery.v0`; the unified, confirmation, confirmation-parameter and family versions consumed |
| `snapshot`, `data_quality` | Copied unchanged from the unified snapshot (identical to the confirmation's identity block) |
| `parameters` | `opportunity_params.v0`: `min_asset_specific_confirmers` 1, `asset_led_min_asset_specific` 2, `experimental` true |
| `discovery_types` | `discovery_types.v0`: `asset_led_confirmation`, `market_aligned_confirmation`, `adverse_confirmation` |
| `gates` | `look_ahead` (`triggered`, `violations`) and `producer_hash` (`check`, `triggered`) |
| `assets.<BTC\|ETH\|SOL\|XRP>` | Fixed order; one block per asset (below) |
| `market_context` | `candidate_assets`, `shared_market_wide_evidence` (`family`, `assets`), `candidates_independent_of_each_other` |
| `notice`, `limitations[]` | The fixed research-only notice and the stated limitations |

Asset block: `status` (`candidate`, `conflicting_evidence`, `insufficient_evidence`, `no_candidate`, `blocked`),
`discovery_type` (or null), `reasons`, `notes`, `basis` (the Phase 45 agreement, reasons, families, asset-specific
and market-wide supporting families, key layer, coverage), `evidence_refs[]` (eligible members with family,
state, strength, freshness, quality flags, source and field ids and freshness records, unchanged),
`excluded_members[]` (the non-voting members with their `exclusion_reason`), `context` (`used_for_discovery`
false; Risk and Context entries without a direction), `comparability` (`expected_domains`,
`not_tracked_domains`, `comparable_with`, `not_comparable_with`) and `independence`
(`shares_market_wide_evidence_with`).

`reasons`: `OD-CANDIDATE`, `OD-CONFLICT`, `OD-INSUFFICIENT`, `OD-UNCONFIRMED`, `OD-ADVERSE-CONFIRMATION`,
`OD-NO-ASSET-SPECIFIC-CONFIRMER`, `OD-UNVERIFIED-SUPPORT`, `OD-LOOK-AHEAD-VIOLATION`, `OD-SNAPSHOT-INTEGRITY`.
`notes`: `OD-NOT-COMPARABLE-COVERAGE`, `OD-SHARED-MARKET-WIDE-EVIDENCE`.

A candidate needs a Phase 45 `confirmed_supportive`, supporting members that are eligible with verified
freshness, and at least one distinct asset-specific supporting family. Mixed, insufficient, unconfirmed and
adverse results are never candidates; adverse confirmation is a review outcome only. A look-ahead violation or a
producer-hash `mismatch` makes every would-be candidate `blocked`. Candidates that rest on the same market-wide
family are not independent of each other. Confirmation is evidence agreement, not a prediction of performance. `blocked` means an opportunity candidate was withheld by an integrity gate; it is neither an actionable signal nor a negative investment signal.

```
metric:            Opportunity discovery (derived view, no table, no worker task)
owner_phase:       46 (2026-10-10)
status:            implemented (ADR-0083)
```

---

## 6. Metric definition template (L2)

Every metric added to the system must have an entry in this form **before** it is used in a signal.

```
metric_id:        funding_rate_oi_weighted.v1
name:             OI-weighted perpetual funding rate
category:         derivatives
unit:             ratio per_8h
formula:          Σ(funding_rate_i × oi_usd_i) / Σ(oi_usd_i), over venues i with quality ok
inputs:           perp_funding_rate (per venue), perp_open_interest_usd (per venue)
period:           8h
point_in_time:    uses inputs with available_at <= as_of
missing_policy:   if venues covering < X% of total OI are present → partial; if none → missing
fill_policy:      none
interpretation:   positive = longs pay shorts (long-side demand for leverage)
caveats:          venue funding intervals differ; normalise to per_8h before weighting
owner_phase:      7
status:           planned
```

---

## 7. Planned metrics glossary (definitions only — not implemented)

Standard definitions to be formalised with the template above in their phase. Formulas are intentionally generic;
exact inputs depend on verified provider data.

| Metric (planned) | Definition | Phase |
|---|---|---|
| ETF net flow (USD / coin) | Creations − redemptions per fund per day; aggregated across funds — **implemented (Phase 6, USD)** | 6 |
| ETF flow z-score | Net flow vs. rolling distribution of past flows (point-in-time window) | 5/12 |
| Exchange netflow | Inflow − outflow for labelled exchange addresses; positive = coins moving onto exchanges | 6 |
| Exchange reserve change | Δ balance held on labelled exchange addresses | 6 |
| Whale accumulation index | Change in supply held by a size band, net of exchange-labelled addresses | 6 |
| Open interest (USD) | Contracts outstanding × contract size × mark price | 7 |
| OI change vs. price change | Joint direction of ΔOI and Δprice (e.g. price↑ OI↑ = new longs *or* short-side leverage — ambiguous without funding) | 7 |
| Funding rate (normalised) | Venue funding converted to per_8h and annualised | 7 |
| Estimated leverage ratio | Derivatives OI ÷ relevant exchange reserve (labelled proxy) | 7 |
| Futures basis (annualised) | (Futures price − spot) ÷ spot × (365 ÷ days to expiry) | 7 |
| Liquidation imbalance | (Long liq − short liq) ÷ total liq over window | 7 |
| 25-delta skew | IV(25Δ put) − IV(25Δ call) at a fixed tenor | 7 |
| Put/call OI ratio | Put OI ÷ call OI | 7 |
| Stablecoin supply change | Δ total supply over window, by issuer/chain | 8 |
| Stablecoin exchange ratio | Stablecoins on exchanges ÷ relevant crypto market cap (dry-powder proxy) | 8 |
| Market depth | Sum of resting bid/ask size within ±x% of mid | 8 |
| Retail attention index | Composite of normalised search/app/social inputs (weights documented) | 9 |
| Institutional–retail divergence | Windowed direction/magnitude comparison, percentile-ranked, never a standardised composite difference — **implemented (Phase 13, see §5i)** | 13 |
| Dominance | Asset market cap ÷ total market cap | 11 |
| Realized volatility | Annualised std. dev. of log returns over window | 11 |
| Rolling correlation | Correlation of returns (e.g. BTC vs. equity index) over window | 10/11 |

---

## 8. Signal and regime outputs (L3 / L4) — planned fields

| Field | Description |
|---|---|
| `signal_id` / `regime_model_id` | Stable, versioned identifier |
| `as_of` | Point-in-time evaluation time |
| `statistic` | e.g. z-score, percentile, test statistic |
| `lookback` | Window used, e.g. `365d` |
| `value` | Signal value |
| `state` | e.g. `extreme_high`, `elevated`, `neutral`, `depressed`, `extreme_low` |
| `confidence` | 0–1, method documented |
| `inputs` | Metric IDs + versions |
| `quality_status` | Worst-of inputs |
| `caveats` | Known limitations for this evaluation |

---

## 9. AI interpretation record (L5) — planned fields (realized shape: §5n `ai.interpretation`)

| Field | Description |
|---|---|
| `interpretation_id` | Unique ID |
| `snapshot_id` | The immutable evidence pack Claude received |
| `model_id` | Exact model identifier used |
| `prompt_version` | Version of the prompt template |
| `output` | Structured output with sections: Summary, Evidence, Contradicting Evidence, Market Regime, Key Changes, Risks, Scenarios, Invalidation Conditions, Data Quality (CLAUDE.md R6). Each statement tagged with its evidence category (R2) |
| `validation_status` | `passed` · `failed` · `flagged` |
| `validation_errors` | Numbers/claims that did not match the snapshot |
| `created_at` | Timestamp |

---

## 9a. AI snapshot content (planned — ADR-0034; realized shape: §5n `ai.snapshot`)

An immutable JSON document; the only evidence Claude may use.

| Element | Description |
|---|---|
| `snapshot_id`, `as_of`, `knowledge_time`, `builder_version` | Identity and point-in-time coordinates |
| `fields[]` | One entry per value: `field_id` (stable, e.g. `m.etf_net_flow_7d.BTC`), `evidence_category`, `label`, `value`, `unit`, `as_of`, `quality_status`, `source_provider`, `original_source`, `confidence`, `context` (pre-computed percentile / z-score / change, each with its own field ID) |
| `missing[]` | Expected inputs that are absent: `field_id`, `reason` — Claude must answer "Insufficient data." for conclusions depending on them |
| `conflicts[]` | Disagreeing providers: `field_id`, values per provider, tolerance |
| `regime` | Current regime state with model version and confidence (field IDs) |
| `changes[]` | Pre-computed changes since the previous snapshot (field IDs) |
| `caveats[]` | Known limitations (e.g. `backfilled_latest` inputs, fallback provider in use) |
| `free_text[]` | Untrusted ingested text (if any), delimited and length-limited; never instructions |
