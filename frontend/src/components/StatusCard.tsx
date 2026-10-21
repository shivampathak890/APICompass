import React from "react";
import { Server, RefreshCw, AlertTriangle, CheckCircle2, Shield, Info, HelpCircle } from "lucide-react";
import { ConnectionStatus, HealthResponse, ProviderLifecycleState } from "../types/health";

interface StatusCardProps {
  connectionStatus: ConnectionStatus;
  healthData: HealthResponse | null;
  error: string | null;
  lastChecked: Date | null;
  onRefresh: () => void;
  apiBaseUrl: string;
}

export const StatusCard: React.FC<StatusCardProps> = ({
  connectionStatus,
  healthData,
  error,
  lastChecked,
  onRefresh,
  apiBaseUrl,
}) => {
  const getStatusBadge = () => {
    switch (connectionStatus) {
      case "connected":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-sm">
            <CheckCircle2 className="w-3 h-3 mr-1 text-emerald-600" />
            Connected
          </span>
        );
      case "connecting":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 shadow-sm">
            <RefreshCw className="w-3 h-3 mr-1 animate-spin text-amber-600" />
            Connecting...
          </span>
        );
      case "unavailable":
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200 shadow-sm">
            <AlertTriangle className="w-3 h-3 mr-1 text-rose-600" />
            Unavailable
          </span>
        );
    }
  };

  const getProviderBadge = (name: string, state?: ProviderLifecycleState) => {
    switch (state) {
      case "configured":
        return (
          <span
            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[11px] font-mono bg-blue-50 text-[#163A6E] border border-blue-200"
            title={`${name}: Credentials are configured. Upstream connectivity and credential validity are not verified until an actual request is made.`}
          >
            <Info className="w-3 h-3 text-[#163A6E]" />
            <span>{name}: Configured (Unverified Connectivity)</span>
          </span>
        );
      case "unavailable":
        return (
          <span
            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[11px] font-mono bg-amber-50 text-amber-800 border border-amber-200"
            title={`${name}: Provider is currently unavailable due to an upstream failure or open circuit breaker. This is a retrieval limitation, not a code defect.`}
          >
            <AlertTriangle className="w-3 h-3 text-[#E26D1E]" />
            <span>{name}: Unavailable (External Limitation)</span>
          </span>
        );
      case "missing_credentials":
        return (
          <span
            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[11px] font-mono bg-slate-100 text-slate-600 border border-slate-200"
            title={`${name}: Required credentials are absent.`}
          >
            <HelpCircle className="w-3 h-3 text-slate-500" />
            <span>{name}: Missing Credentials</span>
          </span>
        );
      case "disabled":
      default:
        return (
          <span
            className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[11px] font-mono bg-slate-100 text-slate-600 border border-slate-200"
            title={`${name}: Intentionally disabled in settings.`}
          >
            <span>{name}: Disabled</span>
          </span>
        );
    }
  };

  return (
    <footer className="border-t border-slate-200 bg-white/95 backdrop-blur-md px-6 py-3 mt-auto shadow-sm">
      <div className="max-w-7xl mx-auto flex flex-col space-y-2">
        <div className="flex flex-wrap items-center justify-between text-xs text-slate-600 gap-3">
          {/* Left: Backend connection info */}
          <div className="flex items-center flex-wrap gap-4">
            <div className="flex items-center space-x-2">
              <Server className="w-4 h-4 text-slate-500" />
              <span className="text-slate-900 font-semibold">Backend API:</span>
              {getStatusBadge()}
              <code className="text-[11px] font-mono text-slate-700 bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200">
                {apiBaseUrl}
              </code>
            </div>

            {healthData && (
              <div className="hidden sm:flex items-center space-x-2 text-slate-500">
                <span>Service: <span className="text-slate-800 font-medium">{healthData.service}</span></span>
                <span>•</span>
                <span>Time (UTC): <span className="text-slate-800 font-medium">{new Date(healthData.timestamp).toLocaleTimeString()}</span></span>
              </div>
            )}

            {error && connectionStatus === "unavailable" && (
              <span className="text-rose-600 text-xs italic max-w-xs truncate" title={error}>
                {error}
              </span>
            )}
          </div>

          {/* Right: Refresh button and timestamps */}
          <div className="flex items-center space-x-4">
            {lastChecked && (
              <span className="text-slate-500 text-[11px]">
                Checked: {lastChecked.toLocaleTimeString()}
              </span>
            )}

            <button
              onClick={onRefresh}
              disabled={connectionStatus === "connecting"}
              className="flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 active:bg-slate-300 border border-slate-200 text-slate-800 text-xs font-semibold transition-all disabled:opacity-50 shadow-sm"
              title="Poll backend healthcheck"
            >
              <RefreshCw className={`w-3 h-3 ${connectionStatus === "connecting" ? "animate-spin text-[#E26D1E]" : "text-[#163A6E]"}`} />
              <span>Check Health</span>
            </button>

            <div className="flex items-center space-x-1.5 text-slate-600">
              <Shield className="w-3.5 h-3.5 text-[#E26D1E]" />
              <span className="font-semibold text-xs text-slate-800">Evidence Court Active</span>
            </div>
          </div>
        </div>

        {/* Honest Provider Status Diagnostics Banner */}
        {healthData?.provider_status && (
          <div className="pt-2 border-t border-slate-200 flex flex-wrap items-center justify-between text-[11px] text-slate-600 gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-800 font-semibold">External Providers:</span>
              {getProviderBadge("TinyFish Docs", healthData.provider_status.tinyfish)}
              {getProviderBadge("LLM Reasoning", healthData.provider_status.llm)}
            </div>
            <span className="text-[10px] text-slate-500 italic">
              "Configured" indicates credentials are set, not that upstream connectivity is verified. Provider outages are not code defects.
            </span>
          </div>
        )}
      </div>
    </footer>
  );
};
