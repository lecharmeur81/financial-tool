import { describe, expect, it, vi } from "vitest";

import {
  DECISION_ASSETS,
  domainLabel,
  evidenceStateLabel,
  fetchDecisionCurrent,
  isAvailableState,
  resolveDecisionAsset,
} from "./decision";

describe("resolveDecisionAsset", () => {
  it("defaults to BTC and accepts the four supported assets in any case", () => {
    expect(resolveDecisionAsset({})).toBe("BTC");
    expect(resolveDecisionAsset({ asset: "eth" })).toBe("ETH");
    expect(resolveDecisionAsset({ asset: ["sol", "xrp"] })).toBe("SOL");
    expect(DECISION_ASSETS).toEqual(["BTC", "ETH", "SOL", "XRP"]);
  });

  it("falls back to BTC for anything unsupported", () => {
    expect(resolveDecisionAsset({ asset: "DOGE" })).toBe("BTC");
    expect(resolveDecisionAsset({ asset: "" })).toBe("BTC");
  });
});

describe("fetchDecisionCurrent", () => {
  it("calls only the read-only decision endpoint with the asset", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ asset: "ETH" }), { status: 200 }),
    ) as unknown as typeof fetch;
    const result = await fetchDecisionCurrent("ETH", fetchMock);
    expect(result.ok).toBe(true);
    const call = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/decision/current?asset=ETH");
    expect((call[1] as RequestInit).method).toBeUndefined(); // a GET, never a mutation
  });

  it("reports an HTTP failure with the status and the problem detail", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ detail: "No stored snapshot" }), { status: 404 }),
    ) as unknown as typeof fetch;
    expect(await fetchDecisionCurrent("BTC", fetchMock)).toEqual({
      ok: false,
      status: 404,
      reason: "No stored snapshot",
    });
  });

  it("reports an unreachable API", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const fetchMock = vi.fn(async () => {
      throw new Error("down");
    }) as unknown as typeof fetch;
    expect(await fetchDecisionCurrent("BTC", fetchMock)).toEqual({
      ok: false,
      status: null,
      reason: "Unreachable",
    });
  });
});

describe("wording", () => {
  it("words a missing source as a state, never as a value", () => {
    expect(evidenceStateLabel("insufficient_data")).toBe("Insufficient data");
    expect(evidenceStateLabel("unavailable")).toBe("Unavailable");
    expect(isAvailableState("insufficient_data")).toBe(false);
    expect(isAvailableState("stale")).toBe(false);
    expect(isAvailableState("available")).toBe(true);
  });

  it("names evidence areas in plain language and passes unknown ones through", () => {
    expect(domainLabel("institutional")).toBe("Institutional flows (US spot ETFs)");
    expect(domainLabel("something_new")).toBe("something_new");
  });
});
