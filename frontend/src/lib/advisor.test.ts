import { describe, expect, it, vi } from "vitest";

import { candidateRaw, insufficientRaw } from "@/components/advisor/advisor-fixtures";

import {
  ADVISOR_ASSETS,
  decisionStateLabel,
  fetchAdvisorBrief,
  isUsableState,
  parseAdvisorBrief,
  resolveAdvisorAsset,
} from "./advisor";

const respond = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

describe("resolveAdvisorAsset", () => {
  it("defaults to BTC, accepts the four assets in any case, and rejects the rest", () => {
    expect(ADVISOR_ASSETS).toEqual(["BTC", "ETH", "SOL", "XRP"]);
    expect(resolveAdvisorAsset({})).toBe("BTC");
    expect(resolveAdvisorAsset({ asset: "sol" })).toBe("SOL");
    expect(resolveAdvisorAsset({ asset: ["xrp", "eth"] })).toBe("XRP");
    expect(resolveAdvisorAsset({ asset: "DOGE" })).toBe("BTC");
  });
});

describe("fetchAdvisorBrief", () => {
  it("calls only the read-only brief endpoint with the asset, as a GET", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const f = respond(insufficientRaw("ETH"));
    const result = await fetchAdvisorBrief("ETH", f);
    expect(result.ok).toBe(true);
    const call = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/advisor/brief?asset=ETH");
    expect((call[1] as RequestInit).method).toBeUndefined();
    expect(JSON.stringify(call[1])).not.toMatch(/authorization|api[-_]?key/i);
  });

  it.each([404, 422, 503])("passes HTTP %i through with the problem detail", async (status) => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const result = await fetchAdvisorBrief("BTC", respond({ detail: `d${status}` }, status));
    expect(result).toEqual({ ok: false, status, reason: `d${status}` });
  });

  it("reports a network failure without throwing", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const f = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    expect(await fetchAdvisorBrief("BTC", f)).toEqual({
      ok: false,
      status: null,
      reason: "Unreachable",
    });
  });

  it("refuses an unexpected response shape instead of rendering it", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const result = await fetchAdvisorBrief("BTC", respond({ hello: "world" }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.status).toBeNull();
      expect(result.reason).toMatch(/unexpected shape/);
    }
  });
});

describe("parseAdvisorBrief", () => {
  it("keeps the engine's words unchanged", () => {
    const b = parseAdvisorBrief(candidateRaw());
    expect(b?.assessment.stance.final).toBe("Bullish");
    expect(b?.assessment.stance.confidence).toBe("Moderate");
    expect(b?.assessment.decision_state).toBe("candidate_unresolved");
  });

  it.each([
    ["null", null],
    ["a string", "x"],
    ["wrong contract version", { ...insufficientRaw(), contract_version: "advisor_brief.v9" }],
    [
      "missing stance",
      { ...insufficientRaw(), assessment: { investment_state: { decision_state: "x" } } },
    ],
    ["data_gaps not an object", { ...insufficientRaw(), data_gaps: [] }],
    ["signals not a list", { ...insufficientRaw(), signals: {} }],
  ])("returns null for %s", (_n, body) => {
    expect(parseAdvisorBrief(body)).toBeNull();
  });

  it("treats a reading with no state as unknown, which is not usable", () => {
    const raw = insufficientRaw() as { readings: Record<string, unknown>[] };
    raw.readings = [{ domain: "macro" }];
    const b = parseAdvisorBrief(raw);
    expect(b?.readings[0].evidence_state).toBe("unknown");
    expect(isUsableState("unknown")).toBe(false);
  });

  it("states that gaps exist when the flag is missing", () => {
    const raw = insufficientRaw() as { data_gaps: Record<string, unknown> };
    raw.data_gaps = { items: [] };
    expect(parseAdvisorBrief(raw)?.data_gaps.has_gaps).toBe(true);
  });
});

describe("wording", () => {
  it("labels insufficient_evidence plainly and falls back for unknown states", () => {
    expect(decisionStateLabel("insufficient_evidence")).toBe("Insufficient evidence");
    expect(decisionStateLabel("some_new_state")).toBe("some new state");
  });
});
