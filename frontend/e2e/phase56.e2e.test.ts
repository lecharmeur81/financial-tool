/**
 * Phase 56 end-to-end validation of the frontend user workflows.
 *
 * What runs: the real, built Next.js server; real HTTP from the test to it; real HTTP from it to a
 * read-only mock API (`mock-api.ts`) that serves hand-written fixtures. Nothing else: no backend,
 * no database, no Docker.
 *
 * What this does and does not show: it exercises server rendering, navigation, the pages' API
 * calls and their loading / error / missing-data / malformed-data handling, and the simulated-
 * paper-trading disclosures. Populated-data behaviour is demonstrated with FIXTURE data only; it is
 * not evidence about the real database or the real backend (those are covered by the backend
 * integration tests, run separately against an isolated database).
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { NAV_GROUPS, NAV_ITEMS } from "@/lib/navigation";

import { type Stack, startStack } from "./harness";
import { DEFAULT_SCENARIO, type Scenario } from "./mock-api";

let stack: Stack;

beforeAll(async () => {
  stack = await startStack();
});

afterAll(async () => {
  await stack?.stop();
});

beforeEach(() => {
  stack.api.reset();
});

const use = (partial: Partial<Scenario>) => {
  stack.api.scenario = { ...DEFAULT_SCENARIO, ...partial };
};
const text = (doc: Document, selector?: string): string =>
  (selector ? doc.querySelector(selector) : doc.body)?.textContent ?? "";
const byId = (doc: Document, id: string): string => text(doc, `[data-testid="${id}"]`);
const hrefs = (doc: Document, selector: string): string[] =>
  Array.from(doc.querySelectorAll(`${selector} a`)).map((a) => a.getAttribute("href") ?? "");
const apiCalls = (path: string) => stack.api.requests.filter((r) => r.path === path);

describe("navigation and page availability", () => {
  it("serves every navigation entry with HTTP 200, its own title and a heading, even when the API has no data", async () => {
    use({ advisor: "404", portfolio: "503", decision: "503", alerts: "503", paper: "503" });
    for (const item of NAV_ITEMS) {
      const page = await stack.get(item.href);
      expect(page.status, item.href).toBe(200);
      // Each page sets its document title from its navigation entry (some pages use a more
      // specific on-page heading, so the title is the common check).
      expect(page.doc.title, item.href).toMatch(new RegExp(`^${item.label}( ·|$)`));
      expect(text(page.doc, "h1"), item.href).not.toBe("");
    }
  });

  it("shows grouped navigation with every entry once, and marks the current page", async () => {
    const page = await stack.get("/portfolio");
    const nav = 'nav[aria-label="Main navigation"]';
    const labels = Array.from(page.doc.querySelectorAll(`${nav} .nav-group-label`)).map(
      (n) => n.textContent,
    );
    expect(labels).toEqual([...NAV_GROUPS]);
    const links = Array.from(page.doc.querySelectorAll(`${nav} a`));
    expect(links.map((a) => a.textContent)).toEqual(NAV_ITEMS.map((i) => i.label));
    const current = links.filter((a) => a.getAttribute("aria-current") === "page");
    expect(current.map((a) => a.textContent)).toEqual(["Portfolio Exposure"]);
    expect(text(page.doc, nav)).toMatch(/not financial advice/i);
  });

  it("follows the Dashboard decision-support links to working pages", async () => {
    const dashboard = await stack.get("/?asset=SOL");
    const links = hrefs(dashboard.doc, ".decision-support-links");
    expect(links).toEqual(["/advisor?asset=SOL", "/portfolio", "/alerts", "/brief", "/paper"]);
    for (const href of links) {
      const page = await stack.get(href);
      expect(page.status, href).toBe(200);
    }
  });

  it("links Advisor Brief, Portfolio Exposure and back, keeping the asset", async () => {
    const advisor = await stack.get("/advisor?asset=ETH");
    expect(hrefs(advisor.doc, '[data-testid="advisor-related"]')).toEqual([
      "/portfolio",
      "/?asset=ETH",
      "/alerts",
    ]);
    const portfolio = await stack.get("/portfolio");
    expect(hrefs(portfolio.doc, 'nav[aria-label="Related views"]')).toEqual([
      "/advisor",
      "/paper",
      "/",
    ]);
    const dashboard = await stack.get("/?asset=ETH");
    expect(text(dashboard.doc, "h1")).toBe("Dashboard");
  });
});

describe("Dashboard", () => {
  it("renders the Decision Center from the API and the decision-support row", async () => {
    const page = await stack.get("/");
    expect(page.status).toBe(200);
    expect(byId(page.doc, "decision-stance")).not.toBe("");
    expect(text(page.doc, ".decision-support-links")).toMatch(/none of them places a trade/);
    expect(apiCalls("/api/v1/decision/current")).toHaveLength(1);
  });

  it("keeps rendering, with honest 'unavailable' notices, when sections have no data", async () => {
    use({ decision: "503" });
    const page = await stack.get("/");
    expect(page.status).toBe(200);
    expect(text(page.doc)).toMatch(/unavailable/i);
    // The links to the other views survive a failing Decision Center.
    expect(hrefs(page.doc, ".decision-support-links")).toContain("/portfolio");
    expect(page.doc.querySelector('[data-testid="decision-stance"]')).toBeNull();
  });
});

describe("Advisor Brief", () => {
  it("renders the brief for the requested asset and passes that asset to the API", async () => {
    const page = await stack.get("/advisor?asset=ETH");
    expect(page.status).toBe(200);
    expect(text(page.doc, "#advisor-title")).toBe("Advisor Brief — ETH");
    expect(byId(page.doc, "advisor-stance")).not.toBe("");
    expect(byId(page.doc, "advisor-not-claimed")).toMatch(/does not claim/);
    const calls = apiCalls("/api/v1/advisor/brief");
    expect(calls.map((c) => c.query)).toEqual(["?asset=ETH"]);
  });

  it("falls back to BTC for an unsupported asset and never forwards it to the API", async () => {
    const page = await stack.get("/advisor?asset=DOGE");
    expect(text(page.doc, "#advisor-title")).toBe("Advisor Brief — BTC");
    expect(apiCalls("/api/v1/advisor/brief").map((c) => c.query)).toEqual(["?asset=BTC"]);
  });

  it("shows insufficient evidence as such, never as a stance", async () => {
    use({ advisor: "insufficient" });
    const page = await stack.get("/advisor");
    expect(byId(page.doc, "advisor-insufficient")).not.toBe("");
    expect(byId(page.doc, "advisor-stance")).toMatch(/Insufficient Evidence/);
  });

  it.each([
    ["404", "advisor-error-404", /No assessment yet/],
    ["503", "advisor-error-503", /unavailable/i],
    ["malformed", "advisor-error-other", /unexpected shape/],
  ] as const)("handles a %s response without rendering any stance", async (mode, id, pattern) => {
    use({ advisor: mode });
    const page = await stack.get("/advisor");
    expect(page.status).toBe(200);
    expect(byId(page.doc, id)).toMatch(pattern);
    expect(page.doc.querySelector('[data-testid="advisor-stance"]')).toBeNull();
  });
});

describe("Portfolio Exposure", () => {
  it("shows the empty state with the simulated-trading and limitation disclosures", async () => {
    use({ portfolio: "empty" });
    const page = await stack.get("/portfolio");
    expect(page.status).toBe(200);
    expect(byId(page.doc, "exposure-simulated-banner")).toMatch(/Simulated paper trades only/);
    expect(byId(page.doc, "exposure-simulated-banner")).toMatch(/not real holdings/);
    expect(byId(page.doc, "exposure-empty")).toMatch(/No valid open paper trades/);
    expect(byId(page.doc, "exposure-unavailable")).toMatch(/Real holdings and account balances/);
    expect(byId(page.doc, "exposure-not-claimed")).toMatch(/not real holdings/);
    expect(page.doc.querySelector('[data-testid="exposure-summary"]')).toBeNull();
  });

  it("renders FIXTURE positions: totals, brief comparison, gaps and exclusions", async () => {
    use({ portfolio: "populated" });
    const page = await stack.get("/portfolio");
    expect(page.status).toBe(200);
    expect(byId(page.doc, "exposure-simulated-banner")).toMatch(/not real holdings/);
    expect(byId(page.doc, "exposure-summary")).toMatch(/1,500 USD/);
    expect(byId(page.doc, "exposure-summary")).toMatch(/not marked to market/);
    const rows = Array.from(page.doc.querySelectorAll('[data-testid="exposure-assets"] tbody tr'));
    const btc = rows.find((r) => r.textContent?.startsWith("BTC"))?.textContent ?? "";
    const eth = rows.find((r) => r.textContent?.startsWith("ETH"))?.textContent ?? "";
    expect(btc).toMatch(/Opposite to the brief/);
    expect(btc).toMatch(/Disagrees with the brief/);
    expect(eth).toMatch(/Not assessed/);
    expect(eth).not.toMatch(/Neutral|Same direction|Disagrees/);
    const gaps = byId(page.doc, "exposure-gaps");
    expect(gaps).toMatch(/no observed price/);
    expect(gaps).toMatch(/Trade t3 was excluded/);
    expect(byId(page.doc, "exposure-positions")).toMatch(/Price missing/);
  });

  it("links each asset row to that asset's Advisor Brief", async () => {
    use({ portfolio: "populated" });
    const page = await stack.get("/portfolio");
    expect(hrefs(page.doc, '[data-testid="exposure-assets"]')).toEqual([
      "/advisor?asset=BTC",
      "/advisor?asset=ETH",
    ]);
  });

  it.each([
    ["503", "exposure-error-503", /cannot be read|unavailable/i],
    ["malformed", "exposure-error-other", /unexpected shape/],
  ] as const)(
    "handles a %s response: banner stays, no figures are shown",
    async (mode, id, pattern) => {
      use({ portfolio: mode });
      const page = await stack.get("/portfolio");
      expect(page.status).toBe(200);
      expect(byId(page.doc, "exposure-simulated-banner")).toMatch(/Simulated paper trades only/);
      expect(byId(page.doc, id)).toMatch(pattern);
      expect(page.doc.querySelector('[data-testid="exposure-summary"]')).toBeNull();
      expect(page.doc.querySelector('[data-testid="exposure-assets"]')).toBeNull();
    },
  );

  it("streams a loading state first, then the content, when the API is slow", async () => {
    use({ portfolio: "slow" });
    const chunks = await stack.streamChunks("/portfolio");
    const firstWithLoading = chunks.findIndex((c) => c.includes("Loading the simulated exposure"));
    const firstWithContent = chunks.findIndex((c) => c.includes('data-testid="exposure-summary"'));
    expect(firstWithLoading).toBeGreaterThanOrEqual(0);
    expect(firstWithContent).toBeGreaterThanOrEqual(0);
    expect(firstWithLoading).toBeLessThan(firstWithContent);
  });
});

describe("Alerts and Paper Trading", () => {
  it("renders the alert list from the API and reports an unavailable alerts service honestly", async () => {
    const ok = await stack.get("/alerts");
    expect(text(ok.doc, "h1")).toBe("Alerts");
    expect(text(ok.doc)).toMatch(/funding_rate > 0\.01/);
    use({ alerts: "503" });
    const down = await stack.get("/alerts");
    expect(down.status).toBe(200);
    expect(text(down.doc)).toMatch(/unavailable/i);
    expect(text(down.doc)).not.toMatch(/funding_rate > 0\.01/);
  });

  it("renders the read-only paper-trading page and its simulated-only disclaimer", async () => {
    const page = await stack.get("/paper");
    expect(page.status).toBe(200);
    expect(text(page.doc)).toMatch(/simulated trades only/i);
    expect(text(page.doc)).toMatch(/No open positions\./);
    use({ paper: "503" });
    const down = await stack.get("/paper");
    expect(down.status).toBe(200);
    expect(text(down.doc)).toMatch(/unavailable/i);
  });
});

describe("read-only and no-advice guarantees", () => {
  it("offers no form or order control on the decision-support pages (only the refresh pause/resume toggle)", async () => {
    use({ portfolio: "populated" });
    for (const path of ["/advisor", "/portfolio", "/paper"]) {
      const page = await stack.get(path);
      expect(page.doc.querySelectorAll("form"), path).toHaveLength(0);
      const buttons = Array.from(page.doc.querySelectorAll("button")).map((b) => b.textContent);
      expect(
        buttons.every((label) => label === "Pause" || label === "Resume"),
        `${path}: ${buttons.join(",")}`,
      ).toBe(true);
    }
  });

  it("contains no recommendation, order or prediction wording on the new views", async () => {
    use({ portfolio: "populated" });
    for (const path of ["/advisor", "/portfolio"]) {
      const page = await stack.get(path);
      expect(text(page.doc, "main"), path).not.toMatch(
        /\b(you should (buy|sell)|buy now|sell now|place (an )?order|will (rise|fall)|guaranteed)\b/i,
      );
    }
  });

  it("made only GET requests to the API across every page it served", async () => {
    use({ portfolio: "populated" });
    for (const item of NAV_ITEMS) await stack.get(item.href);
    expect(stack.api.requests.length).toBeGreaterThan(0);
    expect(stack.api.requests.every((r) => r.method === "GET")).toBe(true);
  });

  it("reads the exposure endpoint exactly once per /portfolio page view", async () => {
    use({ portfolio: "populated" });
    await stack.get("/portfolio");
    expect(apiCalls("/api/v1/portfolio/exposure")).toHaveLength(1);
  });
});
