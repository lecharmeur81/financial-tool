import { type DerivativesAssetView, formatPct } from "@/lib/derivatives";
import { formatNumber } from "@/lib/institutional";

/** Open interest per venue, leverage, funding per venue, account ratios and price context. */
export function PositioningPanel({ view }: { view: DerivativesAssetView }) {
  const oi = view.open_interest;
  const lev = view.leverage;
  const fund = view.funding;
  const unit = oi.unit.toUpperCase();
  return (
    <section className="status-card" aria-labelledby="deriv-positioning-title">
      <h2 id="deriv-positioning-title">Open interest, leverage and funding</h2>

      <h3>Open interest ({unit})</h3>
      <p>
        Total {formatNumber(oi.total, 2)} {unit}
        {oi.total_usd ? ` ≈ $${formatNumber(oi.total_usd)}` : ""} · 24 h{" "}
        {formatPct(oi.change_24h_pct)} ({oi.venues_24h.join(", ") || "—"}) · 7 d{" "}
        {formatPct(oi.change_7d_pct)} ({oi.venues_7d.join(", ") || "—"}) ·{" "}
        <strong>{oi.condition}</strong>
      </p>
      <p className="muted">
        {oi.calculation}. USD: {oi.usd_note}.
      </p>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Venue</th>
            <th scope="col">Open interest</th>
            <th scope="col">≈ USD</th>
            <th scope="col">24 h</th>
            <th scope="col">7 d</th>
            <th scope="col">Snapshot (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {oi.venues.map((v) => (
            <tr key={v.venue}>
              <th scope="row">{v.venue}</th>
              <td>
                {v.open_interest === null
                  ? v.status
                  : `${formatNumber(v.open_interest, 2)} ${unit}`}
              </td>
              <td>{v.open_interest_usd ? `$${formatNumber(v.open_interest_usd)}` : "—"}</td>
              <td>{formatPct(v.change_24h_pct)}</td>
              <td>{formatPct(v.change_7d_pct)}</td>
              <td>{v.time ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Leverage (open interest ÷ market cap)</h3>
      {lev.status === "ok" ? (
        <p>
          {lev.ratio_now_pct} % now vs {lev.ratio_week_ago_pct} % 7 days earlier → change{" "}
          {formatPct(lev.change_7d_pct)} · <strong>{lev.condition}</strong> ({lev.venues.join(", ")}
          )
        </p>
      ) : (
        <p role="status">Insufficient data: {lev.reason}</p>
      )}
      <p className="muted">
        {lev.calculation}. {lev.note}
      </p>

      <h3>Funding</h3>
      <p>
        7-day annualised {formatPct(fund.annualised_7d_pct)} ({fund.weighting}) ·{" "}
        {fund.direction ?? "no direction"} · <strong>{fund.condition}</strong>
      </p>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Venue</th>
            <th scope="col">Settlements (7 d)</th>
            <th scope="col">Annualised (7 d)</th>
            <th scope="col">Latest rate</th>
            <th scope="col">Interval</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {fund.venues.map((v) => (
            <tr key={v.venue}>
              <th scope="row">{v.venue}</th>
              <td>{v.settlements_7d}</td>
              <td>{formatPct(v.annualised_7d_pct)}</td>
              <td>
                {formatPct(v.latest_rate_pct, 4)}
                {v.latest_time ? ` (${v.latest_time})` : ""}
              </td>
              <td>{v.interval_hours ? `${Number(v.interval_hours)} h` : "—"}</td>
              <td>{v.reason ?? v.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{fund.calculation}.</p>

      <h3>Long/short account ratio (context only)</h3>
      <ul className="note-list">
        {view.positioning.long_short_account_ratio.map((r) => (
          <li key={r.venue}>
            {r.venue}: {r.ratio ?? "—"} ({r.population ?? "population unknown"}), 7 d{" "}
            {formatPct(r.change_7d_pct)}
          </li>
        ))}
      </ul>
      <p className="muted">{view.positioning.note}</p>

      <h3>Price context</h3>
      <p>
        {view.price_context.description ?? "Insufficient data."} Price{" "}
        {view.price_context.price ? `$${formatNumber(view.price_context.price, 2)}` : "—"} (24 h{" "}
        {formatPct(view.price_context.change_24h_pct)}, 7 d{" "}
        {formatPct(view.price_context.change_7d_pct)}; {view.price_context.source}).
      </p>
      <p className="muted">{view.price_context.note}</p>
    </section>
  );
}
