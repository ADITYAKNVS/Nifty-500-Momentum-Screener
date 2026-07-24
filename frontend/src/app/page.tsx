"use client";

import { useState } from "react";
import { TradingDeskDashboard } from "@/components/terminal/trading-desk-dashboard";
import { PaperTradingDashboard } from "@/components/terminal/paper-trading-dashboard";

export default function Home() {
  const [activeTab, setActiveTab] = useState<"analysis" | "trading">("analysis");

  return (
    <div className="min-h-screen bg-[#020817] flex flex-col">
      {/* Top Navigation Toggle */}
      <div className="border-b border-white/10 bg-[#081120] px-6 py-4 flex items-center justify-between shadow-[0_1px_15px_rgba(34,211,238,0.05)]">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 shadow-lg shadow-cyan-500/20">
             <span className="font-bold text-white text-xs">PW</span>
          </div>
          <h1 className="text-lg font-bold text-white tracking-wide">PrismWall<span className="text-cyan-400 font-light ml-1">Terminal</span></h1>
        </div>
        
        <div className="flex bg-[#07111f] p-1.5 rounded-xl border border-white/10 shadow-inner">
          <button
            onClick={() => setActiveTab("analysis")}
            className={`px-8 py-2 rounded-lg text-sm font-bold tracking-wide transition-all ${
              activeTab === "analysis" 
                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 shadow-[0_0_10px_rgba(99,102,241,0.15)]" 
                : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
            }`}
          >
            ANALYSIS
          </button>
          <button
            onClick={() => setActiveTab("trading")}
            className={`px-8 py-2 rounded-lg text-sm font-bold tracking-wide transition-all ${
              activeTab === "trading" 
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-[0_0_10px_rgba(16,185,129,0.15)]" 
                : "text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent"
            }`}
          >
            TRADING
          </button>
        </div>
        
        <div className="w-8"></div> {/* Spacer to center the tabs if needed, or leave for other icons */}
      </div>

      <div className="flex-1">
        {activeTab === "analysis" ? <TradingDeskDashboard /> : <PaperTradingDashboard />}
      </div>
    </div>
  );
}
