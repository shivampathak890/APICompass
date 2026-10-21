import React from "react";
import { ShieldCheck, Box, HelpCircle } from "lucide-react";

interface AppHeaderProps {
  mockMode: boolean;
  version: string;
}

export const AppHeader: React.FC<AppHeaderProps> = ({ mockMode, version }) => {
  return (
    <header className="border-b border-slate-200 bg-white/95 backdrop-blur-md px-6 py-3 sticky top-0 z-50 shadow-sm">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Brand identity: New Clean Logo & Typography */}
        <div className="flex items-center space-x-3">
          <img
            src="/logo.jpg"
            alt="APICompass Logo"
            className="h-10 w-10 object-contain rounded-xl border border-slate-200 bg-white shadow-sm p-0.5"
          />
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-sans text-xl font-bold tracking-tight drop-shadow-sm">
                <span className="text-[#163A6E]">API</span>
                <span className="text-[#E26D1E]">Compass</span>
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 border border-slate-200">
                v{version}
              </span>
            </div>
            <p className="text-xs text-slate-500 font-medium">
              Deterministic API Contract Verification
            </p>
          </div>
        </div>

        {/* Selected Target & Mock Mode Indicator */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Target Language Badge */}
          <div className="flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 shadow-sm">
            <span className="h-2 w-2 rounded-full bg-[#163A6E]"></span>
            <span className="text-slate-500 font-normal">Language:</span>
            <span className="font-semibold text-slate-900">Python</span>
          </div>

          {/* Target Ecosystem Badge */}
          <div className="flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 shadow-sm">
            <Box className="h-3.5 w-3.5 text-[#163A6E]" />
            <span className="text-slate-500 font-normal">Ecosystem:</span>
            <span className="font-semibold text-slate-900">Stripe</span>
          </div>

          {/* Explicit Mock Mode Badge - Warm Orange Accent */}
          <div
            className={`flex items-center space-x-2 px-3 py-1 rounded-lg text-xs font-medium border shadow-sm transition-all ${
              mockMode
                ? "bg-amber-50 border-amber-200 text-amber-800"
                : "bg-blue-50 border-blue-200 text-[#163A6E]"
            }`}
            title={mockMode ? "Running in Mock Mode with zero external API calls." : "Live retrieval mode active."}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                mockMode ? "bg-[#E26D1E] animate-ping" : "bg-[#163A6E]"
              }`}
            ></span>
            <span className="font-semibold tracking-wide">
              {mockMode ? "MOCK MODE (OFFLINE FIXTURES)" : "LIVE RETRIEVAL"}
            </span>
            <HelpCircle className="h-3.5 w-3.5 opacity-80 text-current" />
          </div>

          {/* Zero Execution Safety Badge */}
          <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-slate-50 border border-slate-200 text-[11px] text-slate-600 shadow-sm">
            <ShieldCheck className="h-3.5 w-3.5 text-[#E26D1E]" />
            <span>Zero-Execution Guard</span>
          </div>
        </div>
      </div>
    </header>
  );
};
