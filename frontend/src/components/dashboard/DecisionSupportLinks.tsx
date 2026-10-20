import Link from "next/link";

import { ADVISOR_ASSETS } from "@/lib/advisor";
import { navItem } from "@/lib/navigation";

/** The decision-support views reachable from the dashboard, in reading order. */
const TARGETS = ["/advisor", "/portfolio", "/alerts", "/brief", "/paper"] as const;

/**
 * Quick links from the dashboard to the views built on its evidence (Phase 55). It fetches
 * nothing and states nothing new: titles and descriptions are the navigation entries' own, and
 * the Advisor Brief link keeps the asset the Decision Center is showing.
 */
export function DecisionSupportLinks({ asset }: { asset: string }) {
  const advisorAsset = (ADVISOR_ASSETS as readonly string[]).includes(asset) ? asset : null;
  return (
    <section className="decision-support-links" aria-labelledby="decision-support-title">
      <h2 id="decision-support-title">Decision support</h2>
      <p className="muted">
        Each view below reads the same stored evidence. They are descriptive aids, not advice, and
        none of them places a trade.
      </p>
      <div className="summary-grid">
        {TARGETS.map((href) => {
          const item = navItem(href);
          const target =
            href === "/advisor" && advisorAsset ? `/advisor?asset=${advisorAsset}` : href;
          return (
            <Link key={href} href={target} className="tile tile-link">
              <h3>{item.label}</h3>
              <p className="muted">{item.description}</p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
