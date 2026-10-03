import type { Metadata } from "next";
import { connection } from "next/server";

import { AutoRefresh } from "@/components/market/AutoRefresh";
import { formatUtc } from "@/lib/market";
import { navItem } from "@/lib/navigation";
import { fetchOpenPositions, fetchPaperPerformance, fetchRecentTrades } from "@/lib/paper";

const item = navItem("/paper");

export const metadata: Metadata = { title: item.label };

export default async function PaperPage() {
  // Render at request time so positions/performance are never a build-time snapshot.
  await connection();
  const [trades, positions, performance] = await Promise.all([
    fetchRecentTrades(100),
    fetchOpenPositions(),
    fetchPaperPerformance(),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      {performance.ok ? (
        <section className="status-card">
          <h2>Performance</h2>
          <div className="summary-grid">
            <div className="tile">
              <h3>Net P&amp;L</h3>
              <p className="tile-value">{performance.data.net_pnl}</p>
            </div>
            <div className="tile">
              <h3>Trades</h3>
              <p className="tile-value">{performance.data.total_trades}</p>
              <p className="muted">
                {performance.data.open_trades} open · {performance.data.closed_trades} closed ·{" "}
                {performance.data.cancelled_trades} cancelled
              </p>
            </div>
            <div className="tile">
              <h3>Win rate</h3>
              <p className="tile-value">{performance.data.win_rate ?? "—"}</p>
              <p className="muted">
                {performance.data.winning_trades} winning · {performance.data.losing_trades} losing
              </p>
            </div>
            <div className="tile">
              <h3>Expectancy / max drawdown</h3>
              <p>{performance.data.expectancy ?? "—"}</p>
              <p>{performance.data.max_drawdown ?? "—"}</p>
            </div>
          </div>
          <p className="muted">{performance.data.disclaimer}</p>
        </section>
      ) : (
        <div className="status-card" role="alert">
          <span className="badge badge-error">Performance unavailable</span>{" "}
          <span>{performance.reason}</span>
        </div>
      )}

      <section className="status-card">
        <h2>Open positions</h2>
        {positions.ok ? (
          positions.data.length ? (
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Entry</th>
                  <th scope="col">Current</th>
                  <th scope="col">Unrealized net P&amp;L</th>
                  <th scope="col">Data quality</th>
                </tr>
              </thead>
              <tbody>
                {positions.data.map((p) => (
                  <tr key={p.trade.trade_id}>
                    <th scope="row">{p.trade.asset}</th>
                    <td>{p.trade.direction}</td>
                    <td>{p.trade.entry_price_observed}</td>
                    <td>{p.current_price_observed ?? "—"}</td>
                    <td>{p.unrealized_net_pnl ?? "—"}</td>
                    <td>{p.data_quality_state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No open positions.</p>
          )
        ) : (
          <p className="muted">Insufficient data. {positions.reason}</p>
        )}
      </section>

      <section className="status-card">
        <h2>Trade history</h2>
        {trades.ok ? (
          trades.data.length ? (
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Status</th>
                  <th scope="col">Entry</th>
                  <th scope="col">Realized P&amp;L</th>
                  <th scope="col">Return</th>
                </tr>
              </thead>
              <tbody>
                {trades.data.map((t) => (
                  <tr key={t.trade_id}>
                    <th scope="row">{t.asset}</th>
                    <td>{t.direction}</td>
                    <td>{t.status}</td>
                    <td>{formatUtc(t.entry_time)}</td>
                    <td>{t.realized_pnl ?? "—"}</td>
                    <td>{t.return_pct ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No trades recorded yet.</p>
          )
        ) : (
          <p className="muted">Insufficient data. {trades.reason}</p>
        )}
      </section>

      <AutoRefresh seconds={60} renderedAt={new Date().toISOString()} />
    </section>
  );
}
