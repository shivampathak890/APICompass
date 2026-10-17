import React, { useState, useRef } from "react";
import {
  FileCode,
  Shield,
  Layers,
  BookOpen,
  Sparkles,

  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Terminal,
  ExternalLink,
  HelpCircle,
  Quote,
  Hash,
  Scale,
  XCircle,
  Info,
  Wrench,
  Copy,
  Check,
  ArrowRight,
  Database,
  History,
  FolderTree,
  Trash2,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { streamUnifiedAnalysis, runUnifiedAnalysis, proposeFix, ApiError } from "../services/api";
import { AnalysisReport } from "../types/evidence";
import { FixProposalResponse } from "../types/fix_proposal";
import { ConnectionStatus } from "../types/health";
import { ScanProgressEvent } from "../types/stream";
import { ScanHistoryView } from "./ScanHistoryView";
import { MonacoPythonEditor } from "./MonacoPythonEditor";
import { LiveScanProgress } from "./LiveScanProgress";
import { ProjectAnalysisView } from "./ProjectAnalysisView";
import { FindingCard } from "./FindingCard";


const SNIPPET_STRIPE_CHARGE_DEPRECATED = `# Sample Stripe Python snippet with a legacy contract violation
# Notice: 'stripe.Charge.create' with 'source' token is deprecated in modern Stripe APIs.
import stripe

stripe.api_key = "sk_test_placeholder_key"

def process_payment(amount_cents: int, token: str, currency: str = "usd") -> str:
    # APICompass Evidence Court will detect the deprecated 'source' parameter
    charge = stripe.Charge.create(
        amount=amount_cents,
        currency=currency,
        source=token,
        description="Software subscription charge"
    )
    return charge["id"]
`;

const SNIPPET_STRIPE_INTENT_CLEAN = `# Modern Stripe PaymentIntent usage adhering to official contracts
import stripe
from typing import Optional

stripe.api_key = "sk_test_modern_key"

async def create_intent(amount: int, customer_id: Optional[str] = None):
    # Verified against official Stripe PaymentIntents API documentation
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        customer=customer_id,
        automatic_payment_methods={"enabled": True},
    )
    return intent.client_secret
`;

const SNIPPET_SYNTAX_ERROR = `# Syntax error test snippet
import stripe

def incomplete_function(
    return stripe.Charge.create(amount=100)
`;

const SNIPPET_NON_API = `# Standard Python function with no third-party API calls
def calculate_subtotal(items: list[dict], discount: float = 0.0) -> float:
    # APICompass will detect zero in-scope API calls and abstain safely
    base = sum(item["price"] * item["quantity"] for item in items)
    return base * (1.0 - discount)
`;

interface CodeEditorProps {
  backendStatus?: ConnectionStatus;
  mockMode?: boolean;
}

type TabType = "verdict" | "suggestions" | "candidates" | "evidence" | "ast" | "fixes";

export const CodeEditorPlaceholder: React.FC<CodeEditorProps> = ({
  backendStatus = "connected",
  mockMode = true,
}) => {
  const [code, setCode] = useState<string>(SNIPPET_STRIPE_CHARGE_DEPRECATED);
  const [lastAnalyzedCode, setLastAnalyzedCode] = useState<string | null>(null);
  const [editorHeight, setEditorHeight] = useState<"default" | "expanded">("default");
  const [targetHighlightLine, setTargetHighlightLine] = useState<number | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const isAnalyzingRef = useRef<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [analysisNotice, setAnalysisNotice] = useState<string | null>(null);
  const [currentProgressEvent, setCurrentProgressEvent] = useState<ScanProgressEvent | null>(null);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("verdict");

  // Fix Proposal State
  const [proposal, setProposal] = useState<FixProposalResponse | null>(null);
  const [isProposing, setIsProposing] = useState<boolean>(false);
  const isProposingRef = useRef<boolean>(false);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [editorNotice, setEditorNotice] = useState<string | null>(null);
  const [findingSeverityFilter, setFindingSeverityFilter] = useState<"all" | "error" | "warning">("all");

  // Workspace View Mode ('editor' vs 'project' vs 'history')
  const [viewMode, setViewMode] = useState<"editor" | "project" | "history">("editor");

  const lineCount = code.length === 0 ? 0 : code.split("\n").length;
  const charCount = code.length;
  const isModifiedSinceAnalysis = lastAnalyzedCode !== null && code !== lastAnalyzedCode && report !== null;

  const handleClearCode = () => {
    setCode("");
    setReport(null);
    setCurrentProgressEvent(null);
    setProposal(null);
    setProposalError(null);
    setError(null);
    setAnalysisNotice(null);
    setLastAnalyzedCode(null);
    setTargetHighlightLine(null);
    setFindingSeverityFilter("all");
  };

  const handleCancelAnalysis = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    isAnalyzingRef.current = false;
    setIsAnalyzing(false);
    setCurrentProgressEvent(null);
    setAnalysisNotice("Analysis cancelled by user. No code was executed or modified.");
    setTimeout(() => setAnalysisNotice(null), 7000);
  };

  const handleRunAdjudication = async (forceMock = false) => {
    if (isAnalyzing || isAnalyzingRef.current) {
      return;
    }
    if (!code.trim()) {
      setError("Source code is empty. Please enter Python code to analyze.");
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setError(null);
    setAnalysisNotice(null);
    setCurrentProgressEvent(null);

    try {
      const result = await streamUnifiedAnalysis(
        {
          source: code,
          filename: "payment_handler.py",
          ecosystem: "stripe",
          force_mock: forceMock,
        },
        (event) => {
          setCurrentProgressEvent(event);
        },
        controller.signal
      );
      setReport(result);
      setLastAnalyzedCode(code);
      setActiveTab("verdict");
    } catch (err: unknown) {
      if (err instanceof ApiError && err.statusCode === 499) {
        setAnalysisNotice("Analysis was cancelled by the user. No code was executed or modified.");
      } else if (err instanceof Error && (err.name === "AbortError" || err.message.toLowerCase().includes("abort"))) {
        setAnalysisNotice("Analysis was cancelled by the user. No code was executed or modified.");
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected network error occurred while running adjudication.");
      }
    } finally {
      abortControllerRef.current = null;
      isAnalyzingRef.current = false;
      setIsAnalyzing(false);
    }
  };

  const handleRunNonStreamingAnalysis = async () => {
    if (isAnalyzing || isAnalyzingRef.current) {
      return;
    }
    if (!code.trim()) {
      setError("Source code is empty. Please enter Python code to analyze.");
      return;
    }

    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setError(null);
    setAnalysisNotice(null);
    setCurrentProgressEvent({
      event_version: "1.0.0",
      stage: "accepted",
      message: "Running standard (non-streaming) verification...",
      timestamp: new Date().toISOString(),
      progress_percent: 50,
    });

    try {
      const result = await runUnifiedAnalysis({
        source: code,
        filename: "payment_handler.py",
        ecosystem: "stripe",
      });
      setReport(result);
      setLastAnalyzedCode(code);
      setActiveTab("verdict");
      setCurrentProgressEvent(null);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Standard analysis request failed.");
      }
    } finally {
      isAnalyzingRef.current = false;
      setIsAnalyzing(false);
    }
  };

  const handleProposeFix = async (candidateId: string, issueId?: string) => {
    if (isProposing || isProposingRef.current) {
      return;
    }
    isProposingRef.current = true;
    setIsProposing(true);
    setProposalError(null);
    setProposal(null);
    setActiveTab("fixes");

    try {
      const result = await proposeFix({
        source: code,
        candidate_id: candidateId,
        filename: "payment_handler.py",
        ecosystem: "stripe",
        issue_id: issueId,
      });
      setProposal(result);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setProposalError(err.message);
      } else {
        setProposalError("An unexpected error occurred while generating fix proposal.");
      }
    } finally {
      isProposingRef.current = false;
      setIsProposing(false);
    }
  };

  const handleCopyFix = () => {
    if (!proposal) return;
    const textToCopy = proposal.proposed_source || proposal.proposed_excerpt || "";
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApplyFixToEditor = () => {
    if (!proposal?.proposed_source) return;
    setCode(proposal.proposed_source);
    setEditorNotice("Proposed fix applied to editor. Click 'Re-Analyze Code' to confirm that the issue is resolved.");
    setTargetHighlightLine(1);
    setActiveTab("verdict");
    setTimeout(() => setEditorNotice(null), 8000);
  };

  const handleDiscardFix = () => {
    setProposal(null);
    setProposalError(null);
    setEditorNotice("Fix proposal discarded. Original code was preserved without changes.");
    setActiveTab("verdict");
    setTimeout(() => setEditorNotice(null), 6000);
  };

  const handleSnippetSelect = (snippet: string) => {
    setCode(snippet);
    setReport(null);
    setCurrentProgressEvent(null);
    setProposal(null);
    setProposalError(null);
    setError(null);
    setLastAnalyzedCode(null);
    setTargetHighlightLine(null);
    setFindingSeverityFilter("all");
  };


  return (
    <div className="flex flex-col flex-1 w-full">
      {/* Workspace Navigation Switcher */}
      <div className="border-b border-border-subtle bg-slate-950/70 px-6 py-2.5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setViewMode("editor")}
              data-testid="nav-tab-editor"
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 transition-all ${
                viewMode === "editor"
                  ? "bg-violet-950 text-violet-200 border border-violet-800 shadow-md shadow-violet-950/50"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
              }`}
            >
              <Scale className="w-3.5 h-3.5 text-accent-cyan" />
              <span>Verification Studio</span>
            </button>
            <button
              onClick={() => setViewMode("project")}
              data-testid="nav-tab-project"
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 transition-all ${
                viewMode === "project"
                  ? "bg-violet-950 text-violet-200 border border-violet-800 shadow-md shadow-violet-950/50"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
              }`}
            >
              <FolderTree className="w-3.5 h-3.5 text-cyan-400" />
              <span>Multi-File Project</span>
            </button>
            <button
              onClick={() => setViewMode("history")}
              data-testid="nav-tab-history"
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 transition-all ${
                viewMode === "history"
                  ? "bg-violet-950 text-violet-200 border border-violet-800 shadow-md shadow-violet-950/50"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
              }`}
            >
              <History className="w-3.5 h-3.5 text-emerald-400" />
              <span>Scan Audit History</span>
            </button>
          </div>
        </div>
      </div>

      {viewMode === "history" ? (
        <div className="p-6 max-w-7xl mx-auto w-full flex-1">
          <ScanHistoryView onBackToEditor={() => setViewMode("editor")} />
        </div>
      ) : viewMode === "project" ? (
        <div className="p-6 max-w-7xl mx-auto w-full flex-1">
          <ProjectAnalysisView />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 p-6 max-w-7xl mx-auto flex-1 w-full">
          {/* Left 8 Cols: Code Editor & Evidence Court Results */}
          <div className="lg:col-span-8 flex flex-col space-y-4">
            {/* Editor Container */}
            <div className="flex flex-col rounded-xl border border-border bg-background-panel shadow-2xl overflow-hidden">
              {/* Scope & Boundary Transparency Banner (Requirement 2) */}
              <div className="flex flex-wrap items-center justify-between px-4 py-2 bg-slate-950 border-b border-border-subtle text-xs gap-2">
                <div className="flex items-center space-x-2 flex-wrap gap-1.5">
                  <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-violet-950 text-violet-300 border border-violet-800">
                    SUPPORTED SCOPE: PYTHON 3.x • STRIPE SDK
                  </span>
                  <span className="text-slate-400 text-[11px] hidden sm:inline">
                    Evaluates Stripe API operations against official contracts. Non-Stripe code is identified as out of scope without false alarms.
                  </span>
                </div>
                <div data-testid="editor-metrics" className="flex items-center space-x-2 text-[11px] text-slate-400 font-mono">
                  <span>{lineCount} lines</span>
                  <span>•</span>
                  <span>{charCount} chars</span>
                </div>
              </div>

              {/* Editor Header */}
              <div className="flex flex-wrap items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-border-subtle text-xs gap-2">
                <div className="flex items-center space-x-2 text-slate-300">
                  <FileCode className="w-4 h-4 text-accent-cyan" />
                  <span className="font-mono font-medium">payment_handler.py</span>
                  <span className="text-slate-400 font-sans text-[11px]">(Python)</span>
                </div>

                {/* Snippet Presets & Editor Actions */}
                <div className="flex items-center space-x-1.5 flex-wrap gap-1">
                  <span className="text-[11px] text-slate-400">Presets:</span>
                  <button
                    onClick={() => handleSnippetSelect(SNIPPET_STRIPE_CHARGE_DEPRECATED)}
                    aria-label="Charge (Legacy Source)"
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
                  >
                    Charge (Legacy Source)
                  </button>
                  <button
                    onClick={() => handleSnippetSelect(SNIPPET_STRIPE_INTENT_CLEAN)}
                    aria-label="PaymentIntent (Clean)"
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
                  >
                    PaymentIntent (Clean)
                  </button>
                  <button
                    onClick={() => handleSnippetSelect(SNIPPET_SYNTAX_ERROR)}
                    aria-label="Syntax Error"
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
                  >
                    Syntax Error
                  </button>
                  <button
                    onClick={() => handleSnippetSelect(SNIPPET_NON_API)}
                    aria-label="Non-API (Abstain)"
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
                  >
                    Non-API (Abstain)
                  </button>

                  <span className="text-slate-600 px-0.5">|</span>

                  {/* Clear Editor */}
                  <button
                    onClick={handleClearCode}
                    aria-label="Clear code editor"
                    className="px-2 py-0.5 rounded bg-slate-800/80 hover:bg-rose-950 hover:text-rose-300 text-slate-400 text-[11px] transition-colors border border-slate-700/80 flex items-center space-x-1"
                    title="Clear editor to paste new code"
                  >
                    <Trash2 className="w-3 h-3" />
                    <span>Clear</span>
                  </button>

                  {/* Expand / Collapse Editor Height */}
                  <button
                    onClick={() => setEditorHeight((h) => (h === "default" ? "expanded" : "default"))}
                    aria-label={editorHeight === "default" ? "Expand editor height" : "Collapse editor height"}
                    className="px-2 py-0.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700/80 flex items-center space-x-1"
                    title={editorHeight === "default" ? "Expand editor height" : "Collapse editor height"}
                  >
                    {editorHeight === "default" ? <Maximize2 className="w-3 h-3" /> : <Minimize2 className="w-3 h-3" />}
                    <span>{editorHeight === "default" ? "Expand" : "Collapse"}</span>
                  </button>
                </div>
              </div>

              {/* Modified Since Analysis Notice (Requirement 8) */}
              {isModifiedSinceAnalysis && (
                <div className="px-4 py-2 bg-violet-950/50 border-b border-violet-800/60 text-xs text-violet-200 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center space-x-2">
                    <span className="h-2 w-2 rounded-full bg-violet-400 animate-pulse"></span>
                    <span className="font-semibold text-violet-300">Editor modified since last analysis:</span>
                    <span className="text-slate-300 text-[11px]">The results below reflect the previous code.</span>
                  </div>
                  <button
                    onClick={() => handleRunAdjudication(false)}
                    disabled={isAnalyzing || backendStatus === "unavailable"}
                    className="px-2.5 py-0.5 rounded bg-violet-800 hover:bg-violet-700 text-white font-semibold text-[11px] flex items-center space-x-1 transition-colors"
                  >
                    <RefreshCw className="w-3 h-3 text-accent-cyan" />
                    <span>Re-Analyze Code</span>
                  </button>
                </div>
              )}

              {/* Monaco Python Editor */}
              <MonacoPythonEditor
                code={code}
                onChange={(val) => {
                  setCode(val);
                  if (error) setError(null);
                }}
                readOnly={isAnalyzing}
                syntaxError={report?.syntax_error}
                height={editorHeight === "expanded" ? "520px" : "340px"}
                onRun={handleRunAdjudication}
                targetLine={targetHighlightLine}
              />

              {/* Action Bar */}
              <div className="px-4 py-3 bg-slate-900/90 border-t border-border-subtle flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center flex-wrap gap-2.5 text-xs">
                  {/* Pre-Analysis Documentation Source Transparency (Requirement 4) */}
                  <div
                    data-testid="data-source-indicator"
                    className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border ${
                      mockMode
                        ? "bg-amber-950/40 border-amber-600/50 text-amber-300"
                        : "bg-emerald-950/40 border-emerald-600/50 text-emerald-300"
                    }`}
                    title={
                      mockMode
                        ? "Running in Mock Mode. Evaluates code against offline mock fixtures."
                        : "Live Retrieval Active. Fetches official documentation from docs.stripe.com."
                    }
                  >
                    <span className={`h-2 w-2 rounded-full ${mockMode ? "bg-amber-400" : "bg-emerald-400"}`} />
                    <span className="font-semibold">
                      Docs: {mockMode ? "Offline Mock Fixtures" : "Live docs.stripe.com"}
                    </span>
                  </div>

                  <div className="flex items-center space-x-1.5 text-slate-400 text-[11px]">
                    <Shield className="w-3.5 h-3.5 text-violet-400" />
                    <span>Inspection is AST-only • Code is never executed</span>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center space-x-2.5">
                  {isAnalyzing && (
                    <button
                      onClick={handleCancelAnalysis}
                      data-testid="cancel-analysis-button"
                      aria-label="Cancel in-progress analysis"
                      className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 transition-colors"
                    >
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                      <span>Cancel Analysis</span>
                    </button>
                  )}

                  <button
                    onClick={() => handleRunAdjudication(false)}
                    disabled={isAnalyzing || backendStatus === "unavailable"}
                    data-testid="run-verify-button"
                    aria-label="Start Python Stripe API Contract Analysis"
                    className={`flex items-center space-x-2 px-5 py-2 rounded-lg text-xs font-semibold shadow-lg transition-all ${
                      isAnalyzing || backendStatus === "unavailable"
                        ? "bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed opacity-75"
                        : "bg-gradient-to-r from-accent-violet to-violet-600 hover:from-violet-600 hover:to-accent-violet text-white shadow-violet-500/20 active:scale-95"
                    }`}
                    title={
                      backendStatus === "unavailable"
                        ? "Backend is offline"
                        : isModifiedSinceAnalysis
                        ? "Re-analyze modified code in Evidence Court (Ctrl+Enter)"
                        : "Run full Evidence Court adjudication (Ctrl+Enter)"
                    }
                  >
                    {isAnalyzing ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Adjudicating in Evidence Court...</span>
                      </>
                    ) : isModifiedSinceAnalysis ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 text-accent-cyan" />
                        <span>Re-Analyze Code</span>
                        <span className="hidden sm:inline font-mono text-[10px] opacity-75 ml-0.5 bg-black/30 px-1 rounded">
                          Ctrl+↵
                        </span>
                      </>
                    ) : (
                      <>
                        <Scale className="w-3.5 h-3.5" />
                        <span>Verify with Evidence Court</span>
                        <span className="hidden sm:inline font-mono text-[10px] opacity-75 ml-0.5 bg-black/30 px-1 rounded">
                          Ctrl+↵
                        </span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

        {/* Live Scan Progress Stream */}
        {(isAnalyzing || currentProgressEvent || error) && (
          <LiveScanProgress
            currentEvent={currentProgressEvent}
            isAnalyzing={isAnalyzing}
            error={error}
            onRetry={() => handleRunAdjudication(false)}
            onCancel={handleCancelAnalysis}
            onRetryNonStreaming={handleRunNonStreamingAnalysis}
          />
        )}

        {/* Analysis Cancelled Notice Banner */}
        {analysisNotice && (
          <div
            data-testid="analysis-cancelled-notice"
            className="rounded-lg border border-slate-700 bg-slate-900/80 p-3 text-xs text-slate-300 flex items-center space-x-2"
          >
            <Info className="w-4 h-4 text-accent-cyan flex-shrink-0" />
            <span>{analysisNotice}</span>
          </div>
        )}

        {/* Empty Code Submission Alert */}
        {error === "Source code is empty. Please enter Python code to analyze." && (
          <div
            data-testid="empty-code-submission-alert"
            className="rounded-lg border border-amber-800/80 bg-amber-950/40 p-4 text-xs text-amber-200 space-y-2"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 font-semibold text-amber-300">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Cannot Analyze Empty Source Code</span>
              </div>
              <button
                onClick={() => handleSnippetSelect(SNIPPET_STRIPE_INTENT_CLEAN)}
                data-testid="load-example-button"
                className="px-2.5 py-1 rounded bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 font-semibold text-[11px] transition-colors"
              >
                Load Starter Example
              </button>
            </div>
            <p className="text-slate-300">
              Please enter or paste Python source code before starting analysis. APICompass performs static AST analysis on Python code interacting with the Stripe SDK.
            </p>
          </div>
        )}

        {/* Backend Unavailable Banner */}
        {(backendStatus === "unavailable" || (error && error.includes("Cannot connect to APICompass backend"))) && (
          <div
            data-testid="backend-unavailable-banner"
            className="rounded-lg border border-rose-800/80 bg-rose-950/40 p-4 text-xs text-rose-200 space-y-2"
          >
            <div className="flex items-center space-x-2 font-semibold text-rose-300">
              <AlertCircle className="w-4 h-4 text-rose-400" />
              <span>Backend Service Offline or Unreachable</span>
            </div>
            <p className="text-slate-300">
              Cannot establish connection to the APICompass backend at http://127.0.0.1:8000.
            </p>
            <div className="p-2.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300">
              <span className="text-slate-500 mr-2">$</span>
              uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
            </div>
            <p className="text-[11px] text-slate-400">
              Ensure the Python virtual environment is activated and the backend service is running.
            </p>
          </div>
        )}

        {/* Streaming Connection Interruption Banner */}
        {error &&
          (error.includes("Streaming connection was interrupted") ||
            error.includes("Stream ended without receiving final adjudication report")) && (
            <div
              data-testid="streaming-interrupted-banner"
              className="rounded-lg border border-amber-800/80 bg-amber-950/40 p-4 text-xs text-amber-200 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2 font-semibold text-amber-300">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <span>Streaming Connection Interrupted</span>
                </div>
                <button
                  onClick={handleRunNonStreamingAnalysis}
                  data-testid="retry-non-streaming-button"
                  className="px-2.5 py-1 rounded bg-violet-900/70 hover:bg-violet-800 text-violet-200 border border-violet-700 font-semibold text-[11px] transition-colors"
                >
                  Retry with Standard (Non-Streaming) Analysis
                </button>
              </div>
              <p className="text-slate-300">
                The real-time Server-Sent Events stream was interrupted. You can re-attempt analysis using standard non-streaming HTTP requests.
              </p>
            </div>
          )}

        {/* Generic Error Banner */}
        {error &&
          error !== "Source code is empty. Please enter Python code to analyze." &&
          !error.includes("Cannot connect to APICompass backend") &&
          !error.includes("Streaming connection was interrupted") &&
          !error.includes("Stream ended without receiving final adjudication report") && (
            <div className="rounded-lg border border-rose-800/80 bg-rose-950/40 p-3.5 text-xs text-rose-300 flex items-start space-x-2.5">
              <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-rose-200">Adjudication Request Failed</p>
                <p className="text-rose-300/90 mt-0.5">{error}</p>
              </div>
            </div>
          )}

        {/* Editor Notice Banner */}
        {editorNotice && (
          <div className="rounded-lg border border-emerald-800/80 bg-emerald-950/40 p-3 text-xs text-emerald-300 flex items-center space-x-2">
            <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <span>{editorNotice}</span>
          </div>
        )}

        {/* Syntax Error Report */}
        {report?.syntax_error && (
          <div className="rounded-lg border border-amber-800/80 bg-amber-950/40 p-4 text-xs text-amber-200 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 font-semibold text-amber-300">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Python Syntax Error Detected</span>
              </div>
              <button
                onClick={() => {
                  setTargetHighlightLine(report.syntax_error!.lineno ?? null);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                data-testid="jump-to-syntax-error"
                className="px-2.5 py-1 rounded bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 font-mono text-[11px] flex items-center space-x-1.5 transition-colors"
              >
                <span>Jump to Line {report.syntax_error.lineno} in Editor</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>
            <p className="text-slate-300">
              {report.syntax_error.message} on line {report.syntax_error.lineno}
              {report.syntax_error.col_offset !== null && `, column ${report.syntax_error.col_offset}`}.
            </p>
            {report.syntax_error.text && (
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-amber-300 overflow-x-auto">
                <span className="text-slate-500 mr-2">{report.syntax_error.lineno} |</span>
                {report.syntax_error.text}
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Analysis was halted cleanly because invalid syntax cannot be parsed into an AST.
            </p>
          </div>
        )}

        {/* Evidence Court Adjudication Results Panel */}
        {report && (
          <div className="rounded-xl border border-border bg-background-panel shadow-xl overflow-hidden flex flex-col">
            {/* Verdict Header Panel */}
            <div className="p-4 border-b border-border-subtle bg-slate-950/80 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center space-x-3">
                  <div className="flex items-center space-x-2">
                    <Scale className="w-5 h-5 text-accent-cyan" />
                    <span className="text-xs uppercase tracking-wider font-semibold text-slate-400">
                      Evidence Court Verdict
                    </span>
                  </div>

                  {/* Verdict Badges (Explicit Verification States) */}
                  {report.verdict === "clean" && (
                    <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-700/80 flex items-center space-x-1.5 shadow-sm">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span>NO ISSUE DETECTED WITHIN THE CHECKS PERFORMED</span>
                    </span>
                  )}
                  {report.verdict === "issues_found" && (
                    <span className="px-3 py-1 rounded-full text-xs font-bold bg-rose-950 text-rose-300 border border-rose-700/80 flex items-center space-x-1.5 shadow-sm">
                      <XCircle className="w-4 h-4 text-rose-400" />
                      <span>VERIFIED (EVIDENCE-SUPPORTED ISSUES FOUND)</span>
                    </span>
                  )}
                  {report.verdict === "unable_to_verify" && (
                    <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 flex items-center space-x-1.5 shadow-sm">
                      <AlertTriangle className="w-4 h-4 text-amber-400" />
                      <span>UNABLE TO VERIFY</span>
                    </span>
                  )}
                </div>

                {/* Trust Status Badge */}
                <div className="flex items-center space-x-2 text-xs">
                  {report.is_mock ? (
                    <span className="px-2.5 py-0.5 rounded text-[11px] bg-amber-950/70 text-amber-300 border border-amber-700/80 font-semibold flex items-center space-x-1">
                      <Info className="w-3.5 h-3.5" />
                      <span>MOCK FIXTURE QUARANTINE</span>
                    </span>
                  ) : (
                    <span className="px-2.5 py-0.5 rounded text-[11px] bg-emerald-950/70 text-emerald-300 border border-emerald-700/80 font-semibold flex items-center space-x-1">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>LIVE OFFICIAL RETRIEVAL</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Scope & Analysis Metrics */}
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
                <span className="font-semibold text-slate-300">Analysis Scope:</span>
                <span><strong className="text-slate-200">{report.total_lines}</strong> lines analyzed</span>
                <span>•</span>
                <span><strong className="text-slate-200">{report.candidate_assessments.length}</strong> API candidate(s) examined</span>
                <span>•</span>
                <span><strong className="text-slate-200">{report.evidence_items.length}</strong> official doc citation(s)</span>
                <span>•</span>
                <span className="italic">Passive AST inspection only — zero runtime execution</span>
              </div>

              {/* Plain-Language Verdict Definition */}
              <div className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/80 text-xs text-slate-300">
                {report.verdict === "clean" && (
                  <p>
                    <strong className="text-emerald-300">Plain Meaning: </strong>
                    No supported contract violations were found within the checks and official documentation available to this analysis.
                    This is not a guarantee that the entire program is correct or bug-free.
                  </p>
                )}
                {report.verdict === "issues_found" && (
                  <p>
                    <strong className="text-rose-300">Plain Meaning: </strong>
                    One or more specific API contract violations were confirmed by official documentation quotation receipts within the evaluated scope.
                  </p>
                )}
                {report.verdict === "unable_to_verify" && (
                  <p>
                    <strong className="text-amber-300">Plain Meaning: </strong>
                    Evidence Court abstained from issuing a definitive verdict. Available evidence was insufficient, unavailable, ambiguous, incomplete, or quarantined.
                  </p>
                )}
              </div>

              {/* Summary Description */}
              <p className="text-xs text-slate-200 leading-relaxed">{report.summary}</p>

              {/* Mock Warning Banner if Mock Mode */}
              {report.is_mock && (
                <div className="p-2.5 rounded-lg bg-amber-950/40 border border-amber-800/60 text-xs text-amber-200 flex items-start space-x-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-amber-300">Integrity Policy Notice: </span>
                    <span>
                      Analysis executed using offline mock fixtures. Mock evidence is quarantined and can never
                      produce production verified "clean" or "issues_found" verdicts against user code.
                    </span>
                  </div>
                </div>
              )}

              {/* Upstream Documentation Limitation / Error Alert */}
              {report.limitations_and_caveats.some((c) => c.startsWith("TINYFISH_")) && (
                <div
                  data-testid="doc-retrieval-alert"
                  className="p-3 rounded-lg bg-amber-950/40 border border-amber-800/80 text-xs text-amber-200 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 font-semibold text-amber-300">
                      <AlertTriangle className="w-4 h-4 text-amber-400" />
                      <span>Documentation Retrieval Limitation Notice</span>
                    </div>
                    <button
                      onClick={() => handleRunAdjudication(true)}
                      data-testid="switch-to-mock-button"
                      className="px-2.5 py-1 rounded bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 font-semibold text-[11px] transition-colors"
                    >
                      Re-verify in Mock Mode
                    </button>
                  </div>
                  <p className="text-slate-300">
                    {report.limitations_and_caveats.find((c) => c.startsWith("TINYFISH_"))}
                  </p>
                </div>
              )}

              {/* Audit History Persistence Badge */}
              {report.scan_id && (
                <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-xs flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Database className="w-3.5 h-3.5 text-accent-cyan" />
                    <span className="text-slate-400">Audit Record:</span>
                    <span className="font-mono text-slate-200 text-[11px]">{report.scan_id}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-950/80 text-emerald-300 border border-emerald-800/80 font-medium">
                      {report.persistence_status || "saved"}
                    </span>
                  </div>
                  <button
                    onClick={() => setViewMode("history")}
                    className="text-[11px] text-accent-cyan hover:text-cyan-300 flex items-center space-x-1 font-medium transition-colors"
                  >
                    <span>View in History</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>

            {/* Navigation Tabs */}
            <div className="flex items-center justify-between border-b border-border-subtle bg-slate-900/80 px-4 py-2">
              <div className="flex items-center space-x-1 overflow-x-auto">
                <button
                  onClick={() => setActiveTab("verdict")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "verdict"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Scale className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>Verdict & Issues</span>
                  {report.verified_issues.length > 0 && (
                    <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-rose-950 text-rose-300 border border-rose-800/60">
                      {report.verified_issues.length}
                    </span>
                  )}
                </button>

                <button
                  onClick={() => setActiveTab("suggestions")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "suggestions"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Sparkles className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>AI Suggestions</span>
                  {report.ai_suggestions.length > 0 && (
                    <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-violet-950 text-violet-300 border border-violet-800/60 font-semibold">
                      {report.ai_suggestions.length}
                    </span>
                  )}
                </button>

                <button
                  onClick={() => setActiveTab("candidates")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "candidates"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Sparkles className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>Candidate Assessments ({report.candidate_assessments.length})</span>
                </button>

                <button
                  onClick={() => setActiveTab("evidence")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "evidence"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Evidence Receipts ({report.evidence_items.length})</span>
                </button>

                <button
                  onClick={() => setActiveTab("ast")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "ast"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Terminal className="w-3.5 h-3.5 text-slate-400" />
                  <span>AST Scope ({report.total_lines} lines)</span>
                </button>

                <button
                  onClick={() => setActiveTab("fixes")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center space-x-1.5 ${
                    activeTab === "fixes"
                      ? "bg-violet-950/80 text-violet-300 border border-violet-800/60"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Wrench className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>Fix Proposal</span>
                  {proposal && (
                    <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-800/60 font-semibold">
                      {proposal.status === "evidence_supported" ? "✓" : "!"}
                    </span>
                  )}
                </button>
              </div>
            </div>


            {/* Tab Contents */}
            <div className="p-4 space-y-4 min-h-[220px] max-h-[380px] overflow-y-auto">
              {/* Tab 1: Verdict & Issues */}
              {activeTab === "verdict" && (
                <div className="space-y-4">
                  {/* Deterministic Findings Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
                    <div className="flex items-center space-x-2">
                      <Scale className="w-4 h-4 text-accent-cyan" />
                      <h3 className="text-xs font-semibold text-slate-200">Deterministically Verified Findings</h3>
                    </div>
                    <span className="text-[10px] text-slate-400 italic">
                      Strictly substantiated by official documentation quote receipts
                    </span>
                  </div>

                  {/* Severity Filter Controls (Requirement: Group findings by severity / category) */}
                  {report.verified_issues.length > 0 && (
                    <div
                      data-testid="findings-filter-bar"
                      className="flex items-center justify-between gap-2 py-1.5 px-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs"
                    >
                      <div className="flex items-center space-x-1.5 text-slate-400 text-[11px]">
                        <span>Filter Findings:</span>
                      </div>
                      <div className="flex items-center space-x-1">
                        <button
                          onClick={() => setFindingSeverityFilter("all")}
                          data-testid="filter-all-button"
                          aria-label={`Show all ${report.verified_issues.length} findings`}
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "all"
                              ? "bg-violet-900/80 text-violet-200 border border-violet-700"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          All ({report.verified_issues.length})
                        </button>
                        <button
                          onClick={() => setFindingSeverityFilter("error")}
                          data-testid="filter-error-button"
                          aria-label="Filter error findings"
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "error"
                              ? "bg-rose-950 text-rose-300 border border-rose-800"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          Errors ({report.verified_issues.filter((i) => (i.severity || "error").toLowerCase() === "error").length})
                        </button>
                        <button
                          onClick={() => setFindingSeverityFilter("warning")}
                          data-testid="filter-warning-button"
                          aria-label="Filter warning findings"
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "warning"
                              ? "bg-amber-950 text-amber-300 border border-amber-800"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          Warnings ({report.verified_issues.filter((i) => (i.severity || "").toLowerCase() === "warning").length})
                        </button>
                      </div>
                    </div>
                  )}

                  {(() => {
                    const filteredIssues = report.verified_issues.filter((issue) => {
                      if (findingSeverityFilter === "all") return true;
                      const sev = (issue.severity || "error").toLowerCase();
                      return sev === findingSeverityFilter;
                    });

                    if (report.verified_issues.length === 0) {
                      return (
                        <FindingCard
                          id="clean-verdict"
                          status="no_issue_detected"
                          title="No API Contract Violations Detected in Examined Calls"
                          explanation={report.summary || report.disclaimer}
                          checksPerformed={
                            report.checks_performed && report.checks_performed.length > 0
                              ? report.checks_performed
                              : [
                                  "Static AST Operation & Symbol Resolution (Stripe Python SDK)",
                                  "Documented Parameter Presence & Required Argument Verification",
                                  "Deprecated Parameter & Legacy Operation Checking",
                                  "Static Constraint & Value Conformance Validation",
                                ]
                          }
                        />
                      );
                    }

                    if (filteredIssues.length === 0) {
                      return (
                        <div
                          data-testid="no-filtered-findings-notice"
                          className="p-4 rounded-lg bg-slate-900/40 border border-slate-800 text-center text-xs text-slate-400"
                        >
                          No findings match the selected severity filter "{findingSeverityFilter}".
                        </div>
                      );
                    }

                    return filteredIssues.map((issue) => (
                      <FindingCard
                        key={issue.issue_id}
                        id={issue.issue_id}
                        issueId={issue.issue_id}
                        candidateId={issue.candidate_id}
                        status={issue.verification_status || "verified"}
                        title={issue.title || `${issue.violation_type.replace(/_/g, " ").toUpperCase()}: ${issue.claim_checked}`}
                        impactClassification={issue.impact_classification || issue.violation_type.replace(/_/g, " ").toUpperCase()}
                        filePath={issue.file_path || report.filename}
                        sourceLine={issue.source_location.lineno}
                        sourceCol={issue.source_location.col_offset}
                        codeFragment={issue.code_fragment}
                        explanation={issue.explanation}
                        documentedRequirement={issue.documented_requirement}
                        sourceUrl={issue.source_url}
                        canonicalUrl={issue.canonical_url}
                        sourceTitle={issue.source_title}
                        retrievalStatus={issue.retrieval_status}
                        retrievedAt={issue.retrieved_at}
                        isMock={report.is_mock || issue.is_mock}
                        supportingExcerpt={issue.supporting_excerpt || issue.verified_quote}
                        quoteKind={issue.quote_kind}
                        matchMethod={issue.match_method}
                        evidenceFingerprint={issue.content_sha256 || issue.supporting_evidence_id}
                        evidenceRationale={issue.evidence_rationale}
                        uncertaintyOrLimitations={issue.limitations}
                        suggestedCorrection={issue.suggested_correction}
                        severity={issue.severity}
                        confidence={issue.confidence}
                        detectedCall={issue.detected_call}
                        detectedArgument={issue.detected_argument}
                        expectedContract={issue.expected_contract}
                        observedUsage={issue.observed_usage}
                        suggestedAction={issue.suggested_action}
                        onJumpToLine={(line) => {
                          setTargetHighlightLine(line);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                        onProposeFix={(candId, issId) => handleProposeFix(candId, issId)}
                        isProposingFix={isProposing}
                      />
                    ));
                  })()}

                  {/* Abstention Guidance when unable_to_verify (Requirement 7) */}
                  {report.verdict === "unable_to_verify" && (
                    <div className="p-4 rounded-lg bg-slate-900/80 border border-amber-700/60 text-xs space-y-3">
                      <div className="flex items-center space-x-2 text-amber-300 font-semibold text-xs border-b border-slate-800 pb-2">
                        <HelpCircle className="w-4 h-4 text-accent-cyan" />
                        <span>Why did APICompass abstain from a definitive verdict?</span>
                      </div>
                      <p className="text-slate-300 text-xs leading-relaxed">
                        APICompass abstains whenever evidence is mock-only, missing, ambiguous, or incomplete,
                        ensuring no unsupported claim is ever presented as verified truth.
                      </p>

                      {/* Detailed reasons breakdown */}
                      <div className="space-y-2 pt-1">
                        {report.is_mock && (
                          <div className="p-2.5 rounded bg-amber-950/30 border border-amber-800/60 text-xs text-amber-200 flex items-start space-x-2">
                            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                            <div>
                              <strong className="text-amber-300">Mock Mode Active: </strong>
                              <span>
                                The analysis was executed using offline mock fixtures. Offline mock data is quarantined and can never
                                establish verified live contract findings or certify production code as compliant.
                              </span>
                            </div>
                          </div>
                        )}

                        {report.candidate_assessments.filter((c) => c.status === "unresolved").length > 0 && (
                          <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs space-y-2">
                            <div className="flex items-center space-x-1.5 text-accent-cyan font-medium">
                              <Info className="w-3.5 h-3.5" />
                              <span>Unresolved Candidate Operations ({report.candidate_assessments.filter((c) => c.status === "unresolved").length}):</span>
                            </div>
                            <div className="space-y-1.5">
                              {report.candidate_assessments
                                .filter((c) => c.status === "unresolved")
                                .map((cand) => (
                                  <div
                                    key={cand.candidate_id}
                                    className="p-2 rounded bg-slate-900 border border-slate-800 text-[11px] space-y-1"
                                  >
                                    <div className="flex items-center justify-between">
                                      <span className="font-mono text-cyan-300 font-semibold">{cand.call_expr}</span>
                                      <button
                                        onClick={() => {
                                          setTargetHighlightLine(cand.source_location.lineno);
                                          window.scrollTo({ top: 0, behavior: "smooth" });
                                        }}
                                        className="font-mono text-slate-400 hover:text-slate-200 flex items-center space-x-1"
                                        title={`Jump to line ${cand.source_location.lineno}`}
                                      >
                                        <span>Line {cand.source_location.lineno}</span>
                                        <ArrowRight className="w-2.5 h-2.5 text-slate-400" />
                                      </button>
                                    </div>
                                    <div className="flex items-center space-x-2 flex-wrap gap-1">
                                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-amber-300 border border-slate-700 font-mono">
                                        {cand.abstention_reason || "UNRESOLVED"}
                                      </span>
                                      <span className="text-slate-300 text-[11px]">{cand.explanation}</span>
                                    </div>
                                  </div>
                                ))}
                            </div>
                          </div>
                        )}

                        {report.candidate_assessments.length === 0 && (
                          <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs text-slate-300 space-y-1">
                            <div className="flex items-center space-x-1.5 text-amber-400 font-semibold">
                              <AlertCircle className="w-3.5 h-3.5" />
                              <span>No Supported In-Scope Stripe API Calls Detected:</span>
                            </div>
                            <p className="text-[11px] text-slate-400">
                              APICompass evaluates Python code using the official Stripe SDK (e.g., <code className="text-accent-cyan font-mono">stripe.PaymentIntent.create</code> or <code className="text-accent-cyan font-mono">stripe.Charge.create</code>). Standard Python logic and third-party libraries outside Stripe are treated as out-of-scope without raising false errors.
                            </p>
                          </div>
                        )}

                        {report.ai_suggestions.length > 0 && (
                          <div className="p-2.5 rounded bg-violet-950/30 border border-violet-800/60 text-xs text-violet-200 flex items-start space-x-2">
                            <Sparkles className="w-4 h-4 text-accent-cyan shrink-0 mt-0.5" />
                            <div>
                              <strong className="text-violet-300">Unverified AI Hypotheses: </strong>
                              <span>
                                The reasoning engine identified {report.ai_suggestions.length} advisory suggestion(s) in the "AI Suggestions" tab.
                                Because these lack exact official quotation receipts from docs.stripe.com, they remain unverified and cannot alter the Evidence Court verdict.
                              </span>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Developer Next Steps Checklist */}
                      <div className="p-2.5 rounded bg-slate-950/70 border border-slate-800 text-[11px] space-y-1 text-slate-400">
                        <strong className="text-slate-300">How to proceed:</strong>
                        <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px]">
                          <li>To verify against live documentation, configure your TinyFish API credentials.</li>
                          <li>Ensure API symbols correspond to official Stripe endpoint operations.</li>
                          <li>Check candidate assessments for candidate-specific match rationales.</li>
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab: AI Suggestions */}
              {activeTab === "suggestions" && (
                <div className="space-y-3">
                  {/* Advisory Notice Banner */}
                  <div className="p-3 rounded-lg bg-violet-950/40 border border-violet-800/80 text-xs text-violet-200 flex items-start space-x-2">
                    <Sparkles className="w-4 h-4 text-accent-cyan flex-shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <p className="font-semibold text-violet-100">
                        Advisory Hypotheses — Strictly Not Verified
                      </p>
                      <p className="text-[11px] text-violet-300/90 leading-relaxed">
                        AI suggestions analyze static API candidate patterns against expected conventions.
                        Model suggestions are strictly advisory: they CANNOT create confirmed findings or independently alter
                        Evidence Court verdicts. Only deterministic code matching verified official quotations establishes contract findings.
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs text-slate-300">
                    <div className="flex items-center space-x-2">
                      <Sparkles className="w-4 h-4 text-accent-cyan" />
                      <span className="font-semibold text-slate-200">
                        LLM Reasoning Status:
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700 uppercase">
                        {report.llm_reasoning_status}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 italic">
                      The model proposes; deterministic code decides.
                    </span>
                  </div>

                  {report.ai_suggestions.length === 0 ? (
                    <div className="p-4 rounded-lg bg-slate-900/60 border border-slate-800 text-xs text-slate-400 space-y-2">
                      <p className="font-medium text-slate-300">No unverified AI suggestions proposed.</p>
                      <p className="text-[11px] leading-relaxed">
                        {report.llm_reasoning_status === "disabled"
                          ? "LLM reasoning is currently disabled. Set LLM_PROVIDER=mock or configure LLM_API_KEY in your environment to enable AI-assisted reasoning."
                          : report.llm_reasoning_summary || "The reasoning engine identified no unverified contract concerns."}
                      </p>
                    </div>
                  ) : (
                    report.ai_suggestions.map((sug) => (
                      <FindingCard
                        key={sug.suggestion_id}
                        id={sug.suggestion_id}
                        candidateId={sug.candidate_id}
                        status="unverified_suggestion"
                        title={sug.title || `Advisory Hypothesis: ${sug.claim_type.replace(/_/g, " ")}`}
                        filePath={sug.file_path || report.filename}
                        sourceLine={sug.source_location?.lineno}
                        codeFragment={sug.code_fragment}
                        explanation={sug.description}
                        documentedRequirement={
                          sug.documented_requirement ||
                          (sug.suggested_documentation_queries.length > 0
                            ? `Suggested Documentation Queries: ${sug.suggested_documentation_queries.join(", ")}`
                            : undefined)
                        }
                        sourceUrl={sug.source_url}
                        uncertaintyOrLimitations={sug.unverified_aspects}
                        suggestedCorrection={sug.suggested_correction}
                        onJumpToLine={(line) => {
                          setTargetHighlightLine(line);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      />
                    ))
                  )}
                </div>
              )}

              {/* Tab 2: Candidate Assessments */}
              {activeTab === "candidates" && (
                <div className="space-y-3">
                  {/* Candidate Filter Bar */}
                  {report.candidate_assessments.length > 0 && (
                    <div
                      data-testid="findings-filter-bar"
                      className="flex items-center justify-between gap-2 py-1.5 px-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs"
                    >
                      <div className="flex items-center space-x-1.5 text-slate-400 text-[11px]">
                        <span>Filter Assessments:</span>
                      </div>
                      <div className="flex items-center space-x-1">
                        <button
                          onClick={() => setFindingSeverityFilter("all")}
                          data-testid="filter-all-button"
                          aria-label={`Show all ${report.candidate_assessments.length} assessments`}
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "all"
                              ? "bg-violet-900/80 text-violet-200 border border-violet-700"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          All ({report.candidate_assessments.length})
                        </button>
                        <button
                          onClick={() => setFindingSeverityFilter("error")}
                          data-testid="filter-error-button"
                          aria-label="Filter error assessments"
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "error"
                              ? "bg-rose-950 text-rose-300 border border-rose-800"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          Errors ({report.candidate_assessments.filter((i) => (i.severity || "error").toLowerCase() === "error").length})
                        </button>
                        <button
                          onClick={() => setFindingSeverityFilter("warning")}
                          data-testid="filter-warning-button"
                          aria-label="Filter warning assessments"
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                            findingSeverityFilter === "warning"
                              ? "bg-amber-950 text-amber-300 border border-amber-800"
                              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                          }`}
                        >
                          Warnings ({report.candidate_assessments.filter((i) => (i.severity || "").toLowerCase() === "warning").length})
                        </button>
                      </div>
                    </div>
                  )}

                  {(() => {
                    const filteredCandidates = report.candidate_assessments.filter((cand) => {
                      if (findingSeverityFilter === "all") return true;
                      const sev = (cand.severity || "error").toLowerCase();
                      return sev === findingSeverityFilter;
                    });

                    if (report.candidate_assessments.length === 0) {
                      return (
                        <div className="p-4 rounded-lg bg-slate-900/60 border border-slate-800 text-xs space-y-2">
                          <div className="flex items-center space-x-2 text-slate-200 font-semibold">
                            <AlertTriangle className="w-4 h-4 text-amber-400" />
                            <span>No Supported In-Scope API Calls Detected</span>
                          </div>
                          <p className="text-slate-400">
                            The submitted Python snippet contains no recognizable calls to supported API ecosystem operations (Stripe).
                            Zero in-scope calls cannot be certified as clean.
                          </p>
                        </div>
                      );
                    }

                    if (filteredCandidates.length === 0) {
                      return (
                        <div
                          data-testid="no-filtered-candidates-notice"
                          className="p-4 rounded-lg bg-slate-900/40 border border-slate-800 text-center text-xs text-slate-400"
                        >
                          No candidate assessments match the selected severity filter "{findingSeverityFilter}".
                        </div>
                      );
                    }

                    return filteredCandidates.map((cand) => (
                      <FindingCard
                        key={cand.candidate_id}
                        id={cand.candidate_id}
                        candidateId={cand.candidate_id}
                        status={
                          cand.verification_status ||
                          (cand.status === "resolved_clean"
                            ? "no_issue_detected"
                            : cand.status === "resolved_issue"
                            ? "verified"
                            : "unable_to_verify")
                        }
                        abstentionReason={cand.abstention_reason}
                        isMock={report.is_mock || cand.is_mock || cand.evidence_match?.is_mock}
                        title={cand.title || `${cand.target_name} on ${cand.receiver || "Stripe"}`}
                        impactClassification={cand.impact_classification}
                        filePath={cand.file_path || report.filename}
                        sourceLine={cand.source_location.lineno}
                        sourceCol={cand.source_location.col_offset}
                        codeFragment={cand.call_expr}
                        explanation={cand.explanation}
                        documentedRequirement={cand.documented_requirement}
                        sourceUrl={cand.source_url || cand.evidence_match?.source_url}
                        canonicalUrl={cand.canonical_url || cand.evidence_match?.canonical_url}
                        sourceTitle={cand.source_title || cand.evidence_match?.source_title}
                        retrievalStatus={cand.retrieval_status || cand.evidence_match?.retrieval_status}
                        retrievedAt={cand.retrieved_at || cand.evidence_match?.retrieved_at}
                        supportingExcerpt={cand.verified_quotes[0]?.matched_text}
                        quoteKind={cand.verified_quotes[0]?.quote_kind}
                        matchMethod={cand.verified_quotes[0]?.match_method}
                        evidenceFingerprint={cand.content_sha256 || cand.verified_quotes[0]?.content_hash}
                        uncertaintyOrLimitations={
                          cand.uncertainty_or_limitations ||
                          (cand.abstention_reason
                            ? `Abstention Reason: ${cand.abstention_reason}. ${cand.explanation}`
                            : undefined)
                        }
                        suggestedCorrection={cand.suggested_correction}
                        severity={cand.severity}
                        confidence={cand.confidence}
                        detectedCall={cand.detected_call}
                        detectedArgument={cand.detected_argument}
                        expectedContract={cand.expected_contract}
                        observedUsage={cand.observed_usage}
                        suggestedAction={cand.suggested_action}
                        onJumpToLine={(line) => {
                          setTargetHighlightLine(line);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                        onProposeFix={(candId, issId) => handleProposeFix(candId, issId)}
                        isProposingFix={isProposing}
                      />
                    ));
                  })()}
                </div>
              )}

              {/* Tab 3: Official Documentation Evidence Receipts */}
              {activeTab === "evidence" && (
                <div className="space-y-3">
                  {report.evidence_items.length === 0 ? (
                    <div className="p-4 rounded-lg bg-slate-900/60 border border-slate-800 text-xs text-slate-400 space-y-1">
                      <p className="font-semibold text-slate-300">No Documentation Evidence Retrieved</p>
                      <p className="text-[11px]">
                        No documentation queries were dispatched or all target URLs returned empty evidence.
                        Evidence Court cannot certify unverified calls as clean without authoritative receipts.
                      </p>
                    </div>
                  ) : (
                    report.evidence_items.map((ev) => (
                      <div
                        key={ev.evidence_id}
                        className="rounded-lg border border-slate-800 bg-slate-900/60 p-3.5 text-xs space-y-2.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center space-x-2">
                            <span className="font-semibold text-slate-200">
                              {ev.title || "Official Stripe Reference"}
                            </span>
                            {ev.is_mock ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-950 text-amber-300 border border-amber-800">
                                MOCK FIXTURE (OFFLINE)
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
                                LIVE OFFICIAL RETRIEVAL
                              </span>
                            )}
                          </div>
                          <div className="flex items-center space-x-1.5 font-mono text-[10px] text-slate-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                            <Hash className="w-3 h-3 text-slate-500" />
                            <span>{ev.evidence_id}</span>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-2 text-[11px]">
                          <a
                            href={ev.canonical_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent-cyan hover:underline flex items-center space-x-1"
                          >
                            <span>{ev.canonical_url}</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                          <span>•</span>
                          <span className="text-slate-400">Provider: {ev.provider}</span>
                          <span>•</span>
                          <span className="text-slate-400">
                            {ev.doc_version ? `Doc Version: ${ev.doc_version}` : "Version: Not specified by provider"}
                          </span>
                        </div>

                        {/* Content Excerpt */}
                        <div className="p-2.5 rounded bg-slate-950 border border-slate-800 font-sans text-xs text-slate-300 leading-relaxed max-h-36 overflow-y-auto">
                          {ev.content_excerpt || <span className="text-slate-500 italic">No content excerpt available for this evidence item.</span>}
                        </div>

                        {/* Provider Error / Limitation if not success */}
                        {ev.status !== "success" && ev.status !== "mock" && (
                          <div className="p-2.5 rounded bg-amber-950/30 border border-amber-800/60 text-xs text-amber-300 space-y-1">
                            <p className="font-semibold text-amber-200">
                              Provider Retrieval Limitation: {ev.error_code || ev.status.toUpperCase()}
                            </p>
                            <p className="text-[11px] text-slate-300">{ev.error_message || "Retrieval could not be completed."}</p>
                            <p className="text-[10px] text-slate-400 italic">
                              Notice: Provider unavailability reflects an external service condition, not a defect in your code.
                            </p>
                          </div>
                        )}

                        {/* Evaluated Excerpt Fingerprint Explanation */}
                        <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-400 bg-slate-950/80 px-2 py-1.5 rounded border border-slate-800/80 gap-1">
                          <span className="font-mono text-slate-300">
                            Excerpt Fingerprint: {ev.evidence_id}
                          </span>
                          <span className="text-slate-500 text-[10px]">
                            Content Hash (SHA-256): Evaluated text snippet fingerprint (proves content identity, not publisher authenticity or tamper-proof storage)
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1">
                          <span>Retrieved: {new Date(ev.retrieved_at).toUTCString()}</span>
                          <span>Trust Status: {ev.source_trust.toUpperCase()}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Tab 4: AST Scope & Checks Performed */}
              {activeTab === "ast" && (
                <div className="space-y-3 text-xs">
                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
                    <span className="font-semibold text-slate-200">Deterministic Checks Performed:</span>
                    <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px]">
                      {report.checks_performed.map((chk, i) => (
                        <li key={i}>{chk}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
                    <span className="font-semibold text-slate-200">Limitations and Caveats:</span>
                    <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px]">
                      {report.limitations_and_caveats.map((lim, i) => (
                        <li key={i}>{lim}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {/* Tab 5: Fix Proposal & Safe Re-Verification */}
              {activeTab === "fixes" && (
                <div className="space-y-4">
                  {isProposing ? (
                    <div className="p-8 rounded-lg bg-slate-900/60 border border-slate-800 flex flex-col items-center justify-center space-y-3 text-xs text-slate-300">
                      <RefreshCw className="w-6 h-6 text-accent-cyan animate-spin" />
                      <p className="font-semibold text-slate-200">Evaluating Authoritative Evidence & Generating Safe Proposal...</p>
                      <p className="text-[11px] text-slate-400">Performing in-memory deterministic transformation, AST syntax re-validation, and evidence re-adjudication.</p>
                    </div>
                  ) : proposalError ? (
                    <div className="p-4 rounded-lg bg-rose-950/30 border border-rose-800 text-xs text-rose-300 space-y-2">
                      <div className="flex items-center space-x-2 text-rose-400 font-semibold">
                        <AlertCircle className="w-4 h-4" />
                        <span>Fix Proposal Generation Failed</span>
                      </div>
                      <p className="text-slate-300">{proposalError}</p>
                    </div>
                  ) : !proposal ? (
                    <div className="p-6 rounded-lg bg-slate-900/60 border border-slate-800 text-xs text-slate-400 text-center space-y-2">
                      <Wrench className="w-8 h-8 text-slate-500 mx-auto" />
                      <p className="font-medium text-slate-300">No Fix Proposal Selected</p>
                      <p className="text-[11px] text-slate-400 max-w-md mx-auto">
                        Click <span className="font-semibold text-accent-cyan">"Propose Fix"</span> beside any verified issue or API candidate to generate an evidence-gated migration proposal with in-memory static re-verification.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3.5">
                      {/* Proposal Header */}
                      <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-lg bg-slate-900/80 border border-slate-800">
                        <div className="flex items-center space-x-2 text-xs">
                          <span className="font-mono text-[11px] text-slate-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                            {proposal.proposal_id}
                          </span>
                          <span className="text-slate-400 text-xs">
                            Candidate: <span className="text-slate-200 font-mono">{proposal.candidate_id}</span>
                          </span>
                        </div>

                        {/* Status Badge */}
                        <div className="flex items-center space-x-2 text-xs">
                          {proposal.status === "evidence_supported" && (
                            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700 flex items-center space-x-1">
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                              <span>EVIDENCE SUPPORTED</span>
                            </span>
                          )}
                          {proposal.status === "mock_evidence_only" && (
                            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-amber-950 text-amber-300 border border-amber-700 flex items-center space-x-1">
                              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                              <span>MOCK EVIDENCE ONLY</span>
                            </span>
                          )}
                          {proposal.status === "insufficient_evidence" && (
                            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-slate-800 text-slate-300 border border-slate-700 flex items-center space-x-1">
                              <Info className="w-3.5 h-3.5 text-slate-400" />
                              <span>INSUFFICIENT EVIDENCE</span>
                            </span>
                          )}
                          {proposal.status === "unsupported_candidate" && (
                            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-slate-800 text-slate-400 border border-slate-700">
                              UNSUPPORTED CANDIDATE
                            </span>
                          )}
                          {(proposal.status === "syntax_check_failed" || proposal.status === "proposal_invalid") && (
                            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold bg-rose-950 text-rose-300 border border-rose-800 flex items-center space-x-1">
                              <XCircle className="w-3.5 h-3.5 text-rose-400" />
                              <span>{proposal.status.replace(/_/g, " ").toUpperCase()}</span>
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Mock Quarantine Warning */}
                      {proposal.is_mock && (
                        <div className="p-3 rounded-lg bg-amber-950/40 border border-amber-800/80 text-xs text-amber-200 flex items-start space-x-2">
                          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <span className="font-semibold text-amber-300">Mock Mode Quarantine: </span>
                            <span>
                              This proposal was generated using offline mock fixtures. Mock evidence is strictly quarantined and cannot
                              produce an evidence-supported production fix. The edit below is shown for illustrative evaluation only.
                            </span>
                          </div>
                        </div>
                      )}

                      {/* Re-Verification Status Panel */}
                      <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-2 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
                          <span className="font-semibold text-slate-200 flex items-center space-x-1.5">
                            <Shield className="w-3.5 h-3.5 text-accent-cyan" />
                            <span>Static Re-Verification Assessment</span>
                          </span>
                          <div className="flex items-center space-x-2">
                            {proposal.syntax_valid ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
                                SYNTAX VALID
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-950 text-rose-300 border border-rose-800">
                                SYNTAX INVALID
                              </span>
                            )}
                            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700 uppercase">
                              Reverification: {proposal.reverification_status.replace(/_/g, " ")}
                            </span>
                          </div>
                        </div>

                        {/* Syntax Validity Caveat */}
                        <div className="p-2 rounded bg-amber-950/30 border border-amber-800/60 text-[11px] text-amber-200 flex items-start space-x-2">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
                          <span>
                            <strong>Syntax Caveat: </strong>Valid syntax confirms that proposed code parses into a Python AST. It does NOT prove runtime correctness, functional equivalence, or bug freedom. Developer review is required before applying.
                          </span>
                        </div>

                        <p className="text-slate-200 font-medium">{proposal.summary}</p>
                        <p className="text-slate-400 text-[11px] leading-relaxed">{proposal.reasoning}</p>

                        {proposal.warnings.length > 0 && (
                          <div className="pt-1.5 space-y-1">
                            {proposal.warnings.map((w, idx) => (
                              <p key={idx} className="text-[11px] text-amber-300/90 flex items-start space-x-1.5">
                                <span className="text-amber-500 font-bold">•</span>
                                <span>{w}</span>
                              </p>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Unified Diff View */}
                      {proposal.unified_diff && (
                        <div data-testid="diff-view" className="rounded-lg border border-slate-800 bg-slate-950 overflow-hidden text-xs">
                          <div className="px-3 py-2 bg-slate-900 border-b border-slate-800 text-[11px] font-mono text-slate-400 flex items-center justify-between">
                            <span className="flex items-center space-x-1.5">
                              <Terminal className="w-3 h-3 text-accent-cyan" />
                              <span>Unified Diff (In-Memory Proposal)</span>
                            </span>
                            <span className="text-slate-500 text-[10px]">Zero-overwrite guarantee</span>
                          </div>
                          <pre className="p-3 font-mono text-[11px] overflow-x-auto leading-relaxed max-h-48 select-text">
                            {proposal.unified_diff.split("\n").map((line, i) => {
                              const isAdd = line.startsWith("+") && !line.startsWith("+++");
                              const isDel = line.startsWith("-") && !line.startsWith("---");
                              const isHunk = line.startsWith("@@");
                              return (
                                <div
                                  key={i}
                                  className={
                                    isAdd
                                      ? "text-emerald-400 bg-emerald-950/40 px-1 -mx-1"
                                      : isDel
                                      ? "text-rose-400 bg-rose-950/40 px-1 -mx-1"
                                      : isHunk
                                      ? "text-accent-cyan"
                                      : "text-slate-300"
                                  }
                                >
                                  {line || " "}
                                </div>
                              );
                            })}
                          </pre>
                        </div>
                      )}

                      {/* Supporting Evidence Receipts */}
                      {proposal.supporting_quotes.length > 0 && (
                        <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5 text-xs">
                          <span className="font-semibold text-accent-cyan text-[11px] flex items-center space-x-1.5">
                            <Quote className="w-3.5 h-3.5" />
                            <span>Supporting Official Documentation Receipt:</span>
                          </span>
                          {proposal.supporting_quotes.map((q, idx) => (
                            <blockquote key={idx} className="italic text-slate-200 border-l-2 border-accent-cyan pl-3 text-xs leading-relaxed">
                              "{q}"
                            </blockquote>
                          ))}
                          {proposal.source_urls.length > 0 && (
                            <div className="pt-1 flex flex-wrap gap-2 text-[10px]">
                              {proposal.source_urls.map((url, idx) => (
                                <a
                                  key={idx}
                                  href={url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-accent-cyan hover:underline flex items-center space-x-1 font-mono"
                                >
                                  <span>{url}</span>
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Remaining Uncertainties */}
                      {proposal.remaining_uncertainties.length > 0 && (
                        <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 space-y-1.5 text-xs">
                          <div className="font-semibold text-slate-300 text-[11px] flex items-center space-x-1.5">
                            <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
                            <span>What Remains Unverified:</span>
                          </div>
                          <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px]">
                            {proposal.remaining_uncertainties.map((unc, idx) => (
                              <li key={idx}>{unc}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Action Toolbar */}
                      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800">
                        <span className="text-[10px] text-slate-500 italic">
                          A fix proposal is a suggestion, not a guarantee of runtime correctness. Local files are never automatically modified.
                        </span>
                        <div className="flex items-center space-x-2">
                          <button
                            onClick={handleDiscardFix}
                            data-testid="discard-fix-button"
                            aria-label="Discard proposed fix and preserve original code"
                            className="px-3 py-1.5 rounded bg-slate-800/90 hover:bg-rose-950/70 hover:text-rose-300 text-slate-400 border border-slate-700 text-xs font-semibold flex items-center space-x-1.5 transition-colors"
                          >
                            <XCircle className="w-3.5 h-3.5 text-rose-400" />
                            <span>Discard Proposal</span>
                          </button>

                          <button
                            onClick={handleCopyFix}
                            data-testid="copy-fix-button"
                            aria-label="Copy proposed fix to clipboard"
                            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold flex items-center space-x-1.5 transition-colors"
                          >
                            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                            <span>{copied ? "Copied!" : "Copy Proposed Fix"}</span>
                          </button>

                          {proposal.proposed_source && (
                            <button
                              onClick={handleApplyFixToEditor}
                              data-testid="apply-fix-button"
                              aria-label="Apply proposed fix directly to editor"
                              className="px-3 py-1.5 rounded bg-gradient-to-r from-accent-violet to-accent-cyan hover:opacity-90 text-white font-semibold text-xs flex items-center space-x-1.5 shadow-md transition-opacity"
                            >
                              <ArrowRight className="w-3.5 h-3.5" />
                              <span>Use Proposed Version in Editor</span>
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Initial Empty State Card */}
        {!report && !isAnalyzing && (
          <div
            data-testid="initial-empty-state"
            className="rounded-xl border border-border bg-background-panel p-6 shadow-xl space-y-4"
          >
            <div className="flex items-start space-x-3">
              <div className="p-2.5 rounded-lg bg-violet-950/60 border border-violet-800 text-violet-300 mt-0.5">
                <Scale className="w-5 h-5 text-accent-cyan" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-slate-100">
                  {code.trim() ? "Ready for Static API Contract Analysis" : "Code Editor is Empty"}
                </h3>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {code.trim()
                    ? "Click 'Verify with Evidence Court' to parse the Python snippet into an abstract syntax tree and evaluate Stripe SDK calls against official documentation."
                    : "Paste or write Python code into the editor above, or select one of the presets to evaluate against official Stripe API contracts."}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-1.5">
                <span className="font-semibold text-slate-200 flex items-center space-x-1.5">
                  <Layers className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>Zero-Execution Guarantee</span>
                </span>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Submitted code is never imported, executed, or evaluated. Verification is performed entirely via static AST inspection.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-1.5">
                <span className="font-semibold text-slate-200 flex items-center space-x-1.5">
                  <BookOpen className="w-3.5 h-3.5 text-accent-violet" />
                  <span>Official Documentation</span>
                </span>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Findings require exact quotation receipts from official Stripe documentation (docs.stripe.com).
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-1.5">
                <span className="font-semibold text-slate-200 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Supported Scope</span>
                </span>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Active ecosystem: Python Stripe SDK (`stripe`). Calls to unsupported packages are preserved with honest abstention.
                </p>
              </div>
            </div>

            {!code.trim() && (
              <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/80">
                <span className="text-[11px] text-slate-400 font-medium">Quick load preset:</span>
                <button
                  onClick={() => handleSnippetSelect(SNIPPET_STRIPE_INTENT_CLEAN)}
                  data-testid="empty-load-clean-btn"
                  className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-[11px] font-medium transition-colors"
                >
                  PaymentIntent (Clean)
                </button>
                <button
                  onClick={() => handleSnippetSelect(SNIPPET_STRIPE_CHARGE_DEPRECATED)}
                  data-testid="empty-load-deprecated-btn"
                  className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-[11px] font-medium transition-colors"
                >
                  Charge (Legacy Deprecated)
                </button>
                <button
                  onClick={() => handleSnippetSelect(SNIPPET_NON_API)}
                  data-testid="empty-load-nonapi-btn"
                  className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-[11px] font-medium transition-colors"
                >
                  Non-API Code (Abstain)
                </button>
              </div>
            )}
          </div>
        )}

      </div>

      {/* Right 4 Cols: Verification Modules Status Panel */}
      <div className="lg:col-span-4 flex flex-col space-y-4">
        <div className="rounded-xl border border-border bg-background-panel p-5 shadow-xl flex-1 flex flex-col">
          <div className="flex items-center space-x-2 mb-4 pb-3 border-b border-border-subtle">
            <Layers className="w-4 h-4 text-accent-violet" />
            <h2 className="text-sm font-semibold text-white">Pipeline Status</h2>
          </div>

          <div className="space-y-3.5 flex-1">
            {/* AST Analysis - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Static AST Analysis</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                Zero-execution parsing of imports, calls, defs, parameters & heuristic candidates.
              </p>
            </div>

            {/* Doc Retrieval - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Documentation Retrieval</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                TinyFish adapter with canonical domain allowlists & strict SSRF defense. Configured status indicates credentials exist; live connectivity is evaluated on request.
              </p>
            </div>

            {/* Evidence Court & Quote Verifier - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Evidence Court & Verifier</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                Deterministic quote verification, contract matching & conservative adjudication.
              </p>
            </div>

            {/* LLM Candidate Reasoning - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>LLM Candidate Reasoning</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                Structured candidate interpretations, hypotheses & suggested documentation paths. Strictly advisory; cannot alter verdicts.
              </p>
            </div>

            {/* Fix Proposals & Safe Re-Verification - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Fix Proposals & Re-Verification</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                Deterministic line-bounded patch proposals with in-memory static re-verification. Valid syntax does not prove runtime correctness.
              </p>
            </div>

            {/* SQLite Audit Persistence - ACTIVE */}
            <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-emerald-300 flex items-center space-x-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>SQLite Audit Persistence</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-900/60 text-emerald-300 border border-emerald-700/60 font-semibold">
                  Active
                </span>
              </div>
              <p className="text-[11px] text-slate-300 mt-1">
                Zero-source audit logging, canonical evidence relations & SHA-256 fingerprints. Local hash aids integrity, not blockchain immutability.
              </p>
            </div>

          </div>

          <div className="mt-4 pt-3 border-t border-border-subtle text-[11px] text-slate-400 text-center">
            The model proposes; deterministic code decides.
          </div>
        </div>
      </div>
    </div>
  )}
</div>
  );
};
