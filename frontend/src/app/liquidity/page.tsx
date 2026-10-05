import type { Metadata } from "next";
import { connection } from "next/server";

import { Unavailable } from "@/components/dashboard/Unavailable";
import { SupplyHistoryChart } from "@/components/liquidity/SupplyHistoryChart";
import { AutoRefresh } from "@/components/market/AutoRefresh";
import { fetchLiquidityHistory, fetchLiquidityOverview } from "@/lib/liquidity";
import { navItem } from "@/lib/navigation";

const item = navItem("/liquidity");

export const metadata: Metadata = { title: item.label };

const SUBJECTS = ["TOTAL", "USDT", "USDC"] as const;

export default async function LiquidityPage() {
  // Render at request time so freshness is live, never a build-time snapshot.
  await connection();
  const [overview, history] = await Promise.all([
    fetchLiquidityOverview(),
    fetchLiquidityHistory("TOTAL", 90),
  ]);

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      {overview.ok ? (
        <>
          <p className="muted">{overview.data.evidence_note}</p>

          <div className="status-card">
            <h2>Liquidity Score</h2>
            <div className="score-head">
              {overview.data.score.status === "ok" ? (
                <>
                  <p className="score-value">{overview.data.score.score ?? "—"}</p>
                  {overview.data.score.band ? (
                    <span className="badge badge-neutral">{overview.data.score.band}</span>
                  ) : null}
                </>
              ) : (
                <p className="muted">Insufficient data. {overview.data.score.reason ?? ""}</p>
              )}
            </div>
            <p className="muted">{overview.data.score.semantic_note}</p>
          </div>

          <div className="status-card">
            <h2>Circulating supply growth</h2>
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Subject</th>
                  <th scope="col">Value</th>
                  <th scope="col">24h</th>
                  <th scope="col">7d</th>
                  <th scope="col">30d</th>
                </tr>
              </thead>
              <tbody>
                {SUBJECTS.map((s) => {
                  const row = overview.data.supply[s];
                  return (
                    <tr key={s}>
                      <th scope="row">{s}</th>
                      {row && row.status === "ok" ? (
                        <>
                          <td>{row.value ?? "—"}</td>
                          <td>{row.change_24h_pct !== null ? `${row.change_24h_pct}%` : "—"}</td>
                          <td>{row.change_7d_pct !== null ? `${row.change_7d_pct}%` : "—"}</td>
                          <td>{row.change_30d_pct !== null ? `${row.change_30d_pct}%` : "—"}</td>
                        </>
                      ) : (
                        <td colSpan={4} className="muted">
                          Insufficient data. {row?.reason ?? ""}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="status-card">
            <h2>Market share</h2>
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Subject</th>
                  <th scope="col">Value</th>
                  <th scope="col">Share of total</th>
                </tr>
              </thead>
              <tbody>
                {SUBJECTS.filter((s) => s !== "TOTAL").map((s) => {
                  const row = overview.data.market_share[s];
                  return (
                    <tr key={s}>
                      <th scope="row">{s}</th>
                      {row && row.status === "ok" ? (
                        <>
                          <td>{row.value ?? "—"}</td>
                          <td>{row.share_pct !== null ? `${row.share_pct}%` : "—"}</td>
                        </>
                      ) : (
                        <td colSpan={2} className="muted">
                          Insufficient data. {row?.reason ?? ""}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="status-card">
            <h2>Growth acceleration</h2>
            {overview.data.growth_acceleration.status === "ok" ? (
              <p>
                7-day growth rate now: {overview.data.growth_acceleration.rate_now_7d_pct ?? "—"}%,
                prior period: {overview.data.growth_acceleration.rate_prior_7d_pct ?? "—"}% (
                {overview.data.growth_acceleration.change_pct_points ?? "—"} points change)
              </p>
            ) : (
              <p className="muted">
                Insufficient data. {overview.data.growth_acceleration.reason ?? ""}
              </p>
            )}
            <p className="muted">
              Exchange liquidity change:{" "}
              {overview.data.exchange_liquidity_change.reason ?? "Not tracked."}
            </p>
          </div>

          {overview.data.not_tracked.length ? (
            <div className="status-card">
              <h2>Not tracked</h2>
              <ul className="note-list">
                {overview.data.not_tracked.map((n) => (
                  <li key={n.item}>
                    {n.item}: {n.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : (
        <Unavailable what="Liquidity overview" reason={overview.reason} />
      )}

      {history.ok ? (
        history.data.points.length ? (
          <section className="status-card" aria-labelledby="liquidity-chart-title">
            <h2 id="liquidity-chart-title">
              {history.data.subject} supply, {history.data.days} days
            </h2>
            <SupplyHistoryChart history={history.data} />
          </section>
        ) : (
          <p className="muted">No supply history recorded for this period.</p>
        )
      ) : (
        <Unavailable what="Supply history" reason={history.reason} />
      )}

      <AutoRefresh seconds={300} renderedAt={new Date().toISOString()} />
    </section>
  );
}
