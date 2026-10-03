import Link from "next/link";

import type { Overview as InstitutionalOverview } from "@/lib/institutional";
import type { RetailOverview } from "@/lib/retail";
import type { WhaleScore } from "@/lib/whales";

type Opt<T> = T | null;

/**
 * Section 7 — Institutional / Whale / Retail. Each participant type gets its own visually
 * distinct column; they are never merged into one generic sentiment indicator (Phase 26
 * constraint — these three domains measure different things with different evidence classes).
 */
export function ParticipantsSection({
  institutional,
  whaleScore,
  retail,
}: {
  institutional: Opt<InstitutionalOverview>;
  whaleScore: Opt<WhaleScore>;
  retail: Opt<RetailOverview>;
}) {
  const btcInst = institutional?.assets.find((a) => a.asset === "BTC") ?? null;
  return (
    <section className="status-card" aria-labelledby="participants-title">
      <h2 id="participants-title">Institutional / Whale / Retail</h2>
      <div className="summary-grid">
        <div className="tile">
          <h3>Institutional</h3>
          {btcInst && btcInst.score.status === "ok" ? (
            <>
              <p className="tile-value">{btcInst.score.value}</p>
              {btcInst.score.band ? (
                <span className="badge badge-neutral">{btcInst.score.band}</span>
              ) : null}
            </>
          ) : (
            <p className="muted">Insufficient data.</p>
          )}
          <p className="muted">US spot ETF + corporate treasury flows (direct evidence).</p>
          <Link href="/flows" className="link-button">
            Full institutional detail →
          </Link>
        </div>
        <div className="tile">
          <h3>Whales</h3>
          {whaleScore && whaleScore.status === "ok" ? (
            <>
              <p className="tile-value">{whaleScore.value}</p>
              {whaleScore.band ? (
                <span className="badge badge-neutral">{whaleScore.band}</span>
              ) : null}
            </>
          ) : (
            <p className="muted">Insufficient data.</p>
          )}
          <p className="muted">
            Exchange flows, large holders, dormant-coin activity (attributed evidence).
          </p>
          <Link href="/whales" className="link-button">
            Full whale detail →
          </Link>
        </div>
        <div className="tile">
          <h3>Retail</h3>
          {retail && retail.activity_score.status === "ok" ? (
            <>
              <p className="tile-value">{retail.activity_score.score}</p>
              {retail.activity_score.band ? (
                <span className="badge badge-neutral">{retail.activity_score.band}</span>
              ) : null}
            </>
          ) : (
            <p className="muted">Insufficient data.</p>
          )}
          <p className="muted">
            Proxy data only (small on-chain transactions, meme-coin trending, derivatives turnover)
            — never a sentiment poll.
          </p>
          <Link href="/analytics" className="link-button">
            Full retail detail →
          </Link>
        </div>
      </div>
    </section>
  );
}
