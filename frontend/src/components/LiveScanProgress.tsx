import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Terminal,
  Layers,
  Search,
  BookOpen,
  Scale,
  Database,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { ScanProgressEvent, ScanStage } from "../types/stream";

interface LiveScanProgressProps {
  currentEvent: ScanProgressEvent | null;
  isAnalyzing: boolean;
  error: string | null;
  onRetry?: () => void;
  onCancel?: () => void;
  onRetryNonStreaming?: () => void;
}

interface StepConfig {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  matches: (stage: ScanStage) => "completed" | "active" | "pending";
}

const STEPS: StepConfig[] = [
  {
    id: "accepted",
    label: "Accepted",
    icon: Terminal,
    matches: (stage) => (stage === "accepted" ? "active" : "completed"),
  },
  {
    id: "ast",
    label: "Static AST",
    icon: Layers,
    matches: (stage) => {
      if (stage === "accepted") return "pending";
      if (stage === "static_analysis_started") return "active";
      return "completed";
    },
  },
  {
    id: "search",
    label: "Doc Search",
    icon: Search,
    matches: (stage) => {
      if (
        ["accepted", "static_analysis_started", "static_analysis_completed", "ai_reasoning_started", "ai_reasoning_completed"].includes(stage)
      ) {
        return "pending";
      }
      if (stage === "doc_search_started" || stage === "documentation_retrieval_started") return "active";
      return "completed";
    },
  },
  {
    id: "fetch",
    label: "Doc Fetch",
    icon: BookOpen,
    matches: (stage) => {
      if (
        [
          "accepted",
          "static_analysis_started",
          "static_analysis_completed",
          "ai_reasoning_started",
          "ai_reasoning_completed",
          "documentation_retrieval_started",
          "doc_search_started",
          "doc_search_completed",
        ].includes(stage)
      ) {
        return "pending";
      }
      if (stage === "doc_fetch_started") return "active";
      return "completed";
    },
  },
  {
    id: "court",
    label: "Evidence Court",
    icon: Scale,
    matches: (stage) => {
      if (
        [
          "accepted",
          "static_analysis_started",
          "static_analysis_completed",
          "ai_reasoning_started",
          "ai_reasoning_completed",
          "documentation_retrieval_started",
          "doc_search_started",
          "doc_search_completed",
          "doc_fetch_started",
          "doc_fetch_completed",
          "documentation_retrieval_completed",
        ].includes(stage)
      ) {
        return "pending";
      }
      if (stage === "evidence_verification_started") return "active";
      return "completed";
    },
  },
  {
    id: "persistence",
    label: "Persistence",
    icon: Database,
    matches: (stage) => {
      if (stage === "persistence_started") return "active";
      if (["persistence_completed", "completed"].includes(stage)) return "completed";
      return "pending";
    },
  },
];

export const LiveScanProgress: React.FC<LiveScanProgressProps> = ({
  currentEvent,
  isAnalyzing,
  error,
  onRetry,
  onCancel,
  onRetryNonStreaming,
}) => {
  const stage = currentEvent?.stage || "accepted";
  const percent = currentEvent?.progress_percent;
  const isStreamingInterrupted =
    error &&
    (error.toLowerCase().includes("streaming") ||
      error.toLowerCase().includes("stream ended") ||
      error.toLowerCase().includes("interrupted"));

  return (
    <div
      className="rounded-2xl border border-slate-200 bg-white shadow-md p-5 space-y-4"
      aria-live="polite"
      role="status"
      data-testid="live-scan-progress"
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-200">
        <div className="flex items-center space-x-2.5">
          {isAnalyzing ? (
            <RefreshCw className="w-4 h-4 text-[#163A6E] animate-spin" />
          ) : error ? (
            <AlertTriangle className="w-4 h-4 text-amber-600" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          )}
          <span className="font-serif text-sm font-semibold tracking-wide text-slate-900">
            {isAnalyzing
              ? "Live Verification in Progress"
              : error
              ? "Scan Interrupted"
              : "Verification Complete"}
          </span>
        </div>
        <div className="flex items-center space-x-3">
          {percent != null && (
            <span className="text-xs font-mono font-bold text-[#E26D1E] bg-orange-50 px-2 py-0.5 rounded border border-orange-200">
              {percent}%
            </span>
          )}
          {isAnalyzing && onCancel && (
            <button
              onClick={onCancel}
              data-testid="progress-cancel-button"
              className="px-2.5 py-1 text-[11px] font-semibold bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-lg transition-colors flex items-center space-x-1"
              title="Cancel current analysis"
            >
              <XCircle className="w-3.5 h-3.5 text-rose-600" />
              <span>Cancel</span>
            </button>
          )}
        </div>
      </div>

      {/* Brand Compass Gradient Progress Bar */}
      <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden border border-slate-200">
        {percent != null ? (
          <div
            className="bg-gradient-to-r from-[#163A6E] via-[#2563EB] to-[#E26D1E] h-2 transition-all duration-300 ease-out"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="h-2 w-full bg-slate-100 relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-[#163A6E]/30 to-transparent animate-shimmer" />
          </div>
        )}
      </div>

      {/* Current Stage Message */}
      <div className="flex items-start space-x-3 bg-slate-50 border border-slate-200 rounded-xl p-3.5 shadow-xs">
        <div className="mt-0.5">
          <Terminal className="w-4 h-4 text-[#163A6E]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-mono text-slate-600 uppercase tracking-wider flex items-center space-x-1.5">
            <span>Stage:</span>
            <span className="text-[#E26D1E] font-bold">{stage}</span>
          </div>
          <p className="text-xs text-slate-800 mt-0.5 leading-relaxed break-words font-sans">
            {currentEvent?.message || "Initializing verification pipeline..."}
          </p>
        </div>
      </div>

      {/* Checkpoints Timeline (6 steps) */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 pt-1">
        {STEPS.map((step) => {
          const state = currentEvent ? step.matches(stage) : "pending";
          const Icon = step.icon;

          return (
            <div
              key={step.id}
              className={`flex flex-col items-center text-center p-2 rounded-xl border text-[11px] transition-all ${
                state === "completed"
                  ? "bg-blue-50/80 border-blue-200 text-[#163A6E]"
                  : state === "active"
                  ? "bg-orange-50 border-[#E26D1E]/60 text-[#E26D1E] ring-1 ring-[#E26D1E]/30 shadow-xs"
                  : "bg-slate-50 border-slate-200 text-slate-400"
              }`}
            >
              <div className="mb-1">
                {state === "completed" ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#163A6E]" />
                ) : state === "active" ? (
                  <RefreshCw className="w-3.5 h-3.5 text-[#E26D1E] animate-spin" />
                ) : (
                  <Icon className="w-3.5 h-3.5 text-slate-400" />
                )}
              </div>
              <span className="font-medium truncate max-w-full">{step.label}</span>
            </div>
          );
        })}
      </div>

      {/* Error & Recovery Banner */}
      {error && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-800">
          <div className="flex items-start space-x-2.5">
            <ShieldAlert className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-rose-900">{error}</p>
              <p className="text-[11px] text-rose-700 mt-0.5">
                {isStreamingInterrupted
                  ? "The real-time event stream was interrupted. You can retry with standard non-streaming analysis."
                  : "Scan interrupted. Retrying will initiate a new verification scan with a distinct audit record."}
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            {isStreamingInterrupted && onRetryNonStreaming && (
              <button
                onClick={onRetryNonStreaming}
                disabled={isAnalyzing}
                data-testid="retry-non-streaming-button"
                className="px-3 py-1 bg-[#163A6E] hover:bg-[#0f284e] text-white rounded-lg text-xs font-semibold transition-colors shadow-sm"
              >
                Use Standard (Non-Streaming) Analysis
              </button>
            )}
            {onRetry && (
              <button
                onClick={onRetry}
                disabled={isAnalyzing}
                className="px-3 py-1 bg-rose-100 hover:bg-rose-200 text-rose-800 rounded-lg border border-rose-300 text-xs font-medium transition-colors"
              >
                Retry Streaming Scan
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
