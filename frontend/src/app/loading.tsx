/**
 * Instant loading fallback (Phase 26) while a page's server-side data fetches stream in. This
 * is the first client-visible "loading state" anywhere in this codebase — every other page
 * awaits its data directly with no client-side loading state (frontend/AGENTS.md convention) —
 * so it deliberately shows no numbers, same honesty rule as `PagePlaceholder`.
 */
export default function Loading() {
  return (
    <section className="page">
      <div className="placeholder" role="status">
        <span className="badge badge-neutral">Loading</span>
        <p>Fetching the latest data from the platform&apos;s own APIs…</p>
      </div>
    </section>
  );
}
