import Link from "next/link";

import type { Overview as InstitutionalOverview } from "@/lib/institutional";
import type { DerivativesAssetView } from "@/lib/derivatives";
import type { LiquidityOverview } from "@/lib/liquidity";
import type { RetailOverview } from "@/lib/retail";
import type { RotationMatrix } from "@/lib/rotation";
import type { WhaleScore } from "@/lib/whales";

type Opt<T> = T | null;

function Tile({
  title,
  href,
  value,
  band,
  note,
}: {
  title: string;
  href: string;
  value: string;
  band?: string | null;
  note: string;
}) {
  return (
    <Link href={href} className="tile tile-link">
      <h3>{title}</h3>
      <p className="tile-value">{value}</p>
      {band ? <span className="badge badge-neutral">{band}</span> : null}
      <p className="muted">{note}</p>
    </Link>
  );
}

/**
 * Section 3 — Capital Flow / Intelligence Overview. A compact, visual summary across the
 * domains detailed further down the page; observed readings are kept separate from any
 * inferred interpretation (here: rotation's own OBSERVED/INFERRED split, Phase 26 constraint).
 * Each tile links to its full section/page rather than duplicating the detail.
 */
export function IntelligenceOverviewSection({
  institutional,
  whaleScore,
  retail,
  liquidity,
  derivatives,
  rotation,
}: {
  institutional: Opt<InstitutionalOverview>;
  whaleScore: Opt<WhaleScore>;
  retail: Opt<RetailOverview>;
  liquidity: Opt<LiquidityOverview>;
  derivatives: Opt<DerivativesAssetView>;
  rotation: Opt<RotationMatrix>;
}) {
  const btcInst = institutional?.assets.find((a) => a.asset === "BTC") ?? null;
  const inferredRotations = (rotation?.pairs ?? []).filter(
    (p) => p.inferred_capital_rotation.status === "possible_rotation",
  );
  return (
    <section className="status-card" aria-labelledby="intel-overview-title">
      <h2 id="intel-overview-title">Capital Flow / Intelligence Overview</h2>
      <p className="muted">
        Observed positioning across participants, liquidity and derivatives. Any mention of
        &quot;rotation&quot; below is an inferred hypothesis, never a confirmed movement of capital.
      </p>
      <div className="summary-grid">
        <Tile
          title="Institutional (BTC)"
          href="/flows"
          value={
            btcInst && btcInst.score.status === "ok"
              ? (btcInst.score.value ?? "—")
              : "Insufficient data"
          }
          band={btcInst?.score.band}
          note="US spot ETF + treasury flow score."
        />
        <Tile
          title="Whales (BTC)"
          href="/whales"
          value={
            whaleScore && whaleScore.status === "ok"
              ? (whaleScore.value ?? "—")
              : "Insufficient data"
          }
          band={whaleScore?.band}
          note="Exchange-flow accumulation/distribution score."
        />
        <Tile
          title="Retail"
          href="/analytics"
          value={
            retail && retail.activity_score.status === "ok"
              ? (retail.activity_score.score ?? "—")
              : "Insufficient data"
          }
          band={retail?.activity_score.band}
          note="Retail activity score (proxy data, never a sentiment poll)."
        />
        <Tile
          title="Liquidity"
          href="/liquidity"
          value={
            liquidity && liquidity.score.status === "ok"
              ? (liquidity.score.score ?? "—")
              : "Insufficient data"
          }
          band={liquidity?.score.band}
          note="Stablecoin supply growth score."
        />
        <Tile
          title="Derivatives (BTC)"
          href="/derivatives"
          value={
            derivatives && derivatives.score.status === "ok"
              ? (derivatives.score.health ?? "—")
              : "Insufficient data"
          }
          band={derivatives?.score.band}
          note="Derivatives Health Score."
        />
        <Tile
          title="Capital rotation"
          href="#rotation"
          value={String(inferredRotations.length)}
          note="Inferred rotation hypotheses currently flagged (observed direction only, never confirmed flow)."
        />
      </div>
    </section>
  );
}
