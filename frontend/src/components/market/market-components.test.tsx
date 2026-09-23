import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AssetOverview, BarsResponse, Source } from "@/lib/market";

import { AssetSummary } from "./AssetSummary";
import { DataStatus } from "./DataStatus";

afterEach(cleanup);

const coinbase: Source = {
  provider_id: "coinbase",
  provider_name: "Coinbase Exchange",
  original_source: "coinbase_exchange",
  enabled: true,
  attribution: null,
};

const bars = (overrides: Partial<BarsResponse> = {}): BarsResponse => ({
  evidence_category: "observed",
  as_of: "2026-09-01T12:00:30Z",
  asset: "BTC",
  timeframe: "1m",
  instrument: {
    venue_id: "coinbase",
    venue_name: "Coinbase Exchange",
    instrument_id: "coinbase:spot:BTC-USD",
    price_unit: "usd",
    volume_unit: "BTC",
    quote_volume_unit: "usd",
  },
  source: coinbase,
  derivation: null,
  range: { start: "2026-09-01T11:40:00Z", end: "2026-09-01T12:00:00Z" },
  bars: [],
  quality: {
    expected: 14,
    present: 13,
    missing: 1,
    missing_times: ["2026-09-01T11:56:00Z"],
    not_loaded: 5,
    coverage_start: "2026-09-01T11:45:00Z",
    suspect: 0,
    conflicting: 0,
    revised: 0,
  },
  freshness: {
    status: "fresh",
    latest_bar_time: "2026-09-01T11:58:00Z",
    age_seconds: 150,
    limit_seconds: 300,
    last_ingested_at: "2026-09-01T12:00:30Z",
  },
  ingestion: {
    last_run: {
      job_run_id: 1,
      status: "succeeded",
      started_at: "2026-09-01T12:00:30Z",
      finished_at: "2026-09-01T12:00:31Z",
      error_code: null,
      error_detail: null,
    },
    backfill: null,
  },
  warnings: ["1 bar(s) missing in this range."],
  ...overrides,
});

describe("DataStatus", () => {
  it("shows source, last update, freshness and missing-data warnings", () => {
    render(<DataStatus data={bars()} />);
    expect(screen.getByText("Observed data")).toBeDefined();
    expect(screen.getByText(/Coinbase Exchange \(coinbase:spot:BTC-USD\)/)).toBeDefined();
    expect(screen.getByText("Fresh")).toBeDefined();
    expect(screen.getByText(/2026-09-01 12:00 UTC \(stored by our system\)/)).toBeDefined();
    expect(screen.getByText(/13 of 14 expected bars present · 1 missing/)).toBeDefined();
    const warnings = screen.getByRole("list", { name: "Data warnings" });
    expect(within(warnings).getByText("1 bar(s) missing in this range.")).toBeDefined();
    expect(screen.getByText("Missing bars (1)")).toBeDefined();
  });

  it("labels derived bars and failed ingestion", () => {
    render(
      <DataStatus
        data={bars({
          derivation: { from_timeframe: "1h", bars_per_bucket: 4, method: "roll-up" },
          freshness: { ...bars().freshness, status: "stale", age_seconds: 7200 },
          ingestion: {
            last_run: {
              job_run_id: 2,
              status: "failed",
              started_at: "2026-09-01T12:00:30Z",
              finished_at: null,
              error_code: "provider_transient_error",
              error_detail: "timeout",
            },
            backfill: null,
          },
        })}
      />,
    );
    expect(screen.getByText("Derived from 1h bars")).toBeDefined();
    expect(screen.getByText("Stale")).toBeDefined();
    expect(screen.getByText("failed")).toBeDefined();
    expect(screen.getByText(/provider_transient_error: timeout/)).toBeDefined();
  });
});

describe("AssetSummary", () => {
  const overview: AssetOverview = {
    symbol: "BTC",
    name: "Bitcoin",
    last_trade: {
      value: "85265.26",
      unit: "usd",
      time: "2026-09-01T12:00:27Z",
      ingested_at: "2026-09-01T12:00:30Z",
      quality_status: "ok",
      quality_note: null,
      instrument_id: "coinbase:spot:BTC-USD",
      freshness: "fresh",
      age_seconds: 3,
      limit_seconds: 300,
      source: coinbase,
    },
    latest_bars: [
      {
        venue_id: "binance",
        venue_name: "Binance Spot",
        instrument_id: "binance:spot:BTC-USDT",
        timeframe: "1m",
        bar_time: null,
        close: null,
        unit: "usdt",
        quality_status: null,
        freshness: "no_data",
        age_seconds: null,
        source: { ...coinbase, provider_id: "binance", provider_name: "Binance Spot" },
      },
    ],
    market_cap: {
      value: "1691500000000.5",
      unit: "usd",
      time: "2026-09-01T12:00:00Z",
      ingested_at: "2026-09-01T12:00:30Z",
      quality_status: "ok",
      quality_note: null,
      instrument_id: null,
      freshness: "fresh",
      age_seconds: 30,
      limit_seconds: 1800,
      source: {
        provider_id: "coingecko",
        provider_name: "CoinGecko",
        original_source: "coingecko",
        enabled: true,
        attribution: { text: "Data provided by CoinGecko", url: "https://www.coingecko.com" },
      },
    },
  };

  it("shows each value with its source and freshness, and CoinGecko attribution", () => {
    render(<AssetSummary asset={overview} />);
    expect(screen.getByText("85,265.26 USD")).toBeDefined();
    expect(screen.getByText("1.69 T USD")).toBeDefined();
    const link = screen.getByRole("link", { name: "Data provided by CoinGecko" });
    expect(link.getAttribute("href")).toBe("https://www.coingecko.com");
    expect(screen.getByText("No data")).toBeDefined(); // Binance never ingested — shown, not hidden
    expect(screen.getByText(/USD and USDT prices are different units/)).toBeDefined();
  });
});
