import {
  type EtfFunds,
  formatSigned,
  formatUsdCompact,
  formatUsdMillions,
  periodLabel,
} from "@/lib/institutional";
import { FRESHNESS_CLASS, FRESHNESS_LABEL } from "@/lib/market";

/** Per-fund breakdown: which funds carried the flows over the range, and their latest size. */
export function FundsTable({ funds }: { funds: EtfFunds }) {
  if (!funds.funds.length) {
    return <p className="empty-chart">No per-fund data stored yet.</p>;
  }
  return (
    <>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Fund</th>
            <th scope="col">Net flow {periodLabel(funds.range.start, funds.range.end)}</th>
            <th scope="col">Net assets (latest)</th>
            <th scope="col">Share</th>
            <th scope="col">Premium / discount</th>
            <th scope="col">Latest day</th>
          </tr>
        </thead>
        <tbody>
          {funds.funds.map((f) => (
            <tr key={f.ticker}>
              <th scope="row">
                {f.ticker}
                <span className="muted"> {f.name}</span>
              </th>
              <td title={f.range_flow_usd ?? undefined}>
                {formatUsdMillions(f.range_flow_usd)}
                <span className="muted"> ({f.days_present} days)</span>
              </td>
              <td>{formatUsdCompact(f.net_assets_usd)}</td>
              <td>
                {f.share_of_net_assets_pct === null
                  ? "—"
                  : `${Number(f.share_of_net_assets_pct).toFixed(1)} %`}
              </td>
              <td>
                {f.premium_discount === null
                  ? "—"
                  : formatSigned(String(Number(f.premium_discount) * 100), 3, " %")}
              </td>
              <td>
                {f.latest_day}{" "}
                <span className={FRESHNESS_CLASS[f.freshness.status]}>
                  {FRESHNESS_LABEL[f.freshness.status]}
                </span>
                {f.quality.notes.length ? (
                  <ul className="note-list">
                    {f.quality.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        {Object.entries(funds.definition)
          .map(([k, v]) => `${k}: ${v}`)
          .join(" · ")}
      </p>
    </>
  );
}
