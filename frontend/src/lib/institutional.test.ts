import { describe, expect, it } from "vitest";

import {
  bandClass,
  type EtfBucket,
  flowHref,
  formatSigned,
  formatSignedGrouped,
  formatUsdCompact,
  formatUsdMillions,
  periodLabel,
  resolveFlowSelection,
  toFlowChart,
} from "./institutional";

const quality = {
  status: "complete",
  days_expected: 1,
  days_present: 1,
  flagged: 0,
  revised: 0,
  backfilled: 0,
  estimated_availability: 0,
  notes: [],
};

const bucket = (start: string, flow: string | null, status: EtfBucket["status"]): EtfBucket => ({
  start,
  end: start,
  net_flow_usd: flow,
  net_assets_usd: null,
  net_assets_date: null,
  value_traded_usd: null,
  inflow_days: 0,
  outflow_days: 0,
  status,
  quality,
  reconciliation: null,
});

describe("selection", () => {
  it("accepts all four ETF assets, including SOL and XRP", () => {
    expect(resolveFlowSelection({ asset: "sol", interval: "1w" })).toEqual({
      asset: "SOL",
      interval: "1w",
    });
    expect(resolveFlowSelection({ asset: "XRP" }).asset).toBe("XRP");
  });

  it("falls back to defaults for unknown values", () => {
    expect(resolveFlowSelection({ asset: "DOGE", interval: "2h" })).toEqual({
      asset: "BTC",
      interval: "1d",
    });
  });

  it("builds links that keep the other choice", () => {
    expect(flowHref({ asset: "BTC", interval: "1mo" }, { asset: "ETH" })).toBe(
      "/flows?asset=ETH&interval=1mo",
    );
  });
});

describe("formatting", () => {
  it("formats signed USD millions with a real minus sign", () => {
    expect(formatUsdMillions("200000000")).toBe("+200.0 M USD");
    expect(formatUsdMillions("-55066297")).toBe("−55.1 M USD");
    expect(formatUsdMillions(null)).toBe("—");
  });

  it("formats net assets and signed numbers", () => {
    expect(formatUsdCompact("100000000000")).toBe("100.00 B USD");
    expect(formatSigned("69.5", 1)).toBe("+69.5");
    expect(formatSigned("-0.5", 2, " %")).toBe("−0.50 %");
    expect(formatSignedGrouped("59000")).toBe("+59,000");
    expect(formatSignedGrouped("-300.5", 4)).toBe("−300.5");
  });

  it("colours bands by direction only", () => {
    expect(bandClass("strong net inflow")).toContain("badge-ok");
    expect(bandClass("net outflow")).toContain("badge-error");
    expect(bandClass("balanced")).toContain("badge-neutral");
  });
});

describe("chart data", () => {
  it("draws missing buckets as holes, never zeros, and partial buckets lighter", () => {
    const points = toFlowChart([
      bucket("2026-09-03", "400000000", "complete"),
      bucket("2026-09-04", null, "no_data"),
      bucket("2026-09-08", "-100000000", "partial"),
    ]);
    expect(points[0]).toEqual({ time: 1788393600, value: 400, color: "#17803d" });
    expect(points[1]).toEqual({ time: 1788480000 });
    expect(points[2]).toMatchObject({ value: -100, color: "rgba(180,35,24,0.45)" });
  });
});

describe("periods", () => {
  it("shows the last included day of half-open ranges", () => {
    expect(periodLabel("2026-09-14", "2026-09-21")).toBe("2026-09-14 … 2026-09-20");
    expect(periodLabel("2026-09-04", "2026-09-05")).toBe("2026-09-04");
    expect(periodLabel("2026-12-01", "2027-01-01")).toBe("2026-12-01 … 2026-12-31");
  });
});
