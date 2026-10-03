/**
 * Capital Rotation Engine API client (server side) — Phase 20, read-only.
 *
 * Each node carries its own OBSERVED market-share reading; adjacent nodes may additionally
 * carry an INFERRED capital-rotation hypothesis (never stated as a fact that money moved) plus
 * whether OBSERVED institutional/whale flow data corroborates or contradicts it. The dashboard
 * must never display inferred rotation as confirmed capital movement (Phase 26 constraint).
 */

import { type ApiResult, getJson } from "@/lib/market";

export type RotationNode = {
  node_id: string;
  label: string;
  measurement_class: string;
  scope_note?: string | null;
  status: string;
  reason: string | null;
  direction: string | null;
  last_value?: string | null;
  change_pct?: string | null;
};

export type RotationPair = {
  from_node: RotationNode;
  to_node: RotationNode;
  window_days: number;
  as_of: string;
  knowledge_time: string;
  observed_capital_flow: { from_node_direction: string | null; to_node_direction: string | null };
  inferred_capital_rotation: {
    status: string;
    evidence_class: string | null;
    hypothesis: string | null;
  };
  duration: { days: number | null; capped: boolean; since: string | null } | null;
  historical_examples: unknown[];
  flow_corroboration: { supporting_evidence: string[]; contradicting_evidence: string[] };
  evidence_note: string;
};

export type RotationMatrix = {
  as_of: string;
  knowledge_time: string;
  window_days: number;
  pairs: RotationPair[];
  evidence_note: string;
  not_tracked: string[];
};

export const fetchRotationMatrix = (f?: typeof fetch): Promise<ApiResult<RotationMatrix>> =>
  getJson<RotationMatrix>("/api/v1/rotation/matrix", {}, f);
