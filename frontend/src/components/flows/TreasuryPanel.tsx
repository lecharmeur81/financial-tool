import {
  formatNumber,
  formatSigned,
  formatSignedGrouped,
  formatUsdMillions,
  periodLabel,
  type Treasury,
} from "@/lib/institutional";

import { MetricFacts } from "./MetricFacts";

/** Listed-company treasuries: disclosed purchases (BTC) and holdings totals (attributed evidence). */
export function TreasuryPanel({ treasury }: { treasury: Treasury }) {
  const { purchases, holdings_totals: totals } = treasury;
  return (
    <section className="status-card" aria-labelledby="treasury-title">
      <h2 id="treasury-title">Corporate treasuries · {treasury.asset}</h2>
      <p className="muted">{treasury.evidence_note}</p>
      {treasury.warnings.length ? (
        <ul className="warnings">
          {treasury.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}

      {totals ? (
        <>
          <h3>Holdings of listed companies</h3>
          <p className="tile-value">
            {formatNumber(totals.holdings.value)} {treasury.asset}
          </p>
          <ul className="note-list">
            {totals.changes.map((c) => (
              <li key={c.days}>
                {c.days}-day change:{" "}
                {c.change_native === null
                  ? (c.note ?? "—")
                  : `${formatSigned(c.change_native, 0)} ${treasury.asset} (${formatSigned(c.change_pct, 2, " %")}) vs ${c.compared_with}`}
              </li>
            ))}
          </ul>
          <MetricFacts metric={totals.holdings} />
        </>
      ) : null}

      {purchases ? (
        <>
          <h3>{purchases.definition.label}</h3>
          <p className="muted">{purchases.definition.calculation}</p>
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Period</th>
                <th scope="col">BTC acquired (net)</th>
                <th scope="col">Reported cost</th>
                <th scope="col">Purchases</th>
                <th scope="col">Companies</th>
              </tr>
            </thead>
            <tbody>
              {[...purchases.buckets].reverse().map((b) => (
                <tr key={b.start}>
                  <th scope="row">{periodLabel(b.start, b.end)}</th>
                  <td>
                    {b.events === 0 ? (
                      <span className="muted">none disclosed</span>
                    ) : (
                      formatSignedGrouped(b.btc_acquired, 4)
                    )}
                  </td>
                  <td>{b.events === 0 ? "" : formatUsdMillions(b.cost_usd)}</td>
                  <td>{b.events}</td>
                  <td>{b.companies}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Latest disclosed purchases and sales</h3>
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Company</th>
                <th scope="col">BTC</th>
                <th scope="col">Cost</th>
                <th scope="col" title="Calculated: |cost ÷ BTC|">
                  Cost per BTC (calculated)
                </th>
                <th scope="col">Holdings after</th>
                <th scope="col">Public by</th>
              </tr>
            </thead>
            <tbody>
              {purchases.recent.map((p) => (
                <tr key={`${p.ticker}-${p.date}`}>
                  <th scope="row">{p.date}</th>
                  <td>
                    {p.company} <span className="muted">({p.ticker})</span>
                    {p.quality_status !== "ok" ? (
                      <span className="badge badge-warn" title={p.quality_note ?? undefined}>
                        {p.quality_status}
                      </span>
                    ) : null}
                  </td>
                  <td>{formatSignedGrouped(p.btc_acquired, 4)}</td>
                  <td>{formatUsdMillions(p.cost_usd)}</td>
                  <td>
                    {p.implied_cost_per_btc_usd === null
                      ? "—"
                      : `${formatNumber(p.implied_cost_per_btc_usd)} USD`}
                  </td>
                  <td>{formatNumber(p.holdings_after_btc)}</td>
                  <td>
                    {p.available_at.slice(0, 10)}
                    {p.available_at_estimated ? " (estimated)" : ""}
                    {p.pit_reliability === "backfilled_latest" ? " · loaded later" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Largest reported holders ({purchases.companies_tracked} companies tracked)</h3>
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">BTC held</th>
                <th scope="col">As of its latest purchase</th>
              </tr>
            </thead>
            <tbody>
              {purchases.top_holders.map((h) => (
                <tr key={h.ticker}>
                  <th scope="row">
                    {h.company} <span className="muted">({h.ticker})</span>
                  </th>
                  <td>{formatNumber(h.holdings_btc)}</td>
                  <td>{h.as_of_purchase_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <MetricFacts metric={purchases.reported_holdings} />
        </>
      ) : null}
    </section>
  );
}
