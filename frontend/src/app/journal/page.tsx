import type { Metadata } from "next";
import { connection } from "next/server";

import { fetchDecisionStats, fetchRecentDecisions } from "@/lib/journal";
import { formatUtc } from "@/lib/market";
import { navItem } from "@/lib/navigation";

const item = navItem("/journal");

export const metadata: Metadata = { title: item.label };

export default async function JournalPage() {
  // Render at request time so decisions/stats are never a build-time snapshot.
  await connection();
  const [decisions, stats] = await Promise.all([fetchRecentDecisions(200), fetchDecisionStats()]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      {stats.ok ? (
        <section className="status-card">
          <h2>Review (descriptive only)</h2>
          <div className="summary-grid">
            <div className="tile">
              <h3>Total decisions</h3>
              <p className="tile-value">{stats.data.total_decisions}</p>
              <p className="muted">
                {stats.data.open_decisions} open · {stats.data.resolved_decisions} resolved ·{" "}
                {stats.data.invalidated_decisions} invalidated · {stats.data.cancelled_decisions}{" "}
                cancelled
              </p>
            </div>
            <div className="tile">
              <h3>Thesis outcomes</h3>
              <p className="muted">
                Supported {stats.data.thesis_supported_count} · Contradicted{" "}
                {stats.data.thesis_contradicted_count} · Invalidation occurred{" "}
                {stats.data.invalidation_occurred_count}
              </p>
            </div>
            <div className="tile">
              <h3>Average time to resolution</h3>
              <p className="tile-value">{stats.data.average_time_to_resolution_hours ?? "—"} h</p>
            </div>
          </div>
          <p className="muted">{stats.data.disclaimer}</p>
        </section>
      ) : (
        <div className="status-card" role="alert">
          <span className="badge badge-error">Review unavailable</span> <span>{stats.reason}</span>
        </div>
      )}

      <section className="status-card">
        <h2>Decisions</h2>
        {decisions.ok ? (
          decisions.data.length ? (
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Type</th>
                  <th scope="col">Thesis</th>
                  <th scope="col">Status</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Regime at decision</th>
                  <th scope="col">Decided</th>
                </tr>
              </thead>
              <tbody>
                {decisions.data.map((d) => (
                  <tr key={d.decision_id}>
                    <th scope="row">{d.asset}</th>
                    <td>{d.decision_type}</td>
                    <td>{d.thesis}</td>
                    <td>{d.status}</td>
                    <td>{d.outcome ?? "—"}</td>
                    <td>{d.market_regime_label ?? "—"}</td>
                    <td>{formatUtc(d.decision_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No decisions recorded yet.</p>
          )
        ) : (
          <p className="muted">Insufficient data. {decisions.reason}</p>
        )}
      </section>
    </section>
  );
}
