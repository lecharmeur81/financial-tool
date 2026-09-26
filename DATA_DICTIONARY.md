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
| `alert_rule` | User-defined rules (versioned) | `rule_id`, `version`, `user_id`, `rule_type`, `definition` (JSON), `min_quality`, `cooldown`, `channels`, `enabled` |
| `alert_event` | Fired alerts | `event_id`, `rule_id`, `rule_version`, `fired_at`, `triggering_values` (IDs + values), `quality_status`, `snapshot_id`, `delivered` |

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
owner_phase:      8 (addendum: 2026-09-26, parameter externalisation and reproducibility fields)
status:           implemented
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
| Institutional–retail divergence | Difference between standardised institutional and retail composites | 12 |
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

## 9. AI interpretation record (L5) — planned fields

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

## 9a. AI snapshot content (planned — ADR-0034)

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
