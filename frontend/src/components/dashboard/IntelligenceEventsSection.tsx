import Link from "next/link";

import type { IntelligenceEvent } from "@/lib/intelligence";
import { formatUtc } from "@/lib/market";
import { Unavailable } from "@/components/dashboard/Unavailable";

const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge badge-error",
  elevated: "badge badge-warn",
  notable: "badge badge-neutral",
};

/**
 * Compact Intelligence Events summary for the Executive Dashboard (Phase 36). Reuses the Phase 35
 * `/intelligence-events/` list unchanged — this tile only summarizes; the full list with event
 * detail lives on /analytics (Phase 36 navigation decision: no separate /intelligence page unless
 * /analytics becomes crowded).
 */
export function IntelligenceEventsSection({
  events,
}: {
  events: { ok: true; data: IntelligenceEvent[] } | { ok: false; reason: string };
}) {
  if (!events.ok) return <Unavailable what="Intelligence events" reason={events.reason} />;
  const recent = events.data.slice(0, 5);

  return (
    <section className="status-card" aria-labelledby="intel-events-tile-title">
      <h2 id="intel-events-tile-title">Intelligence Events</h2>
      {recent.length ? (
        <ul className="note-list">
          {recent.map((e) => (
            <li key={e.event_id}>
              <span className={SEVERITY_BADGE[e.severity] ?? "badge badge-neutral"}>
                {e.severity}
              </span>{" "}
              {e.domain}/{e.event_type}: {e.current_value} ({formatUtc(e.observed_at)})
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No intelligence events recorded recently.</p>
      )}
      <Link href="/analytics" className="link-button">
        All intelligence events →
      </Link>
    </section>
  );
}
