import { formatCompact, formatDecimal, type Overview, type Summary } from "@/lib/market";
import type { MarketStructureOverview } from "@/lib/market-structure";

/**
 * Section 2 — Market Overview. Price, 24h change and volume come from the same analyst tool
 * used by the AI Analyst (`/market/summary`, a pass-through — no new calculation); market
 * structure's own trend/volatility reading and market cap are reused unchanged, never
 * recomputed here (Phase 26 constraint).
 */
export function MarketOverviewSection({
  summary,
  structure,
  overview,
}: {
  summary: Summary;
  structure: MarketStructureOverview | null;
  overview: Overview | null;
}) {
  if (summary.status !== "ok" || !summary.data) {
    return (
      <section className="status-card" aria-labelledby="market-overview-title">
        <h2 id="market-overview-title">Market Overview</h2>
        <p className="muted">Insufficient data. {summary.error?.detail ?? ""}</p>
      </section>
    );
  }
  const caps = new Map((overview?.assets ?? []).map((a) => [a.symbol, a.market_cap]));
  return (
    <section className="status-card" aria-labelledby="market-overview-title">
      <h2 id="market-overview-title">Market Overview</h2>
      <div className="summary-grid">
        {Object.entries(summary.data.assets).map(([asset, a]) => {
          const structureAsset = structure?.assets[asset];
          const cap = caps.get(asset);
          return (
            <div className="tile" key={asset}>
              <h3>{asset}</h3>
              <p className="tile-value">
                {a.price_close.value === null ? "—" : `$${formatDecimal(a.price_close.value, 2)}`}
              </p>
              <p>
                24h: {a.change_24h_pct.value === null ? "—" : `${a.change_24h_pct.value}%`} · 7d:{" "}
                {a.change_7d_pct.value === null ? "—" : `${a.change_7d_pct.value}%`}
              </p>
              <p>
                Volume 24h:{" "}
                {a.volume_24h.value === null ? "—" : formatDecimal(a.volume_24h.value, 2)}
              </p>
              <p>
                Volatility (30d, annualized):{" "}
                {a.realized_volatility_30d.value === null ? "—" : a.realized_volatility_30d.value}
              </p>
              <p>Structure: {structureAsset?.trend?.condition ?? "Insufficient data."}</p>
              <p>Market cap: {cap ? formatCompact(cap.value, "usd") : "Insufficient data."}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
