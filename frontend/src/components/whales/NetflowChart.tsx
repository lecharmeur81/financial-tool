"use client";

import { ColorType, createChart, HistogramSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { toNetflowChart, type WhaleFlows } from "@/lib/whales";

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Daily net flow to exchanges in coins (red = coins moving onto exchanges, green = off them).
 * Days without both inflow and outflow are holes, never zeros.
 */
export function NetflowChart({ days, unit }: { days: WhaleFlows["days"]; unit: string }) {
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
        priceFormatter: (p: number) => p.toLocaleString("en-US", { maximumFractionDigits: 0 }),
      },
    });
    const series = chart.addSeries(HistogramSeries, {
      title: `Net flow to exchanges (${unit.toUpperCase()})`,
    });
    series.setData(toNetflowChart(days).map((p) => ({ ...p, time: p.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [days, unit]);

  return (
    <div
      ref={container}
      className="flow-chart"
      role="img"
      aria-label={`Daily net flow to exchanges in ${unit.toUpperCase()}, ${days.length} days`}
    />
  );
}
