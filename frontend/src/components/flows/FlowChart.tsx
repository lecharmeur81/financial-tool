"use client";

import { ColorType, createChart, HistogramSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { type EtfBucket, toFlowChart } from "@/lib/institutional";

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Net ETF flow per day/week/month in millions of USD (green = net creations, red = net
 * redemptions; lighter = partial bucket). Buckets without data are holes, never zeros.
 */
export function FlowChart({ buckets, label }: { buckets: EtfBucket[]; label: string }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const text = cssVar("--text", "#16191d");
    const border = cssVar("--border", "#dfe3e8");
    const chart = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: text,
        attributionLogo: true,
      },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: false },
      localization: {
        priceFormatter: (p: number) =>
          `${p.toLocaleString("en-US", { maximumFractionDigits: 1 })} M`,
      },
    });
    const series = chart.addSeries(HistogramSeries, { title: `${label} (M USD)` });
    series.setData(toFlowChart(buckets).map((p) => ({ ...p, time: p.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [buckets, label]);

  return (
    <div
      ref={container}
      className="flow-chart"
      role="img"
      aria-label={`${label}: net flow bar chart, ${buckets.length} periods`}
    />
  );
}
