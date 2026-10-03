/**
 * Shared "no data shown" state for a dashboard section (Phase 26) — the same honest pattern
 * already used on /flows, /whales, /derivatives: nothing is displayed in place of missing data,
 * ever (R3).
 */
export function Unavailable({ what, reason }: { what: string; reason: string }) {
  return (
    <div className="status-card" role="alert">
      <span className="badge badge-error">{what} unavailable</span> <span>{reason}</span>
      <p className="muted">Nothing is shown in its place — no cached or estimated values.</p>
    </div>
  );
}

/** For a field that came back `status: "insufficient_data"` inside an otherwise-ok response. */
export function InsufficientData({ what, reason }: { what: string; reason?: string | null }) {
  return (
    <p className="muted">
      <span className="badge badge-neutral">{what}: Insufficient data.</span>{" "}
      {reason ?? "Not enough data to compute this right now."}
    </p>
  );
}
