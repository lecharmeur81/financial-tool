import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Condition, DerivativesAssetView, HealthScore } from "@/lib/derivatives";

import { ConditionsPanel } from "./ConditionsPanel";
import { CurveOptionsPanel } from "./CurveOptionsPanel";
import { HealthScoreCard } from "./HealthScoreCard";
import { LiquidationsPanel } from "./LiquidationsPanel";

afterEach(cleanup);

const component = (overrides: Partial<HealthScore["components"][number]> = {}) => ({
  component_id: "funding",
  metric_id: "funding_annualised_7d_abs.v1",
  label: "Funding pressure (7 days, annualised)",
  weight: "0.25",
  scale: "|funding| = 30 % a year → stress 1",
  definition: "Σ funding rates settled over the last 7 days × 365 ÷ 7.",
  status: "ok" as const,
  reason: null,
  value: "15.64",
  value_unit: "% a year",
  stress: "0.5214",
  effective_weight: "0.2500",
  contribution: "13.04",
  calculation: "open-interest weighted: +15.64 % a year; stress = 0.5214",
  context: "positive: long positions pay short positions",
  inputs: { binance_annualised_7d: "0.1095" },
  ...overrides,
});

const score: HealthScore = {
  score_id: "derivatives_health_score",
  version: "derivatives_health_v1",
  calculated_at: "2026-09-26T12:00:00+00:00",
  evidence_category: "Calculated Metric",
  status: "ok",
  health: "59.4",
  stress: "40.6",
  band: "moderate stress",
  band_note: "Bands … not price direction.",
  semantic_note:
    "Higher Derivatives Health Score means lower measured derivatives stress across the " +
    "available components. It is not a probability of price increase and does not indicate " +
    "market direction.",
  available_weight: "1.00",
  reason: null,
  components: [
    component(),
    component({
      component_id: "basis",
      label: "Futures basis outside its ordinary range",
      status: "not_applicable",
      value: null,
      stress: null,
      effective_weight: null,
      contribution: null,
      context: null,
      reason: "no Deribit futures for this asset",
    }),
  ],
};

describe("HealthScoreCard", () => {
  it("shows the score, its band and every component with stress and context", () => {
    render(<HealthScoreCard score={score} asset="BTC" />);
    expect(screen.getByLabelText("health score").textContent).toContain("59.4");
    expect(screen.getByText("moderate stress")).toBeDefined();
    const row = screen.getByRole("row", { name: /Funding pressure/ });
    expect(within(row).getByText("0.5214")).toBeDefined();
    expect(within(row).getByText("positive: long positions pay short positions")).toBeDefined();
    expect(screen.getByText("not applicable")).toBeDefined();
    expect(screen.getAllByText(/open-interest weighted/).length).toBeGreaterThan(0);
  });

  it("says Insufficient data instead of a number", () => {
    render(
      <HealthScoreCard
        score={{
          ...score,
          status: "insufficient_data",
          health: null,
          stress: null,
          band: null,
          reason: "Insufficient data: weight 0.25",
        }}
        asset="SOL"
      />,
    );
    expect(screen.getByRole("status").textContent).toBe("Insufficient data");
    expect(screen.queryByLabelText("health score")).toBeNull();
  });
});

describe("ConditionsPanel", () => {
  it("labels states without a direction", () => {
    const conditions: Condition[] = [
      {
        condition_id: "oi_expansion",
        label: "Open interest expansion",
        state: "active",
        detail: "24 h +12.00 %",
      },
      {
        condition_id: "basis_extreme",
        label: "Basis extreme",
        state: "not_applicable",
        detail: "no Deribit futures",
      },
      { condition_id: "funding_extreme", label: "Funding extreme", state: "unknown", detail: "—" },
    ];
    const { container } = render(<ConditionsPanel conditions={conditions} />);
    expect(screen.getByText("Active")).toBeDefined();
    expect(screen.getByText("Not applicable")).toBeDefined();
    expect(screen.getByText("Insufficient data")).toBeDefined();
    expect(container.textContent?.toLowerCase()).not.toMatch(/bullish|bearish/);
  });
});

const liquidations: DerivativesAssetView["liquidations"] = {
  status: "ok",
  reason: null,
  venue: "okx",
  unit: "btc",
  window_start: "2026-09-09T12:00:00+00:00",
  window_end: "2026-09-10T12:00:00+00:00",
  hours_expected: 24,
  hours_present: 24,
  long_24h: "31.80",
  short_24h: "11.20",
  total_24h: "43.00",
  long_share_pct: "74.0",
  share_of_oi_pct: "0.1433",
  open_interest: "30000",
  events: [
    {
      hour: "2026-09-10T05:00:00+00:00",
      total: "20",
      long: "18",
      short: "2",
      median_before: "1",
      share_of_oi_pct: "0.0667",
    },
  ],
  events_note: null,
  note: "OKX USDT perpetual only.",
};

describe("LiquidationsPanel", () => {
  it("shows the 24-hour totals and the event hours", () => {
    render(<LiquidationsPanel liq={liquidations} />);
    expect(screen.getByText(/total 43 BTC = 0.1433 % of open interest/)).toBeDefined();
    expect(screen.getByRole("row", { name: /2026-09-10T05:00/ })).toBeDefined();
  });

  it("says Insufficient data when hours are missing", () => {
    render(
      <LiquidationsPanel
        liq={{
          ...liquidations,
          total_24h: null,
          reason: "no totals",
          events: [],
          events_note: "events need more than 24 stored hours (3 so far)",
        }}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("Insufficient data: no totals");
    expect(screen.getByText(/events need more than 24/)).toBeDefined();
  });
});

describe("CurveOptionsPanel", () => {
  it("says why an asset has no basis or options", () => {
    const view = {
      basis: { status: "not_applicable", reason: "no Deribit futures for this asset" },
      options: { status: "not_applicable", reason: "no Deribit options for this asset" },
      volatility: { status: "not_applicable", reason: "no DVOL index for this asset" },
    } as unknown as DerivativesAssetView;
    render(<CurveOptionsPanel view={view} />);
    expect(screen.getByText("no Deribit futures for this asset")).toBeDefined();
    expect(screen.getByText("no Deribit options for this asset")).toBeDefined();
    expect(screen.getByText("no DVOL index for this asset")).toBeDefined();
  });
});
