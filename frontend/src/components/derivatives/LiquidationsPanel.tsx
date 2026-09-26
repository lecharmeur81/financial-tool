import { type DerivativesAssetView, formatPct } from "@/lib/derivatives";
import { formatNumber } from "@/lib/institutional";

/** OKX liquidations over the last 24 complete hours and liquidation-event hours (7 days). */
export function LiquidationsPanel({ liq }: { liq: DerivativesAssetView["liquidations"] }) {
  const unit = liq.unit.toUpperCase();
  return (
    <section className="status-card" aria-labelledby="deriv-liq-title">
      <h2 id="deriv-liq-title">Liquidations</h2>
      {liq.total_24h === null ? (
        <p role="status">Insufficient data: {liq.reason}</p>
      ) : (
        <p>
          Last 24 h ({liq.window_start} … {liq.window_end}, {liq.hours_present} of{" "}
          {liq.hours_expected} hours): long {formatNumber(liq.long_24h, 4)} {unit}, short{" "}
          {formatNumber(liq.short_24h, 4)} {unit}, total {formatNumber(liq.total_24h, 4)} {unit}
          {liq.share_of_oi_pct ? ` = ${liq.share_of_oi_pct} % of open interest` : ""}
          {liq.long_share_pct ? ` · ${liq.long_share_pct} % long positions` : ""}
          {liq.reason ? ` (${liq.reason})` : ""}
        </p>
      )}
      <h3>Liquidation events (7 days)</h3>
      {liq.events_note ? (
        <p className="muted">{liq.events_note}</p>
      ) : liq.events.length === 0 ? (
        <p>No hour met the event rule.</p>
      ) : (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Hour (UTC)</th>
              <th scope="col">Total</th>
              <th scope="col">Long</th>
              <th scope="col">Short</th>
              <th scope="col">Median hour before</th>
              <th scope="col">Share of OI</th>
            </tr>
          </thead>
          <tbody>
            {liq.events.map((e) => (
              <tr key={e.hour}>
                <th scope="row">{e.hour}</th>
                <td>
                  {formatNumber(e.total, 4)} {unit}
                </td>
                <td>{formatNumber(e.long, 4)}</td>
                <td>{formatNumber(e.short, 4)}</td>
                <td>{formatNumber(e.median_before, 4)}</td>
                <td>{formatPct(e.share_of_oi_pct, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">{liq.note}</p>
    </section>
  );
}
