"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Re-fetches the page's server data on an interval so freshness stays current; can be paused. */
export function AutoRefresh({
  seconds = 30,
  renderedAt,
}: {
  seconds?: number;
  renderedAt: string;
}) {
  const router = useRouter();
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const id = window.setInterval(() => router.refresh(), seconds * 1000);
    return () => window.clearInterval(id);
  }, [paused, router, seconds]);

  return (
    <p className="muted auto-refresh">
      Page data as of {renderedAt.slice(11, 19)} UTC ·{" "}
      {paused ? "auto-refresh paused" : `refreshes every ${seconds} s`}{" "}
      <button type="button" className="link-button" onClick={() => setPaused((p) => !p)}>
        {paused ? "Resume" : "Pause"}
      </button>
    </p>
  );
}
