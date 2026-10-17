import React from "react";
import { Compass, ShieldCheck, Box, HelpCircle } from "lucide-react";

interface AppHeaderProps {
  mockMode: boolean;
  version: string;
}

export const AppHeader: React.FC<AppHeaderProps> = ({ mockMode, version }) => {
  return (
    <header className="border-b border-border-subtle bg-background-secondary/80 backdrop-blur-md px-6 py-3.5 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Brand identity */}
        <div className="flex items-center space-x-3">
          <div className="h-10 w-10 rounded-lg bg-gradient-to-tr from-accent-violet to-accent-cyan p-0.5 flex items-center justify-center shadow-lg shadow-violet-500/10">
            <div className="h-full w-full bg-[#0b0f19] rounded-[7px] flex items-center justify-center">
              <Compass className="h-5 w-5 text-accent-cyan animate-pulse" />
            </div>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-lg font-bold tracking-tight text-white">APICompass</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                v{version}
              </span>
            </div>
            <p className="text-xs text-slate-400">Deterministic API Usage Verification</p>
          </div>
        </div>

        {/* Selected Target & Mock Mode Indicator */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Target Language Badge */}
          <div className="flex items-center space-x-1.5 px-3 py-1 rounded-md bg-slate-800/80 border border-slate-700 text-xs text-slate-200">
            <span className="h-2 w-2 rounded-full bg-blue-400"></span>
            <span className="text-slate-400 font-normal">Language:</span>
            <span className="font-semibold">Python</span>
          </div>

          {/* Target Ecosystem Badge */}
          <div className="flex items-center space-x-1.5 px-3 py-1 rounded-md bg-slate-800/80 border border-slate-700 text-xs text-slate-200">
            <Box className="h-3.5 w-3.5 text-accent-violet" />
            <span className="text-slate-400 font-normal">Ecosystem:</span>
            <span className="font-semibold">Stripe</span>
          </div>

          {/* Explicit Mock Mode Badge */}
          <div
            className={`flex items-center space-x-2 px-3 py-1 rounded-md text-xs font-medium border ${
              mockMode
                ? "bg-amber-950/40 border-amber-600/50 text-amber-300"
                : "bg-emerald-950/40 border-emerald-600/50 text-emerald-300"
            }`}
            title={mockMode ? "Running in Mock Mode with zero external API calls." : "Live retrieval mode active."}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                mockMode ? "bg-amber-400 animate-ping" : "bg-emerald-400"
              }`}
            ></span>
            <span className="font-semibold tracking-wide">
              {mockMode ? "MOCK MODE (OFFLINE FIXTURES)" : "LIVE RETRIEVAL"}
            </span>
            <HelpCircle className="h-3.5 w-3.5 text-amber-400/80 opacity-80" />
          </div>

          {/* Zero Execution Safety Badge */}
          <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-violet-950/30 border border-violet-800/40 text-[11px] text-violet-300">
            <ShieldCheck className="h-3.5 w-3.5 text-violet-400" />
            <span>Zero-Execution Guard</span>
          </div>
        </div>
      </div>
    </header>
  );
};
