import type { MacroOverview } from "@/lib/macro";
import { formatUtc } from "@/lib/market";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Section 9 — Macro. Existing macro readings only (yield curve, VIX, net liquidity); no new
 * macro providers are added this phase (Phase 26 constraint). Stale/unavailable series are
 * called out explicitly rather than silently dropped.
 */
export function MacroSection({
  macro,
}: {
  macro: { ok: true; data: MacroOverview } | { ok: false; reason: string };
}) {
  if (!macro.ok) return <Unavailable what="Macro" reason={macro.reason} />;
  const d = macro.data;
  const rows: {
    label: string;
    status: string;
    value: string | null;
    time: string | null;
    condition: string | null;
  }[] = [
    {
      label: "Yield curve (10y−2y)",
      status: d.yield_curve.status,
      value: d.yield_curve.slope_pp,
      time: d.yield_curve.time,
      condition: d.yield_curve.condition,
    },
    {
      label: "Real policy rate",
      status: d.real_policy_rate.status,
      value: d.real_policy_rate.value,
      time: d.real_policy_rate.time,
      condition: d.real_policy_rate.condition,
    },
    {
      label: "VIX",
      status: d.vix.status,
      value: d.vix.value,
      time: d.vix.time,
      condition: d.vix.condition,
    },
    {
      label: "US net liquidity",
      status: d.us_net_liquidity.status,
      value: d.us_net_liquidity.value,
      time: d.us_net_liquidity.time,
      condition: null,
    },
    {
      label: "Equity trend",
      status: d.equity_trend.status,
      value: d.equity_trend.value,
      time: d.equity_trend.time,
      condition: d.equity_trend.condition,
    },
    {
      label: "Dollar trend",
      status: d.dollar_trend.status,
      value: d.dollar_trend.value,
      time: d.dollar_trend.time,
      condition: d.dollar_trend.condition,
    },
  ];
  return (
    <section className="status-card" aria-labelledby="macro-title">
      <h2 id="macro-title">
        Macro{" "}
        {d.score.status === "ok" ? (
          <span className="badge badge-neutral">
            score {d.score.score} ({d.score.band})
          </span>
        ) : (
          <span className="badge badge-warn">score insufficient data</span>
        )}
      </h2>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Series</th>
            <th scope="col">Value</th>
            <th scope="col">Condition</th>
            <th scope="col">As of</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label}</th>
              <td>{r.status === "ok" ? (r.value ?? "—") : "Insufficient data."}</td>
              <td>{r.condition ?? "—"}</td>
              <td>{r.time ? formatUtc(r.time) : "stale / unavailable"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
