# Test fixtures

| File | Origin | Notes |
|---|---|---|
| `coinbase_candles_BTC-USD_3600.json` | **Captured** from the public Coinbase Exchange API on 2026-09-23: `GET https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600&start=2026-09-22T00:00:00Z&end=2026-09-22T03:00:00Z` | Used to prove the adapter reads the real field order `[time, low, high, open, close, volume]`, newest first, and that `end` is inclusive (4 candles for a 3-hour range). |

All other market data used in tests is **synthetic**, generated in `tests/market_fakes.py` in each
provider's documented format. Synthetic values are test fixtures only — they are never loaded into a
running application (R3).
