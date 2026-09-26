# Third-party notices

## TradingView Lightweight Charts™ (frontend charts)

Licensed under the Apache License, Version 2.0 (`frontend/node_modules/lightweight-charts/LICENSE`).
Attribution notice from the project's NOTICE file:

> TradingView Lightweight Charts™
> Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/

The licence also requires a link to https://www.tradingview.com/ on pages that show the charts. The Market page
keeps the chart's built-in TradingView attribution logo enabled and shows a text link under the chart.

## Market data sources

Data remains the property of its providers and is used under their terms. Terms have been read for CoinGecko;
the exchange terms (Coinbase, Kraken, Binance, OKX, Bybit) are **not yet reviewed by the user** (`terms_verified = false`
in `ops.provider`).

| Source | Used for | Attribution / terms notes |
|---|---|---|
| SoSoValue OpenAPI | US spot ETF flows (BTC, ETH, SOL, XRP), listed-company bitcoin purchases | Free API key. No API terms, licence or attribution rules are published in the documentation (checked 2026-09-24); `terms_verified = false`; the dashboard credits "Data: SoSoValue". User decision pending (TODO.md, Phase 6). |
| CoinGecko API | Market capitalisation; listed-company treasury holdings totals | Required attribution shown next to the data: "Data provided by CoinGecko" linking to https://www.coingecko.com. Terms discourage storing data and ask that stored data be refreshed at least every 24 hours (see PROGRESS.md, Phase 5 decisions). |
| Coin Metrics Community API | Exchange inflow / outflow / supply, current supply, issuance (BTC, ETH, daily) | Community Network Data is licensed **CC BY-NC 4.0**: attribution required (the Whales page shows "Source: Coin Metrics Community Network Data (CC BY-NC 4.0)" with a link) and **non-commercial use only** — commercial use needs a Coin Metrics licence. |
| Blockchair API | Large transfers, top-100 address balances, Bitcoin coin days destroyed and coin-age / coinbase spending | Free without a key for personal, non-commercial or academic use up to 1,440 requests a day (30 a minute); applications used on a constant basis "should apply for an API key". The dashboard credits "Data: Blockchair". |
| BitInfoCharts (labels) | 27 Bitcoin address labels (exchanges, Tether, Binance Pool, government seizures, hack funds), copied once on 2026-09-24 into `backend/src/cfi/whales/seed_labels/labels_bitinfocharts_btc_2026-09-24.csv` | Attributed evidence; every label cites "BitInfoCharts" and the page URL. Terms of use for reusing the labels were **not found / not reviewed** — user decision pending (TODO.md, Phase 7). |
| Coinbase Exchange public API | USD candles, last trade | — |
| Kraken public API | USD candles | — |
| Binance public market-data API | USDT candles | — |
| OKX public API | USDT candles | — |
| Bybit public API | USDT candles | — |
| Binance USDⓈ-M Futures public market data | Open interest, funding rates, all-account long/short ratio (USDT perpetuals) | Public endpoints, no key. Terms of use **not yet reviewed** by the user (`terms_verified = false`). The dashboard names Binance as the venue of each value. |
| OKX public market data | Open interest, funding rates, long/short account ratio, liquidation orders (USDT perpetuals) | Public endpoints, no key. Terms of use **not yet reviewed** by the user (`terms_verified = false`). |
| Deribit public API | Futures curve and option chain snapshots, DVOL (BTC, ETH) | Public endpoints, no key. Terms of use **not yet reviewed** by the user (`terms_verified = false`). "DVOL" is Deribit's volatility index; the dashboard names Deribit as its source. |
