import Link from "next/link";

import type { DerivativesAssetView } from "@/lib/derivatives";
import type { LiquidityOverview } from "@/lib/liquidity";

type Opt<T> = T | null;

/**
 * Section 8 — Derivatives & Liquidity. Reuses the Derivatives Health Score and Liquidity Score
 * unchanged; missing-data rules apply — nothing here fabricates a funding rate, OI figure or
 * stablecoin growth number (Phase 26 constraint; same R3 rule as every other section).
 */
export function DerivativesLiquiditySection({
  derivatives,
  liquidity,
}: {
  derivatives: Opt<DerivativesAssetView>;
  liquidity: Opt<LiquidityOverview>;
}) {
  return (
    <section className="status-card" aria-labelledby="deriv-liq-title">
      <h2 id="deriv-liq-title">Derivatives &amp; Liquidity</h2>
      <div className="summary-grid">
        <div className="tile">
          <h3>Derivatives Health (BTC)</h3>
          {derivatives && derivatives.score.status === "ok" ? (
            <>
              <p className="tile-value">{derivatives.score.health}</p>
              {derivatives.score.band ? (
                <span className="badge badge-neutral">{derivatives.score.band}</span>
              ) : null}
            </>
          ) : (
            <p className="muted">Insufficient data.</p>
          )}
          <p>
            Open interest 24h change:{" "}
            {derivatives?.open_interest.change_24h_pct
              ? `${derivatives.open_interest.change_24h_pct}%`
              : "Insufficient data."}
          </p>
          <Link href="/derivatives" className="link-button">
            Full derivatives detail →
          </Link>
        </div>
        <div className="tile">
          <h3>Liquidity (stablecoins)</h3>
          {liquidity && liquidity.score.status === "ok" ? (
            <>
              <p className="tile-value">{liquidity.score.score}</p>
              {liquidity.score.band ? (
                <span className="badge badge-neutral">{liquidity.score.band}</span>
              ) : null}
            </>
          ) : (
            <p className="muted">Insufficient data.</p>
          )}
          <p>
            Total stablecoin supply growth (7d):{" "}
            {liquidity?.supply.TOTAL?.change_7d_pct
              ? `${liquidity.supply.TOTAL.change_7d_pct}%`
              : "Insufficient data."}
          </p>
          <Link href="/liquidity" className="link-button">
            Full liquidity detail →
          </Link>
        </div>
      </div>
    </section>
  );
}
