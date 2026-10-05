import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DecisionCurrent } from "@/lib/decision";
import type { ApiResult } from "@/lib/market";

import { DecisionCenterLoading, DecisionCenterView } from "./DecisionCenter";
import {
  bullishDecision,
  cappedDecision,
  conflictedDecision,
  forAsset,
  insufficientDecision,
} from "./decision-fixtures";

afterEach(cleanup);

const ok = (data: DecisionCurrent): ApiResult<DecisionCurrent> => ({ ok: true, data });

function renderView(data: DecisionCurrent) {
  return render(<DecisionCenterView result={ok(data)} asset={data.asset} />);
}

describe("Insufficient Evidence (the current real-data state)", () => {
  it("shows the engine's stance, confidence and posture and says it is not an error", () => {
    renderView(insufficientDecision());
    expect(screen.getByTestId("decision-stance").textContent).toBe("Insufficient Evidence");
    expect(screen.getByTestId("decision-confidence").textContent).toBe("Insufficient Evidence");
    expect(screen.getByTestId("decision-posture").textContent).toBe("INVESTIGATE FURTHER");
    expect(screen.getByText(/valid result, not an error/)).toBeTruthy();
    expect(
      screen.getByText(/enough reliable evidence to take a bullish or bearish stance/),
    ).toBeTruthy();
    expect(screen.getByText(/1 of 5 core evidence areas/)).toBeTruthy();
  });

  it("is not an alert: nothing about it is presented as a failure", () => {
    renderView(insufficientDecision());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("stance, confidence and posture", () => {
  it("renders the labels exactly as the engine returned them", () => {
    renderView(bullishDecision());
    expect(screen.getByTestId("decision-stance").textContent).toBe("Bullish");
    expect(screen.getByTestId("decision-confidence").textContent).toBe("Moderate");
    expect(screen.getByTestId("decision-posture").textContent).toBe(
      "MONITOR WITH ELEVATED CAUTION",
    );
    expect(
      screen.getByText(/More of the available evidence leans supportive than adverse/),
    ).toBeTruthy();
  });

  it("never turns confidence into a probability", () => {
    const { container } = renderView(bullishDecision());
    expect(screen.getByText(/It is not a probability of any price move/)).toBeTruthy();
    expect(screen.getByText(/decision support, not financial advice/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/\d\s*%/);
    expect(container.textContent).not.toMatch(/chance|likelihood/i);
  });
});

describe("supporting and adverse evidence", () => {
  it("lists each with the engine's sentence, its calculated band and its scope", () => {
    renderView(bullishDecision());
    const support = screen.getByRole("heading", { name: "Supporting evidence" }).closest("section");
    const adverse = screen
      .getByRole("heading", { name: "Contradicting or cautionary evidence" })
      .closest("section");
    expect(within(support as HTMLElement).getByText(/flowing into US spot funds/)).toBeTruthy();
    expect(within(support as HTMLElement).getByText("Asset-specific")).toBeTruthy();
    expect(within(support as HTMLElement).getByText(/strong net inflow/)).toBeTruthy();
    expect(within(adverse as HTMLElement).getByText(/Stablecoin supply is shrinking/)).toBeTruthy();
    expect(within(adverse as HTMLElement).getByText("Market-wide")).toBeTruthy();
  });

  it("says plainly when there is no adverse evidence, without calling missing data neutral", () => {
    renderView(insufficientDecision());
    expect(screen.getByText(/No contradicting or cautionary evidence was found/)).toBeTruthy();
    expect(screen.getByText(/Missing evidence is not neutral and not zero/)).toBeTruthy();
  });

  it("shows the main risks with their level", () => {
    renderView(insufficientDecision());
    const risks = screen.getByRole("heading", { name: "Main risks" }).closest("section");
    expect(within(risks as HTMLElement).getByText(/Market:/)).toBeTruthy();
    expect(within(risks as HTMLElement).getByText(/Low/)).toBeTruthy();
  });
});

describe("missing and insufficient data", () => {
  it("explains each missing area with the snapshot's own reason, verbatim", () => {
    renderView(insufficientDecision());
    const missing = screen.getByRole("heading", { name: /What is missing/ }).closest("section");
    const scope = within(missing as HTMLElement);
    expect(scope.getByText("no ETF data stored")).toBeTruthy();
    expect(
      scope.getByText(/Insufficient data: available components carry weight 0 of 1.00/),
    ).toBeTruthy();
    expect(scope.getByText("no circulating-supply snapshot for USDT")).toBeTruthy();
    expect(scope.getByText("no VIX value near as_of")).toBeTruthy();
    expect(scope.getAllByText("Insufficient data").length).toBe(4);
    expect(scope.getByText(/expected by 2026-10-02/)).toBeTruthy();
  });

  it("states when the snapshot records no reason, instead of inventing one", () => {
    renderView(insufficientDecision());
    expect(screen.getAllByText("The stored snapshot records no reason for this.").length).toBe(1);
  });

  it("never claims a cause the stored data does not state", () => {
    const { container } = renderView(insufficientDecision());
    expect(container.textContent).not.toMatch(
      /api key|provider (is )?down|ingestion (has )?failed|disconnected|not configured|outage/i,
    );
  });

  it("does not present a missing source as zero", () => {
    renderView(insufficientDecision());
    const missing = screen.getByRole("heading", { name: /What is missing/ }).closest("section");
    const institutional = within(missing as HTMLElement)
      .getByText("Institutional flows (US spot ETFs)")
      .closest("li") as HTMLElement;
    expect(within(institutional).getByText("Insufficient data")).toBeTruthy();
    expect(institutional.textContent).not.toMatch(/\b0\b/);
  });

  it("shows each missing-context sentence once, not twice", () => {
    renderView(insufficientDecision());
    expect(screen.getAllByText(/broader economic backdrop/).length).toBe(1);
  });

  it("keeps 'Sources conflict' distinct from 'Insufficient data'", () => {
    const { unmount } = renderView(conflictedDecision());
    expect(screen.getByText("Sources conflict")).toBeTruthy();
    expect(screen.getByText(/regime disagrees/)).toBeTruthy();
    unmount();
    renderView(insufficientDecision());
    expect(screen.queryByText("Sources conflict")).toBeNull();
    expect(screen.getAllByText("Insufficient data").length).toBeGreaterThan(0);
  });

  it("labels formal invalidation as a future capability and invents no conditions", () => {
    const { container } = renderView(insufficientDecision());
    expect(screen.getByText(/invalidation conditions are a future capability/)).toBeTruthy();
    expect(container.textContent).not.toMatch(
      /invalidat\w+ (level|price)|stop[- ]loss|target price/i,
    );
  });
});

describe("CAP-U", () => {
  it("explains why the final stance is more cautious than the underlying evidence", () => {
    renderView(cappedDecision());
    const cap = screen.getByTestId("decision-cap-u");
    expect(cap.textContent).toMatch(/underlying evidence reads Bullish/);
    expect(cap.textContent).toMatch(/final stance is Neutral \/ Wait/);
    expect(cap.textContent).toMatch(/market regime could not be read/);
    expect(cap.textContent).toMatch(/CU-01/);
    expect(screen.getByTestId("decision-stance").textContent).toBe("Neutral / Wait");
  });

  it("shows no CAP-U block when nothing was capped", () => {
    renderView(bullishDecision());
    expect(screen.queryByTestId("decision-cap-u")).toBeNull();
  });
});

describe("asset-specific versus market-wide", () => {
  it("tags each evidence area with its scope", () => {
    renderView(insufficientDecision());
    expect(screen.getAllByText("Asset-specific").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Market-wide").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Market-wide (BTC-benchmarked)").length).toBeGreaterThan(0);
  });

  it("does not present another asset as an independent analysis", () => {
    renderView(forAsset(insufficientDecision(), "ETH"));
    expect(screen.getByText(/ETH is not a fully independent analysis/)).toBeTruthy();
  });

  it("shows no such banner for BTC", () => {
    renderView(insufficientDecision());
    expect(screen.queryByText(/not a fully independent analysis/)).toBeNull();
  });

  it("shows the server's scope notes (for example, no whale evidence for SOL)", () => {
    const sol = {
      ...forAsset(insufficientDecision(), "SOL"),
      scope_notes: [
        "Whale activity is only tracked for BTC and ETH, so it is not part of the SOL assessment.",
      ],
    };
    renderView(sol);
    expect(screen.getByText(/Whale activity is only tracked for BTC and ETH/)).toBeTruthy();
  });
});

describe("asset switching", () => {
  it("links to each asset on the dashboard and marks the current one", () => {
    renderView(forAsset(insufficientDecision(), "SOL"));
    const nav = screen.getByRole("navigation", { name: "Decision Center asset" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/?asset=BTC",
      "/?asset=ETH",
      "/?asset=SOL",
      "/?asset=XRP",
    ]);
    expect(within(nav).getByRole("link", { name: "SOL" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(within(nav).getByRole("link", { name: "BTC" }).getAttribute("aria-current")).toBeNull();
  });
});

describe("timestamp, data quality and technical details", () => {
  it("shows when the assessment was observed and which snapshot it came from", () => {
    renderView(insufficientDecision());
    expect(screen.getByTestId("decision-observed").textContent).toMatch(/2026-10-05 23:09 UTC/);
    expect(screen.getByTestId("decision-observed").textContent).toMatch(/snapshot #467/);
  });

  it("keeps technical detail collapsed behind a disclosure", () => {
    const { container } = renderView(insufficientDecision());
    const details = container.querySelector("details.decision-disclosure") as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);
  });

  it("derives data quality from the assessment, not from the producer's summary flag", () => {
    renderView(insufficientDecision());
    expect(screen.getByText(/not from the snapshot producer's summary flag/)).toBeTruthy();
    expect(screen.getByText("institutional.score, macro.score")).toBeTruthy();
    expect(screen.queryByText(/data_quality_state/)).toBeNull();
  });

  it("separates Observed, Calculated and Interpretation", () => {
    renderView(insufficientDecision());
    expect(screen.getAllByText("Observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Calculated").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Interpretation").length).toBeGreaterThan(0);
    expect(screen.getByText(/No AI model writes any of this text/)).toBeTruthy();
  });

  it("shows the hash check and does not treat fields without a value as evidence", () => {
    renderView(insufficientDecision());
    expect(screen.getByText(/\(verified\)/)).toBeTruthy();
    expect(
      screen.getByText(/2 cited field\(s\) have no recorded value and are not treated as evidence/),
    ).toBeTruthy();
    expect(screen.getByText("get_macro.score.status")).toBeTruthy();
  });
});

describe("loading, empty and error states", () => {
  it("shows a loading state", () => {
    render(<DecisionCenterLoading />);
    expect(screen.getByRole("status").textContent).toMatch(/Loading the latest assessment/);
  });

  it("shows an empty state, not an error, when no snapshot is stored yet", () => {
    render(<DecisionCenterView result={{ ok: false, status: 404, reason: "x" }} asset="BTC" />);
    expect(screen.getByText(/No assessment yet/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("link", { name: "ETH" })).toBeTruthy(); // can still switch asset
  });

  it("shows an unavailable state with the reason for a real failure", () => {
    render(
      <DecisionCenterView
        result={{ ok: false, status: 503, reason: "The latest stored snapshot cannot be used" }}
        asset="BTC"
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/Decision Center unavailable/);
    expect(screen.getByText(/latest stored snapshot cannot be used/)).toBeTruthy();
  });

  it("shows an unreachable API as unavailable", () => {
    render(
      <DecisionCenterView
        result={{ ok: false, status: null, reason: "Unreachable" }}
        asset="BTC"
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/Unreachable/);
  });
});

describe("responsive layout", () => {
  const css = readFileSync(join(__dirname, "../../app/globals.css"), "utf8");

  it("wraps the stance tiles and evidence columns instead of overflowing", () => {
    expect(css).toMatch(/\.decision-tiles\s*{[^}]*auto-fit/);
    expect(css).toMatch(/\.decision-columns\s*{[^}]*auto-fit/);
  });

  it("has a narrow-screen rule for the Decision Center", () => {
    expect(css).toMatch(/@media \(max-width: 760px\)\s*{\s*\.decision-value/);
  });
});
