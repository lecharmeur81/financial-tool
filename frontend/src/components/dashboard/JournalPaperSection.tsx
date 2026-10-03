import Link from "next/link";

import type { DecisionStatus } from "@/lib/journal";
import type { OpenPositionStatus, PerformanceStats, TradeStatus } from "@/lib/paper";

type Res<T> = { ok: true; data: T } | { ok: false; reason: string };

/**
 * Section 12 — Decision Journal / Paper Trading. Recent decisions, open simulated positions
 * and basic performance only; links to the full journal/paper-trading views rather than
 * duplicating all of their functionality (Phase 26 constraint).
 */
export function JournalPaperSection({
  trades,
  positions,
  performance,
  decisions,
}: {
  trades: Res<TradeStatus[]>;
  positions: Res<OpenPositionStatus[]>;
  performance: Res<PerformanceStats>;
  decisions: Res<DecisionStatus[]>;
}) {
  return (
    <section className="status-card" aria-labelledby="journal-paper-title">
      <h2 id="journal-paper-title">Decision Journal &amp; Paper Trading</h2>
      <p className="muted">
        Simulated trades and the user&apos;s own recorded decisions — never a recommendation or a
        ranking of strategies.
      </p>
      <div className="summary-grid">
        <div className="tile">
          <h3>Open paper positions</h3>
          {positions.ok ? (
            positions.data.length ? (
              <ul className="note-list">
                {positions.data.map((p) => (
                  <li key={p.trade.trade_id}>
                    {p.trade.asset} {p.trade.direction} · unrealized{" "}
                    {p.unrealized_net_pnl ?? "insufficient data"}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No open positions.</p>
            )
          ) : (
            <p className="muted">Insufficient data. {positions.reason}</p>
          )}
        </div>
        <div className="tile">
          <h3>Performance (simulated)</h3>
          {performance.ok ? (
            <>
              <p className="tile-value">{performance.data.net_pnl}</p>
              <p className="muted">
                {performance.data.total_trades} trades · win rate {performance.data.win_rate ?? "—"}
              </p>
              <p className="muted">{performance.data.disclaimer}</p>
            </>
          ) : (
            <p className="muted">Insufficient data. {performance.reason}</p>
          )}
        </div>
        <div className="tile">
          <h3>Recent decisions</h3>
          {decisions.ok ? (
            decisions.data.length ? (
              <ul className="note-list">
                {decisions.data.slice(0, 5).map((d) => (
                  <li key={d.decision_id}>
                    {d.asset} · {d.decision_type} · {d.status}
                    {d.outcome ? ` (${d.outcome})` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No decisions recorded yet.</p>
            )
          ) : (
            <p className="muted">Insufficient data. {decisions.reason}</p>
          )}
        </div>
      </div>
      {trades.ok && trades.data.length ? (
        <p className="muted">{trades.data.length} trade(s) in recent history.</p>
      ) : null}
      <p>
        <Link href="/paper" className="link-button">
          Full paper trading →
        </Link>{" "}
        <Link href="/journal" className="link-button">
          Full decision journal →
        </Link>
      </p>
    </section>
  );
}
