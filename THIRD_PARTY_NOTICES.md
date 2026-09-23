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
| Coinbase Exchange public API | USD candles, last trade | — |
| Kraken public API | USD candles | — |
| Binance public market-data API | USDT candles | — |
| OKX public API | USDT candles | — |
| Bybit public API | USDT candles | — |
