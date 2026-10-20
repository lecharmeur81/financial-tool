/**
 * Phase 56 real-browser validation: Chromium driving the built production frontend.
 *
 * Each test talks to the real Next.js server, which talks to a read-only fixture API
 * (e2e/mock-api.ts: GET-only, 404 for anything unmocked). No backend, database or scheduler runs.
 * Populated-portfolio data is FIXTURE data; this suite says nothing about the real backend.
 */
import { type Page, expect, test } from "@playwright/test";

import { NAV_GROUPS, NAV_ITEMS } from "../src/lib/navigation";
import { type Stack, startStack } from "../e2e/harness";
import { DEFAULT_SCENARIO, type Scenario } from "../e2e/mock-api";

let stack: Stack;
let problems: string[] = [];

test.beforeAll(async () => {
  stack = await startStack();
});

test.afterAll(async () => {
  await stack?.stop();
});

test.beforeEach(({ page }) => {
  stack.api.reset();
  problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console.error: ${m.text()}`);
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText ?? "";
    // Navigating away aborts in-flight prefetches; that is not a failure.
    if (!reason.includes("ERR_ABORTED")) problems.push(`requestfailed: ${r.url()} ${reason}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400) problems.push(`http ${r.status()}: ${r.url()}`);
  });
});

test.afterEach(() => {
  // No uncaught page errors, console errors or failed/error responses in any test.
  expect(problems).toEqual([]);
});

const url = (path: string) => `${stack.baseUrl}${path}`;
const use = (partial: Partial<Scenario>) => {
  stack.api.scenario = { ...DEFAULT_SCENARIO, ...partial };
};
const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main navigation" });

test("Dashboard renders and the sidebar navigates between the decision-support views", async ({
  page,
}) => {
  await page.goto(url("/"));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  await expect(mainNav(page).locator(".nav-group-label")).toHaveText([...NAV_GROUPS]);
  await expect(mainNav(page).getByRole("link", { name: "Dashboard" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await mainNav(page).getByRole("link", { name: "Portfolio Exposure" }).click();
  await expect(page).toHaveURL(/\/portfolio$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Portfolio Exposure");
  await expect(mainNav(page).getByRole("link", { name: "Portfolio Exposure" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await mainNav(page).getByRole("link", { name: "Advisor Brief" }).click();
  await expect(page).toHaveURL(/\/advisor$/);
  await mainNav(page).getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL(url("/"));
});

test("Dashboard decision-support links open the views, keeping the asset", async ({ page }) => {
  await page.goto(url("/"));
  const links = page.locator(".decision-support-links");
  await expect(links).toContainText("none of them places a trade");
  await links.locator('a[href^="/advisor"]').click();
  await expect(page).toHaveURL(/\/advisor\?asset=BTC$/);
  await expect(page.locator("#advisor-title")).toHaveText("Advisor Brief — BTC");
});

test("Advisor Brief renders, switches asset and links on to Portfolio Exposure", async ({
  page,
}) => {
  await page.goto(url("/advisor"));
  await expect(page.getByTestId("advisor-stance")).toBeVisible();
  await expect(page.getByTestId("advisor-not-claimed")).toBeVisible();

  await page
    .getByRole("navigation", { name: "Advisor Brief asset" })
    .getByRole("link", {
      name: "ETH",
    })
    .click();
  await expect(page).toHaveURL(/asset=ETH$/);
  await expect(page.locator("#advisor-title")).toHaveText("Advisor Brief — ETH");

  await page
    .getByTestId("advisor-related")
    .getByRole("link", {
      name: "Paper Portfolio Exposure",
    })
    .click();
  await expect(page).toHaveURL(/\/portfolio$/);
});

for (const [mode, testId] of [
  ["404", "advisor-error-404"],
  ["503", "advisor-error-503"],
  ["malformed", "advisor-error-other"],
] as const) {
  test(`Advisor Brief shows a ${mode} response as a clear state, with no stance`, async ({
    page,
  }) => {
    use({ advisor: mode });
    await page.goto(url("/advisor"));
    await expect(page.getByTestId(testId)).toBeVisible();
    await expect(page.getByTestId("advisor-stance")).toHaveCount(0);
  });
}

test("Portfolio Exposure empty state shows the simulated-paper-trade disclosure", async ({
  page,
}) => {
  await page.goto(url("/portfolio"));
  const banner = page.getByTestId("exposure-simulated-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Simulated paper trades only");
  await expect(banner).toContainText("not real holdings");
  await expect(page.getByTestId("exposure-empty")).toContainText("No valid open paper trades");
  await expect(page.getByTestId("exposure-unavailable")).toContainText(
    "Real holdings and account balances",
  );

  // A real click opens the disclosure and reveals its text.
  const claims = page.getByTestId("exposure-not-claimed");
  await expect(claims.locator("li").first()).toBeHidden();
  await claims.locator("summary").click();
  await expect(claims.locator("li").first()).toBeVisible();
  await expect(claims).toContainText("not real holdings");
});

test("Portfolio Exposure shows FIXTURE positions with gaps and the disagreement flag", async ({
  page,
}) => {
  use({ portfolio: "populated" });
  await page.goto(url("/portfolio"));
  await expect(page.getByTestId("exposure-summary")).toContainText("1,500 USD");
  await expect(page.getByTestId("exposure-assets")).toContainText("Disagrees with the brief");
  await expect(page.getByTestId("exposure-gaps")).toContainText("Trade t3 was excluded");
  await expect(page.getByTestId("exposure-simulated-banner")).toBeVisible();
});

test("keyboard: Tab walks the sidebar in order and Enter follows a link", async ({ page }) => {
  await page.goto(url("/"));
  const order = NAV_GROUPS.flatMap((g) =>
    NAV_ITEMS.filter((i) => i.group === g).map((i) => i.label),
  );
  const target = order.indexOf("Portfolio Exposure");
  expect(target).toBeGreaterThan(0);
  const focused = () =>
    page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return {
        inNav: !!el?.closest('nav[aria-label="Main navigation"]'),
        text: el?.textContent?.trim() ?? "",
      };
    });

  for (const label of order.slice(0, target + 1)) {
    await page.keyboard.press("Tab");
    expect(await focused()).toEqual({ inNav: true, text: label });
  }
  // Focus is visible on the keyboard-focused link.
  const outline = await page.evaluate(
    () => getComputedStyle(document.activeElement as Element).outlineStyle,
  );
  expect(outline).not.toBe("none");

  await page.keyboard.press("Shift+Tab");
  expect(await focused()).toEqual({ inNav: true, text: order[target - 1] });
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/portfolio$/);
});

test("the auto-refresh toggle is a real, keyboard-operable control", async ({ page }) => {
  await page.goto(url("/paper"));
  const toggle = page.getByRole("button", { name: "Pause" });
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
  await expect(page.getByText("auto-refresh paused")).toBeVisible();
});

for (const path of ["/", "/advisor", "/portfolio"]) {
  test(`basic accessibility structure of ${path}`, async ({ page }) => {
    use({ portfolio: "populated" });
    await page.goto(url(path));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const report = await page.evaluate(() => {
      const name = (el: Element) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim();
      const ids = Array.from(document.querySelectorAll("[id]")).map((e) => e.id);
      return {
        lang: document.documentElement.lang,
        h1: document.querySelectorAll("h1").length,
        main: document.querySelectorAll("main").length,
        unnamedNav: Array.from(document.querySelectorAll("nav")).filter((n) => !name(n)).length,
        unnamedControls: Array.from(document.querySelectorAll("a, button")).filter((e) => !name(e))
          .length,
        duplicateIds: ids.filter((id, i) => ids.indexOf(id) !== i),
        tablesWithoutHeaders: Array.from(document.querySelectorAll("table")).filter(
          (t) => !t.hidden && t.querySelectorAll("th").length === 0,
        ).length,
        title: document.title,
      };
    });
    expect(report.lang).toBe("en");
    expect(report.h1).toBe(1);
    expect(report.main).toBe(1);
    expect(report.unnamedNav).toBe(0);
    expect(report.unnamedControls).toBe(0);
    expect(report.duplicateIds).toEqual([]);
    expect(report.tablesWithoutHeaders).toBe(0);
    expect(report.title.trim()).not.toBe("");
  });
}

test("the browser only ever caused GET requests to the API", async ({ page }) => {
  use({ portfolio: "populated" });
  for (const path of ["/", "/advisor", "/portfolio", "/alerts", "/paper"]) {
    await page.goto(url(path));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  expect(stack.api.requests.length).toBeGreaterThan(0);
  expect(stack.api.requests.every((r) => r.method === "GET")).toBe(true);
});
