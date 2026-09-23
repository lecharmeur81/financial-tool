import { describe, expect, it, vi } from "vitest";

import {
  type Bar,
  type Catalog,
  fetchBars,
  formatAge,
  formatCompact,
  formatDecimal,
  formatUtc,
  resolveSelection,
  selectionHref,
  toChartData,
} from "./market";

const bar = (time: string, close: string | null, status = "ok"): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume_base: close === null ? null : "2.5",
  volume_quote: null,
  trade_count: null,
  quality_status: status,
  quality_note: status === "ok" ? null : "note",
  revision: 0,
});

const catalog: Catalog = {
  assets: [
    { symbol: "BTC", name: "Bitcoin" },
    { symbol: "ETH", name: "Ethereum" },
  ],
  timeframes: ["1m", "5m", "15m", "1h", "4h", "1d"],
  venues: [
    {
      venue_id: "coinbase",
      display_name: "Coinbase Exchange",
      quote: "usd",
      instruments: { BTC: "coinbase:spot:BTC-USD" },
      timeframes: [
        { timeframe: "1h", source: "native", derived_from: null },
        { timeframe: "4h", source: "derived", derived_from: "1h" },
      ],
      source: {
        provider_id: "coinbase",
        provider_name: "Coinbase Exchange",
        original_source: "coinbase_exchange",
        enabled: true,
        attribution: null,
      },
    },
  ],
  market_cap_source: {
    provider_id: "coingecko",
    provider_name: "CoinGecko",
    original_source: "coingecko",
    enabled: true,
    attribution: { text: "Data provided by CoinGecko", url: "https://www.coingecko.com" },
  },
};

describe("formatting keeps reported digits", () => {
  it("groups digits without float rounding", () => {
    expect(formatDecimal("85265.26")).toBe("85,265.26");
    expect(formatDecimal("0.123456789123", 8)).toBe("0.12345678");
    expect(formatDecimal("1.50000000")).toBe("1.5");
    expect(formatDecimal("12345678901234567890.1")).toBe("12,345,678,901,234,567,890.1");
    expect(formatDecimal(null)).toBe("—");
  });

  it("formats large values, ages and UTC times", () => {
    expect(formatCompact("1691500000000.5", "usd")).toBe("1.69 T USD");
    expect(formatCompact(null, "usd")).toBe("—");
    expect(formatAge(null)).toBe("never");
    expect(formatAge(45)).toBe("45 s ago");
    expect(formatAge(600)).toBe("10 min ago");
    expect(formatUtc("2026-09-01T11:58:00Z")).toBe("2026-09-01 11:58 UTC");
  });
});

describe("chart data", () => {
  it("turns missing bars into holes, never zeros", () => {
    const { candles, volumes, flagged } = toChartData([
      bar("2026-09-01T00:00:00Z", "10"),
      bar("2026-09-01T01:00:00Z", null, "missing"),
      bar("2026-09-01T02:00:00Z", "11", "suspect"),
    ]);
    const t = (iso: string) => Date.parse(iso) / 1000;
    expect(candles[1]).toEqual({ time: t("2026-09-01T01:00:00Z") });
    expect(volumes[1]).toEqual({ time: t("2026-09-01T01:00:00Z") });
    expect(candles[0]).toMatchObject({ open: 10, close: 10 });
    expect(flagged).toEqual([{ time: t("2026-09-01T02:00:00Z"), status: "suspect", note: "note" }]);
  });
});

describe("selection", () => {
  it("falls back to known values", () => {
    expect(resolveSelection(catalog, {})).toEqual({
      asset: "BTC",
      timeframe: "1h",
      venue: "coinbase",
    });
    expect(resolveSelection(catalog, { asset: "eth", tf: "4h", venue: "nope" })).toEqual({
      asset: "ETH",
      timeframe: "4h",
      venue: "coinbase",
    });
    expect(resolveSelection(catalog, { tf: "2h" }).timeframe).toBe("1h");
  });

  it("builds links", () => {
    expect(
      selectionHref({ asset: "BTC", timeframe: "1h", venue: "coinbase" }, { asset: "SOL" }),
    ).toBe("/market?asset=SOL&tf=1h&venue=coinbase");
  });
});

describe("API client", () => {
  it("reports API errors instead of hiding them", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const failing = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Unknown asset 'DOGE'." }), { status: 404 }),
    ) as unknown as typeof fetch;
    const result = await fetchBars({ asset: "DOGE", timeframe: "1h", venue: "coinbase" }, failing);
    expect(result).toEqual({ ok: false, status: 404, reason: "Unknown asset 'DOGE'." });
    const call = (failing as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe(
      "http://api.test/api/v1/market/bars?asset=DOGE&timeframe=1h&venue=coinbase&limit=300",
    );
  });

  it("reports an unreachable API", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const result = await fetchBars({ asset: "BTC", timeframe: "1h", venue: "coinbase" }, down);
    expect(result).toEqual({ ok: false, status: null, reason: "Unreachable" });
  });
});
