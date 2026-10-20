import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ApiResult } from "@/lib/market";
import type { PortfolioExposure } from "@/lib/portfolio";

import { PortfolioExposureLoading, PortfolioExposureView } from "./PortfolioExposureView";
import { emptyRaw, parsed, populatedRaw } from "./portfolio-fixtures";

afterEach(cleanup);

const ok = (data: PortfolioExposure): ApiResult<PortfolioExposure> => ({ ok: true, data });
const fail = (status: number | null, reason: string): ApiResult<PortfolioExposure> => ({
  ok: false,
  status,
  reason,
});
const view = (result: ApiResult<PortfolioExposure>) =>
  render(<PortfolioExposureView result={result} />);
const text = (id: string) => screen.getByTestId(id).textContent ?? "";

describe("simulated-only labelling", () => {
  it.each([
    ["populated", () => ok(parsed(populatedRaw()))],
    ["empty", () => ok(parsed(emptyRaw()))],
    ["error", () => fail(503, "no database")],
  ])("shows the simulated / not-real-holdings banner in the %s state", (_n, make) => {
    view(make());
    expect(text("exposure-simulated-banner")).toMatch(/Simulated paper trades only/);
    expect(text("exposure-simulated-banner")).toMatch(/not real holdings/);
  });
});

describe("populated exposure", () => {
  it("shows the calculated totals unchanged, with notional called out as entry size", () => {
    view(ok(parsed(populatedRaw())));
    const summary = text("exposure-summary");
    expect(summary).toMatch(/1,500 USD/);
    expect(summary).toMatch(/not marked to market/);
    expect(summary).toMatch(/BTC 66\.7%/);
    expect(summary).toMatch(/no threshold, no verdict/i);
  });

  it("compares each asset with its brief and flags disagreement without calling it advice", () => {
    view(ok(parsed(populatedRaw())));
    const table = within(screen.getByTestId("exposure-assets"));
    const rows = table.getAllByRole("row");
    const btc = rows.find((r) => r.textContent?.startsWith("BTC"))!;
    expect(btc.textContent).toMatch(/Bearish/);
    expect(btc.textContent).toMatch(/Opposite to the brief/);
    expect(btc.textContent).toMatch(/Disagrees with the brief/);
    expect(text("exposure-assets")).toMatch(/descriptive, not an instruction/);
  });

  it("shows a missing brief as not assessed, never neutral or agreeing", () => {
    view(ok(parsed(populatedRaw())));
    const eth = within(screen.getByTestId("exposure-assets"))
      .getAllByRole("row")
      .find((r) => r.textContent?.startsWith("ETH"))!;
    expect(eth.textContent).toMatch(/Not assessed/);
    expect(eth.textContent).not.toMatch(/Neutral|Same direction|Disagrees/);
  });

  it("links each asset to its Advisor Brief", () => {
    view(ok(parsed(populatedRaw())));
    const link = within(screen.getByTestId("exposure-assets")).getByRole("link", { name: "ETH" });
    expect(link.getAttribute("href")).toBe("/advisor?asset=ETH");
  });

  it("surfaces data gaps: missing price, unassessed brief and the excluded invalid trade", () => {
    view(ok(parsed(populatedRaw())));
    const gaps = text("exposure-gaps");
    expect(gaps).toMatch(/1 position\(s\) have no observed price/);
    expect(gaps).toMatch(/No usable Advisor Brief for ETH/);
    expect(gaps).toMatch(/Trade t3 was excluded.*unsupported asset/);
    expect(text("exposure-positions")).toMatch(/Price missing/);
    expect(text("exposure-source")).toMatch(/1 excluded as invalid/);
  });

  it("always lists what is unavailable and what is not claimed", () => {
    view(ok(parsed(populatedRaw())));
    expect(text("exposure-unavailable")).toMatch(/Real holdings and account balances/);
    expect(text("exposure-unavailable")).toMatch(/Return correlation/);
    expect(text("exposure-not-claimed")).toMatch(/not real holdings/);
    expect(text("exposure-conventions")).toMatch(/not marked to market/);
  });

  it("contains no recommendation, order or prediction wording", () => {
    const { container } = view(ok(parsed(populatedRaw())));
    expect(container.textContent).not.toMatch(
      /\b(you should|buy now|sell now|will rise|guaranteed)\b/i,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("empty and failing states", () => {
  it("says there is no simulated exposure and still shows the disclosures", () => {
    view(ok(parsed(emptyRaw())));
    expect(text("exposure-empty")).toMatch(/No valid open paper trades/);
    expect(screen.queryByTestId("exposure-summary")).toBeNull();
    expect(text("exposure-no-gaps")).toMatch(/No data gaps/);
    expect(text("exposure-not-claimed")).toMatch(/not real holdings/);
  });

  it("renders a 503 and a network failure as unavailable, with nothing in their place", () => {
    view(fail(503, "database not configured"));
    expect(text("exposure-error-503")).toMatch(/unavailable/);
    expect(screen.queryByTestId("exposure-summary")).toBeNull();
    cleanup();
    view(fail(null, "Unreachable"));
    expect(text("exposure-error-other")).toMatch(/Unreachable/);
  });

  it("links to the related views and shows a loading state", () => {
    view(fail(503, "x"));
    const nav = screen.getByRole("navigation", { name: "Related views" });
    expect(within(nav).getByRole("link", { name: "Advisor Brief" }).getAttribute("href")).toBe(
      "/advisor",
    );
    expect(within(nav).getByRole("link", { name: "Paper Trading" }).getAttribute("href")).toBe(
      "/paper",
    );
    cleanup();
    render(<PortfolioExposureLoading />);
    expect(screen.getByRole("status").textContent).toMatch(/Loading/);
  });
});
