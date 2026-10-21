import React, { useState, useEffect, useCallback } from "react";
import {
  History,
  RotateCw,
  Trash2,
  ExternalLink,
  Shield,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Scale,
  Sparkles,
  BookOpen,
  Copy,
  Check,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Database,
  Lock,
} from "lucide-react";
import { listScans, getScan, deleteScan } from "../services/api";
import { ScanSummaryItem, HistoricalScanDetail } from "../types/scan_history";

interface ScanHistoryViewProps {
  onBackToEditor?: () => void;
}

export const ScanHistoryView: React.FC<ScanHistoryViewProps> = ({ onBackToEditor }) => {
  const [scans, setScans] = useState<ScanSummaryItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [limit] = useState<number>(10);
  const [offset, setOffset] = useState<number>(0);
  const [verdictFilter, setVerdictFilter] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Selected detail state
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [scanDetail, setScanDetail] = useState<HistoricalScanDetail | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Deletion state
  const [deleteCandidateId, setDeleteCandidateId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Copy indicator state
  const [copiedText, setCopiedText] = useState<string | null>(null);

  const fetchScanList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await listScans(limit, offset, verdictFilter || undefined);
      setScans(resp.items);
      setTotal(resp.total);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load historical scans from SQLite repository.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [limit, offset, verdictFilter]);

  useEffect(() => {
    fetchScanList();
  }, [fetchScanList]);

  const handleSelectScan = async (scanId: string) => {
    setSelectedScanId(scanId);
    setIsLoadingDetail(true);
    setDetailError(null);
    try {
      const detail = await getScan(scanId);
      setScanDetail(detail);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setDetailError(err.message);
      } else {
        setDetailError("Failed to retrieve scan detail.");
      }
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteCandidateId) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteScan(deleteCandidateId);
      setDeleteCandidateId(null);
      if (selectedScanId === deleteCandidateId) {
        setSelectedScanId(null);
        setScanDetail(null);
      }
      // Refresh list
      await fetchScanList();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setDeleteError(err.message);
      } else {
        setDeleteError("Failed to delete scan record.");
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(null), 2000);
  };

  const formatDate = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });
    } catch {
      return isoString;
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div className="flex items-center space-x-3">
          {onBackToEditor && (
            <button
              onClick={onBackToEditor}
              className="px-3 py-1.5 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs flex items-center space-x-1.5 transition-colors border border-slate-300 shadow-xs"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Editor</span>
            </button>
          )}
          <div className="flex items-center space-x-2.5">
            <History className="w-5 h-5 text-[#163A6E]" />
            <h2 className="font-serif text-lg font-bold text-slate-900 tracking-tight">SQLite Scan Audit Repository</h2>
            <span className="px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-blue-50 text-[#163A6E] border border-blue-200">
              {total} Scans Stored
            </span>
          </div>
        </div>

        {/* Filters and Actions */}
        <div className="flex items-center space-x-2.5">
          <select
            value={verdictFilter}
            onChange={(e) => {
              setVerdictFilter(e.target.value);
              setOffset(0);
            }}
            className="px-3 py-1.5 rounded-lg bg-white border border-slate-300 text-slate-800 text-xs focus:outline-none focus:border-[#163A6E] shadow-xs"
          >
            <option value="">All Verdicts</option>
            <option value="clean">Clean</option>
            <option value="issues_found">Issues Found</option>
            <option value="unable_to_verify">Unable to Verify</option>
          </select>

          <button
            onClick={fetchScanList}
            disabled={isLoading}
            className="p-2 rounded-lg bg-white hover:bg-slate-100 text-slate-600 hover:text-slate-900 transition-colors border border-slate-300 shadow-xs"
            title="Refresh Scan History"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin text-[#E26D1E]" : "text-[#163A6E]"}`} />
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800 flex items-start space-x-2.5">
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-rose-900">History Query Error</p>
            <p className="text-rose-800/90 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Detail Modal / Panel if selected */}
      {selectedScanId && (
        <div className="rounded-2xl border border-blue-200 bg-white p-5 shadow-xl space-y-4 backdrop-blur-sm">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <div className="flex items-center space-x-2">
              <button
                onClick={() => {
                  setSelectedScanId(null);
                  setScanDetail(null);
                }}
                className="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs flex items-center space-x-1 border border-slate-300"
              >
                <ArrowLeft className="w-3 h-3" />
                <span>Close Detail</span>
              </button>
              <span className="text-xs font-mono text-slate-500">ID: {selectedScanId}</span>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={() => setDeleteCandidateId(selectedScanId)}
                className="px-2.5 py-1 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs flex items-center space-x-1 border border-rose-200"
              >
                <Trash2 className="w-3 h-3" />
                <span>Delete Audit Record</span>
              </button>
            </div>
          </div>

          {isLoadingDetail ? (
            <div className="py-8 text-center text-xs text-slate-500 flex items-center justify-center space-x-2">
              <RotateCw className="w-4 h-4 animate-spin text-[#163A6E]" />
              <span>Loading stored audit snapshot from SQLite...</span>
            </div>
          ) : detailError ? (
            <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
              {detailError}
            </div>
          ) : scanDetail ? (
            <div className="space-y-4">
              {/* Historical Warning Banner */}
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 flex items-start space-x-2.5">
                <Shield className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-amber-900">Historical Audit Snapshot</p>
                  <p className="text-amber-800/90 mt-0.5">
                    Originally analyzed on {formatDate(scanDetail.created_at)}. This is a stored audit snapshot
                    reflecting evidence evaluated at that time; it does not perform live verification against current API documentation.
                  </p>
                </div>
              </div>

              {/* Top Summary Bar */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Verdict</div>
                  <div className="mt-1 flex items-center space-x-1.5">
                    {scanDetail.verdict === "clean" ? (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
                        CLEAN
                      </span>
                    ) : scanDetail.verdict === "issues_found" ? (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300">
                        ISSUES FOUND
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                        UNABLE TO VERIFY
                      </span>
                    )}
                  </div>
                </div>

                <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Trust & Mock</div>
                  <div className="mt-1 flex items-center space-x-1.5">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      scanDetail.is_mock
                        ? "bg-amber-100 text-amber-900 border border-amber-300"
                        : "bg-blue-100 text-[#163A6E] border border-blue-200"
                    }`}>
                      {scanDetail.is_mock ? "Mock Fixture" : "Live Official"}
                    </span>
                  </div>
                </div>

                <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Source Length</div>
                  <div className="mt-1 text-xs font-mono text-slate-800">
                    {scanDetail.source_length} chars ({scanDetail.filename})
                  </div>
                </div>

                <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Engine Version</div>
                  <div className="mt-1 text-xs font-mono text-slate-800">
                    v{scanDetail.pipeline_version}
                  </div>
                </div>
              </div>

              {/* Source SHA-256 Fingerprint */}
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-600">Source Code SHA-256 Fingerprint:</span>
                  <button
                    onClick={() => handleCopy(scanDetail.source_sha256, "source_hash")}
                    className="text-[10px] text-[#163A6E] hover:text-[#0f284e] flex items-center space-x-1 font-medium"
                  >
                    {copiedText === "source_hash" ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedText === "source_hash" ? "Copied" : "Copy Hash"}</span>
                  </button>
                </div>
                <div className="font-mono text-xs text-slate-800 break-all select-all">
                  {scanDetail.source_sha256}
                </div>
                <p className="text-[10px] text-slate-500 italic">
                  Cryptographic hash of submitted source code at scan time. Identifies evaluated code without storing raw source in the database (Privacy: raw source retention disabled).
                </p>
              </div>

              {/* Audit Integrity Hash */}
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-600 flex items-center space-x-1.5">
                    <Lock className="w-3 h-3 text-emerald-600" />
                    <span>Audit Record Integrity Fingerprint:</span>
                  </span>
                  <button
                    onClick={() => handleCopy(scanDetail.integrity_hash, "integrity_hash")}
                    className="text-[10px] text-[#163A6E] hover:text-[#0f284e] flex items-center space-x-1 font-medium"
                  >
                    {copiedText === "integrity_hash" ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedText === "integrity_hash" ? "Copied" : "Copy Fingerprint"}</span>
                  </button>
                </div>
                <div className="font-mono text-xs text-emerald-800 break-all select-all font-semibold">
                  {scanDetail.integrity_hash}
                </div>
                <p className="text-[10px] text-slate-500 italic">
                  SHA-256 digest computed across canonical scan record fields (verdict, source hash, timestamp, findings, evidence IDs). Protects against local accidental corruption. Note: A locally stored hash does not provide tamper-proof immutability against an attacker who can modify both the SQLite database file and the hash.
                </p>
              </div>

              {/* Summary */}
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-700">
                <span className="font-semibold text-slate-900">Analysis Summary: </span>
                {scanDetail.summary}
              </div>

              {/* Verified Issues */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-900 flex items-center space-x-1.5">
                  <Scale className="w-3.5 h-3.5 text-rose-600" />
                  <span>Verified Contract Violations ({scanDetail.verified_issues.length})</span>
                </h4>
                {scanDetail.verified_issues.length === 0 ? (
                  <div className="p-3 rounded bg-slate-50 border border-slate-200 text-xs text-slate-500">
                    No verified contract violations were recorded for this scan.
                  </div>
                ) : (
                  scanDetail.verified_issues.map((issue) => (
                    <div key={issue.issue_id} className="p-3 rounded-lg bg-rose-50/60 border border-rose-200 space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-rose-800">{issue.violation_type}</span>
                        <span className="text-slate-500 font-mono text-[11px]">Line {issue.source_location.lineno}</span>
                      </div>
                      <p className="text-slate-700">{issue.explanation}</p>
                      <div className="p-2 rounded bg-white border border-slate-200 text-[11px] font-mono text-slate-800">
                        "{issue.verified_quote}"
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* AI Suggestions (Separated) */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-900 flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-[#163A6E]" />
                  <span>AI Suggestions ({scanDetail.ai_suggestions.length}) — Strictly Advisory</span>
                </h4>
                {scanDetail.ai_suggestions.length === 0 ? (
                  <div className="p-3 rounded bg-slate-50 border border-slate-200 text-xs text-slate-500">
                    No AI suggestions recorded for this scan.
                  </div>
                ) : (
                  scanDetail.ai_suggestions.map((sug) => (
                    <div key={sug.suggestion_id} className="p-3 rounded-lg bg-violet-50/60 border border-violet-200 space-y-1.5 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-violet-900">{sug.claim_type}</span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-violet-100 text-violet-800 border border-violet-200">
                          {sug.label}
                        </span>
                      </div>
                      <p className="text-slate-700">{sug.description}</p>
                    </div>
                  ))
                )}
              </div>

              {/* Evidence Receipts */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-900 flex items-center space-x-1.5">
                  <BookOpen className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Retrieved Official Evidence Receipts ({scanDetail.evidence_items.length})</span>
                </h4>
                {scanDetail.evidence_items.length === 0 ? (
                  <div className="p-3 rounded bg-slate-50 border border-slate-200 text-xs text-slate-500">
                    No documentation evidence receipts associated with this record.
                  </div>
                ) : (
                  scanDetail.evidence_items.map((ev) => (
                    <div key={ev.evidence_id} className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1.5 text-xs">
                      <div className="flex items-center justify-between">
                        <a
                          href={ev.canonical_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-semibold text-[#163A6E] hover:text-[#0f284e] hover:underline flex items-center space-x-1"
                        >
                          <span>{ev.title || ev.canonical_url}</span>
                          <ExternalLink className="w-3 h-3 text-slate-500" />
                        </a>
                        <span className="text-slate-500 font-mono text-[10px]">{ev.provider}</span>
                      </div>
                      <p className="text-slate-700 line-clamp-3 font-mono text-[11px] bg-white p-2 rounded border border-slate-200">
                        {ev.content_excerpt}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Scans Table / List View */}
      <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm backdrop-blur-sm">
        {isLoading ? (
          <div className="py-12 text-center text-xs text-slate-500 flex items-center justify-center space-x-2">
            <RotateCw className="w-4 h-4 animate-spin text-[#E26D1E]" />
            <span>Loading historical scans...</span>
          </div>
        ) : scans.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-500 space-y-2">
            <Database className="w-8 h-8 text-slate-400 mx-auto" />
            <p className="font-serif font-semibold text-slate-800">No historical scans found</p>
            <p className="text-slate-500 max-w-sm mx-auto font-sans">
              {verdictFilter
                ? `No scans match the verdict filter '${verdictFilter}'.`
                : "Analyze Python API code in the Verification Studio to create your first persistent audit record."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-[11px] text-slate-600 uppercase tracking-wider font-mono">
                <tr>
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Verdict</th>
                  <th className="py-3 px-4">Filename</th>
                  <th className="py-3 px-4">Ecosystem</th>
                  <th className="py-3 px-4 text-center">Issues</th>
                  <th className="py-3 px-4 text-center">Candidates</th>
                  <th className="py-3 px-4 text-center">Trust</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 font-sans">
                {scans.map((scan) => (
                  <tr key={scan.scan_id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4 font-mono text-[11px] text-slate-600 whitespace-nowrap">
                      {formatDate(scan.created_at)}
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      {scan.verdict === "clean" ? (
                        <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-300 flex items-center space-x-1 w-fit">
                          <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                          <span>Clean</span>
                        </span>
                      ) : scan.verdict === "issues_found" ? (
                        <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-rose-50 text-rose-800 border border-rose-300 flex items-center space-x-1 w-fit">
                          <AlertCircle className="w-3 h-3 text-rose-600" />
                          <span>Issues Found</span>
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-50 text-amber-900 border border-amber-300 flex items-center space-x-1 w-fit">
                          <AlertTriangle className="w-3 h-3 text-amber-600" />
                          <span>Unable to Verify</span>
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4 font-mono text-slate-900 font-medium">
                      {scan.filename}
                    </td>

                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                        {scan.ecosystem}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-center font-mono">
                      {scan.issues_count > 0 ? (
                        <span className="text-rose-600 font-bold">{scan.issues_count}</span>
                      ) : (
                        <span className="text-slate-400">0</span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-center font-mono text-slate-700">
                      {scan.candidates_count}
                    </td>

                    <td className="py-3 px-4 text-center">
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold ${
                        scan.is_mock
                          ? "bg-amber-50 text-amber-800 border border-amber-300"
                          : "bg-blue-50 text-[#163A6E] border border-blue-200"
                      }`}>
                        {scan.is_mock ? "Mock" : "Live"}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-right space-x-2 whitespace-nowrap">
                      <button
                        onClick={() => handleSelectScan(scan.scan_id)}
                        className="px-3 py-1 rounded-lg bg-[#163A6E] hover:bg-[#0f284e] text-white text-[11px] font-semibold transition-colors shadow-xs"
                      >
                        Inspect
                      </button>
                      <button
                        onClick={() => setDeleteCandidateId(scan.scan_id)}
                        className="p-1.5 rounded-lg bg-white hover:bg-rose-50 text-slate-400 hover:text-rose-600 border border-slate-300 hover:border-rose-300 transition-colors shadow-xs"
                        title="Delete Record"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {total > limit && (
          <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-t border-slate-200 text-xs text-slate-600">
            <div>
              Showing {offset + 1} to {Math.min(offset + limit, total)} of {total} scans
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className={`p-1.5 rounded border border-slate-300 text-slate-700 bg-white ${
                  offset === 0 ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"
                }`}
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono text-slate-700">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
                className={`p-1.5 rounded border border-slate-300 text-slate-700 bg-white ${
                  offset + limit >= total ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"
                }`}
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteCandidateId && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="rounded-xl border border-rose-300 bg-white p-5 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center space-x-2 text-rose-700 font-semibold text-sm">
              <AlertTriangle className="w-5 h-5 flex-shrink-0" />
              <span>Confirm Explicit Scan Deletion</span>
            </div>

            <p className="text-xs text-slate-700">
              Are you sure you want to permanently delete scan audit record{" "}
              <span className="font-mono font-semibold text-rose-700">{deleteCandidateId}</span>?
            </p>

            <p className="text-[11px] text-slate-600 bg-slate-50 p-2.5 rounded border border-slate-200">
              This action will remove the scan audit trail, dependent evidence receipts, and findings records from the local SQLite database. This action cannot be undone.
            </p>

            {deleteError && (
              <div className="text-xs text-rose-700 bg-rose-50 p-2 rounded border border-rose-200">
                {deleteError}
              </div>
            )}

            <div className="flex items-center justify-end space-x-2.5 pt-2">
              <button
                onClick={() => setDeleteCandidateId(null)}
                disabled={isDeleting}
                className="px-3 py-1.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium border border-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                className="px-3.5 py-1.5 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-md transition-colors flex items-center space-x-1.5"
              >
                {isDeleting ? (
                  <>
                    <RotateCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Permanently Delete</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
