import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { IntelligenceEvent } from "@/lib/intelligence";
import type { SimilarityCurrent } from "@/lib/similarity";

import { IntelligenceEventsPanel } from "./IntelligenceEventsPanel";
import { SimilaritySection } from "./SimilaritySection";

afterEach(cleanup);

const similarityOk: SimilarityCurrent = {
  asset: "BTC",
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_note: "Historical context only, never a prediction.",
  not_tracked: [],
  status: "ok",
  query_available_weight: "0.9",
  analogues: [
    {
      date: "2021-04-01T00:00:00Z",
      similarity_score: "0.87",
      available_weight: "0.9",
      regime: { regime_id: "r1", label: "risk-on", confidence: "0.7", status: "ok" },
      forward_returns: [
        { horizon_days: 7, status: "ok", value_pct: "4.2", reason: null },
        { horizon_days: 30, status: "not_yet_knowable", value_pct: null, reason: "future" },
      ],
      max_drawdown: {
        window_days: 30,
        status: "ok",
        value_pct: "-12.1",
        partial: false,
        reason: null,
      },
      volatility_annualized_pct: "55.0",
      compared_features: [],
    },
  ],
  distribution: [
    {
      horizon_days: 7,
      status: "ok",
      count: 5,
      min_pct: "-2",
      p25_pct: "0",
      median_pct: "3",
      p75_pct: "6",
      max_pct: "9",
      reason: null,
    },
  ],
  candidates_evaluated: 20,
  candidates_selected_for_distribution: 5,
};

describe("SimilaritySection", () => {
  it("shows analogues as historical context, never a prediction", () => {
    render(<SimilaritySection similarity={{ ok: true, data: similarityOk }} />);
    expect(screen.getByText(/never a prediction/)).toBeTruthy();
    expect(screen.getByText("risk-on")).toBeTruthy();
    expect(screen.getByText(/4.2%/)).toBeTruthy();
  });

  it("reports insufficient data rather than fabricating analogues", () => {
    render(
      <SimilaritySection
        similarity={{
          ok: true,
          data: {
            ...similarityOk,
            status: "insufficient_data",
            reason: "only 0.3 of the required 0.6 feature weight was available",
            analogues: [],
            distribution: [],
          },
        }}
      />,
    );
    expect(screen.getByText(/Insufficient data/)).toBeTruthy();
  });

  it("reports an unreachable API rather than hiding it", () => {
    render(<SimilaritySection similarity={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Historical similarity unavailable")).toBeTruthy();
  });
});

const intelligenceEventsOk: IntelligenceEvent[] = [
  {
    event_id: "11111111-1111-1111-1111-111111111111",
    created_at: "2026-10-01T00:05:00Z",
    observed_at: "2026-10-01T00:00:00Z",
    domain: "regime",
    event_type: "regime_change",
    severity: "critical",
    previous_value: "risk-off",
    current_value: "risk-on",
    change_magnitude: "1",
    detection_method: "rule_engine",
    data_quality_state: "ok",
    component_status: "ok",
    dedup_key: "regime:BTC",
    correlation_key: "regime:BTC:2026-10-01",
    snapshot_id: 42,
    status: "active",
    ai_interpretation_id: 7,
  },
];

describe("IntelligenceEventsPanel", () => {
  it("lists events with severity, domain, and event type", () => {
    render(<IntelligenceEventsPanel events={{ ok: true, data: intelligenceEventsOk }} />);
    expect(screen.getByText("critical")).toBeTruthy();
    expect(screen.getByText("regime")).toBeTruthy();
    expect(screen.getByText("regime_change")).toBeTruthy();
  });

  it("shows no fabricated events when none are recorded", () => {
    render(<IntelligenceEventsPanel events={{ ok: true, data: [] }} />);
    expect(screen.getByText("No intelligence events recorded.")).toBeTruthy();
  });

  it("reports an unreachable API rather than hiding it", () => {
    render(<IntelligenceEventsPanel events={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Intelligence events unavailable")).toBeTruthy();
  });
});
