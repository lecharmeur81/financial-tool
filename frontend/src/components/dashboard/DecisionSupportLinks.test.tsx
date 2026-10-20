import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NAV_ITEMS } from "@/lib/navigation";

import { DecisionSupportLinks } from "./DecisionSupportLinks";

afterEach(cleanup);

const hrefs = () => screen.getAllByRole("link").map((a) => a.getAttribute("href"));

describe("DecisionSupportLinks", () => {
  it("links the decision-support views, each backed by a real navigation entry", () => {
    render(<DecisionSupportLinks asset="BTC" />);
    expect(hrefs()).toEqual(["/advisor?asset=BTC", "/portfolio", "/alerts", "/brief", "/paper"]);
    for (const link of screen.getAllByRole("link")) {
      const path = (link.getAttribute("href") ?? "").split("?")[0];
      expect(NAV_ITEMS.some((i) => i.href === path)).toBe(true);
    }
  });

  it("keeps the asset the Decision Center is showing, and falls back for an unsupported one", () => {
    render(<DecisionSupportLinks asset="SOL" />);
    expect(hrefs()[0]).toBe("/advisor?asset=SOL");
    cleanup();
    render(<DecisionSupportLinks asset="DOGE" />);
    expect(hrefs()[0]).toBe("/advisor");
  });

  it("states that the views are descriptive and place no trade", () => {
    render(<DecisionSupportLinks asset="BTC" />);
    expect(screen.getByText(/none of them places a trade/)).toBeTruthy();
  });
});
