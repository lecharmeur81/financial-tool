import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { NAV_ITEMS, isActive, navItem } from "./navigation";

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

  it("rejects unknown items", () => {
    expect(() => navItem("/nope")).toThrow("Unknown navigation item");
  });
});
