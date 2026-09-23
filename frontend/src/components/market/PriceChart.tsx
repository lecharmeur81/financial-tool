"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { type Bar, formatUnit, toChartData } from "@/lib/market";

type Props = {
  bars: Bar[];
  priceUnit: string;
  volumeUnit: string;
  label: string;
};

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Candlestick chart with a separate volume pane (TradingView Lightweight Charts, ADR-0043).
 * Missing bars are drawn as holes. The TradingView attribution logo stays on (licence requirement).
 */
export function PriceChart({ bars, priceUnit, volumeUnit, label }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
        panes: { separatorColor: border },
      },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: true, secondsVisible: false },
      localization: {
        priceFormatter: (p: number) => p.toLocaleString("en-US", { maximumFractionDigits: 6 }),
      },
    });
    chartRef.current = chart;

    const { candles, volumes } = toChartData(bars);
    const candleSeries = chart.addSeries(CandlestickSeries, {
      title: `${label} (${formatUnit(priceUnit)})`,
      upColor: "#17803d",
      borderUpColor: "#17803d",
      wickUpColor: "#17803d",
      downColor: "#b42318",
      borderDownColor: "#b42318",
      wickDownColor: "#b42318",
    });
    candleSeries.setData(candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    const volumeSeries = chart.addSeries(
      HistogramSeries,
      {
        title: `Volume (${formatUnit(volumeUnit)})`,
        color: "#6e8fbf",
        priceFormat: { type: "volume" },
      },
      1,
    );
    volumeSeries.setData(volumes.map((v) => ({ ...v, time: v.time as UTCTimestamp })));
    const panes = chart.panes();
    if (panes[1]) panes[1].setHeight(110);
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, priceUnit, volumeUnit, label]);

  return (
    <div
      ref={container}
      className="price-chart"
      role="img"
      aria-label={`${label} candlestick and volume chart, ${bars.length} bars`}
    />
  );
}
