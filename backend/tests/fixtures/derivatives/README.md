# Derivatives — historical test fixtures (Phase 8)

Two kinds of fixture are used.

## 1. Real responses (adapter and calculation tests)

Captured on 2026-09-25/26 from the public endpoints, stored byte for byte except where noted:

| File | Endpoint | Notes |
|---|---|---|
| `okx_open_interest_BTC.json` | OKX `rubik/stat/contracts/open-interest-history?instId=BTC-USDT-SWAP&period=1H&limit=6` | 6 hourly rows, 2026-09-22 21:00 … 2026-09-23 02:00 UTC |
| `okx_funding_BTC.json` | OKX `public/funding-rate-history?instId=BTC-USDT-SWAP&limit=6` | 6 settlements, newest 2026-09-26 00:00 UTC |
| `okx_long_short_BTC.json` | OKX `rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H&begin=…&end=…` | 4 rows, 10:00 … 13:00 on 2026-09-25 (both ends inclusive) |
| `okx_instrument_BTC-USDT-SWAP.json` | OKX `public/instruments?instType=SWAP&instId=BTC-USDT-SWAP` | `ctVal` 0.01 BTC, linear |
| `okx_liquidations_BTC_excerpt.json` | OKX `public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled&limit=100` | **excerpt**: the first 12 and last 2 of the 100 details of the real page (14:04–14:05 UTC on 2026-09-25) |
| `deribit_future_BTC.json` | Deribit `get_book_summary_by_currency?currency=BTC&kind=future` | complete: 13 dated futures + perpetual, snapshot `usOut` 2026-09-26 07:08:17.005971 UTC |
| `deribit_option_BTC_30OCT26_excerpt.json` | Deribit `…&kind=option` | **excerpt**: 23 of the 491 options (all of expiry 30OCT26 that were extracted); the envelope times (`usIn`/`usOut`) of this response were not captured and are set to the rows' `creation_timestamp` (2026-09-25 14:28:42.744 UTC) |
| `deribit_dvol_BTC.json` | Deribit `get_volatility_index_data?currency=BTC&resolution=3600&start_timestamp=1790380800000&end_timestamp=1790402400000` | 7 hourly candles, 00:00 … 06:00 on 2026-09-26 |

Binance answered HTTP 451 to every request from the development environment, so its tests use the **documented**
response shapes with made-up values (marked as such in the tests).

Results computed by hand from the real Deribit data (tests: `tests/unit/test_derivative_metrics.py`):

- **Basis.** Snapshot 2026-09-26 07:08:17 UTC. Futures with ≥ 14 days: 16OCT26 (20.04 d), 30OCT26 (34.04 d), 27NOV26,
  25DEC26 (90.0359 d), 26MAR27, 25JUN27, 24SEP27; 9OCT26 has 13.04 days (excluded). Headline = **BTC-25DEC26**
  (closest to 90 days): (85,024.53 ÷ 83,996.18 − 1) = 1.2243 % → × 365 ÷ 90.0359 = **4.9632 % a year** (normal,
  contango; inside 0 … 10 % → basis stress 0). Perpetual premium 83,998.87 ÷ 83,996.18 − 1 = 0.0032 %.
- **Options (excerpt).** 15 calls: open interest 47,286.1, 24 h volume 4,913.6; 8 puts: 2,367.3 and 394.4 → put/call
  0.0501 (OI) and 0.0803 (volume); notional (47,286.1 + 2,367.3) × 83,585.2 = $4,150,289,369.68. Expiry 30OCT26,
  34.7301 days. Forward = median `underlying_price` = 83,995.83. ATM strike 84,000: call and put 34.69 % → **ATM IV
  34.69 %**. 0.9 F = 75,596.25 → put 76,000 (36.61 %); 1.1 F = 92,395.41 → call 90,000 (34.86 %; 95,000 is further)
  → **skew +1.75 points**.
- **Liquidations (excerpt).** 14 long liquidations, Σ sz = 85.20 contracts × 0.01 = **0.8520 BTC** in the 14:00 hour.

## 2. Synthetic history (ingestion and API tests)

**All values are synthetic**, chosen so every expected result can be computed on paper. They are served by
`tests/derivative_fakes.py` in the providers' response shapes (OKX and Deribit as verified above, Binance as documented)
to the real adapters, engine and jobs; Coinbase BTC-USD hourly closes and CoinGecko daily market caps are written
directly as canonical rows (`tests/integration/derivative_support.py`). They are not market data.

**NOW = 2026-09-10 12:05 UTC** (in the past on purpose: the API never looks beyond the real current time). The newest
complete hourly snapshot is **L = 11:00**. The fakes know nothing before NOW − 10 days.

| Series | Values |
|---|---|
| Binance BTC open interest (coins) | 90,000 before L − 24 h; 95,000 from L − 24 h; **110,000 at L** |
| OKX BTC open interest (coins) | 30,000 throughout |
| Binance SOL open interest | 1,000,000 throughout (no other SOL data except Binance funding) |
| Funding (settlements 00:00 / 08:00 / 16:00 UTC) | Binance BTC and SOL 0.0001; OKX BTC 0.0003 per interval |
| Long/short account ratio | Binance 1.5, OKX 1.2 |
| OKX BTC liquidations | every hour one long order of 60 contracts and one short of 40 (0.6 / 0.4 BTC), at :30; the hour **05:00 on 2026-09-10**: 1,800 long + 200 short (18 / 2 BTC). Collected by running the job every 12 h from NOW − 8 days |
| Deribit BTC DVOL | 45 (%) every hour |
| Deribit BTC futures (index 60,000) | PERPETUAL 60,030; 11SEP26 60,010; 18SEP26 60,100; 25SEP26 60,200; 30OCT26 60,900; **25DEC26 62,100**; 26MAR27 63,500 |
| Deribit BTC options (forward 60,300 for 9OCT26) | 9OCT26: 54000-P IV 55 %, OI 1,500, vol 200; 60000-C 45 %, 1,000, 100; 60000-P 45 %, 500, 100; 66000-C 47 %, 2,000, 300. 25SEP26 (forward 60,150): 60000-C 44 %, 100, 10 |
| Coinbase BTC-USD hourly close | 50,000 for bars opening up to L − 7 d − 1 h, 60,000 after |
| CoinGecko BTC market cap (daily, 00:00) | 1.0 × 10¹² before 2026-09-04, 1.2 × 10¹² from 2026-09-04 |

### Expected results — BTC as of NOW (knowledge time = NOW)

| Item | Computation | Value |
|---|---|---|
| Open interest | 110,000 + 30,000 | **140,000 BTC** (× 60,000 = $8.4 bn) |
| OI change 24 h / 7 d | 140,000 ÷ 125,000 − 1 / 140,000 ÷ 120,000 − 1 | **+12.00 % / +16.67 %** → expansion |
| Leverage | 140,000 × 60,000 ÷ 1.2e12 = 0.70 %; 7 d earlier 120,000 × 50,000 ÷ 1.0e12 = 0.60 % | **+16.67 %** → expansion; stress 0.1667 ÷ 0.20 = **0.8333** |
| Funding | 21 settlements in (09-03 12:05, 09-10 12:05]: Binance 0.0021 × 365 ÷ 7 = 10.95 %, OKX 32.85 %; OI-weighted (10.95 × 110,000 + 32.85 × 30,000) ÷ 140,000 | **15.64 %** a year (normal); stress 0.1564 ÷ 0.30 = **0.5214** |
| Basis | 25DEC26 is 105.8299 days away (closest to 90 among ≥ 14 d): (62,100 ÷ 60,000 − 1) × 365 ÷ 105.8299 | **12.07 %** a year (normal, contango); outside 0 … 10 % by 2.07 points → stress 0.0207 ÷ 0.15 = **0.1381**; perpetual premium 0.05 % |
| Liquidations 24 h | hours 09-09 12:00 … 09-10 11:00: 23 × (0.6 + 0.4) + 18 + 2 | long **31.80**, short **11.20**, total **43.00** BTC = 0.1433 % of 30,000 → stress **0.1433** |
| Liquidation events | 05:00: 20 ≥ 5 × median 1 and 20 ÷ 30,000 = 0.067 % ≥ 0.05 % | one event (05:00 on 2026-09-10) |
| Options | expiry 9OCT26 (28.83 d, closest to 30); calls OI 3,100, puts 2,000; volume 410 / 300 | put/call **0.6452** (OI), **0.7317** (volume); ATM (60,000) **45 %**; skew put 54,000 (55 %) − call 66,000 (47 %) = **+8 points** |
| DVOL | 45 % | stress (45 − 30) ÷ (80 − 30) = **0.3000** |
| **Health score** | stress = 0.25 × 0.5214 + 0.15 × 0.1381 + 0.20 × 0.8333 + 0.20 × 0.1433 + 0.20 × 0.3000 = 0.4064 | **stress 40.6, health 59.4 — moderate stress** |
| Price context | price 60,000 now and 24 h earlier (flat), OI +12 % | "Open interest rising while price is flat: new positions are being opened without a price move." |

Conditions: OI expansion **active**, leverage expansion **active**, liquidation event **active**; funding extreme,
basis extreme, OI contraction, leverage reduction and derivatives stress (health ≥ 50) **not active**.

**SOL:** only Binance funding (10.95 % a year, weight 0.25) → **Insufficient data** (minimum weight 0.5); basis and
DVOL not applicable; liquidation events unknown (no OKX data — the OKX liquidation job fails because the fake lists no
SOL instrument, and the failure is recorded). **ETH, XRP:** no data → Insufficient data.

**Point in time:** as of NOW − 24 h the open interest is 95,000 + 30,000 = **125,000**; the Deribit snapshots (taken at
NOW) and the 05:00 liquidation event are not visible. With knowledge time NOW − 1 minute nothing ingested at NOW is
used (no open interest).
