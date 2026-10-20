import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { NAV_GROUPS, NAV_ITEMS, isActive, navGroups, navItem } from "./navigation";

const APP_DIR = join(__dirname, "..", "app");

describe("navigation", () => {
  it("contains exactly the sections built so far, in order", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual([
      "Dashboard",
      "Market",
      "Flows",
      "Whales",
      "Derivatives",
      "Liquidity",
      "Analytics",
      "Advisor Brief",
      "Portfolio Exposure",
      "Alerts",
      "Daily Brief",
      "Paper Trading",
      "Decision Journal",
      "Settings",
    ]);
  });

  it("has unique hrefs", () => {
    const hrefs = NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it.each(NAV_ITEMS.map((i) => [i.href]))("has a page file for %s", (href) => {
    expect(existsSync(join(APP_DIR, href, "page.tsx"))).toBe(true);
  });

  it("marks the active item", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/", "/market")).toBe(false);
    expect(isActive("/market", "/market")).toBe(true);
    expect(isActive("/market", "/market/btc")).toBe(true);
    expect(isActive("/market", "/marketplace")).toBe(false);
  });

  it("puts every item in a known group and keeps each group contiguous", () => {
    for (const item of NAV_ITEMS) expect(NAV_GROUPS).toContain(item.group);
    const grouped = navGroups();
    expect(grouped.map((g) => g.group)).toEqual([...NAV_GROUPS]);
    expect(grouped.flatMap((g) => g.items.map((i) => i.href))).toEqual(
      NAV_ITEMS.map((i) => i.href),
    );
    expect(grouped.find((g) => g.group === "Decision support")?.items.map((i) => i.label)).toEqual([
      "Advisor Brief",
      "Portfolio Exposure",
      "Alerts",
      "Daily Brief",
    ]);
  });

  it("rejects unknown items", () => {
    expect(() => navItem("/nope")).toThrow("Unknown navigation item");
  });
});
