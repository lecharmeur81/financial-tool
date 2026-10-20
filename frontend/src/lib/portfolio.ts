/**
 * Paper Portfolio Exposure client (Phase 55): a read-only view of `GET /api/v1/portfolio/exposure`
 * (`portfolio_exposure.v0`, ADR-0095).
 *
 * The browser never calls the API (ADR-0015): this runs on the server through `getJson`. Nothing
 * here computes, scores or judges — every amount, share and relation is the API's own value,
 * shown unchanged. Decimal amounts stay strings. An unexpected response shape is refused, and a
 * missing brief, price or position is never turned into a neutral or agreeing value.
 */
import { type ApiResult, getJson } from "@/lib/market";

export const PORTFOLIO_CONTRACT = "portfolio_exposure.v0";

export type ExposureSummary = {
  status: string;
  gross_notional: string;
  long_notional: string;
  short_notional: string;
  net_notional: string;
  total_margin: string;
  notional_weighted_leverage: string | null;
  asset_count: number;
  largest_asset: string | null;
  largest_asset_share: string | null;
  concentration_hhi: string | null;
};

export type ExposureBrief =
  | { status: "assessed"; stance: string; confidence: string; decision_state: string }
  | { status: "not_assessed"; reason: string };

export type ExposureAsset = {
  asset: string;
  position_count: number;
  net_direction: string;
  brief: ExposureBrief;
  brief_relation: string;
  disagreement: boolean | null;
  long_notional: string;
  short_notional: string;
  gross_notional: string;
  net_notional: string;
  share_of_gross: string;
};

export type ExposurePosition = {
  trade_id: string;
  asset: string;
  direction: string;
  notional: string;
  leverage: string;
  margin: string;
  price_status: string;
  brief_relation: string;
  disagreement: boolean | null;
};

export type PortfolioExposure = {
  contract_version: string;
  source: { kind: string; label: string; positions_received: number; positions_invalid: number };
  conventions: string[];
  summary: ExposureSummary;
  assets: ExposureAsset[];
  positions: ExposurePosition[];
  invalid_positions: { trade_id: string; reasons: string[] }[];
  data_quality: {
    positions_missing_price: number;
    assets_without_assessed_brief: string[];
    has_gaps: boolean;
  };
  unavailable: { id: string; what: string; reason: string }[];
  not_claimed: { id: string; text: string }[];
};

// --------------------------------------------------------------------------- guarded parsing

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
const objList = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);

function parseSummary(raw: unknown): ExposureSummary | null {
  if (!isObj(raw)) return null;
  const status = str(raw.status);
  const gross = str(raw.gross_notional);
  const long = str(raw.long_notional);
  const short = str(raw.short_notional);
  const net = str(raw.net_notional);
  const margin = str(raw.total_margin);
  const count = num(raw.asset_count);
  if (!status || gross === null || long === null || short === null) return null;
  if (net === null || margin === null || count === null) return null;
  return {
    status,
    gross_notional: gross,
    long_notional: long,
    short_notional: short,
    net_notional: net,
    total_margin: margin,
    notional_weighted_leverage: str(raw.notional_weighted_leverage),
    asset_count: count,
    largest_asset: str(raw.largest_asset),
    largest_asset_share: str(raw.largest_asset_share),
    concentration_hhi: str(raw.concentration_hhi),
  };
}

function parseBrief(raw: unknown): ExposureBrief | null {
  if (!isObj(raw)) return null;
  if (raw.status === "assessed") {
    const stance = str(raw.stance);
    const confidence = str(raw.confidence);
    const state = str(raw.decision_state);
    if (!stance || !confidence || !state) return null;
    return { status: "assessed", stance, confidence, decision_state: state };
  }
  if (raw.status === "not_assessed") {
    return { status: "not_assessed", reason: str(raw.reason) ?? "Not assessed." };
  }
  return null;
}

const disagreementOf = (v: unknown): boolean | null | undefined =>
  v === null ? null : typeof v === "boolean" ? v : undefined;

function parseAsset(raw: Obj): ExposureAsset | null {
  const brief = parseBrief(raw.brief);
  const disagreement = disagreementOf(raw.disagreement);
  const asset = str(raw.asset);
  const count = num(raw.position_count);
  const direction = str(raw.net_direction);
  const relation = str(raw.brief_relation);
  const long = str(raw.long_notional);
  const short = str(raw.short_notional);
  const gross = str(raw.gross_notional);
  const net = str(raw.net_notional);
  const share = str(raw.share_of_gross);
  if (!asset || count === null || !direction || !relation || !brief) return null;
  if (disagreement === undefined) return null;
  if (long === null || short === null || gross === null || net === null || share === null) {
    return null;
  }
  return {
    asset,
    position_count: count,
    net_direction: direction,
    brief,
    brief_relation: relation,
    disagreement,
    long_notional: long,
    short_notional: short,
    gross_notional: gross,
    net_notional: net,
    share_of_gross: share,
  };
}

function parsePosition(raw: Obj): ExposurePosition | null {
  const disagreement = disagreementOf(raw.disagreement);
  const id = str(raw.trade_id);
  const asset = str(raw.asset);
  const direction = str(raw.direction);
  const notional = str(raw.notional);
  const leverage = str(raw.leverage);
  const margin = str(raw.margin);
  const price = str(raw.price_status);
  const relation = str(raw.brief_relation);
  if (!id || !asset || !direction || notional === null || leverage === null) return null;
  if (margin === null || !price || !relation || disagreement === undefined) return null;
  return {
    trade_id: id,
    asset,
    direction,
    notional,
    leverage,
    margin,
    price_status: price,
    brief_relation: relation,
    disagreement,
  };
}

/**
 * Validates the response and returns it in a closed shape, or `null` if a field the page depends
 * on is absent or of the wrong type. Any malformed asset or position makes the whole response
 * unusable: a partial exposure table could understate what the paper portfolio holds.
 */
export function parsePortfolioExposure(raw: unknown): PortfolioExposure | null {
  if (!isObj(raw) || raw.contract_version !== PORTFOLIO_CONTRACT) return null;
  if (!isObj(raw.source) || !isObj(raw.data_quality)) return null;
  const summary = parseSummary(raw.summary);
  const kind = str(raw.source.kind);
  const label = str(raw.source.label);
  const received = num(raw.source.positions_received);
  const invalidCount = num(raw.source.positions_invalid);
  const missingPrice = num(raw.data_quality.positions_missing_price);
  if (!summary || !kind || !label || received === null || invalidCount === null) return null;
  if (missingPrice === null || typeof raw.data_quality.has_gaps !== "boolean") return null;
  if (!Array.isArray(raw.assets) || !Array.isArray(raw.positions)) return null;
  if (!Array.isArray(raw.invalid_positions)) return null;

  const assets = objList(raw.assets).map(parseAsset);
  const positions = objList(raw.positions).map(parsePosition);
  if (assets.length !== raw.assets.length || assets.some((a) => a === null)) return null;
  if (positions.length !== raw.positions.length || positions.some((p) => p === null)) return null;
  const invalid = objList(raw.invalid_positions).map((p) => ({
    trade_id: str(p.trade_id),
    reasons: strList(p.reasons),
  }));
  if (invalid.length !== raw.invalid_positions.length || invalid.some((p) => !p.trade_id)) {
    return null;
  }
  return {
    contract_version: PORTFOLIO_CONTRACT,
    source: { kind, label, positions_received: received, positions_invalid: invalidCount },
    conventions: strList(raw.conventions),
    summary,
    assets: assets as ExposureAsset[],
    positions: positions as ExposurePosition[],
    invalid_positions: invalid as { trade_id: string; reasons: string[] }[],
    data_quality: {
      positions_missing_price: missingPrice,
      assets_without_assessed_brief: strList(raw.data_quality.assets_without_assessed_brief),
      has_gaps: raw.data_quality.has_gaps,
    },
    unavailable: objList(raw.unavailable).flatMap((u) => {
      const id = str(u.id);
      const what = str(u.what);
      const reason = str(u.reason);
      return id && what && reason ? [{ id, what, reason }] : [];
    }),
    not_claimed: objList(raw.not_claimed).flatMap((n) => {
      const id = str(n.id);
      const text = str(n.text);
      return id && text ? [{ id, text }] : [];
    }),
  };
}

export async function fetchPortfolioExposure(
  fetchImpl?: typeof fetch,
): Promise<ApiResult<PortfolioExposure>> {
  const result = await getJson<unknown>("/api/v1/portfolio/exposure", undefined, fetchImpl);
  if (!result.ok) return result;
  const exposure = parsePortfolioExposure(result.data);
  if (!exposure) {
    return {
      ok: false,
      status: null,
      reason:
        "The portfolio service returned a response in an unexpected shape, so nothing is shown.",
    };
  }
  return { ok: true, data: exposure };
}

// --------------------------------------------------------------------------- wording

/** Display words for the API's closed brief-relation vocabulary. */
export const RELATION_LABEL: Record<string, string> = {
  same_direction: "Same direction as the brief",
  opposite_direction: "Opposite to the brief",
  stance_neutral: "Brief stance is neutral",
  no_directional_view: "Brief has no directional view",
  not_assessed: "Not assessed",
  no_net_direction: "No net direction",
};
export const relationLabel = (r: string): string => RELATION_LABEL[r] ?? r.replace(/_/g, " ");

export const PRICE_STATUS_LABEL: Record<string, string> = {
  ok: "Price observed",
  missing: "Price missing",
};
export const priceStatusLabel = (s: string): string =>
  PRICE_STATUS_LABEL[s] ?? s.replace(/_/g, " ");

export const INVALID_REASON_LABEL: Record<string, string> = {
  unknown_asset: "unsupported asset",
  unknown_direction: "unrecognised direction",
  invalid_notional: "invalid notional",
  invalid_leverage: "invalid leverage",
  invalid_margin: "invalid margin",
  margin_inconsistent_with_notional_and_leverage: "margin inconsistent with notional and leverage",
  malformed_position: "malformed position",
};
export const invalidReasonLabel = (r: string): string =>
  INVALID_REASON_LABEL[r] ?? r.replace(/_/g, " ");

/** Decimal strings like "0.666667" shown as a percentage; anything unparseable is shown as-is. */
export function formatShare(share: string | null): string {
  if (share === null) return "—";
  const value = Number(share);
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : share;
}
