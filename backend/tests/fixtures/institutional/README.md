# Institutional capital — historical test fixtures (Phase 6)

**All values in this folder are synthetic.** They were designed by hand so that every expected
result can be computed on paper. They are not market data and must never be shown as such.
Tickers and company names are fictional (`TSTA`, `TSTF`, "Test Treasury Co A", …).

Only the *shapes* are real: each file follows the response format documented by the provider
(verified 2026-09-24):

| File | Provider endpoint (documented format) |
|---|---|
| `sosovalue_etf_summary_{BTC,ETH,SOL,XRP}.json` | SoSoValue `GET /etfs/summary-history` |
| `sosovalue_etf_list_BTC.json` | SoSoValue `GET /etfs` |
| `sosovalue_etf_history_TSTF.json`, `…_TSTG.json` | SoSoValue `GET /etfs/{ticker}/history` |
| `sosovalue_btc_treasuries.json` | SoSoValue `GET /btc-treasuries` |
| `sosovalue_purchase_history_TST{A,B,C}.json` | SoSoValue `GET /btc-treasuries/{ticker}/purchase-history` |
| `coingecko_public_treasury_bitcoin.json` | CoinGecko `GET /companies/public_treasury/bitcoin` |

No real SoSoValue response could be captured: this development environment cannot reach the API,
and the API needs a personal key. After the first real run, a captured payload can be copied
from the raw archive (`data/raw/…`) and added here with its capture date.

## Design of the ETF data

- 25 US trading days, 2026-08-03 … 2026-09-04 (no NYSE holiday in that range; Monday 2026-09-07
  is Labor Day). The summary lists them newest first (as documented), plus the row for
  2026-09-08 with `null` settled fields (the documented T+1 behaviour for the current day).
- BTC: total net assets 100,000 M USD every day. ETH: the same flows ÷ 10, net assets 10,000 M.
  XRP: the same flows ÷ 50, net assets 2,000 M. SOL: the same flows ÷ 100, net assets 1,000 M,
  but only the **12 most recent trading days** (2026-08-20 … 2026-09-04) — a young fund family
  with less history than the 20-day window needs.
- Daily net flow (M USD, BTC):

| Week | Mon | Tue | Wed | Thu | Fri | Week total |
|---|---|---|---|---|---|---|
| Aug 3 | −300 | −200 | +100 | +50 | −50 | −400 |
| Aug 10 | +100 | −50 | +50 | −100 | +100 | +100 |
| Aug 17 | +200 | −100 | +100 | 0 | −100 | +100 |
| Aug 24 | +300 | −200 | +100 | 0 | +100 | +300 |
| Aug 31 | +200 | +300 | −100 | +400 | +200 | +1,000 |

- Two funds, TSTF and TSTG, carry 60 % and 40 % of every daily flow, so the per-fund sum
  reconciles exactly with the total.

## Design of the treasury data (BTC)

| Company | Older purchase | Purchase in the 30-day window | Holdings after |
|---|---|---|---|
| TSTA | 2026-06-01: +59,000 BTC | 2026-08-31: +1,000 BTC for 110 M USD | 60,000 |
| TSTB | 2026-05-01: +29,500 BTC | 2026-08-20: +500 BTC for 55 M USD | 30,000 |
| TSTC | 2026-04-01: +10,300 BTC | 2026-09-01: −300 BTC (sale), reported cost 33 M USD | 10,000 |

## Expected results (as of 2026-09-09 12:00 UTC, knowledge time = ingestion time)

The latest trading day due by then is **2026-09-04** (2026-09-08 is due only at 18:00 New York
time on 2026-09-09). Windows end on 2026-09-04.

| Component | Computation | Value | Sub-score |
|---|---|---|---|
| ETF flow 5 d | (200 + 300 − 100 + 400 + 200) M ÷ 100,000 M × 100 | 1.0000 % | 1.0 ÷ 1.0 = **+1.0000** |
| ETF flow 20 d | (100 + 100 + 300 + 1,000) M ÷ 100,000 M × 100 | 1.5000 % | 1.5 ÷ 3.0 = **+0.5000** |
| Breadth 10 d | Aug 24 … Sep 4: 7 inflow days, 2 outflow days, 1 zero day | (7 − 2) ÷ 10 | **+0.5000** |
| Treasury 30 d | (1,000 + 500 − 300) BTC ÷ (60,000 + 30,000 + 10,000) BTC × 100 | 1.2000 % | 1.2 ÷ 2.0 = **+0.6000** |

- **BTC score** = 100 × (0.35 × 1.0 + 0.30 × 0.5 + 0.15 × 0.5 + 0.20 × 0.6) ÷ 1.00 = **69.5**
  → band "strong net inflow".
- **ETH score** (no treasury component; weights renormalised over 0.80) = 100 × (0.35 + 0.15 +
  0.075) ÷ 0.80 = 71.875 → **71.9**.
- **XRP score**: same percentages as ETH → **71.9**.
- **SOL score**: the 20-day component is excluded (12 of 20 days), leaving weight 0.35 + 0.15 =
  0.50 (exactly the minimum) → 100 × (0.35 × 1.0 + 0.15 × 0.5) ÷ 0.50 = **85.0**.
- **BTC weekly totals** (M USD): Aug 3: −400; Aug 10: +100; Aug 17: +100; Aug 24: +300; Aug 31:
  +1,000.
- **With 2026-09-02 removed** (a missing day): 5-day coverage 4/5 < 90 % → excluded; 20-day =
  1,600 M ÷ 100,000 M = 1.6 % → sub-score 0.5333; breadth = (7 − 1) ÷ 9 = 0.6667; score = 100 ×
  (0.30 × 0.5333 + 0.15 × 0.6667 + 0.20 × 0.6) ÷ 0.65 = **58.5**.
