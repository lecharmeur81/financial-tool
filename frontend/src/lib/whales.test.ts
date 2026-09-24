import { describe, expect, it } from "vitest";

import {
  classBadge,
  type Classification,
  contradictionClass,
  formatCoins,
  resolveWhaleAsset,
  shortAddress,
  toNetflowChart,
  whaleBandClass,
} from "./whales";

const cls = (overrides: Partial<Classification> = {}): Classification => ({
  address: "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
  chain: "bitcoin",
  actor_class: "exchange",
  display: "Known exchange: Binance",
  entity_id: "binance",
  entity_name: "Binance",
  evidence_class: "attributed",
  confidence: "0.6",
  evidence: 'wallet label "Binance-coldwallet"',
  source: "BitInfoCharts",
  source_url: null,
  rule: "label (attributed)",
  conflicting_labels: [],
  ...overrides,
});

describe("whale helpers", () => {
  it("accepts only tracked assets and defaults to BTC", () => {
    expect(resolveWhaleAsset({ asset: "eth" })).toBe("ETH");
    expect(resolveWhaleAsset({ asset: "SOL" })).toBe("BTC");
    expect(resolveWhaleAsset({})).toBe("BTC");
    expect(resolveWhaleAsset({ asset: ["ETH", "BTC"] })).toBe("ETH");
  });

  it("draws days without data as holes, never zeros", () => {
    const points = toNetflowChart([
      { date: "2026-09-08", values: {}, netflow: "-1000" },
      { date: "2026-09-09", values: {}, netflow: null },
      { date: "2026-09-10", values: {}, netflow: "250.5" },
    ]);
    expect(points[0]).toEqual({ time: 1788825600, value: -1000, color: "#17803d" });
    expect(points[1]).toEqual({ time: 1788912000 });
    expect(points[2]).toMatchObject({ value: 250.5, color: "#b42318" });
  });

  it("formats coins and addresses", () => {
    expect(formatCoins("12118.44914273", "btc")).toBe("12,118.45 BTC");
    expect(formatCoins(null, "eth")).toBe("—");
    expect(shortAddress("34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo")).toBe("34xp4vRo…4Twseo");
    expect(shortAddress("0x12")).toBe("0x12");
  });

  it("styles bands, contradictions and classes", () => {
    expect(whaleBandClass("strong accumulation")).toBe("badge badge-ok");
    expect(whaleBandClass("distribution")).toBe("badge badge-error");
    expect(whaleBandClass("neutral")).toBe("badge badge-neutral");
    expect(contradictionClass("contradiction")).toBe("badge badge-warn");
    expect(contradictionClass("consistent")).toBe("badge badge-ok");
    expect(classBadge(cls())).toBe("badge badge-ok");
    expect(
      classBadge(cls({ actor_class: "unknown_large_holder", evidence_class: "inferred" })),
    ).toBe("badge badge-neutral");
    expect(classBadge(cls({ actor_class: "unlabelled", evidence_class: null }))).toBe(
      "badge badge-neutral",
    );
  });
});
