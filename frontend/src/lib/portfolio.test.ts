import { describe, expect, it, vi } from "vitest";

import { emptyRaw, populatedRaw } from "@/components/portfolio/portfolio-fixtures";

import {
  fetchPortfolioExposure,
  formatShare,
  invalidReasonLabel,
  parsePortfolioExposure,
  relationLabel,
} from "./portfolio";

const respond = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

describe("parsePortfolioExposure", () => {
  it("accepts the populated and the empty response and keeps decimals as strings", () => {
    const populated = parsePortfolioExposure(populatedRaw());
    expect(populated?.summary.gross_notional).toBe("1500");
    expect(populated?.assets[1].net_notional).toBe("-500");
    expect(populated?.assets[0].brief.status).toBe("assessed");
    expect(populated?.assets[1].disagreement).toBeNull();
    const empty = parsePortfolioExposure(emptyRaw());
    expect(empty?.summary.status).toBe("empty");
    expect(empty?.summary.notional_weighted_leverage).toBeNull();
  });

  it("refuses a wrong contract version, a non-object, and a missing summary field", () => {
    expect(parsePortfolioExposure(null)).toBeNull();
    expect(
      parsePortfolioExposure({ ...populatedRaw(), contract_version: "portfolio_exposure.v1" }),
    ).toBeNull();
    const raw = populatedRaw();
    delete (raw.summary as Record<string, unknown>).net_notional;
    expect(parsePortfolioExposure(raw)).toBeNull();
  });

  it("refuses the whole response when any asset or position is malformed", () => {
    const badAsset = populatedRaw();
    (badAsset.assets as Record<string, unknown>[])[1].brief = { status: "agrees" };
    expect(parsePortfolioExposure(badAsset)).toBeNull();
    const badPosition = populatedRaw();
    (badPosition.positions as Record<string, unknown>[])[0].disagreement = "yes";
    expect(parsePortfolioExposure(badPosition)).toBeNull();
    const badInvalid = populatedRaw();
    badInvalid.invalid_positions = [{ reasons: ["unknown_asset"] }];
    expect(parsePortfolioExposure(badInvalid)).toBeNull();
  });

  it("never turns a missing brief into an assessed one", () => {
    const raw = populatedRaw();
    (raw.assets as Record<string, unknown>[])[0].brief = { status: "assessed", stance: "Bullish" };
    expect(parsePortfolioExposure(raw)).toBeNull();
  });
});

describe("fetchPortfolioExposure", () => {
  it("calls only the read-only exposure endpoint, as a plain GET", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    const f = respond(populatedRaw());
    const result = await fetchPortfolioExposure(f);
    expect(result.ok).toBe(true);
    const call = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(call[0])).toBe("http://api.test/api/v1/portfolio/exposure");
    expect((call[1] as RequestInit).method).toBeUndefined();
    expect(JSON.stringify(call[1])).not.toMatch(/authorization|api[-_]?key/i);
  });

  it("passes HTTP errors through, reports a network failure, and refuses an unexpected shape", async () => {
    process.env.API_INTERNAL_URL = "http://api.test";
    expect(await fetchPortfolioExposure(respond({ detail: "no db" }, 503))).toEqual({
      ok: false,
      status: 503,
      reason: "no db",
    });
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    expect(await fetchPortfolioExposure(down)).toEqual({
      ok: false,
      status: null,
      reason: "Unreachable",
    });
    const odd = await fetchPortfolioExposure(respond({ contract_version: "other" }));
    expect(odd.ok).toBe(false);
    expect(!odd.ok && odd.reason).toMatch(/unexpected shape/);
  });
});

describe("wording helpers", () => {
  it("labels the closed relation vocabulary and falls back readably", () => {
    expect(relationLabel("not_assessed")).toBe("Not assessed");
    expect(relationLabel("opposite_direction")).toBe("Opposite to the brief");
    expect(relationLabel("brand_new_value")).toBe("brand new value");
    expect(invalidReasonLabel("unknown_asset")).toBe("unsupported asset");
  });

  it("formats shares as percentages and leaves unparseable values visible", () => {
    expect(formatShare("0.666667")).toBe("66.7%");
    expect(formatShare(null)).toBe("—");
    expect(formatShare("n/a")).toBe("n/a");
  });
});
