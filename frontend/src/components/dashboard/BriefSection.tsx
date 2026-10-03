import Link from "next/link";

import type { BriefStatus } from "@/lib/brief";
import { formatUtc } from "@/lib/market";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Section 11 — Daily Brief. Shows the latest completed brief's own summary unchanged; the
 * dashboard does not generate a second interpretation of it (Phase 26 constraint). Full access
 * to the complete brief is via the link to /brief, never re-rendered field-by-field here.
 */
export function BriefSection({
  brief,
}: {
  brief: { ok: true; data: BriefStatus } | { ok: false; reason: string };
}) {
  if (!brief.ok) return <Unavailable what="Daily brief" reason={brief.reason} />;
  const response = brief.data.response;
  return (
    <section className="status-card" aria-labelledby="brief-title">
      <h2 id="brief-title">Daily Brief</h2>
      <p className="muted">
        Reporting period {formatUtc(brief.data.reporting_period_start)} …{" "}
        {formatUtc(brief.data.reporting_period_end)} · data quality:{" "}
        {brief.data.data_quality_state ?? "—"}
      </p>
      {response?.summary ? <p>{response.summary}</p> : <p className="muted">Insufficient data.</p>}
      <Link href="/brief" className="link-button">
        Read the complete brief →
      </Link>
    </section>
  );
}
