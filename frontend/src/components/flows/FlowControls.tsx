import Link from "next/link";

import {
  ETF_ASSETS,
  type FlowSelection,
  flowHref,
  INTERVAL_LABEL,
  INTERVALS,
} from "@/lib/institutional";

/** Asset and aggregation switching. Plain links: the page re-renders on the server. */
export function FlowControls({ selection }: { selection: FlowSelection }) {
  return (
    <div className="market-controls">
      <nav aria-label="Asset" className="segmented">
        {ETF_ASSETS.map((a) => (
          <Link
            key={a}
            href={flowHref(selection, { asset: a })}
            className={a === selection.asset ? "segment active" : "segment"}
            aria-current={a === selection.asset ? "page" : undefined}
          >
            {a}
          </Link>
        ))}
      </nav>
      <nav aria-label="Aggregation" className="segmented">
        {INTERVALS.map((i) => (
          <Link
            key={i}
            href={flowHref(selection, { interval: i })}
            className={i === selection.interval ? "segment active" : "segment"}
            aria-current={i === selection.interval ? "page" : undefined}
          >
            {INTERVAL_LABEL[i]}
          </Link>
        ))}
      </nav>
    </div>
  );
}
