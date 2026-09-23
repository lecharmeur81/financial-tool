import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { EtfFlows, Metric, Score, Source } from "@/lib/institutional";

import { FlowTable } from "./FlowTable";
import { MetricFacts } from "./MetricFacts";
import { ScoreCard } from "./ScoreCard";

afterEach(cleanup);

const source: Source = {
  provider_id: "sosovalue",
  provider_name: "SoSoValue",
  original_source: "sosovalue",
  dataset_id: "institutional.etf_flow.us_spot.1d",
  enabled: true,
  terms_verified: false,
  attribution: { text: "Data: SoSoValue", url: "https://sosovalue.com" },
};

const metric = (overrides: Partial<Metric> = {}): Metric => ({
  metric_id: "etf_net_flow_5d_pct_aum.v1",
  label: "US spot ETF net flow, last 5 trading days",
  evidence_category: "metric",
  evidence_class: "direct",
  value: "1.0000",
  unit: "% of ETF net assets",
  timestamp: "2026-09-04",
  calculation: "$1,000.0M net flow over 5 trading days ÷ $100,000.0M net assets × 100 = 1.0000 %",
  source,
  freshness: {
    status: "fresh",
    latest: "2026-09-04",
    expected_latest: "2026-09-04",
    age_seconds: 50400,
    rule: "newest trading day ≥ latest day due",
    note: "up to date",
  },
  quality: {
    status: "ok",
    days_expected: 5,
    days_present: 5,
    flagged: 0,
    revised: 0,
    backfilled: 0,
    estimated_availability: 5,
    notes: ["5 input(s) have an estimated publication time (available_at_estimated)"],
  },
  ...overrides,
});

const score: Score = {
  score_id: "institutional_flow_score",
  version: "v1",
  asset: "SOL",
  as_of: "2026-09-09T12:00:00Z",
  knowledge_time: "2026-09-09T12:00:00Z",
  evidence_category: "metric",
  status: "ok",
  value: "85.0",
  unit: "points (−100 … +100)",
  band: "strong net inflow",
  reason: null,
  available_weight: "0.50",
  calculation: "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components)",
  etf_due_until: "2026-09-04",
  components: [
    {
      component_id: "etf_flow_5d",
      status: "ok",
      reason: null,
      definition: "Σ daily net flow over the last 5 US trading days ÷ net assets × 100.",
      evidence: "Calculated metric from direct evidence",
      weight: "0.35",
      effective_weight: "0.7000",
      reference_scale: "1.0",
      sub_score: "1.0000",
      contribution: "70.00",
      window: { start: "2026-08-31", end: "2026-09-04" },
      inputs: {},
      metric: metric(),
    },
    {
      component_id: "etf_flow_20d",
      status: "unavailable",
      reason: "only 12 of 20 trading days have data (minimum 90%)",
      definition: "Σ daily net flow over the last 20 US trading days ÷ net assets × 100.",
      evidence: "Calculated metric from direct evidence",
      weight: "0.30",
      effective_weight: null,
      reference_scale: "3.0",
      sub_score: null,
      contribution: null,
      window: { start: "2026-08-10", end: "2026-09-04" },
      inputs: {},
      metric: metric({
        label: "US spot ETF net flow, last 20 trading days",
        value: null,
        quality: { ...metric().quality, status: "missing", notes: ["only 12 of 20"] },
      }),
    },
  ],
  interpretation_limits: ["The score is not a forecast, a signal to act, or investment advice."],
  bands_note: "Bands describe flow direction only.",
};

describe("MetricFacts", () => {
  it("shows source, timestamp, unit, calculation, freshness and data quality", () => {
    render(<MetricFacts metric={metric()} />);
    for (const term of [
      "Source",
      "Timestamp",
      "Unit",
      "Calculation",
      "Freshness",
      "Data quality",
    ]) {
      expect(screen.getByText(term)).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: "Data: SoSoValue" })).toBeTruthy();
    expect(screen.getByText("% of ETF net assets")).toBeTruthy();
    expect(screen.getByText(/1.0000 %/)).toBeTruthy();
    expect(screen.getByText("direct evidence")).toBeTruthy();
  });
});

describe("ScoreCard", () => {
  it("shows the score, every component and why one is excluded", () => {
    render(<ScoreCard score={score} />);
    expect(screen.getByLabelText("score value").textContent).toContain("+85.0");
    expect(screen.getByText("strong net inflow")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("excluded")).toBeTruthy();
    expect(within(table).getByText("+70.00 pts")).toBeTruthy();
    expect(screen.getAllByText(/only 12 of 20 trading days/).length).toBeGreaterThan(0);
    expect(screen.getByText(/not a forecast/)).toBeTruthy();
  });

  it("says Insufficient data instead of a number", () => {
    render(
      <ScoreCard
        score={{ ...score, status: "insufficient_data", value: null, band: null, reason: "x" }}
      />,
    );
    expect(screen.getByRole("status").textContent).toBe("Insufficient data");
  });
});

describe("FlowTable", () => {
  it("lists buckets newest first with completeness and reconciliation", () => {
    const flows = {
      interval: "1d",
      buckets: [
        {
          start: "2026-09-04",
          end: "2026-09-05",
          net_flow_usd: "200000000",
          net_assets_usd: "100000000000",
          net_assets_date: "2026-09-04",
          value_traded_usd: null,
          inflow_days: 1,
          outflow_days: 0,
          status: "complete",
          quality: { ...metric().quality, days_expected: 1, days_present: 1, notes: [] },
          reconciliation: {
            funds_reporting: 2,
            funds_total_usd: "200000000",
            difference_usd: "0",
            reconciles: true,
            tolerance_usd: "1000000",
          },
        },
        {
          start: "2026-09-08",
          end: "2026-09-09",
          net_flow_usd: null,
          net_assets_usd: null,
          net_assets_date: null,
          value_traded_usd: null,
          inflow_days: 0,
          outflow_days: 0,
          status: "not_due",
          quality: { ...metric().quality, days_expected: 0, days_present: 0, notes: [] },
          reconciliation: null,
        },
      ],
    } as unknown as EtfFlows;
    render(<FlowTable flows={flows} />);
    const rows = screen.getAllByRole("row");
    expect(rows[1].textContent).toContain("2026-09-08");
    expect(rows[1].textContent).toContain("Not reported yet");
    expect(rows[2].textContent).toContain("+200.0 M USD");
    expect(rows[2].textContent).toContain("matches total");
  });
});
