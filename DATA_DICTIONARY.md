# DATA_DICTIONARY.md

**Status:** Draft v0.1 (Phase 0). Defines conventions, shared fields, and the planned dataset/metric catalogue.
**Nothing here is implemented.** Entries marked `planned` have no table, code, or data yet.
Exact column types and table names are finalised when each phase is implemented; this file is updated in the same commit.

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

## 2. Universal fields (every L1 observation)

| Field | Type | Description |
|---|---|---|
| `observation_id` | id | Unique ID |
| `dataset_id` | text | Which dataset this belongs to (see §5) |
| `metric` | text | What is measured, e.g. `perp_funding_rate`, `etf_net_flow` (canonical name) |
| `asset` | text | Canonical asset symbol, e.g. `BTC`; `NULL` only for non-asset series (e.g. macro) |
| `entity_ref` | text | What it describes: asset, instrument, venue, ETF, address cluster, macro series |
| `event_time` | timestamptz | When the event happened / start of the period described |
| `period` | text | Granularity: `tick`, `1m`, `1h`, `8h`, `1d`, `1w`, `1q` |
| `available_at` | timestamptz | Earliest time the value was publicly knowable (point-in-time key) |
| `available_at_estimated` | bool | `true` if `available_at` comes from a documented rule rather than the source |
| `ingested_at` | timestamptz | When our system received it |
| `value` | decimal | The observed value |
| `unit` | text | Unit of `value` |
| `source_provider` | text | Provider we fetched it from (e.g. an aggregator or API vendor) |
| `original_source` | text | Who first published it (e.g. the ETF issuer, the exchange), if different from the provider; `unknown` if the provider does not say |
| `raw_ref` | id | Pointer to the L0 raw payload |
| `revision` | int | 0 = first publication; increments on each revision |
| `quality_status` | enum | See §3 |
| `quality_note` | text | Human-readable reason when status is not `ok` |
| `confidence` | decimal 0–1, nullable | Where appropriate: for estimated, attributed, or inferred values. `NULL` for values reported directly by the source |

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

### `evidence_class` (entity classification)
| Value | Meaning |
|---|---|
| `direct` | The source itself identifies the actor (issuer reports, filings, exchange-published data) |
| `attributed` | A named third party labels the actor (e.g. analytics provider cluster label) |
| `inferred` | Heuristic proxy (size band, venue mix, cross-venue premium) |

### `actor_class`
`institutional` · `professional` · `whale` · `retail` · `exchange` · `miner` · `market_maker` · `fund` · `treasury_company` · `unknown`

Every non-`unknown` assignment requires an `evidence_class`, `confidence` (0–1), `rule_or_source`, `valid_from`, `valid_to`.

---

## 4. Core reference entities (planned)

| Entity | Key fields | Notes |
|---|---|---|
| `asset` | `asset_id`, `symbol`, `name`, `asset_type` (coin, stablecoin, token), `chain` | Canonical symbols |
| `venue` | `venue_id`, `name`, `venue_type` (cex, dex, cme, etf_issuer, otc) | |
| `instrument` | `instrument_id`, `venue_id`, `type` (spot, perp, future, option, etf), `base`, `quote`, `expiry`, `strike`, `option_type`, `contract_size`, `contract_unit` | Contract size needed to convert contracts → coin/USD |
| `provider` | `provider_id`, `name`, `licence_notes`, `rate_limits`, `status` | Terms of use recorded before ingestion |
| `dataset` | `dataset_id`, `category`, `period`, `availability_rule`, `freshness_limit`, `eligible_providers` | See §5 |
| `entity_label` | `subject`, `actor_class`, `evidence_class`, `confidence`, `rule_or_source`, `valid_from`, `valid_to` | Time-versioned labels |
| `job_run` | `job_id`, `started_at`, `finished_at`, `status`, `rows_written`, `error` | Ingestion audit |

---

## 5. Planned dataset catalogue (L1)

Evidence class indicates how directly the dataset tells us *who* is acting.

| Category | Dataset (planned) | Typical period | Evidence of actor | Phase |
|---|---|---|---|---|
| Market | Spot OHLCV per venue | 1m–1d | n/a | 4 |
| Market | Spot volume by venue | 1h–1d | inferred (venue mix) | 4 |
| Institutional | Spot ETF daily net flows, holdings, AUM | 1d | direct | 5 |
| Institutional | CME futures OI & volume | 1d | inferred (regulated venue) | 5 |
| Institutional | Regulatory position filings (e.g. quarterly holdings) | 1q, lagged | direct, heavily lagged | 5 |
| Institutional | Public company / treasury holdings | event | direct (filings) / attributed | 5 |
| Institutional | Cross-venue premium (e.g. US-regulated vs offshore spot) | 1m–1h | inferred | 5 |
| Whale | Large on-chain transfers | event | inferred (size) / attributed (labels) | 6 |
| Whale | Balances by holder-size band | 1d | inferred | 6 |
| Exchange flows | Exchange net inflow/outflow, reserves | 1h–1d | attributed (exchange address labels) | 6 |
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
| ETF net flow (USD / coin) | Creations − redemptions per fund per day; aggregated across funds | 5 |
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
