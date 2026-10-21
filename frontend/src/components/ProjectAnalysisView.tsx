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
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 mr-1.5 text-amber-600" />
          {isMock ? "Mock Fixture Quarantine (Unable to Verify)" : "Unable to Verify (Abstained)"}
        </span>
      );
    }
    if (verdict === "issues_found") {
      return (
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300">
          <XCircle className="w-3.5 h-3.5 mr-1.5 text-rose-600" />
          Contract Violations Found
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
        <CheckCircle2 className="w-3.5 h-3.5 mr-1.5 text-emerald-600" />
        Verified Clean
      </span>
    );
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 p-6 max-w-7xl mx-auto flex-1 w-full">
      {/* Left 7 Cols: Multi-File Project Manager & Monaco Editor */}
      <div className="lg:col-span-7 flex flex-col space-y-4">
        {/* Project Header Bar */}
        <div className="flex flex-col rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden backdrop-blur-sm">
          {/* Presets and Controls */}
          <div className="flex flex-wrap items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-200 text-xs gap-2">
            <div className="flex items-center space-x-2 text-slate-900">
              <FolderTree className="w-4 h-4 text-[#163A6E]" />
              <span className="font-serif font-semibold text-slate-900">Multi-File Project</span>
              <span className="text-slate-500 font-mono text-[11px]">({files.length} files)</span>
            </div>

            <div className="flex items-center space-x-1.5 flex-wrap">
              <span className="text-[11px] text-slate-500">Presets:</span>
              <button
                onClick={() => handleSelectPreset(PRESET_MIGRATION)}
                className="px-2.5 py-0.5 rounded-md bg-white hover:bg-slate-100 text-slate-700 hover:text-slate-900 text-[11px] transition-colors border border-slate-300 hover:border-[#163A6E] shadow-xs"
              >
                Stripe Migration
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_CLEAN)}
                className="px-2.5 py-0.5 rounded-md bg-white hover:bg-slate-100 text-slate-700 hover:text-slate-900 text-[11px] transition-colors border border-slate-300 hover:border-[#163A6E] shadow-xs"
              >
                Clean Intent
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_CIRCULAR)}
                className="px-2.5 py-0.5 rounded-md bg-white hover:bg-slate-100 text-slate-700 hover:text-slate-900 text-[11px] transition-colors border border-slate-300 hover:border-[#163A6E] shadow-xs"
              >
                Circular
              </button>
              <button
                onClick={() => handleSelectPreset(PRESET_SYNTAX_ERROR)}
                className="px-2.5 py-0.5 rounded-md bg-white hover:bg-slate-100 text-slate-700 hover:text-slate-900 text-[11px] transition-colors border border-slate-300 hover:border-[#163A6E] shadow-xs"
              >
                Syntax Error
              </button>
            </div>
          </div>

          {/* File Tabs Bar */}
          <div className="flex items-center px-3 py-2 bg-slate-100/70 border-b border-slate-200 overflow-x-auto space-x-1">
            {files.map((file) => {
              const isActive = file.path === activeFilePath;
              return (
                <button
                  key={file.path}
                  onClick={() => setActiveFilePath(file.path)}
                  className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-mono transition-all border ${
                    isActive
                      ? "bg-[#163A6E] text-white border-[#163A6E] shadow-xs"
                      : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <FileCode className={`w-3.5 h-3.5 ${isActive ? "text-amber-300" : "text-slate-400"}`} />
                  <span>{file.path}</span>
                  {files.length > 1 && (
                    <span
                      onClick={(e) => handleRemoveFile(file.path, e)}
                      title="Remove file"
                      className="ml-1 text-slate-400 hover:text-rose-600 p-0.5 rounded"
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
                className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs text-slate-600 hover:text-[#E26D1E] hover:bg-white border border-dashed border-slate-300 transition-colors shadow-xs"
                title="Add Python file"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New File</span>
              </button>
            ) : (
              <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-300 shadow-xs">
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
                  className="bg-slate-50 text-slate-900 text-xs px-2 py-1 rounded border border-slate-300 outline-none w-36 font-mono"
                />
                <button
                  onClick={handleAddFile}
                  data-testid="add-file-btn"
                  className="bg-[#163A6E] hover:bg-[#0f284e] text-white text-xs px-2.5 py-1 rounded-md font-semibold"
                >
                  Add
                </button>
                <button
                  onClick={() => {
                    setIsAddingFile(false);
                    setAddFileError(null);
                  }}
                  className="text-slate-500 hover:text-slate-800 text-xs px-1.5 py-1"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>

          {addFileError && (
            <div className="px-4 py-1.5 bg-rose-50 border-b border-rose-200 text-rose-700 text-xs flex items-center space-x-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
              <span>{addFileError}</span>
            </div>
          )}

          {/* Active File Header */}
          <div className="px-4 py-1.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between text-[11px] text-slate-500">
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
          <div className="px-4 py-3 bg-white border-t border-slate-200 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center space-x-2 text-xs text-slate-500">
              <Shield className="w-4 h-4 text-[#E26D1E]" />
              <span>Zero Execution Guarantee: files are parsed via static AST only.</span>
            </div>

            <button
              onClick={handleRunProjectAnalysis}
              disabled={isAnalyzing}
              data-testid="analyze-project-button"
              className={`px-5 py-2.5 rounded-lg text-xs font-semibold flex items-center space-x-2 shadow-md transition-all ${
                isAnalyzing
                  ? "bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed"
                  : "bg-[#163A6E] hover:bg-[#0f284e] active:bg-[#0a1b35] text-white shadow-blue-900/10 active:scale-95"
              }`}
            >
              {isAnalyzing ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-amber-300" />
                  <span>Analyzing Project...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-amber-300 text-amber-300" />
                  <span>Analyze Project</span>
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 text-xs flex items-start space-x-3">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-rose-900">Project Analysis Error</p>
              <p className="text-rose-800 mt-0.5">{error}</p>
            </div>
          </div>
        )}
      </div>

      {/* Right 5 Cols: Project Evidence Court & Dependency Results */}
      <div className="lg:col-span-5 flex flex-col space-y-4">
        <div className="flex flex-col rounded-2xl border border-slate-200 bg-white shadow-md overflow-hidden min-h-[500px] backdrop-blur-sm">
          {/* Navigation Tabs */}
          <div className="flex items-center border-b border-slate-200 bg-slate-50 px-2.5 py-1.5 overflow-x-auto text-xs space-x-1">
            <button
              onClick={() => setActiveTab("summary")}
              data-testid="project-tab-summary"
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "summary"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              Summary
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              data-testid="project-tab-graph"
              className={`px-3 py-1.5 rounded-lg font-medium flex items-center space-x-1.5 transition-all ${
                activeTab === "graph"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              <GitBranch className="w-3.5 h-3.5" />
              <span>Dependencies</span>
              {report && (
                <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-white text-slate-700 border border-slate-300 font-mono">
                  {report.relationships.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("issues")}
              data-testid="project-tab-issues"
              className={`px-3 py-1.5 rounded-lg font-medium flex items-center space-x-1.5 transition-all ${
                activeTab === "issues"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              <span>Issues</span>
              {report && (
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                    report.verified_issues.length > 0
                      ? "bg-rose-100 text-rose-800 border border-rose-300 font-bold"
                      : "bg-white text-slate-700 border border-slate-300"
                  }`}
                >
                  {report.verified_issues.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("files")}
              data-testid="project-tab-files"
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "files"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              Files
            </button>
            <button
              onClick={() => setActiveTab("evidence")}
              data-testid="project-tab-evidence"
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "evidence"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              Evidence
            </button>
            <button
              onClick={() => setActiveTab("suggestions")}
              data-testid="project-tab-suggestions"
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "suggestions"
                  ? "bg-[#163A6E] text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white"
              }`}
            >
              AI Insights
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-4 flex-1 overflow-y-auto max-h-[600px] text-xs">
            {!report ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-16 text-slate-400 space-y-3">
                <FolderTree className="w-10 h-10 text-slate-300" />
                <p className="font-medium text-slate-700">Ready for Project Analysis</p>
                <p className="text-[11px] max-w-xs text-slate-500">
                  Click <span className="text-[#E26D1E] font-semibold">Analyze Project</span> to parse all files, resolve
                  cross-file imports, and verify API contracts against official evidence.
                </p>
              </div>
            ) : (
              <>
                {/* 1. Summary Tab */}
                {activeTab === "summary" && (
                  <div className="space-y-4">
                    {/* Verdict Banner */}
                    <div className="p-4 rounded-xl border border-slate-200 bg-slate-50 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">
                          Project Verdict
                        </span>
                        {renderVerdictBadge(report.verdict, report.is_mock)}
                      </div>
                      <p className="text-slate-800 font-medium leading-relaxed">{report.summary}</p>
                    </div>

                    {/* Stats Metrics Grid */}
                    <div className="grid grid-cols-2 gap-2 text-center">
                      <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                        <span className="text-slate-500 text-[10px] block">Total Files</span>
                        <span className="text-base font-bold text-slate-800 font-mono">{report.total_files}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                        <span className="text-slate-500 text-[10px] block">Total Lines</span>
                        <span className="text-base font-bold text-slate-800 font-mono">{report.total_lines}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                        <span className="text-slate-500 text-[10px] block">API Candidates</span>
                        <span className="text-base font-bold text-slate-800 font-mono">{report.total_candidates}</span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                        <span className="text-slate-500 text-[10px] block">Resolved Imports</span>
                        <span className="text-base font-bold text-emerald-600 font-mono">
                          {report.resolved_imports_count}
                        </span>
                      </div>
                    </div>

                    {/* Incomplete Analysis Warning if Syntax Errors */}
                    {report.syntax_errors_count > 0 && (
                      <div className="p-3.5 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 space-y-1">
                        <div className="flex items-center space-x-1.5 font-semibold text-rose-900 text-xs">
                          <AlertCircle className="w-4 h-4 text-rose-600" />
                          <span>Incomplete Analysis Warning: {report.syntax_errors_count} of {report.total_files} file(s) failed syntax parsing</span>
                        </div>
                        <p className="text-[11px] text-rose-700 leading-relaxed">
                          Files with syntax errors could not be parsed into ASTs. The overall project verdict cannot certify absence of issues in unparsed files.
                        </p>
                      </div>
                    )}

                    {/* Unresolved Imports Warning */}
                    {report.unresolved_imports_count > 0 && (
                      <div className="p-3 rounded-xl border border-amber-200 bg-amber-50 text-amber-900 space-y-1">
                        <div className="flex items-center space-x-1.5 font-semibold text-amber-900 text-xs">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                          <span>Import Resolution Caveat: {report.unresolved_imports_count} internal import(s) could not be statically resolved</span>
                        </div>
                        <p className="text-[11px] text-amber-800 leading-relaxed">
                          Cross-module call chains depending on these unresolved imports may not be fully evaluated.
                        </p>
                      </div>
                    )}

                    {/* Limitations & Caveats */}
                    {report.limitations_and_caveats.length > 0 && (
                      <div className="p-3.5 rounded-xl border border-amber-200 bg-amber-50 text-amber-900 space-y-1.5">
                        <div className="flex items-center space-x-1.5 font-semibold text-amber-900 text-[11px]">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                          <span>Limitations & Caveats</span>
                        </div>
                        <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-800 pl-1">
                          {report.limitations_and_caveats.map((c, idx) => (
                            <li key={idx}>{c}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Disclaimer */}
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-[11px] text-slate-500 leading-relaxed">
                      {report.disclaimer}
                    </div>
                  </div>
                )}

                {/* 2. Dependencies & Graph Tab */}
                {activeTab === "graph" && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-slate-500 text-[11px]">
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
                              ? "text-emerald-800 border-emerald-300 bg-emerald-50"
                              : rel.status === "unresolved"
                              ? "text-amber-800 border-amber-300 bg-amber-50"
                              : rel.status === "ambiguous"
                              ? "text-purple-800 border-purple-300 bg-purple-50"
                              : "text-blue-800 border-blue-300 bg-blue-50";

                          return (
                            <div
                              key={idx}
                              className="p-3 rounded-lg border border-slate-200 bg-slate-50 space-y-1.5 font-sans"
                            >
                              <div className="flex items-center justify-between font-mono text-[11px]">
                                <span className="text-slate-800 font-semibold">{rel.source_file}</span>
                                <ArrowRight className="w-3 h-3 text-slate-400 mx-1 shrink-0" />
                                <span className="text-[#E26D1E] font-semibold truncate max-w-[150px]">
                                  {rel.target}
                                </span>
                                <span className={`ml-auto px-2 py-0.5 rounded text-[10px] border ${statusColor}`}>
                                  {rel.status}
                                </span>
                              </div>
                              <p className="text-[11px] text-slate-600">{rel.reason}</p>
                              {rel.target_file && (
                                <button
                                  onClick={() => handleJumpToFileAndLine(rel.target_file)}
                                  className="text-[10px] text-[#163A6E] hover:underline flex items-center space-x-1 font-medium"
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
                        <CheckCircle2 className="w-8 h-8 text-emerald-600 mx-auto" />
                        <p className="text-slate-800 font-medium">No Contract Violations Found</p>
                        <p className="text-[11px] text-slate-500">
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
                        className="p-3 rounded-lg border border-slate-200 bg-slate-50 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-semibold text-slate-800">{file.path}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] border font-medium ${
                              file.parse_status === "success"
                                ? "text-emerald-800 bg-emerald-50 border-emerald-300"
                                : "text-rose-800 bg-rose-50 border-rose-300"
                            }`}
                          >
                            {file.parse_status}
                          </span>
                        </div>

                        {file.syntax_error && (
                          <div className="p-2 rounded bg-rose-50 border border-rose-200 text-rose-800 text-[11px]">
                            Syntax Error (Line {file.syntax_error.lineno}): {file.syntax_error.message}
                          </div>
                        )}

                        <div className="grid grid-cols-3 gap-1.5 text-center text-[10px]">
                          <div className="p-1 rounded bg-white border border-slate-200 text-slate-700">
                            <span className="text-slate-500">Lines:</span> {file.total_lines}
                          </div>
                          <div className="p-1 rounded bg-white border border-slate-200 text-slate-700">
                            <span className="text-slate-500">Imports:</span> {file.imports.length}
                          </div>
                          <div className="p-1 rounded bg-white border border-slate-200 text-slate-700">
                            <span className="text-slate-500">Candidates:</span> {file.candidates.length}
                          </div>
                        </div>

                        {file.defined_symbols.length > 0 && (
                          <div className="text-[10px] text-slate-600">
                            <span className="font-semibold text-slate-800">Top-Level Symbols: </span>
                            <span className="font-mono text-[#E26D1E]">
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
                          className="p-3.5 rounded-lg border border-slate-200 bg-slate-50 space-y-2"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center space-x-2">
                              <span className="font-semibold text-slate-800">{ev.title || "Official Stripe Reference"}</span>
                              {ev.is_mock ? (
                                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                                  MOCK FIXTURE (OFFLINE)
                                </span>
                              ) : (
                                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-[#163A6E] border border-blue-200">
                                  LIVE OFFICIAL RETRIEVAL
                                </span>
                              )}
                            </div>
                            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-white text-slate-600 border border-slate-300">
                              {ev.evidence_id}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-700 italic bg-white p-2 rounded border border-slate-200">
                            "{ev.content_excerpt}"
                          </p>
                          <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-500 pt-1 border-t border-slate-200 gap-1">
                            <a
                              href={ev.canonical_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#163A6E] hover:underline flex items-center space-x-1 font-medium"
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
                    <div className="p-3 rounded-lg bg-violet-50 border border-violet-200 text-xs text-violet-900 flex items-start space-x-2">
                      <Sparkles className="w-4 h-4 text-violet-600 flex-shrink-0 mt-0.5" />
                      <div className="space-y-1">
                        <p className="font-semibold text-violet-900">
                          AI Suggestions — Advisory Only (Not Verified)
                        </p>
                        <p className="text-[11px] text-violet-800 leading-relaxed">
                          AI suggestions are non-deterministic hypotheses. Model suggestions CANNOT create verified findings or alter the project verdict.
                        </p>
                      </div>
                    </div>

                    {report.ai_suggestions.length === 0 ? (
                      <div className="text-center py-8 text-slate-400 space-y-1">
                        <Sparkles className="w-6 h-6 text-slate-400 mx-auto" />
                        <p>No advisory suggestions generated.</p>
                      </div>
                    ) : (
                      report.ai_suggestions.map((sug) => (
                        <div
                          key={sug.suggestion_id}
                          className="p-3.5 rounded-lg border border-violet-200 bg-violet-50/50 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-2">
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-violet-100 text-violet-800 border border-violet-200">
                                {sug.label}
                              </span>
                              <span className="text-violet-900 font-semibold text-xs">{sug.claim_type.replace(/_/g, " ")}</span>
                            </div>
                            <span className="font-mono text-[10px] text-slate-500">
                              {sug.candidate_id}
                            </span>
                          </div>
                          <p className="text-slate-700 text-xs leading-relaxed">{sug.description}</p>
                          <div className="p-2 rounded bg-white border border-slate-200 text-[11px] space-y-0.5">
                            <span className="font-semibold text-amber-800 text-[10px] block">What Remains Unverified:</span>
                            <p className="text-slate-600 text-[11px]">{sug.unverified_aspects}</p>
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
