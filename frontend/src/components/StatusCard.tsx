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
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-700/50">
            <CheckCircle2 className="w-3 h-3 mr-1" />
            Connected
          </span>
        );
      case "connecting":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-cyan-950/60 text-cyan-400 border border-cyan-700/50">
            <RefreshCw className="w-3 h-3 mr-1 animate-spin" />
            Connecting...
          </span>
        );
      case "unavailable":
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-rose-950/60 text-rose-400 border border-rose-700/50">
            <AlertTriangle className="w-3 h-3 mr-1" />
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
            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[11px] font-mono bg-cyan-950/60 text-cyan-300 border border-cyan-800/60"
            title={`${name}: Credentials are configured. Upstream connectivity and credential validity are not verified until an actual request is made.`}
          >
            <Info className="w-3 h-3 text-cyan-400" />
            <span>{name}: Configured (Unverified Connectivity)</span>
          </span>
        );
      case "unavailable":
        return (
          <span
            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[11px] font-mono bg-amber-950/60 text-amber-300 border border-amber-800/60"
            title={`${name}: Provider is currently unavailable due to an upstream failure or open circuit breaker. This is a retrieval limitation, not a code defect.`}
          >
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            <span>{name}: Unavailable (External Limitation)</span>
          </span>
        );
      case "missing_credentials":
        return (
          <span
            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[11px] font-mono bg-slate-800/80 text-slate-400 border border-slate-700"
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
            className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[11px] font-mono bg-slate-800/60 text-slate-400 border border-slate-700/60"
            title={`${name}: Intentionally disabled in settings.`}
          >
            <span>{name}: Disabled</span>
          </span>
        );
    }
  };

  return (
    <footer className="border-t border-border-subtle bg-background-secondary/90 px-6 py-3 mt-auto">
      <div className="max-w-7xl mx-auto flex flex-col space-y-2">
        <div className="flex flex-wrap items-center justify-between text-xs text-slate-400 gap-3">
          {/* Left: Backend connection info */}
          <div className="flex items-center flex-wrap gap-4">
            <div className="flex items-center space-x-2">
              <Server className="w-4 h-4 text-slate-400" />
              <span className="text-slate-300 font-medium">Backend API:</span>
              {getStatusBadge()}
              <code className="text-[11px] font-mono text-slate-400 bg-slate-800/80 px-1.5 py-0.5 rounded border border-slate-700">
                {apiBaseUrl}
              </code>
            </div>

            {healthData && (
              <div className="hidden sm:flex items-center space-x-2 text-slate-400">
                <span>Service: <span className="text-slate-200">{healthData.service}</span></span>
                <span>•</span>
                <span>Time (UTC): <span className="text-slate-200">{new Date(healthData.timestamp).toLocaleTimeString()}</span></span>
              </div>
            )}

            {error && connectionStatus === "unavailable" && (
              <span className="text-rose-400 text-xs italic max-w-xs truncate" title={error}>
                {error}
              </span>
            )}
          </div>

          {/* Right: Refresh button and timestamps */}
          <div className="flex items-center space-x-4">
            {lastChecked && (
              <span className="text-slate-400 text-[11px]">
                Checked: {lastChecked.toLocaleTimeString()}
              </span>
            )}

            <button
              onClick={onRefresh}
              disabled={connectionStatus === "connecting"}
              className="flex items-center space-x-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 active:bg-slate-900 border border-slate-700 text-slate-300 transition-colors disabled:opacity-50"
              title="Poll backend healthcheck"
            >
              <RefreshCw className={`w-3 h-3 ${connectionStatus === "connecting" ? "animate-spin" : ""}`} />
              <span>Check Health</span>
            </button>

            <div className="flex items-center space-x-1 text-slate-400">
              <Shield className="w-3.5 h-3.5 text-accent-cyan" />
              <span>Evidence Court Active</span>
            </div>
          </div>
        </div>

        {/* Honest Provider Status Diagnostics Banner */}
        {healthData?.provider_status && (
          <div className="pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] text-slate-400 gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-400 font-semibold">External Providers:</span>
              {getProviderBadge("TinyFish Docs", healthData.provider_status.tinyfish)}
              {getProviderBadge("LLM Reasoning", healthData.provider_status.llm)}
            </div>
            <span className="text-[10px] text-slate-400 italic">
              "Configured" indicates credentials are set, not that upstream connectivity is verified. Provider outages are not code defects.
            </span>
          </div>
        )}
      </div>
    </footer>
  );
};
