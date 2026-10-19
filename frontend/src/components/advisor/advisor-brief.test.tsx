import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AdvisorAsset, AdvisorBrief } from "@/lib/advisor";
import type { ApiResult } from "@/lib/market";

import { AdvisorBriefLoading, AdvisorBriefView } from "./AdvisorBriefView";
import { candidateRaw, insufficientRaw, parsed } from "./advisor-fixtures";

afterEach(cleanup);

const ok = (data: AdvisorBrief): ApiResult<AdvisorBrief> => ({ ok: true, data });
const fail = (status: number | null, reason: string): ApiResult<AdvisorBrief> => ({
  ok: false,
  status,
  reason,
});
const view = (result: ApiResult<AdvisorBrief>, asset: AdvisorAsset = "BTC") =>
  render(<AdvisorBriefView result={result} asset={asset} />);
const text = (id: string) => screen.getByTestId(id).textContent;

describe("asset selection", () => {
  it("offers BTC, ETH, SOL and XRP as links and marks only the current one", () => {
    view(ok(parsed(insufficientRaw("SOL"))), "SOL");
    const nav = screen.getByRole("navigation", { name: "Advisor Brief asset" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["BTC", "ETH", "SOL", "XRP"]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/advisor?asset=BTC",
      "/advisor?asset=ETH",
      "/advisor?asset=SOL",
      "/advisor?asset=XRP",
    ]);
    expect(
      links.filter((l) => l.getAttribute("aria-current") === "page").map((l) => l.textContent),
    ).toEqual(["SOL"]);
    expect(screen.getByRole("heading", { name: /Advisor Brief — SOL/ })).toBeTruthy();
  });

  it("warns that a non-BTC brief is not fully independent", () => {
    view(ok(parsed(insufficientRaw("ETH"))), "ETH");
    expect(screen.getByText(/not a fully independent analysis/)).toBeTruthy();
  });

  it("keeps the selector available when the fetch failed", () => {
    view(fail(404, "none"), "XRP");
    expect(screen.getByRole("navigation", { name: "Advisor Brief asset" })).toBeTruthy();
  });
});

describe("successful rendering", () => {
  it("shows stance, confidence, posture and decision state as the engine returned them", () => {
    view(ok(parsed(candidateRaw())));
    expect(text("advisor-stance")).toBe("Bullish");
    expect(text("advisor-confidence")).toBe("Moderate");
    expect(text("advisor-posture")).toBe("MONITOR WITH ELEVATED CAUTION");
    expect(text("advisor-decision-state")).toBe("Candidate: unresolved checks");
    expect(screen.queryByTestId("advisor-insufficient")).toBeNull();
  });

  it("labels each signal with its layer and scope, and flags quality issues", () => {
    view(ok(parsed(candidateRaw())));
    const signals = screen.getByTestId("advisor-signals");
    expect(within(signals).getByText("Calculated signal")).toBeTruthy();
    expect(within(signals).getByText("Hypothesis")).toBeTruthy();
    expect(within(signals).getByText(/scope: asset_specific/)).toBeTruthy();
    expect(within(signals).getByText("partial")).toBeTruthy();
  });

  it("never presents confidence as a probability or the brief as a prediction", () => {
    const { container } = view(ok(parsed(candidateRaw())));
    expect(container.textContent).not.toMatch(/\d\s*%/);
    expect(container.textContent).not.toMatch(/\b(buy|sell)\b/i);
    expect(container.textContent).toMatch(/not a prediction, not personalized advice/);
  });
});

describe("insufficient_evidence", () => {
  it("explains it as a valid result, not an error and not a recommendation", () => {
    view(ok(parsed(insufficientRaw())));
    expect(text("advisor-stance")).toBe("Insufficient Evidence");
    expect(text("advisor-decision-state")).toBe("Insufficient evidence");
    const note = screen.getByTestId("advisor-insufficient");
    expect(note.textContent).toMatch(/valid result, not an error/);
    expect(note.textContent).toMatch(/not a hold, buy or sell recommendation/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says plainly that no signals were usable instead of showing a neutral reading", () => {
    view(ok(parsed(insufficientRaw())));
    expect(screen.getByTestId("advisor-no-signals").textContent).toMatch(/not a neutral reading/);
    expect(screen.queryByTestId("advisor-signals")).toBeNull();
  });
});

describe("data gaps and evidence quality", () => {
  it("lists every gap kind conspicuously, with the count", () => {
    view(ok(parsed(insufficientRaw())));
    const gaps = screen.getByTestId("advisor-gaps");
    expect(within(gaps).getByRole("heading").textContent).toMatch(/Data gaps\s*6/);
    for (const label of [
      "Evidence area not usable",
      "Missing directional evidence",
      "Stale component",
      "Partial component",
      "Not assessed",
      "Investment state not conclusive",
    ]) {
      expect(within(gaps).getByText(label)).toBeTruthy();
    }
    expect(within(gaps).getByText("ETF flow source returned nothing.")).toBeTruthy();
    expect(gaps.textContent).toMatch(/never counted as neutral/);
  });

  it("marks stale and unavailable readings as unusable, and only available ones as usable", () => {
    view(ok(parsed(insufficientRaw())));
    const rows = within(screen.getByTestId("advisor-readings")).getAllByRole("listitem");
    const byUsable = rows.map((r) => r.getAttribute("data-usable"));
    expect(byUsable).toEqual(["no", "no", "yes"]);
    expect(rows[0].textContent).toMatch(/Unavailable/);
    expect(rows[1].textContent).toMatch(/Stale/);
    expect(rows[1].textContent).toMatch(/not counted as neutral/);
    expect(rows[1].textContent).not.toMatch(/direction: supportive/);
  });

  it("does not hide the case where gaps are reported but not itemised", () => {
    const raw = insufficientRaw() as { data_gaps: Record<string, unknown> };
    raw.data_gaps = { has_gaps: true, items: [] };
    view(ok(parsed(raw)));
    expect(screen.getByTestId("advisor-gaps").textContent).toMatch(/incomplete/);
  });

  it("reports no gaps only when the brief says so", () => {
    const raw = candidateRaw() as { data_gaps: Record<string, unknown> };
    raw.data_gaps = { has_gaps: false, items: [] };
    view(ok(parsed(raw)));
    expect(screen.getByTestId("advisor-gaps").textContent).toMatch(/reports no data gaps/);
  });
});

describe("risk, invalidation and reassessment", () => {
  it("shows decision risks and limits", () => {
    view(ok(parsed(insufficientRaw())));
    expect(screen.getByTestId("advisor-risks").textContent).toMatch(/Market stress — Moderate/);
    expect(screen.getByText(/Highest decision risk: Moderate/)).toBeTruthy();
    expect(screen.getByText("Formal confirmation is a future capability.")).toBeTruthy();
  });

  it("says that missing invalidation conditions are not proof of validity", () => {
    view(ok(parsed(insufficientRaw())));
    expect(screen.getByTestId("advisor-invalidation").textContent).toMatch(
      /No invalidation conditions/,
    );
    expect(screen.getByTestId("advisor-invalidation").textContent).toMatch(/not a statement/);
  });

  it("marks only not_triggered as clean and keeps cannot-evaluate visibly unresolved", () => {
    view(ok(parsed(candidateRaw())));
    const panel = screen.getByTestId("advisor-invalidation");
    const clean = within(panel).getByText("Not triggered");
    const unresolved = within(panel).getAllByText("Cannot be evaluated");
    expect(clean.className).toContain("badge-ok");
    expect(unresolved.every((e) => e.className.includes("badge-warn"))).toBe(true);
  });

  it("shows reassessment triggers and flags the ones that cannot be evaluated now", () => {
    view(ok(parsed(insufficientRaw())));
    const list = screen.getByTestId("advisor-reassessment");
    expect(list.textContent).toMatch(/When a newer snapshot is stored/);
    expect(within(list).getAllByText("cannot be evaluated now")).toHaveLength(1);
  });
});

describe("not_claimed disclosure", () => {
  it("is a collapsed details element with the API's statements", () => {
    view(ok(parsed(insufficientRaw())));
    const d = screen.getByTestId("advisor-not-claimed") as HTMLDetailsElement;
    expect(d.tagName).toBe("DETAILS");
    expect(d.open).toBe(false);
    expect(within(d).getByText("Not personalized financial advice.")).toBeTruthy();
    expect(within(d).getAllByRole("listitem")).toHaveLength(3);
  });

  it("still disclaims when the service returned none", () => {
    const raw = insufficientRaw() as { not_claimed: unknown[] };
    raw.not_claimed = [];
    view(ok(parsed(raw)));
    expect(screen.getByTestId("advisor-not-claimed").textContent).toMatch(/not a prediction/);
  });
});

describe("error and loading states", () => {
  it("404 is a normal 'no assessment yet' state, not an alert", () => {
    view(fail(404, "No stored snapshot"));
    expect(screen.getByTestId("advisor-error-404").textContent).toMatch(/No assessment yet/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("422 names the supported assets", () => {
    view(fail(422, "Unsupported asset."));
    expect(screen.getByTestId("advisor-error-422").textContent).toMatch(/BTC, ETH, SOL or XRP/);
  });

  it("503 is an alert carrying the reason, and shows nothing in its place", () => {
    view(fail(503, "payload refused"));
    const e = screen.getByTestId("advisor-error-503");
    expect(e.textContent).toMatch(/payload refused/);
    expect(e.textContent).toMatch(/Nothing is shown in its place/);
    expect(screen.queryByTestId("advisor-stance")).toBeNull();
  });

  it("network and unexpected-shape failures render without crashing", () => {
    view(fail(null, "Unreachable"));
    expect(screen.getByTestId("advisor-error-other").textContent).toMatch(/Unreachable/);
    cleanup();
    view(
      fail(
        null,
        "The advisor service returned a response in an unexpected shape, so nothing is shown.",
      ),
    );
    expect(screen.getByTestId("advisor-error-other").textContent).toMatch(/unexpected shape/);
    expect(screen.queryByTestId("advisor-stance")).toBeNull();
  });

  it("shows a loading state", () => {
    render(<AdvisorBriefLoading />);
    expect(screen.getByRole("status").textContent).toMatch(/Loading/);
  });
});
