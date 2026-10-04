"use client";

import { ColorType, createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { type SupplyHistory, toSupplyHistoryChart } from "@/lib/liquidity";

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Daily circulating-supply history for one subject (TradingView Lightweight Charts, Phase 36). */
export function SupplyHistoryChart({ history }: { history: SupplyHistory }) {
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
      timeScale: { borderColor: border, timeVisible: true },
      localization: {
        priceFormatter: (p: number) => p.toLocaleString("en-US", { maximumFractionDigits: 0 }),
      },
    });
    const series = chart.addSeries(LineSeries, {
      title: `${history.subject} supply (${history.unit})`,
      color: "#2458a6",
    });
    series.setData(
      toSupplyHistoryChart(history).map((p) => ({ ...p, time: p.time as UTCTimestamp })),
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [history]);

  return (
    <div
      ref={container}
      className="flow-chart"
      role="img"
      aria-label={`Daily ${history.subject} circulating supply, ${history.days} days`}
    />
  );
}
