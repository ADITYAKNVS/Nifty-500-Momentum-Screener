"use client";

import { createChart, CandlestickData, ColorType, HistogramData, IChartApi, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

type Timeframe = "5m" | "1H" | "4H" | "1D";

type MarketChartProps = {
  symbol: string;
  timeframe: Timeframe;
  series: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
};

function toTimestamp(value: string) {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

export function MarketChart({ symbol, timeframe, series }: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const candleData = useMemo<CandlestickData[]>(() => {
    return series.map((point) => ({
      time: toTimestamp(point.time),
      open: point.open,
      high: point.high,
      low: point.low,
      close: point.close,
    }));
  }, [series]);

  const volumeData = useMemo<HistogramData[]>(() => {
    return series.map((point) => ({
      time: toTimestamp(point.time),
      value: point.volume,
      color: point.close >= point.open ? "rgba(34,197,94,0.45)" : "rgba(248,113,113,0.45)",
    }));
  }, [series]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#07111f" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.08)" },
        horzLines: { color: "rgba(148,163,184,0.08)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148,163,184,0.12)",
      },
      timeScale: {
        borderColor: "rgba(148,163,184,0.12)",
        timeVisible: timeframe !== "1D",
      },
      crosshair: {
        vertLine: { color: "rgba(56,189,248,0.35)" },
        horzLine: { color: "rgba(56,189,248,0.35)" },
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#f87171",
      priceLineVisible: true,
      lastValueVisible: true,
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });

    candlestickSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candleData, timeframe, volumeData]);

  return (
    <div className="flex h-full min-h-[320px] flex-col rounded-2xl border border-white/10 bg-[#07111f]">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.24em] text-slate-500">Market Structure</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-100">
            {symbol} · {timeframe}
          </h3>
        </div>
        <div className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 font-mono text-xs text-emerald-300">
          Lightweight Charts
        </div>
      </div>
      <div ref={containerRef} className="h-[360px] w-full" />
    </div>
  );
}
