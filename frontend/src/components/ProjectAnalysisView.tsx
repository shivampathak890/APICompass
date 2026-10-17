import React, { useState, useRef } from "react";
import {
  FolderTree,
  FileCode,
  Plus,
  Play,
  Shield,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ArrowRight,
  GitBranch,
  Sparkles,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import { MonacoPythonEditor } from "./MonacoPythonEditor";
import { analyzeProject } from "../services/api";
import {
  ProjectAnalysisReport,
  ProjectFileItem,
} from "../types/project";
import { FindingCard } from "./FindingCard";

const PRESET_MIGRATION: ProjectFileItem[] = [
  {
    path: "main.py",
    content: `# Entry point for processing user checkout
from services.payment import process_order

def handle_checkout(amount_cents: int, token: str):
    print("Initiating checkout flow...")
    return process_order(amount_cents, token)
`,
  },
  {
    path: "services/payment.py",
    content: `# Payment processing service
import stripe

stripe.api_key = "sk_test_placeholder_key"

def process_order(amount: int, token: str):
    # APICompass Evidence Court will detect deprecated 'source' parameter
    charge = stripe.Charge.create(
        amount=amount,
        currency="usd",
        source=token,
        description="E-commerce checkout order"
    )
    return charge["id"]
`,
  },
  {
    path: "services/__init__.py",
    content: `# Package initialization
SERVICE_NAME = "payment_services"
SERVICE_VERSION = "2.1.0"
`,
  },
];

const PRESET_CLEAN: ProjectFileItem[] = [
  {
    path: "app.py",
    content: `# Modern application entry point
from billing.intents import create_checkout_session

async def run():
    client_secret = await create_checkout_session("cus_123", 2500)
    return client_secret
`,
  },
  {
    path: "billing/intents.py",
    content: `# Modern Stripe PaymentIntent service compliant with official contracts
import stripe

stripe.api_key = "sk_test_modern_key"

async def create_checkout_session(customer_id: str, amount: int):
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        customer=customer_id,
        automatic_payment_methods={"enabled": True}
    )
    return intent.client_secret
`,
  },
];

const PRESET_CIRCULAR: ProjectFileItem[] = [
  {
    path: "mod_alpha.py",
    content: `# Module Alpha
import mod_beta

def alpha_task():
    return mod_beta.beta_task()
`,
  },
  {
    path: "mod_beta.py",
    content: `# Module Beta
import mod_alpha

def beta_task():
    return "Beta completed"
`,
  },
];

const PRESET_SYNTAX_ERROR: ProjectFileItem[] = [
  {
    path: "broken_module.py",
    content: `# Broken Python file with a syntax error
def incomplete_function(
    return stripe.Charge.create()
`,
  },
  {
    path: "valid_worker.py",
    content: `# Valid Python file parsed independently
import stripe

def run_worker():
    return stripe.PaymentIntent.create(amount=1000, currency="usd")
`,
  },
];

interface ProjectAnalysisViewProps {
  onBackToSingleFile?: () => void;
}

type ProjectTab = "summary" | "graph" | "issues" | "files" | "evidence" | "suggestions";

export const ProjectAnalysisView: React.FC<ProjectAnalysisViewProps> = () => {
  const [files, setFiles] = useState<ProjectFileItem[]>(PRESET_MIGRATION);
  const [activeFilePath, setActiveFilePath] = useState<string>("main.py");
  const [activeTab, setActiveTab] = useState<ProjectTab>("summary");
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [report, setReport] = useState<ProjectAnalysisReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef<number>(0);

  // New file input state
  const [isAddingFile, setIsAddingFile] = useState<boolean>(false);
  const [newFilePath, setNewFilePath] = useState<string>("");
  const [addFileError, setAddFileError] = useState<string | null>(null);
  const [targetHighlightLine, setTargetHighlightLine] = useState<number | null>(null);

  const activeFile = files.find((f) => f.path === activeFilePath) || files[0];

  const handleUpdateActiveFileCode = (newContent: string) => {
    setFiles((prev) =>
      prev.map((f) => (f.path === activeFilePath ? { ...f, content: newContent } : f))
    );
  };

  const handleSelectPreset = (preset: ProjectFileItem[]) => {
    requestIdRef.current++;
    setFiles(preset);
    setActiveFilePath(preset[0].path);
    setReport(null);
    setError(null);
  };

  const handleAddFile = () => {
    const trimmed = newFilePath.trim().replace(/\\/g, "/");
    if (!trimmed) {
      setAddFileError("File path cannot be empty.");
      return;
    }
    if (!trimmed.toLowerCase().endsWith(".py") || trimmed.toLowerCase() === ".py") {
      setAddFileError("Only Python files (.py) are supported.");
      return;
    }
    if (files.some((f) => f.path.toLowerCase() === trimmed.toLowerCase())) {
      setAddFileError(`File '${trimmed}' already exists in this project.`);
      return;
    }
    if (trimmed.startsWith("/") || trimmed.includes("..")) {
      setAddFileError("Path must be a relative project path without traversal components.");
      return;
    }

    const newFile: ProjectFileItem = {
      path: trimmed,
      content: `# Python module: ${trimmed}\n\ndef example():\n    pass\n`,
    };

    setFiles((prev) => [...prev, newFile]);
    setActiveFilePath(trimmed);
    setNewFilePath("");
    setAddFileError(null);
    setIsAddingFile(false);
  };

  const handleRemoveFile = (pathToRemove: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (files.length <= 1) {
      return;
    }
    const remaining = files.filter((f) => f.path !== pathToRemove);
    setFiles(remaining);
    if (activeFilePath === pathToRemove) {
      setActiveFilePath(remaining[0].path);
    }
  };

  const handleRunProjectAnalysis = async () => {
    if (isAnalyzing) return;
    const currentRequestId = ++requestIdRef.current;
    setIsAnalyzing(true);
    setError(null);

    try {
      const res = await analyzeProject({
        project_name: "workspace_project",
        ecosystem: "stripe",
        files: files,
      });
      // Guard against stale response if a newer request was dispatched
      if (currentRequestId !== requestIdRef.current) {
        return;
      }
      setReport(res);
      setActiveTab("summary");
    } catch (err: unknown) {
      if (currentRequestId !== requestIdRef.current) {
        return;
      }
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unknown error occurred during multi-file project analysis.");
      }
    } finally {
      if (currentRequestId === requestIdRef.current) {
        setIsAnalyzing(false);
      }
    }
  };

  const handleJumpToFileAndLine = (filePath?: string | null, line?: number | null) => {
    if (filePath && files.some((f) => f.path === filePath)) {
      setActiveFilePath(filePath);
      if (typeof line === "number") {
        setTargetHighlightLine(line);
      }
    }
  };

  // Helper for verdict badge
  const renderVerdictBadge = (verdict: string, isMock: boolean) => {
    if (isMock || verdict === "unable_to_verify") {
      return (
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-950/80 text-amber-300 border border-amber-800">
          <AlertTriangle className="w-3.5 h-3.5 mr-1.5" />
          {isMock ? "Mock Fixture Quarantine (Unable to Verify)" : "Unable to Verify (Abstained)"}
        </span>
      );
    }
    if (verdict === "issues_found") {
      return (
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-red-950/80 text-red-300 border border-red-800">
          <XCircle className="w-3.5 h-3.5 mr-1.5" />
          Contract Violations Found
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800">
        <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
        Verified Clean
      </span>
    );
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 p-6 max-w-7xl mx-auto flex-1 w-full">
      {/* Left 7 Cols: Multi-File Project Manager & Monaco Editor */}
      <div className="lg:col-span-7 flex flex-col space-y-4">
        {/* Project Header Bar */}
        <div className="flex flex-col rounded-xl border border-border bg-background-panel shadow-2xl overflow-hidden">
          {/* Presets and Controls */}
          <div className="flex flex-wrap items-center justify-between px-4 py-2.5 bg-slate-900/90 border-b border-border-subtle text-xs gap-2">
            <div className="flex items-center space-x-2 text-slate-300">
              <FolderTree className="w-4 h-4 text-amber-400" />
              <span className="font-semibold text-slate-200">Multi-File Project</span>
              <span className="text-slate-400 font-mono text-[11px]">({files.length} files)</span>
            </div>

            <div className="flex items-center space-x-1.5">
              <span className="text-[11px] text-slate-400">Presets:</span>
              <button
                onClick={() => handleSelectPreset(PRESET_MIGRATION)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
              >
                Stripe Migration
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_CLEAN)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
              >
                Clean Intent
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_CIRCULAR)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
              >
                Circular
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_SYNTAX_ERROR)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors border border-slate-700"
              >
                Syntax Error
              </button>
            </div>
          </div>

          {/* File Tabs Bar */}
          <div className="flex items-center px-3 py-2 bg-slate-950/80 border-b border-border-subtle overflow-x-auto space-x-1">
            {files.map((file) => {
              const isActive = file.path === activeFilePath;
              return (
                <button
                  key={file.path}
                  onClick={() => setActiveFilePath(file.path)}
                  className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition-all border ${
                    isActive
                      ? "bg-slate-800 text-amber-300 border-amber-500/50 shadow-sm"
                      : "bg-slate-900/60 text-slate-400 border-slate-800 hover:bg-slate-800/60 hover:text-slate-200"
                  }`}
                >
                  <FileCode className={`w-3.5 h-3.5 ${isActive ? "text-amber-400" : "text-slate-400"}`} />
                  <span>{file.path}</span>
                  {files.length > 1 && (
                    <span
                      onClick={(e) => handleRemoveFile(file.path, e)}
                      title="Remove file"
                      className="ml-1 text-slate-400 hover:text-red-400 p-0.5 rounded"
                    >
                      ×
                    </span>
                  )}
                </button>
              );
            })}

            {/* Add File Button */}
            {!isAddingFile ? (
              <button
                onClick={() => setIsAddingFile(true)}
                data-testid="new-file-open-btn"
                className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-amber-300 hover:bg-slate-800/70 border border-dashed border-slate-700 transition-colors"
                title="Add Python file"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New File</span>
              </button>
            ) : (
              <div className="flex items-center space-x-1 bg-slate-900 p-1 rounded-lg border border-slate-700">
                <input
                  type="text"
                  placeholder="e.g. utils/calc.py"
                  data-testid="new-file-input"
                  value={newFilePath}
                  onChange={(e) => {
                    setNewFilePath(e.target.value);
                    setAddFileError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleAddFile();
                    if (e.key === "Escape") {
                      setIsAddingFile(false);
                      setAddFileError(null);
                    }
                  }}
                  autoFocus
                  className="bg-slate-950 text-slate-200 text-xs px-2 py-1 rounded border border-slate-700 outline-none w-36 font-mono"
                />
                <button
                  onClick={handleAddFile}
                  data-testid="add-file-btn"
                  className="bg-amber-600 hover:bg-amber-500 text-slate-950 text-xs px-2 py-1 rounded font-semibold"
                >
                  Add
                </button>
                <button
                  onClick={() => {
                    setIsAddingFile(false);
                    setAddFileError(null);
                  }}
                  className="text-slate-400 hover:text-slate-200 text-xs px-1.5 py-1"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>

          {addFileError && (
            <div className="px-4 py-1.5 bg-red-950/60 border-b border-red-800/50 text-red-300 text-xs flex items-center space-x-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
              <span>{addFileError}</span>
            </div>
          )}

          {/* Active File Header */}
          <div className="px-4 py-1.5 bg-slate-900/60 border-b border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
            <span className="font-mono">Editing: {activeFile.path}</span>
            <span>{activeFile.content.split("\n").length} lines</span>
          </div>

          {/* Monaco Editor */}
          <MonacoPythonEditor
            code={activeFile.content}
            onChange={handleUpdateActiveFileCode}
            readOnly={isAnalyzing}
            syntaxError={report?.files.find((f) => f.path === activeFile.path)?.syntax_error}
            targetLine={targetHighlightLine}
            height="340px"
          />

          {/* Action Bar */}
          <div className="px-4 py-3 bg-slate-900/80 border-t border-border-subtle flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center space-x-2 text-xs text-slate-400">
              <Shield className="w-4 h-4 text-emerald-400" />
              <span>Zero Execution Guarantee: files are parsed via static AST only.</span>
            </div>

            <button
              onClick={handleRunProjectAnalysis}
              disabled={isAnalyzing}
              data-testid="analyze-project-button"
              className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center space-x-2 shadow-lg transition-all ${
                isAnalyzing
                  ? "bg-slate-800 text-slate-400 cursor-not-allowed"
                  : "bg-amber-500 hover:bg-amber-400 text-slate-950 shadow-amber-950/50"
              }`}
            >
              {isAnalyzing ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-slate-400" />
                  <span>Analyzing Project...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-slate-950" />
                  <span>Analyze Project</span>
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-xl border border-red-800 bg-red-950/60 text-red-200 text-xs flex items-start space-x-3">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Project Analysis Error</p>
              <p className="text-red-300 mt-0.5">{error}</p>
            </div>
          </div>
        )}
      </div>

      {/* Right 5 Cols: Project Evidence Court & Dependency Results */}
      <div className="lg:col-span-5 flex flex-col space-y-4">
        <div className="flex flex-col rounded-xl border border-border bg-background-panel shadow-2xl overflow-hidden min-h-[500px]">
          {/* Navigation Tabs */}
          <div className="flex items-center border-b border-border-subtle bg-slate-950/80 px-2 py-1 overflow-x-auto text-xs">
            <button
              onClick={() => setActiveTab("summary")}
              data-testid="project-tab-summary"
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                activeTab === "summary"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Summary
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              data-testid="project-tab-graph"
              className={`px-3 py-1.5 rounded-lg font-medium flex items-center space-x-1.5 transition-colors ${
                activeTab === "graph"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <GitBranch className="w-3.5 h-3.5" />
              <span>Dependencies</span>
              {report && (
                <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-700 text-slate-300">
                  {report.relationships.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("issues")}
              data-testid="project-tab-issues"
              className={`px-3 py-1.5 rounded-lg font-medium flex items-center space-x-1.5 transition-colors ${
                activeTab === "issues"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>Issues</span>
              {report && (
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                    report.verified_issues.length > 0
                      ? "bg-red-950 text-red-300 border border-red-800"
                      : "bg-slate-700 text-slate-300"
                  }`}
                >
                  {report.verified_issues.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("files")}
              data-testid="project-tab-files"
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                activeTab === "files"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Files
            </button>
            <button
              onClick={() => setActiveTab("evidence")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                activeTab === "evidence"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Evidence
            </button>
            <button
              onClick={() => setActiveTab("suggestions")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                activeTab === "suggestions"
                  ? "bg-slate-800 text-amber-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              AI Insights
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-4 flex-1 overflow-y-auto max-h-[600px] text-xs">
            {!report ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-16 text-slate-400 space-y-3">
                <FolderTree className="w-10 h-10 text-slate-600" />
                <p className="font-medium text-slate-300">Ready for Project Analysis</p>
                <p className="text-[11px] max-w-xs text-slate-400">
                  Click <span className="text-amber-400 font-semibold">Analyze Project</span> to parse all files, resolve
                  cross-file imports, and verify API contracts against official evidence.
                </p>
              </div>
            ) : (
              <>
                {/* 1. Summary Tab */}
                {activeTab === "summary" && (
                  <div className="space-y-4">
                    {/* Verdict Banner */}
                    <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
                          Project Verdict
                        </span>
                        {renderVerdictBadge(report.verdict, report.is_mock)}
                      </div>
                      <p className="text-slate-200 font-medium leading-relaxed">{report.summary}</p>
                    </div>

                    {/* Stats Metrics Grid */}
                    <div className="grid grid-cols-2 gap-2 text-center">
                      <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
                        <span className="text-slate-400 text-[10px] block">Total Files</span>
                        <span className="text-base font-bold text-slate-200 font-mono">{report.total_files}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
                        <span className="text-slate-400 text-[10px] block">Total Lines</span>
                        <span className="text-base font-bold text-slate-200 font-mono">{report.total_lines}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
                        <span className="text-slate-400 text-[10px] block">API Candidates</span>
                        <span className="text-base font-bold text-slate-200 font-mono">{report.total_candidates}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
                        <span className="text-slate-400 text-[10px] block">Resolved Imports</span>
                        <span className="text-base font-bold text-emerald-400 font-mono">
                          {report.resolved_imports_count}
                        </span>
                      </div>
                    </div>

                    {/* Incomplete Analysis Warning if Syntax Errors */}
                    {report.syntax_errors_count > 0 && (
                      <div className="p-3.5 rounded-xl border border-rose-900/60 bg-rose-950/40 text-rose-200 space-y-1">
                        <div className="flex items-center space-x-1.5 font-semibold text-rose-300 text-xs">
                          <AlertCircle className="w-4 h-4 text-rose-400" />
                          <span>Incomplete Analysis Warning: {report.syntax_errors_count} of {report.total_files} file(s) failed syntax parsing</span>
                        </div>
                        <p className="text-[11px] text-rose-300/90 leading-relaxed">
                          Files with syntax errors could not be parsed into ASTs. The overall project verdict cannot certify absence of issues in unparsed files.
                        </p>
                      </div>
                    )}

                    {/* Unresolved Imports Warning */}
                    {report.unresolved_imports_count > 0 && (
                      <div className="p-3 rounded-xl border border-amber-900/60 bg-amber-950/30 text-amber-200 space-y-1">
                        <div className="flex items-center space-x-1.5 font-semibold text-amber-300 text-xs">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                          <span>Import Resolution Caveat: {report.unresolved_imports_count} internal import(s) could not be statically resolved</span>
                        </div>
                        <p className="text-[11px] text-amber-200/90 leading-relaxed">
                          Cross-module call chains depending on these unresolved imports may not be fully evaluated.
                        </p>
                      </div>
                    )}

                    {/* Limitations & Caveats */}
                    {report.limitations_and_caveats.length > 0 && (
                      <div className="p-3.5 rounded-xl border border-amber-900/50 bg-amber-950/30 text-amber-200 space-y-1.5">
                        <div className="flex items-center space-x-1.5 font-semibold text-amber-300 text-[11px]">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>Limitations & Caveats</span>
                        </div>
                        <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-200/90 pl-1">
                          {report.limitations_and_caveats.map((c, idx) => (
                            <li key={idx}>{c}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Disclaimer */}
                    <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800/80 text-[11px] text-slate-400 leading-relaxed">
                      {report.disclaimer}
                    </div>
                  </div>
                )}

                {/* 2. Dependencies & Graph Tab */}
                {activeTab === "graph" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-slate-400 text-[11px]">
                      <span>Cross-File Relationships</span>
                      <span>{report.relationships.length} total edges</span>
                    </div>

                    {report.relationships.length === 0 ? (
                      <p className="text-slate-400 text-center py-8">No import statements detected in project.</p>
                    ) : (
                      <div className="space-y-2">
                        {report.relationships.map((rel, idx) => {
                          const statusColor =
                            rel.status === "resolved"
                              ? "text-emerald-400 border-emerald-900/60 bg-emerald-950/40"
                              : rel.status === "unresolved"
                              ? "text-amber-400 border-amber-900/60 bg-amber-950/40"
                              : rel.status === "ambiguous"
                              ? "text-purple-400 border-purple-900/60 bg-purple-950/40"
                              : "text-blue-400 border-blue-900/60 bg-blue-950/40";

                          return (
                            <div
                              key={idx}
                              className="p-3 rounded-lg border border-slate-800 bg-slate-900/70 space-y-1.5 font-sans"
                            >
                              <div className="flex items-center justify-between font-mono text-[11px]">
                                <span className="text-slate-300 font-semibold">{rel.source_file}</span>
                                <ArrowRight className="w-3 h-3 text-slate-400 mx-1 shrink-0" />
                                <span className="text-amber-300 font-semibold truncate max-w-[150px]">
                                  {rel.target}
                                </span>
                                <span className={`ml-auto px-2 py-0.5 rounded text-[10px] border ${statusColor}`}>
                                  {rel.status}
                                </span>
                              </div>
                              <p className="text-[11px] text-slate-400">{rel.reason}</p>
                              {rel.target_file && (
                                <button
                                  onClick={() => handleJumpToFileAndLine(rel.target_file)}
                                  className="text-[10px] text-amber-400 hover:underline flex items-center space-x-1"
                                >
                                  <span>View target file ({rel.target_file})</span>
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* 3. Verified Issues Tab */}
                {activeTab === "issues" && (
                  <div className="space-y-3">
                    {report.verified_issues.length === 0 ? (
                      <div className="text-center py-12 text-slate-400 space-y-2">
                        <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto" />
                        <p className="text-slate-300 font-medium">No Contract Violations Found</p>
                        <p className="text-[11px]">
                          {report.verdict === "unable_to_verify"
                            ? "Analysis abstained from certifying cleanliness due to incomplete/mock evidence."
                            : "All evaluated candidates adhere to official documentation contracts."}
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {report.verified_issues.map((issue) => (
                          <FindingCard
                            key={issue.issue_id}
                            id={issue.issue_id}
                            issueId={issue.issue_id}
                            candidateId={issue.candidate_id}
                            status={issue.verification_status || "verified"}
                            title={issue.title || `${issue.violation_type.replace(/_/g, " ").toUpperCase()}: ${issue.claim_checked}`}
                            impactClassification={issue.impact_classification || issue.violation_type.replace(/_/g, " ").toUpperCase()}
                            filePath={issue.file_path}
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
                              if (issue.file_path) {
                                handleJumpToFileAndLine(issue.file_path, line ?? issue.source_location.lineno);
                              }
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 4. Files Tab */}
                {activeTab === "files" && (
                  <div className="space-y-3">
                    {report.files.map((file) => (
                      <div
                        key={file.path}
                        className="p-3 rounded-lg border border-slate-800 bg-slate-900/60 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-semibold text-slate-200">{file.path}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] border ${
                              file.parse_status === "success"
                                ? "text-emerald-400 bg-emerald-950/60 border-emerald-900"
                                : "text-red-400 bg-red-950/60 border-red-900"
                            }`}
                          >
                            {file.parse_status}
                          </span>
                        </div>

                        {file.syntax_error && (
                          <div className="p-2 rounded bg-red-950/40 border border-red-800 text-red-300 text-[11px]">
                            Syntax Error (Line {file.syntax_error.lineno}): {file.syntax_error.message}
                          </div>
                        )}

                        <div className="grid grid-cols-3 gap-1.5 text-center text-[10px]">
                          <div className="p-1 rounded bg-slate-800/80">
                            <span className="text-slate-400">Lines:</span> {file.total_lines}
                          </div>
                          <div className="p-1 rounded bg-slate-800/80">
                            <span className="text-slate-400">Imports:</span> {file.imports.length}
                          </div>
                          <div className="p-1 rounded bg-slate-800/80">
                            <span className="text-slate-400">Candidates:</span> {file.candidates.length}
                          </div>
                        </div>

                        {file.defined_symbols.length > 0 && (
                          <div className="text-[10px] text-slate-400">
                            <span className="font-semibold text-slate-300">Top-Level Symbols: </span>
                            <span className="font-mono text-amber-300/80">
                              {file.defined_symbols.slice(0, 5).join(", ")}
                              {file.defined_symbols.length > 5 ? "..." : ""}
                            </span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* 5. Evidence Tab */}
                {activeTab === "evidence" && (
                  <div className="space-y-3">
                    {report.evidence_items.length === 0 ? (
                      <p className="text-slate-400 text-center py-8">No official documentation evidence retrieved.</p>
                    ) : (
                      report.evidence_items.map((ev) => (
                        <div
                          key={ev.evidence_id}
                          className="p-3.5 rounded-lg border border-slate-800 bg-slate-900/60 space-y-2"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center space-x-2">
                              <span className="font-semibold text-slate-200">{ev.title || "Official Stripe Reference"}</span>
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
                            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                              {ev.evidence_id}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-300 italic">"{ev.content_excerpt}"</p>
                          <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-slate-800/80 gap-1">
                            <a
                              href={ev.canonical_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-amber-400 hover:underline flex items-center space-x-1"
                            >
                              <span>{ev.canonical_url}</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                            <span className="text-slate-500 font-mono">
                              Fingerprint (SHA-256): {ev.evidence_id} (identifies excerpt, not publisher authenticity)
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* 6. AI Insights Tab */}
                {activeTab === "suggestions" && (
                  <div className="space-y-3">
                    {/* Advisory Disclaimer */}
                    <div className="p-3 rounded-lg bg-violet-950/40 border border-violet-800/80 text-xs text-violet-200 flex items-start space-x-2">
                      <Sparkles className="w-4 h-4 text-violet-400 flex-shrink-0 mt-0.5" />
                      <div className="space-y-1">
                        <p className="font-semibold text-violet-100">
                          AI Suggestions — Advisory Only (Not Verified)
                        </p>
                        <p className="text-[11px] text-violet-300/90 leading-relaxed">
                          AI suggestions are non-deterministic hypotheses. Model suggestions CANNOT create verified findings or alter the project verdict.
                        </p>
                      </div>
                    </div>

                    {report.ai_suggestions.length === 0 ? (
                      <div className="text-center py-8 text-slate-400 space-y-1">
                        <Sparkles className="w-6 h-6 text-slate-600 mx-auto" />
                        <p>No advisory suggestions generated.</p>
                      </div>
                    ) : (
                      report.ai_suggestions.map((sug) => (
                        <div
                          key={sug.suggestion_id}
                          className="p-3.5 rounded-lg border border-violet-900/60 bg-violet-950/20 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-2">
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-violet-900/60 text-violet-300 border border-violet-700/60">
                                {sug.label}
                              </span>
                              <span className="text-violet-200 font-semibold text-xs">{sug.claim_type.replace(/_/g, " ")}</span>
                            </div>
                            <span className="font-mono text-[10px] text-slate-400">
                              {sug.candidate_id}
                            </span>
                          </div>
                          <p className="text-slate-200 text-xs leading-relaxed">{sug.description}</p>
                          <div className="p-2 rounded bg-slate-950 border border-slate-800/80 text-[11px] space-y-0.5">
                            <span className="font-semibold text-amber-300 text-[10px] block">What Remains Unverified:</span>
                            <p className="text-slate-300 text-[11px]">{sug.unverified_aspects}</p>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
