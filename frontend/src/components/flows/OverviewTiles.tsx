import Link from "next/link";

import {
  bandClass,
  type FlowSelection,
  flowHref,
  formatSigned,
  formatUsdMillions,
  type Overview,
} from "@/lib/institutional";
import { FRESHNESS_CLASS, FRESHNESS_LABEL } from "@/lib/market";

/** One tile per asset with US spot ETFs: score, last reported day and 5-day flow. */
export function OverviewTiles({
  overview,
  selection,
}: {
  overview: Overview;
  selection: FlowSelection;
}) {
  return (
    <div className="summary-grid">
      {overview.assets.map((a) => (
        <Link
          key={a.asset}
          href={flowHref(selection, { asset: a.asset })}
          className={a.asset === selection.asset ? "tile tile-link active" : "tile tile-link"}
        >
          <h3>
            {a.asset} · US spot ETFs{" "}
            <span className={FRESHNESS_CLASS[a.freshness.status]}>
              {FRESHNESS_LABEL[a.freshness.status]}
            </span>
          </h3>
          <p className="tile-value">
            {a.score.status === "ok" ? formatSigned(a.score.value, 1) : "Insufficient data"}
          </p>
          {a.score.band ? <span className={bandClass(a.score.band)}>{a.score.band}</span> : null}
          <p>
            Last day {a.latest_day.date ?? "—"}: {formatUsdMillions(a.latest_day.net_flow_usd)}
          </p>
          <p>
            5 trading days:{" "}
            {a.flow_5d.status === "ok"
              ? `${formatUsdMillions(a.flow_5d.net_flow_usd)} (${formatSigned(a.flow_5d.pct_of_net_assets, 3, " % of net assets")})`
              : "unavailable"}
          </p>
        </Link>
      ))}
    </div>
  );
}
