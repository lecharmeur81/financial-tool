"use client";

import { ColorType, createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { type DerivativesHistory, toOpenInterestChart } from "@/lib/derivatives";

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Hourly aggregate open interest (coins, left scale; only hours where every venue reported) and
 * the Coinbase USD price (right scale). Hours without data are holes, never zeros.
 */
export function OpenInterestChart({ history }: { history: DerivativesHistory }) {
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
      leftPriceScale: { visible: true, borderColor: border },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: true },
      localization: {
        priceFormatter: (p: number) => p.toLocaleString("en-US", { maximumFractionDigits: 0 }),
      },
    });
    const data = toOpenInterestChart(history);
    const oi = chart.addSeries(LineSeries, {
      title: `Open interest (${history.open_interest.unit.toUpperCase()})`,
      priceScaleId: "left",
      color: "#2458a6",
    });
    oi.setData(data.openInterest.map((p) => ({ ...p, time: p.time as UTCTimestamp })));
    const price = chart.addSeries(LineSeries, {
      title: "Price (USD)",
      priceScaleId: "right",
      color: "#8a8f98",
    });
    price.setData(data.price.map((p) => ({ ...p, time: p.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [history]);

  return (
    <div
      ref={container}
      className="flow-chart"
      role="img"
      aria-label={`Hourly open interest and USD price, ${history.days} days`}
    />
  );
}
