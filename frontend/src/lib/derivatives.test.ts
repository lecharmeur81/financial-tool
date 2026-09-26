import { describe, expect, it } from "vitest";

import {
  conditionClass,
  type DerivativesHistory,
  formatPct,
  formatPoints,
  hasDetail,
  resolveDerivativeAsset,
  stressBandClass,
  toOpenInterestChart,
} from "./derivatives";

describe("derivatives helpers", () => {
  it("resolves the asset from the query, defaulting to BTC", () => {
    expect(resolveDerivativeAsset({ asset: "sol" })).toBe("SOL");
    expect(resolveDerivativeAsset({ asset: ["xrp", "eth"] })).toBe("XRP");
    expect(resolveDerivativeAsset({ asset: "DOGE" })).toBe("BTC");
    expect(resolveDerivativeAsset({})).toBe("BTC");
  });

  it("formats signed percentages and shows missing values as a dash", () => {
    expect(formatPct("12")).toBe("+12.00 %");
    expect(formatPct("-3.1")).toBe("−3.10 %");
    expect(formatPct("0")).toBe("0.00 %");
    expect(formatPct("0.05", 4)).toBe("+0.0500 %");
    expect(formatPct(null)).toBe("—");
    expect(formatPoints("8")).toBe("+8.00 pts");
    expect(formatPoints(null)).toBe("—");
  });

  it("colours stress bands without a direction", () => {
    expect(stressBandClass("low stress")).toBe("badge badge-ok");
    expect(stressBandClass("moderate stress")).toBe("badge badge-neutral");
    expect(stressBandClass("high stress")).toBe("badge badge-warn");
    expect(stressBandClass(null)).toBe("badge badge-neutral");
    expect(conditionClass("active")).toBe("badge badge-warn");
    expect(conditionClass("unknown")).toBe("badge badge-neutral");
  });

  it("tells sections with details from not-applicable ones", () => {
    expect(hasDetail({ status: "not_applicable", reason: "none" })).toBe(false);
    expect(hasDetail({ status: "ok", venue: "deribit" })).toBe(true);
  });

  it("builds chart lines with holes for missing hours", () => {
    const history = {
      asset: "BTC",
      as_of: "2026-09-10T12:05:00+00:00",
      days: 1,
      open_interest: {
        unit: "btc",
        venues: {},
        aggregate: [
          { time: "2026-09-10T10:00:00+00:00", value: "130000" },
          { time: "2026-09-10T11:00:00+00:00", value: null },
        ],
        aggregate_venues: ["binance", "okx"],
      },
      price: {
        unit: "usd",
        source: "Coinbase",
        points: [{ time: "2026-09-10T11:00:00+00:00", value: "60000" }],
      },
    } satisfies DerivativesHistory;
    const chart = toOpenInterestChart(history);
    expect(chart.openInterest).toEqual([{ time: 1789034400, value: 130000 }, { time: 1789038000 }]);
    expect(chart.price).toEqual([{ time: 1789038000, value: 60000 }]);
  });
});
