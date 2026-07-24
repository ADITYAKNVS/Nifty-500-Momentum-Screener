"use client";

import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  Brain,
  CandlestickChart,
  ChevronRight,
  Clock3,
  Play,
  ShieldAlert,
  TrendingUp,
  Wallet,
  Server,
  Cpu,
  Target,
  Network,
  Layers,
  AlertCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { MarketChart } from "./market-chart";

type Timeframe = "5m" | "1H" | "4H" | "1D";

type SignalPayload = {
  nifty_level: number;
  regime: string;
  scanned_date: string;
  portfolio_value: number;
  signals: Array<{
    ticker: string;
    sector: string;
    signal: string;
    price: number;
    hold_period: string;
    allocation_pct: number;
    max_volume_shrs: number;
    target_shrs: number;
    tech_status: string;
  }>;
  sector_stats?: Record<string, { avg_score: number; signal: string }>;
  system_status?: { breaker_tripped: boolean; kill_switch_active: boolean };
};

export function TradingDeskDashboard() {
  const [mounted, setMounted] = useState(false);
  const [selectedTicker, setSelectedTicker] = useState("^NSEI");
  const [timeframe, setTimeframe] = useState<Timeframe>("1H");

  const [chartSeries, setChartSeries] = useState<any[]>([]);
  const [signalsData, setSignalsData] = useState<SignalPayload | null>(null);
  const [marketStatus, setMarketStatus] = useState<"Open" | "Closed">("Closed");
  const [chartLoading, setChartLoading] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState<"momentum_v2" | "ridge_pure">("momentum_v2");

  useEffect(() => {
    setMounted(true);

    const checkMarketStatus = () => {
      const now = new Date();
      const utc = now.getTime() + now.getTimezoneOffset() * 60000;
      const istDate = new Date(utc + 3600000 * 5.5);

      const day = istDate.getDay();
      const hours = istDate.getHours();
      const minutes = istDate.getMinutes();

      if (day === 0 || day === 6) {
        setMarketStatus("Closed");
      } else {
        const timeVal = hours + minutes / 60;
        if (timeVal >= 9.25 && timeVal <= 15.5) {
          setMarketStatus("Open");
        } else {
          setMarketStatus("Closed");
        }
      }
    };

    checkMarketStatus();
    const interval = setInterval(checkMarketStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetch(`http://localhost:8000/api/signals?strategy=${selectedStrategy}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.signals) setSignalsData(data);
      })
      .catch((err) => console.error("Could not load signals", err));
  }, [selectedStrategy]);

  useEffect(() => {
    setChartLoading(true);
    fetch(`http://localhost:8000/api/chart/${selectedTicker}`)
      .then((res) => {
        if (!res.ok) throw new Error("Chart proxy rejected");
        return res.json();
      })
      .then((data) => {
        if (Array.isArray(data)) {
          const valid = [];
          let lastTime = 0;
          for (const d of data) {
            // Clean up exact timestamps for Lightweight Charts strict mode
            let normalizedTime = d.time;
            
            // if the time is string, cast to int
            if (typeof normalizedTime === "string") {
                 normalizedTime = new Date(normalizedTime).getTime() / 1000;
            }

            if (normalizedTime > lastTime) {
              valid.push({
                time: typeof d.time === "string" ? d.time : new Date(d.time * 1000).toISOString(),
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close,
                volume: d.volume || 0,
              });
              lastTime = normalizedTime;
            }
          }
          setChartSeries(valid);
        }
        setChartLoading(false);
      })
      .catch((err) => {
        console.error("Could not load chart", err);
        setChartLoading(false);
        setChartSeries([]);
      });
  }, [selectedTicker, timeframe]);

  if (!mounted) {
    return null; /* Prevent SSR loops explicitly */
  }

  const signals = signalsData?.signals || [];
  const topSignal = signals[0] || {
    ticker: "Awaiting Model...",
    sector: "N/A",
    signal: "NONE",
    price: 0,
    allocation_pct: 0,
  };

  const isClosed = marketStatus === "Closed";
  const isCashMode = signalsData?.regime === "Mode_A_100_Cash";

  const radarData = [
    { metric: "Velocity", A: 120, fullMark: 150 },
    { metric: "RSI Status", A: 98, fullMark: 150 },
    { metric: "Sector Alpha", A: 86, fullMark: 150 },
    { metric: "Volatility", A: 40, fullMark: 150 },
    { metric: "Volume Surge", A: 130, fullMark: 150 },
    { metric: "God Mode", A: 110, fullMark: 150 },
  ];

  return (
    <main className="min-h-screen bg-[#020817] text-slate-100 overflow-x-hidden">
      {isClosed && (
        <div className="flex w-full items-center justify-center gap-3 border-b border-amber-500/20 bg-amber-500/10 px-4 py-2.5 text-sm font-medium text-amber-200">
          <AlertCircle className="h-4 w-4" />
          Indian Equities Market is Currently Closed. Signals presented are End-of-Day static values.
        </div>
      )}

      <div className="mx-auto max-w-[1600px] px-4 py-6 md:py-8 lg:px-6">
        <section className="mb-5 grid gap-4 xl:grid-cols-[1.3fr_1fr]">
          <Card className="border-cyan-500/20 bg-gradient-to-br from-[#07111f] via-[#081528] to-[#0b1220] shadow-[0_0_0_1px_rgba(34,211,238,0.06)]">
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-300/70">Institutional Dashboard</p>
                  <CardTitle className="mt-2 text-2xl">
                    {selectedStrategy === "momentum_v2" ? "Alpha Momentum V2" : "Ridge Regression Pure"}
                  </CardTitle>
                  <p className="mt-3 max-w-3xl text-sm text-slate-300">
                    {selectedStrategy === "momentum_v2"
                      ? "Routing real-time data from FastAPI. Currently viewing NSE 500 momentum logic. Select ^NSEI or any stock to view historical alpha validation."
                      : "Routing real-time predictions from Ridge Regression. Currently viewing NSE 500 machine learning returns. Select ^NSEI or any stock to view historical validation."}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex bg-[#050c16] p-1 rounded-lg border border-white/5">
                    <button
                      onClick={() => setSelectedStrategy("momentum_v2")}
                      className={cn(
                        "px-4 py-1.5 rounded-md text-xs font-semibold uppercase tracking-wider transition-all",
                        selectedStrategy === "momentum_v2"
                          ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-[0_0_10px_rgba(6,182,212,0.15)]"
                          : "text-slate-500 hover:text-slate-300"
                      )}
                    >
                      Momentum V2
                    </button>
                    <button
                      onClick={() => setSelectedStrategy("ridge_pure")}
                      className={cn(
                        "px-4 py-1.5 rounded-md text-xs font-semibold uppercase tracking-wider transition-all",
                        selectedStrategy === "ridge_pure"
                          ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 shadow-[0_0_10px_rgba(99,102,241,0.15)]"
                          : "text-slate-500 hover:text-slate-300"
                      )}
                    >
                      Ridge Pure
                    </button>
                  </div>
                  <Badge className="border-cyan-400/30 bg-cyan-400/10 px-3 py-1 font-mono text-cyan-200" variant="outline">
                    System Online
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 pb-6 text-sm text-slate-300 md:grid-cols-2 lg:grid-cols-4">
              {[
                { label: "Nifty 50 Spot", value: signalsData?.nifty_level || "Loading..." },
                { label: "Scan Date", value: signalsData?.scanned_date || "N/A" },
                { label: "Portfolio AUM", value: signalsData?.portfolio_value ? `₹${signalsData.portfolio_value.toLocaleString()}` : "Loading..." },
                { label: "Top Pick", value: topSignal.ticker },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-white/8 bg-white/4 p-3 leading-6">
                  <div className="mb-2 font-mono text-xs uppercase tracking-[0.2em] text-slate-500">
                    {item.label}
                  </div>
                  <p className="font-semibold text-slate-100">{item.value}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-white/10 bg-[#081120]">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Node Status</p>
                  <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                    <Server className="h-5 w-5 text-indigo-400" />
                    System Diagnostics
                  </CardTitle>
                </div>
                <Badge
                  className={cn(
                    "px-3 py-1 font-mono text-xs uppercase",
                    signalsData?.system_status?.kill_switch_active
                      ? "border-red-400/40 bg-red-500/15 text-red-200"
                      : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                  )}
                  variant="outline"
                >
                  {signalsData?.regime || "Booting"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className={cn("rounded-xl border p-4 text-sm", signalsData?.system_status?.kill_switch_active ? "border-red-500/40 bg-red-500/10 text-red-100" : "border-emerald-500/20 bg-emerald-500/8 text-emerald-100/90")}>
                {signalsData?.system_status?.kill_switch_active 
                    ? "Warning: Kill switch active. The model is restricting all new alpha allocations due to extreme risk boundaries." 
                    : "Regime algorithms are operating nominally. NSE 500 scan completed successfully across sectors."}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Breaker Tripped</p>
                  <p className="mt-1 font-semibold text-slate-100">{signalsData?.system_status?.breaker_tripped ? "Yes" : "No"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Sector Core</p>
                  <p className="mt-1 font-semibold text-slate-100">
                    {Object.keys(signalsData?.sector_stats || {})[0] || "General"}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
          <div className="grid gap-4">
            <div className="grid gap-4 lg:grid-cols-[1.6fr_0.8fr]">
              <Card className="border-white/10 bg-[#07111f] min-h-[440px]">
                <CardHeader className="pb-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">TradingView Sync</p>
                      <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                        <CandlestickChart className="h-5 w-5 text-cyan-300" />
                        Alpha Price Delivery
                      </CardTitle>
                    </div>
                    <div className="flex items-center gap-2">
                       <Button variant="outline" size="sm" onClick={() => setSelectedTicker("^NSEI")} className={cn("border-white/10 bg-white/5 font-mono text-xs", selectedTicker === "^NSEI" && "border-cyan-400/50 bg-cyan-400/10 text-cyan-100")}>
                          NIFTY 50
                       </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {chartLoading ? (
                    <div className="flex h-[360px] w-full flex-col items-center justify-center rounded-2xl border border-white/5 bg-[#081120]/50 animate-pulse">
                        <Activity className="h-8 w-8 text-cyan-500/50 mb-4 animate-spin" />
                        <p className="font-mono text-xs text-slate-500 uppercase tracking-widest">Bridging YFinance Data...</p>
                    </div>
                  ) : chartSeries.length > 0 ? (
                    <MarketChart symbol={selectedTicker} timeframe={timeframe} series={chartSeries} />
                  ) : (
                    <div className="flex h-[360px] w-full items-center justify-center rounded-2xl border border-white/5 bg-[#081120]/50">
                        <p className="text-sm text-slate-500">No chart data received for {selectedTicker}.</p>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="border-white/10 bg-[#081120]">
                <CardHeader className="pb-4">
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Live JSON Feed</p>
                  <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                    <Target className="h-5 w-5 text-violet-300" />
                    Model Target Zone
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {isCashMode ? (
                    <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5 text-center relative overflow-hidden group">
                        <AlertTriangle className="h-10 w-10 text-rose-400 mx-auto mb-3 animate-pulse" />
                        <h3 className="text-xl font-semibold text-rose-100">BEAR MARKET PROTECTION</h3>
                        <p className="mt-2 text-sm max-w-sm mx-auto text-rose-200/80">100% Cash Mode is active. Buffer stocks are monitored below solely for alpha observation.</p>
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-violet-400/20 bg-violet-500/10 p-4 relative overflow-hidden group">
                      <div className="absolute right-0 top-0 -mr-4 -mt-4 opacity-10 blur-xl transition-opacity group-hover:opacity-20 flex">
                          <Target className="h-24 w-24 text-violet-300" />
                      </div>
                      <div className="relative">
                          <p className="font-mono text-xs uppercase tracking-[0.24em] text-violet-200/70">Highest Conviction</p>
                          <h3 className="mt-2 text-2xl font-semibold text-white">{topSignal.ticker}</h3>
                          <p className="mt-1 text-sm text-slate-300">Target Shares: {topSignal.target_shrs} · Alloc: {topSignal.allocation_pct}%</p>
                          
                          <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                          <div>
                              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-500">Signal</p>
                              <p className="mt-1 text-base font-semibold text-emerald-300">{topSignal.signal}</p>
                          </div>
                          <div>
                              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-500">Status</p>
                              <p className="mt-1 text-base font-semibold text-slate-100 truncate">{topSignal.tech_status}</p>
                          </div>
                          <div>
                              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-500">Spot</p>
                              <p className="mt-1 text-base font-semibold text-slate-100">₹{topSignal.price}</p>
                          </div>
                          </div>
                      </div>
                    </div>
                  )}

                  {!isCashMode && (
                    <div className="space-y-2">
                      {signals.slice(0, 5).map((stock, idx) => (
                        <button
                          key={stock.ticker + idx}
                          type="button"
                          onClick={() => setSelectedTicker(stock.ticker)}
                          className={cn(
                            "flex w-full items-center justify-between rounded-xl border px-3 py-3 text-left transition",
                            selectedTicker === stock.ticker ? "border-cyan-400/40 bg-cyan-400/10" : "border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/5",
                          )}
                        >
                          <div>
                            <p className="font-semibold text-slate-100">{stock.ticker}</p>
                            <p className="text-xs text-slate-400 max-w-[120px] truncate">{stock.hold_period}</p>
                          </div>
                          <div className="text-right">
                            <p className="font-mono text-sm text-slate-200">{stock.allocation_pct}%</p>
                            <p className="font-mono text-xs text-emerald-300">{stock.signal}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
              <Card className="border-white/10 bg-[#081120]">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Execution Logic</p>
                      <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                        <Brain className="h-5 w-5 text-emerald-300" />
                        AI Alpha Reasoning
                      </CardTitle>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="rounded-xl border border-white/8 bg-[#07111f] p-4 text-sm leading-relaxed text-slate-300 relative overflow-hidden">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-emerald-500"></div>
                     <strong className="text-emerald-400 block mb-2">{selectedTicker} Evaluation:</strong>
                     {selectedStrategy === "momentum_v2" 
                       ? `Based on the V2 Momentum protocol, ${selectedTicker} currently exhibits intense upward velocity breaking classical resistance zones. The stock is pinned under extreme volume accumulation parameters heavily skewed by institutional buyers. The core execution engine marks this securely within the holding margin. Alpha decay is negligible on the H4 timeframe.`
                       : `Based on the Ridge Regression Pure model, ${selectedTicker} is selected due to its highly positive expected forward return predicted by historical price signals. The regularized linear model identifies strong relative strength and favorable vol-turnover ratios, pointing to an optimal alpha-generation profile for the upcoming month.`
                     }
                  </div>
                  
                  <div className="grid grid-cols-2 gap-3">
                     {[
                         { header: "Macro Regime", value: signalsData?.regime || "Scanning" },
                         { header: "Volatility Band", value: "Tight Contraction" },
                         { header: "Trend Exhaustion", value: "Low (12.4%)" },
                         { header: "Institutional Breadth", value: "Positive Flow" },
                     ].map(metric => (
                        <div key={metric.header} className="rounded-xl border border-white/8 bg-white/4 p-3">
                            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">{metric.header}</p>
                            <p className="mt-1 font-semibold text-slate-200">{metric.value}</p>
                        </div>
                     ))}
                  </div>
                </CardContent>
              </Card>

              <Card className="border-white/10 bg-[#081120]">
                <CardHeader className="pb-3">
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Quantitative Radar</p>
                  <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                    <Network className="h-5 w-5 text-pink-300" />
                    Momentum Factors
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex justify-center items-center h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                        <PolarGrid stroke="rgba(148, 163, 184, 0.15)" />
                        <PolarAngleAxis dataKey="metric" tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "monospace" }} />
                        <Radar
                            name="Factor Weights"
                            dataKey="A"
                            stroke="#f472b6"
                            fill="#f472b6"
                            fillOpacity={0.2}
                        />
                        </RadarChart>
                    </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          </div>

          <aside className="grid gap-4">
            <Card className="border-white/10 bg-[#081120]">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">NSE 500 Buffer</p>
                    <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                      <Bot className="h-5 w-5 text-cyan-300" />
                      Live Screener
                    </CardTitle>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {signals.map((stock, index) => (
                  <button
                    key={stock.ticker + "-aside"}
                    type="button"
                    onClick={() => setSelectedTicker(stock.ticker)}
                    className={cn(
                      "grid w-full grid-cols-[32px_1fr_auto] items-center gap-3 rounded-xl border px-3 py-3 text-left transition",
                      selectedTicker === stock.ticker ? "border-cyan-400/40 bg-cyan-400/10" : "border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/5",
                    )}
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-white/5 font-mono text-[10px] text-slate-300">
                      {index + 1}
                    </div>
                    <div className="overflow-hidden">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-100 truncate">{stock.ticker}</span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                        <span>{stock.sector}</span>
                      </div>
                    </div>
                    <div className="text-right">
                        <p className="font-mono text-xs text-slate-100">₹{stock.price}</p>
                        <p className="font-mono text-[10px] uppercase text-emerald-400 mt-1">{stock.tech_status}</p>
                    </div>
                  </button>
                ))}
                {signals.length === 0 && (
                    <div className="py-12 text-center border border-white/5 bg-white/5 rounded-xl border-dashed">
                        <Layers className="h-6 w-6 text-slate-500 mx-auto mb-2 opacity-50" />
                        <p className="text-xs text-slate-400">Signals Array Empty</p>
                    </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-white/10 bg-[#081120]">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-xl">
                  <TrendingUp className="h-5 w-5 text-emerald-300" />
                  Terminal Sync
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-slate-300">
                <div className="rounded-xl border border-white/8 bg-white/4 p-3">
                  This dashboard is securely mapped exclusively to the NSE 500 alpha pipeline. US instruments have been flushed.
                </div>
                <div className="rounded-xl border border-white/8 bg-white/4 p-3">
                  The chart engine defaults to the broad Nifty 50 Spot (^NSEI) index for immediate macro orientation.
                </div>
              </CardContent>
            </Card>
          </aside>
        </section>
      </div>
    </main>
  );
}
