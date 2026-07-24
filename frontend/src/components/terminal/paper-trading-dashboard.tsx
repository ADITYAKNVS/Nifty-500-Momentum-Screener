"use client";

import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3, Bot, Brain, CandlestickChart, ChevronRight, Clock3, Play, ShieldAlert, TrendingUp, Wallet, Server, Cpu, Target, Network, Layers, AlertCircle, RefreshCw, DollarSign, Zap, Info
} from "lucide-react";
import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend 
} from 'recharts';

export function PaperTradingDashboard() {
  const [mounted, setMounted] = useState(false);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [cumulative, setCumulative] = useState<any>(null);
  const [benchmark, setBenchmark] = useState<any>(null);
  const [history, setHistory] = useState<any>({ trades: [], snapshots: [] });
  
  const [tradeSymbol, setTradeSymbol] = useState("");
  const [tradeQty, setTradeQty] = useState("");
  const [tradeAction, setTradeAction] = useState<"buy"|"sell">("buy");
  const [tradeStatus, setTradeStatus] = useState("");
  
  const [selectedStrategy, setSelectedStrategy] = useState<"momentum_v2" | "ridge_pure">("momentum_v2");
  const [signalsData, setSignalsData] = useState<any>(null);
  
  const refreshData = useCallback(() => {
    const s = selectedStrategy;
    fetch(`http://localhost:8001/api/portfolio?strategy=${s}`).then(r => r.json()).then(setPortfolio).catch(console.error);
    fetch(`http://localhost:8001/api/stats?strategy=${s}`).then(r => r.json()).then(setStats).catch(console.error);
    fetch(`http://localhost:8001/api/history?strategy=${s}`).then(r => r.json()).then(setHistory).catch(console.error);
    fetch(`http://localhost:8001/api/cumulative?strategy=${s}`).then(r => r.json()).then(setCumulative).catch(console.error);
    fetch(`http://localhost:8001/api/benchmark?strategy=${s}`).then(r => r.json()).then(setBenchmark).catch(console.error);
  }, [selectedStrategy]);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Refresh all data when strategy changes or on mount
  useEffect(() => {
    if (!mounted) return;
    refreshData();
    const interval = setInterval(refreshData, 5000);
    return () => clearInterval(interval);
  }, [mounted, refreshData]);

  // Fetch signals from scanner server (port 8000)
  useEffect(() => {
    fetch(`http://localhost:8000/api/signals?strategy=${selectedStrategy}`)
      .then(r => r.json())
      .then(setSignalsData)
      .catch(console.error);
  }, [selectedStrategy]);

  const handleRecommendationClick = (ticker: string, targetShrs: number, signal: string) => {
    setTradeSymbol(ticker);
    if (targetShrs && targetShrs > 0) {
      setTradeQty(targetShrs.toString());
    } else {
      const signalObj = signalsData?.signals?.find((s: any) => s.ticker === ticker);
      const allocPct = signalObj?.allocation_pct || 22;
      const price = signalObj?.price || 1;
      const portfolioVal = portfolio?.total_value || 1000000;
      const calculatedShrs = Math.floor((portfolioVal * (allocPct / 100)) / price);
      setTradeQty(calculatedShrs > 0 ? calculatedShrs.toString() : "10");
    }
    setTradeAction("buy");
    setTradeStatus(`Selected ${ticker}. Order populated in form below.`);
    
    // Auto-scroll to order form
    const formElement = document.getElementById("order-form");
    if (formElement) {
      formElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const handleTrade = async (e: React.FormEvent) => {
    e.preventDefault();
    setTradeStatus("Processing...");
    try {
      const res = await fetch("http://localhost:8001/api/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: tradeSymbol,
          side: tradeAction,
          qty: parseFloat(tradeQty),
          strategy: selectedStrategy
        })
      });
      const data = await res.json();
      if (!res.ok) {
        setTradeStatus(`Error: ${data.detail || 'Unknown error'}`);
      } else {
        setTradeStatus(`Success: ${data.message}`);
        refreshData();
        setTradeSymbol("");
        setTradeQty("");
      }
    } catch (err: any) {
      setTradeStatus(`Error: ${err.message}`);
    }
  };

  if (!mounted) return null;

  return (
    <main className="min-h-screen bg-[#020817] text-slate-100 overflow-x-hidden">
      <div className="mx-auto max-w-[1600px] px-4 py-6 md:py-8 lg:px-6">
        
        {/* Top Section: Telemetry & Stats */}
        <section className="mb-5 grid gap-4 xl:grid-cols-[1.3fr_1fr]">
          {/* Portfolio Card */}
          <Card className="border-cyan-500/20 bg-gradient-to-br from-[#07111f] via-[#081528] to-[#0b1220] shadow-[0_0_0_1px_rgba(34,211,238,0.06)]">
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-300/70">Execution Engine</p>
                  <CardTitle className="mt-2 text-2xl">
                    {selectedStrategy === "momentum_v2" ? "Alpha Momentum V2 Telemetry" : "Ridge Regression Pure Telemetry"}
                  </CardTitle>
                  <p className="mt-3 max-w-3xl text-sm text-slate-300">
                    {selectedStrategy === "momentum_v2" 
                      ? "Live portfolio tracking synced with the SQLite execution engine. Currently routing active Momentum V2 trades."
                      : "Live portfolio tracking synced with the SQLite execution engine. Currently routing active Ridge Regression Pure trades."}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
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
                  <Badge className="border-cyan-400/30 bg-cyan-400/10 px-3 py-1 font-mono text-cyan-200 cursor-pointer hover:bg-cyan-400/20 transition-all" variant="outline" onClick={refreshData}>
                    <RefreshCw className="inline h-3 w-3 mr-1" /> Sync
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 pb-6 text-sm text-slate-300 md:grid-cols-2 lg:grid-cols-4">
              {[
                { label: "Portfolio AUM", value: portfolio ? `₹${portfolio.total_value?.toLocaleString()}` : "Loading..." },
                { label: "Available Cash", value: portfolio ? `₹${portfolio.cash?.toLocaleString()}` : "Loading..." },
                { label: "Cumulative PnL", value: cumulative ? `₹${cumulative.cumulative_pnl?.toLocaleString()} (${cumulative.cumulative_pnl_pct?.toFixed(2)}%)` : "Loading...", isCumPnl: true },
                { label: "Holdings Value", value: portfolio ? `₹${portfolio.holdings_value?.toLocaleString()}` : "Loading..." },
              ].map((item: any) => (
                <div key={item.label} className="rounded-xl border border-white/8 bg-white/4 p-3 leading-6">
                  <div className="mb-2 font-mono text-xs uppercase tracking-[0.2em] text-slate-500">
                    {item.label}
                  </div>
                  <p className={cn("font-semibold text-slate-100", item.isCumPnl && cumulative?.cumulative_pnl < 0 ? "text-rose-400" : (item.isCumPnl && cumulative?.cumulative_pnl > 0 ? "text-emerald-400" : ""))}>
                    {item.value}
                  </p>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Stats Card */}
          <Card className="border-white/10 bg-[#081120]">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Performance</p>
                  <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                    <Activity className="h-5 w-5 text-indigo-400" />
                    Trading Statistics
                  </CardTitle>
                </div>
                <Badge className={cn(
                  "px-3 py-1 font-mono text-xs uppercase",
                  selectedStrategy === "momentum_v2"
                    ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                    : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                )} variant="outline">
                  {selectedStrategy === "momentum_v2" ? "MOM V2" : "RIDGE"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Win Rate</p>
                  <p className="mt-1 font-semibold text-slate-100">{stats ? `${stats.win_rate}%` : "-"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Expectancy</p>
                  <p className="mt-1 font-semibold text-slate-100">{stats ? `₹${stats.expectancy}` : "-"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Max Drawdown (All Time)</p>
                  <p className="mt-1 font-semibold text-rose-400">{cumulative ? `₹${cumulative.max_drawdown?.toLocaleString()} (${cumulative.max_drawdown_pct?.toFixed(2)}%)` : "-"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Total Trades</p>
                  <p className="mt-1 font-semibold text-slate-100">{stats?.total_trades || 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/3 px-3 py-3 col-span-2">
                  <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-slate-500">Days Active</p>
                  <p className="mt-1 font-semibold text-cyan-300">{cumulative?.total_snapshots || 0} snapshots tracked</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* Bottom Section: Execution & Holdings */}
        <section className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
          <div className="grid gap-4">
            {/* Strategy Recommendations Card */}
            <Card className="border-white/10 bg-[#07111f]">
              <CardHeader className="pb-4 flex flex-row items-center justify-between gap-4">
                <div>
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">
                    {selectedStrategy === "momentum_v2" ? "Alpha Momentum V2" : "Ridge Regression Pure"}
                  </p>
                  <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                    <Brain className={cn("h-5 w-5", selectedStrategy === "momentum_v2" ? "text-cyan-400" : "text-indigo-400")} />
                    Active Recommendations
                  </CardTitle>
                </div>
                <div className="text-right text-xs font-mono text-slate-400">
                  <p>Spot: {signalsData?.nifty_level ? `₹${signalsData.nifty_level.toLocaleString(undefined, {maximumFractionDigits:2})}` : "Loading..."}</p>
                  <p className="mt-0.5">Date: {signalsData?.scanned_date || "—"}</p>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {signalsData?.signals?.length > 0 ? (
                  <div className="grid gap-2">
                    {signalsData.signals.slice(0, 5).map((stock: any, idx: number) => {
                      const allocPct = stock.allocation_pct || (selectedStrategy === "ridge_pure" ? 22.0 : 0.0);
                      const portfolioVal = portfolio?.total_value || 1000000;
                      const calculatedShrs = stock.target_shrs || Math.floor((portfolioVal * (allocPct / 100)) / stock.price);
                      
                      return (
                        <div 
                          key={idx} 
                          onClick={() => handleRecommendationClick(stock.ticker, calculatedShrs, stock.signal)}
                          className={cn(
                            "group flex w-full items-center justify-between rounded-xl border px-4 py-3 cursor-pointer transition-all hover:bg-white/5",
                            selectedStrategy === "momentum_v2" 
                              ? "border-cyan-500/10 hover:border-cyan-500/30" 
                              : "border-indigo-500/10 hover:border-indigo-500/30"
                          )}
                        >
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-slate-100 group-hover:text-cyan-300 transition-colors">{stock.ticker}</span>
                              <Badge className={cn(
                                "text-[10px] px-2 py-0.5", 
                                stock.signal === "BUY" || stock.signal === "NEW ENTRY" 
                                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" 
                                  : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                              )}>
                                {stock.signal}
                              </Badge>
                            </div>
                            <p className="text-xs text-slate-400 mt-1">Price: ₹{stock.price?.toLocaleString()} • Target Alloc: {allocPct}%</p>
                          </div>
                          <div className="text-right flex items-center gap-3">
                            <div>
                              <p className="font-mono text-sm text-slate-200">{calculatedShrs} shrs</p>
                              <p className="text-[10px] text-slate-500 font-mono">≈ ₹{(calculatedShrs * stock.price).toLocaleString(undefined, {maximumFractionDigits:0})}</p>
                            </div>
                            <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="py-8 text-center border border-white/5 bg-white/5 rounded-xl border-dashed">
                      <Brain className="h-6 w-6 text-slate-500 mx-auto mb-2 opacity-50" />
                      <p className="text-xs text-slate-400">No active signals found for this strategy</p>
                  </div>
                )}
                <p className="text-[11px] text-slate-500 text-center italic mt-2">
                  💡 Click any recommendation above to auto-populate the order execution form below.
                </p>
              </CardContent>
            </Card>

            {/* Execution Form */}
            <Card className="border-white/10 bg-[#07111f]">
              <CardHeader className="pb-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Direct Access</p>
                    <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                      <Target className="h-5 w-5 text-violet-300" />
                      Order Execution
                    </CardTitle>
                  </div>
                  <Badge className={cn(
                    "px-3 py-1 font-mono text-xs uppercase",
                    selectedStrategy === "momentum_v2"
                      ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                      : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                  )} variant="outline">
                    → {selectedStrategy === "momentum_v2" ? "MOM V2 BOOK" : "RIDGE BOOK"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                 <form id="order-form" onSubmit={handleTrade} className="space-y-4 max-w-lg mx-auto bg-white/5 p-6 rounded-2xl border border-white/10">
                   <div className="grid grid-cols-2 gap-4">
                     <div className="space-y-2">
                       <label className="font-mono text-xs uppercase tracking-widest text-slate-400">Ticker Symbol</label>
                       <input 
                         required
                         className="w-full bg-[#0b1220] border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-violet-500/50 transition-colors" 
                         value={tradeSymbol} 
                         onChange={e=>setTradeSymbol(e.target.value.toUpperCase())} 
                         placeholder="e.g. RELIANCE"
                       />
                     </div>
                     <div className="space-y-2">
                       <label className="font-mono text-xs uppercase tracking-widest text-slate-400">Quantity</label>
                       <input 
                         required
                         type="number"
                         min="1"
                         className="w-full bg-[#0b1220] border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-violet-500/50 transition-colors" 
                         value={tradeQty} 
                         onChange={e=>setTradeQty(e.target.value)} 
                         placeholder="Shares"
                       />
                     </div>
                   </div>
                   
                   <div className="grid grid-cols-2 gap-4 mt-6">
                     <button 
                       type="button" 
                       onClick={() => setTradeAction("buy")}
                       className={cn("px-4 py-3 rounded-xl font-bold uppercase tracking-wider transition-all", tradeAction === 'buy' ? "bg-emerald-500 text-emerald-50" : "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 hover:bg-emerald-500/20")}
                     >
                       Buy
                     </button>
                     <button 
                       type="button" 
                       onClick={() => setTradeAction("sell")}
                       className={cn("px-4 py-3 rounded-xl font-bold uppercase tracking-wider transition-all", tradeAction === 'sell' ? "bg-rose-500 text-rose-50" : "bg-rose-500/10 text-rose-500 border border-rose-500/20 hover:bg-rose-500/20")}
                     >
                       Sell
                     </button>
                   </div>
                   
                   <button type="submit" className="w-full mt-4 bg-violet-600 hover:bg-violet-500 text-white font-bold py-3 px-4 rounded-xl shadow-[0_0_15px_rgba(124,58,237,0.3)] transition-all flex items-center justify-center gap-2">
                     <Zap className="w-4 h-4" /> Execute Order
                   </button>
                   
                   {tradeStatus && (
                     <div className={cn("mt-4 p-3 rounded-lg text-sm font-mono text-center transition-all", tradeStatus.startsWith("Success") ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : tradeStatus.includes("Processing") ? "bg-blue-500/10 text-blue-400" : "bg-rose-500/10 text-rose-400 border border-rose-500/20")}>
                       {tradeStatus}
                     </div>
                   )}
                 </form>
              </CardContent>
            </Card>

            {/* Holdings view */}
            <Card className="border-white/10 bg-[#081120]">
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Live Positions</p>
                    <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                      <Wallet className="h-5 w-5 text-emerald-300" />
                      Current Holdings
                    </CardTitle>
                  </div>
                  <Badge className={cn(
                    "px-3 py-1 font-mono text-xs uppercase",
                    selectedStrategy === "momentum_v2"
                      ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                      : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                  )} variant="outline">
                    {selectedStrategy === "momentum_v2" ? "MOM V2" : "RIDGE"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {portfolio?.positions?.length > 0 ? (
                  <div className="space-y-2">
                    {portfolio.positions.map((pos: any, idx: number) => (
                      <div key={idx} className="flex w-full items-center justify-between rounded-xl border border-white/8 bg-white/3 px-4 py-3">
                        <div>
                          <p className="font-semibold text-slate-100">{pos.symbol}</p>
                          <p className="text-xs text-slate-400">Avg: ₹{pos.avg_cost} • Ltp: ₹{pos.current_price}</p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono text-sm text-slate-200">{pos.qty} shrs</p>
                          <p className={cn("font-mono text-xs", pos.unrealized_pnl >= 0 ? "text-emerald-300" : "text-rose-400")}>
                            {pos.unrealized_pnl >= 0 ? '+' : ''}₹{pos.unrealized_pnl} ({pos.unrealized_pnl_pct}%)
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-8 text-center border border-white/5 bg-white/5 rounded-xl border-dashed">
                      <Wallet className="h-6 w-6 text-slate-500 mx-auto mb-2 opacity-50" />
                      <p className="text-xs text-slate-400">No active positions</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Trade History */}
          <aside className="grid gap-4">
            <Card className="border-white/10 bg-[#081120] h-[800px] overflow-hidden flex flex-col">
              <CardHeader className="pb-3 flex-shrink-0">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">Execution Log</p>
                    <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                      <Clock3 className="h-5 w-5 text-cyan-300" />
                      Trade History
                    </CardTitle>
                  </div>
                  <Badge className={cn(
                    "px-3 py-1 font-mono text-xs uppercase",
                    selectedStrategy === "momentum_v2"
                      ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                      : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                  )} variant="outline">
                    {selectedStrategy === "momentum_v2" ? "MOM V2" : "RIDGE"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 flex-grow overflow-y-auto">
                {history?.trades?.length > 0 ? (
                  history.trades.map((trade: any, idx: number) => (
                    <div key={idx} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-xl border border-white/8 bg-white/3 px-3 py-3">
                      <div className={cn("flex h-8 w-8 items-center justify-center rounded-full border font-mono text-[10px]", trade.side === "buy" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" : "border-rose-500/20 bg-rose-500/10 text-rose-400")}>
                        {trade.side.toUpperCase().charAt(0)}
                      </div>
                      <div className="overflow-hidden">
                        <span className="font-semibold text-slate-100 truncate">{trade.symbol}</span>
                        <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                          <span>{new Date(trade.timestamp).toLocaleString()}</span>
                        </div>
                      </div>
                      <div className="text-right">
                          <p className="font-mono text-xs text-slate-100">{trade.qty} @ ₹{trade.price}</p>
                          {trade.pnl !== 0 && (
                            <p className={cn("font-mono text-[10px] mt-1", trade.pnl > 0 ? "text-emerald-400" : "text-rose-400")}>
                                {trade.pnl > 0 ? '+' : ''}₹{trade.pnl}
                            </p>
                          )}
                      </div>
                    </div>
                  ))
                ) : (
                    <div className="py-12 text-center border border-white/5 bg-white/5 rounded-xl border-dashed">
                        <Clock3 className="h-6 w-6 text-slate-500 mx-auto mb-2 opacity-50" />
                        <p className="text-xs text-slate-400">No trades recorded</p>
                    </div>
                )}
              </CardContent>
            </Card>
          </aside>
        </section>

        {/* PERFORMANCE BENCHMARK SECTION */}
        <section className="mt-8 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-300/70">Alpha Analytics</p>
              <h2 className="mt-2 text-2xl font-bold text-white">Performance Benchmark</h2>
            </div>
            <div className="flex items-center gap-3">
              <Badge className={cn(
                "px-3 py-1 font-mono text-xs uppercase",
                selectedStrategy === "momentum_v2"
                  ? "border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                  : "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
              )} variant="outline">
                {selectedStrategy === "momentum_v2" ? "Momentum V2" : "Ridge Pure"}
              </Badge>
              <Button 
                variant="outline" 
                size="sm" 
                onClick={refreshData}
                className="border-cyan-500/20 bg-cyan-500/5 text-cyan-300 hover:bg-cyan-500/10"
              >
                <RefreshCw className="mr-2 h-4 w-4" /> Sync Benchmark
              </Button>
            </div>
          </div>

          {benchmark?.error && (
             <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 flex items-center gap-3 text-rose-200">
                <AlertTriangle className="h-5 w-5 text-rose-400" />
                <p className="text-sm">{benchmark.error}</p>
             </div>
          )}

          {/* 1. Metrics Cards Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {[
              { 
                label: "Alpha", 
                value: benchmark?.metrics?.alpha != null ? `${benchmark.metrics.alpha > 0 ? '+' : ''}${benchmark.metrics.alpha}%` : "—",
                info: "How much you beat the Nifty 50",
                color: benchmark?.metrics?.alpha > 0 ? "text-emerald-400" : (benchmark?.metrics?.alpha < 0 ? "text-rose-400" : "text-slate-300")
              },
              { 
                label: "Beta", 
                value: benchmark?.metrics?.beta != null ? benchmark.metrics.beta : "—",
                info: "Your portfolio's sensitivity to market moves",
                color: benchmark?.metrics?.beta > 1.5 ? "text-amber-400" : (benchmark?.metrics?.beta >= 0.8 && benchmark?.metrics?.beta <= 1.2 ? "text-emerald-400" : "text-slate-300")
              },
              { 
                label: "Sharpe Ratio", 
                value: benchmark?.metrics?.sharpe_ratio != null && benchmark.metrics.sharpe_ratio !== -999 ? benchmark.metrics.sharpe_ratio : (benchmark?.metrics?.sharpe_ratio === -999 ? "TBD" : "—"),
                info: "Return earned per unit of risk taken (6.5% RFR)",
                color: benchmark?.metrics?.sharpe_ratio > 1 ? "text-emerald-400" : (benchmark?.metrics?.sharpe_ratio >= 0.5 ? "text-amber-400" : "text-rose-400")
              },
              { 
                label: "Max Drawdown (Port)", 
                value: benchmark?.metrics?.portfolio_max_drawdown_pct != null ? `${benchmark.metrics.portfolio_max_drawdown_pct}%` : "—",
                info: "Worst peak-to-trough loss in the period",
                color: benchmark?.metrics?.portfolio_max_drawdown_pct < -20 ? "text-rose-600" : "text-rose-400"
              },
              { 
                label: "Max Drawdown (Nifty)", 
                value: benchmark?.metrics?.nifty_max_drawdown_pct != null ? `${benchmark.metrics.nifty_max_drawdown_pct}%` : "—",
                info: "Benchmark worst peak-to-trough loss",
                color: "text-rose-400"
              }
            ].map((m, idx) => (
              <Card key={idx} className="border-white/10 bg-[#081120] p-4 flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">{m.label}</p>
                  <span title={m.info}>
                    <Info className="h-3 w-3 text-slate-600 cursor-help" />
                  </span>
                </div>
                <p className={cn("mt-2 text-2xl font-bold font-mono", m.color)}>{m.value}</p>
              </Card>
            ))}
          </div>

          {/* 2. Cumulative Performance Chart */}
          <Card className="border-white/10 bg-[#07111f] p-6">
            <CardHeader className="px-0 pt-0 pb-6 flex flex-row items-center justify-between">
               <div>
                  <CardTitle className="text-lg flex items-center gap-2 text-slate-100">
                     <TrendingUp className="h-5 w-5 text-cyan-400" />
                     Cumulative Alpha Delivery
                  </CardTitle>
                  <p className="text-xs text-slate-500 mt-1 uppercase tracking-widest font-mono">
                    {selectedStrategy === "momentum_v2" ? "Momentum V2" : "Ridge Pure"} — Normalized to ₹10.00L Starting Capital
                  </p>
               </div>
               <div className="flex items-center gap-4 text-xs font-mono">
                  <div className="flex items-center gap-2">
                     <div className={cn("h-3 w-3 rounded-full", selectedStrategy === "momentum_v2" ? "bg-cyan-500" : "bg-indigo-500")}></div>
                     <span className="text-slate-300">Portfolio</span>
                  </div>
                  <div className="flex items-center gap-2">
                     <div className="h-3 w-3 rounded-full bg-amber-500"></div>
                     <span className="text-slate-300">Nifty 50</span>
                  </div>
               </div>
            </CardHeader>
            <div className="h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={benchmark?.equity_curve || []}>
                  <defs>
                    <linearGradient id="colorPort" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={selectedStrategy === "momentum_v2" ? "#06b6d4" : "#6366f1"} stopOpacity={0.2}/>
                      <stop offset="95%" stopColor={selectedStrategy === "momentum_v2" ? "#06b6d4" : "#6366f1"} stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="colorNifty" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.1}/>
                      <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis 
                    dataKey="date" 
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }}
                    tickFormatter={(val) => {
                       const d = new Date(val);
                       return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
                    }}
                    minTickGap={30}
                  />
                  <YAxis 
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }}
                    tickFormatter={(val) => `₹${(val/100000).toFixed(1)}L`}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#0b1220', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px' }}
                    itemStyle={{ fontSize: '12px', fontFamily: 'monospace' }}
                    labelStyle={{ color: '#94a3b8', marginBottom: '4px', fontSize: '11px', fontFamily: 'monospace' }}
                    formatter={(value: any) => [`₹${value.toLocaleString()}`, ""]}
                    labelFormatter={(label) => {
                       const d = new Date(label);
                       return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' });
                    }}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="portfolio_value" 
                    stroke={selectedStrategy === "momentum_v2" ? "#06b6d4" : "#6366f1"} 
                    strokeWidth={2}
                    fillOpacity={1} 
                    fill="url(#colorPort)" 
                    name="Portfolio"
                    animationDuration={1500}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="nifty_value" 
                    stroke="#f59e0b" 
                    strokeWidth={1.5}
                    strokeDasharray="5 5"
                    fillOpacity={1} 
                    fill="url(#colorNifty)" 
                    name="Nifty 50"
                    animationDuration={2000}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* 3. Monthly Returns Table */}
          <Card className="border-white/10 bg-[#081120] overflow-hidden">
             <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center gap-2 text-slate-100">
                   <Layers className="h-5 w-5 text-indigo-400" />
                   Monthly Alpha Distribution
                </CardTitle>
             </CardHeader>
             <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                   <thead>
                      <tr className="bg-white/5 border-b border-white/10">
                         <th className="px-6 py-4 font-mono text-[10px] uppercase tracking-widest text-slate-500">Month</th>
                         <th className="px-6 py-4 font-mono text-[10px] uppercase tracking-widest text-slate-500">Portfolio Return</th>
                         <th className="px-6 py-4 font-mono text-[10px] uppercase tracking-widest text-slate-500">Nifty Return</th>
                         <th className="px-6 py-4 font-mono text-[10px] uppercase tracking-widest text-slate-500">Alpha (Spread)</th>
                      </tr>
                   </thead>
                   <tbody className="divide-y divide-white/5">
                      {benchmark?.monthly_returns?.map((row: any, idx: number) => (
                         <tr key={idx} className="hover:bg-white/2 transition-colors">
                            <td className="px-6 py-4 text-sm font-semibold text-slate-100">{row.month}</td>
                            <td className={cn("px-6 py-4 text-sm font-mono font-bold", row.portfolio_return >= 0 ? "text-emerald-400" : "text-rose-400")}>
                               {row.portfolio_return >= 0 ? '+' : ''}{row.portfolio_return}%
                            </td>
                            <td className={cn("px-6 py-4 text-sm font-mono", row.nifty_return >= 0 ? "text-emerald-400" : "text-rose-400")}>
                               {row.nifty_return >= 0 ? '+' : ''}{row.nifty_return}%
                            </td>
                            <td className={cn("px-6 py-4 text-sm font-mono font-bold", row.alpha >= 0 ? "text-emerald-400" : "text-rose-400")}>
                               {row.alpha >= 0 ? '+' : ''}{row.alpha}%
                            </td>
                         </tr>
                      ))}
                      {!benchmark?.monthly_returns?.length && (
                         <tr>
                            <td colSpan={4} className="px-6 py-12 text-center text-slate-500 italic text-sm">
                               Insufficient historical data to generate monthly attribution.
                            </td>
                         </tr>
                      )}
                   </tbody>
                </table>
             </div>
          </Card>
        </section>
      </div>
    </main>
  );
}
