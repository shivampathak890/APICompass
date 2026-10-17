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
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border-subtle pb-4">
        <div className="flex items-center space-x-3">
          {onBackToEditor && (
            <button
              onClick={onBackToEditor}
              className="px-2.5 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs flex items-center space-x-1.5 transition-colors border border-slate-700"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Editor</span>
            </button>
          )}
          <div className="flex items-center space-x-2">
            <History className="w-5 h-5 text-accent-cyan" />
            <h2 className="text-base font-semibold text-slate-100">SQLite Scan Audit Repository</h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-violet-950/80 text-violet-300 border border-violet-800/60">
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
            className="px-2.5 py-1.5 rounded-md bg-slate-900 border border-slate-700 text-slate-200 text-xs focus:outline-none focus:border-violet-500"
          >
            <option value="">All Verdicts</option>
            <option value="clean">Clean</option>
            <option value="issues_found">Issues Found</option>
            <option value="unable_to_verify">Unable to Verify</option>
          </select>

          <button
            onClick={fetchScanList}
            disabled={isLoading}
            className="p-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
            title="Refresh Scan History"
          >
            <RotateCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-lg border border-rose-800/80 bg-rose-950/40 p-3.5 text-xs text-rose-300 flex items-start space-x-2.5">
          <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-rose-200">History Query Error</p>
            <p className="text-rose-300/90 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Detail Modal / Panel if selected */}
      {selectedScanId && (
        <div className="rounded-xl border border-violet-800/50 bg-slate-900/95 p-5 shadow-2xl space-y-4">
          <div className="flex items-center justify-between border-b border-border-subtle pb-3">
            <div className="flex items-center space-x-2">
              <button
                onClick={() => {
                  setSelectedScanId(null);
                  setScanDetail(null);
                }}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs flex items-center space-x-1 border border-slate-700"
              >
                <ArrowLeft className="w-3 h-3" />
                <span>Close Detail</span>
              </button>
              <span className="text-xs font-mono text-slate-400">ID: {selectedScanId}</span>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={() => setDeleteCandidateId(selectedScanId)}
                className="px-2.5 py-1 rounded bg-rose-950/60 hover:bg-rose-900 text-rose-300 text-xs flex items-center space-x-1 border border-rose-800/60"
              >
                <Trash2 className="w-3 h-3" />
                <span>Delete Audit Record</span>
              </button>
            </div>
          </div>

          {isLoadingDetail ? (
            <div className="py-8 text-center text-xs text-slate-400 flex items-center justify-center space-x-2">
              <RotateCw className="w-4 h-4 animate-spin text-accent-cyan" />
              <span>Loading stored audit snapshot from SQLite...</span>
            </div>
          ) : detailError ? (
            <div className="p-4 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300">
              {detailError}
            </div>
          ) : scanDetail ? (
            <div className="space-y-4">
              {/* Historical Warning Banner */}
              <div className="rounded-lg border border-amber-800/60 bg-amber-950/40 p-3 text-xs text-amber-200 flex items-start space-x-2.5">
                <Shield className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-amber-300">Historical Audit Snapshot</p>
                  <p className="text-amber-200/90 mt-0.5">
                    Originally analyzed on {formatDate(scanDetail.created_at)}. This is a stored audit snapshot
                    reflecting evidence evaluated at that time; it does not perform live verification against current API documentation.
                  </p>
                </div>
              </div>

              {/* Top Summary Bar */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-2.5">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">Verdict</div>
                  <div className="mt-1 flex items-center space-x-1.5">
                    {scanDetail.verdict === "clean" ? (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800/60">
                        CLEAN
                      </span>
                    ) : scanDetail.verdict === "issues_found" ? (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-rose-950 text-rose-300 border border-rose-800/60">
                        ISSUES FOUND
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-xs font-semibold bg-amber-950 text-amber-300 border border-amber-800/60">
                        UNABLE TO VERIFY
                      </span>
                    )}
                  </div>
                </div>

                <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-2.5">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">Trust & Mock</div>
                  <div className="mt-1 flex items-center space-x-1.5">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      scanDetail.is_mock
                        ? "bg-amber-950 text-amber-300 border border-amber-800/60"
                        : "bg-emerald-950 text-emerald-300 border border-emerald-800/60"
                    }`}>
                      {scanDetail.is_mock ? "Mock Fixture" : "Live Official"}
                    </span>
                  </div>
                </div>

                <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-2.5">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">Source Length</div>
                  <div className="mt-1 text-xs font-mono text-slate-200">
                    {scanDetail.source_length} chars ({scanDetail.filename})
                  </div>
                </div>

                <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-2.5">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">Engine Version</div>
                  <div className="mt-1 text-xs font-mono text-slate-200">
                    v{scanDetail.pipeline_version}
                  </div>
                </div>
              </div>

              {/* Source SHA-256 Fingerprint */}
              <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-400">Source Code SHA-256 Fingerprint:</span>
                  <button
                    onClick={() => handleCopy(scanDetail.source_sha256, "source_hash")}
                    className="text-[10px] text-violet-400 hover:text-violet-300 flex items-center space-x-1"
                  >
                    {copiedText === "source_hash" ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedText === "source_hash" ? "Copied" : "Copy Hash"}</span>
                  </button>
                </div>
                <div className="font-mono text-xs text-slate-300 break-all select-all">
                  {scanDetail.source_sha256}
                </div>
                <p className="text-[10px] text-slate-500 italic">
                  Cryptographic hash of submitted source code at scan time. Identifies evaluated code without storing raw source in the database (Privacy: raw source retention disabled).
                </p>
              </div>

              {/* Audit Integrity Hash */}
              <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-400 flex items-center space-x-1.5">
                    <Lock className="w-3 h-3 text-emerald-400" />
                    <span>Audit Record Integrity Fingerprint:</span>
                  </span>
                  <button
                    onClick={() => handleCopy(scanDetail.integrity_hash, "integrity_hash")}
                    className="text-[10px] text-violet-400 hover:text-violet-300 flex items-center space-x-1"
                  >
                    {copiedText === "integrity_hash" ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedText === "integrity_hash" ? "Copied" : "Copy Fingerprint"}</span>
                  </button>
                </div>
                <div className="font-mono text-xs text-emerald-300 break-all select-all">
                  {scanDetail.integrity_hash}
                </div>
                <p className="text-[10px] text-slate-500 italic">
                  SHA-256 digest computed across canonical scan record fields (verdict, source hash, timestamp, findings, evidence IDs). Protects against local accidental corruption. Note: A locally stored hash does not provide tamper-proof immutability against an attacker who can modify both the SQLite database file and the hash.
                </p>
              </div>

              {/* Summary */}
              <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 text-xs text-slate-300">
                <span className="font-semibold text-slate-200">Analysis Summary: </span>
                {scanDetail.summary}
              </div>

              {/* Verified Issues */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                  <Scale className="w-3.5 h-3.5 text-rose-400" />
                  <span>Verified Contract Violations ({scanDetail.verified_issues.length})</span>
                </h4>
                {scanDetail.verified_issues.length === 0 ? (
                  <div className="p-3 rounded bg-slate-950/40 border border-slate-800 text-xs text-slate-400">
                    No verified contract violations were recorded for this scan.
                  </div>
                ) : (
                  scanDetail.verified_issues.map((issue) => (
                    <div key={issue.issue_id} className="p-3 rounded-lg bg-rose-950/30 border border-rose-800/40 space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-rose-300">{issue.violation_type}</span>
                        <span className="text-slate-400 font-mono text-[11px]">Line {issue.source_location.lineno}</span>
                      </div>
                      <p className="text-slate-300">{issue.explanation}</p>
                      <div className="p-2 rounded bg-slate-950/80 border border-slate-800 text-[11px] font-mono text-emerald-300">
                        "{issue.verified_quote}"
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* AI Suggestions (Separated) */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-accent-cyan" />
                  <span>AI Suggestions ({scanDetail.ai_suggestions.length}) — Strictly Advisory</span>
                </h4>
                {scanDetail.ai_suggestions.length === 0 ? (
                  <div className="p-3 rounded bg-slate-950/40 border border-slate-800 text-xs text-slate-400">
                    No AI suggestions recorded for this scan.
                  </div>
                ) : (
                  scanDetail.ai_suggestions.map((sug) => (
                    <div key={sug.suggestion_id} className="p-3 rounded-lg bg-violet-950/20 border border-violet-800/40 space-y-1.5 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-violet-300">{sug.claim_type}</span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-violet-950 text-violet-300 border border-violet-800/60">
                          {sug.label}
                        </span>
                      </div>
                      <p className="text-slate-300">{sug.description}</p>
                    </div>
                  ))
                )}
              </div>

              {/* Evidence Receipts */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                  <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Retrieved Official Evidence Receipts ({scanDetail.evidence_items.length})</span>
                </h4>
                {scanDetail.evidence_items.length === 0 ? (
                  <div className="p-3 rounded bg-slate-950/40 border border-slate-800 text-xs text-slate-400">
                    No documentation evidence receipts associated with this record.
                  </div>
                ) : (
                  scanDetail.evidence_items.map((ev) => (
                    <div key={ev.evidence_id} className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-1.5 text-xs">
                      <div className="flex items-center justify-between">
                        <a
                          href={ev.canonical_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-semibold text-violet-300 hover:text-violet-200 flex items-center space-x-1"
                        >
                          <span>{ev.title || ev.canonical_url}</span>
                          <ExternalLink className="w-3 h-3 text-slate-400" />
                        </a>
                        <span className="text-slate-400 font-mono text-[10px]">{ev.provider}</span>
                      </div>
                      <p className="text-slate-300 line-clamp-3 font-mono text-[11px] bg-slate-900/60 p-2 rounded">
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
      <div className="rounded-xl border border-border-subtle bg-slate-900/70 overflow-hidden shadow-lg">
        {isLoading ? (
          <div className="py-12 text-center text-xs text-slate-400 flex items-center justify-center space-x-2">
            <RotateCw className="w-4 h-4 animate-spin text-accent-cyan" />
            <span>Loading historical scans...</span>
          </div>
        ) : scans.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-400 space-y-2">
            <Database className="w-8 h-8 text-slate-600 mx-auto" />
            <p className="font-semibold text-slate-300">No historical scans found</p>
            <p className="text-slate-500 max-w-sm mx-auto">
              {verdictFilter
                ? `No scans match the verdict filter '${verdictFilter}'.`
                : "Analyze Python API code in the Verification Studio to create your first persistent audit record."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/80 border-b border-border-subtle text-[11px] text-slate-400 uppercase tracking-wider font-mono">
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
              <tbody className="divide-y divide-border-subtle font-sans">
                {scans.map((scan) => (
                  <tr key={scan.scan_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 font-mono text-[11px] text-slate-300 whitespace-nowrap">
                      {formatDate(scan.created_at)}
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      {scan.verdict === "clean" ? (
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/60 flex items-center space-x-1 w-fit">
                          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                          <span>Clean</span>
                        </span>
                      ) : scan.verdict === "issues_found" ? (
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-950/80 text-rose-300 border border-rose-800/60 flex items-center space-x-1 w-fit">
                          <AlertCircle className="w-3 h-3 text-rose-400" />
                          <span>Issues Found</span>
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/60 flex items-center space-x-1 w-fit">
                          <AlertTriangle className="w-3 h-3 text-amber-400" />
                          <span>Unable to Verify</span>
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4 font-mono text-slate-200">
                      {scan.filename}
                    </td>

                    <td className="py-3 px-4">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                        {scan.ecosystem}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-center font-mono">
                      {scan.issues_count > 0 ? (
                        <span className="text-rose-400 font-bold">{scan.issues_count}</span>
                      ) : (
                        <span className="text-slate-500">0</span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-center font-mono text-slate-300">
                      {scan.candidates_count}
                    </td>

                    <td className="py-3 px-4 text-center">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        scan.is_mock
                          ? "bg-amber-950 text-amber-300 border border-amber-800/60"
                          : "bg-emerald-950 text-emerald-300 border border-emerald-800/60"
                      }`}>
                        {scan.is_mock ? "Mock" : "Live"}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-right space-x-2 whitespace-nowrap">
                      <button
                        onClick={() => handleSelectScan(scan.scan_id)}
                        className="px-2.5 py-1 rounded bg-violet-950/60 hover:bg-violet-900 text-violet-300 text-[11px] font-medium border border-violet-800/60 transition-colors"
                      >
                        Inspect
                      </button>
                      <button
                        onClick={() => setDeleteCandidateId(scan.scan_id)}
                        className="p-1 rounded bg-slate-800 hover:bg-rose-950 text-slate-400 hover:text-rose-300 border border-slate-700 hover:border-rose-800/60 transition-colors"
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
          <div className="flex items-center justify-between px-4 py-3 bg-slate-950/60 border-t border-border-subtle text-xs text-slate-400">
            <div>
              Showing {offset + 1} to {Math.min(offset + limit, total)} of {total} scans
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className={`p-1.5 rounded border border-slate-700 text-slate-300 ${
                  offset === 0 ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-800"
                }`}
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono text-slate-300">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
                className={`p-1.5 rounded border border-slate-700 text-slate-300 ${
                  offset + limit >= total ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-800"
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
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="rounded-xl border border-rose-800/80 bg-slate-900 p-5 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center space-x-2 text-rose-400 font-semibold text-sm">
              <AlertTriangle className="w-5 h-5 flex-shrink-0" />
              <span>Confirm Explicit Scan Deletion</span>
            </div>

            <p className="text-xs text-slate-300">
              Are you sure you want to permanently delete scan audit record{" "}
              <span className="font-mono font-semibold text-rose-300">{deleteCandidateId}</span>?
            </p>

            <p className="text-[11px] text-slate-400 bg-slate-950 p-2.5 rounded border border-slate-800">
              This action will remove the scan audit trail, dependent evidence receipts, and findings records from the local SQLite database. This action cannot be undone.
            </p>

            {deleteError && (
              <div className="text-xs text-rose-400 bg-rose-950/40 p-2 rounded border border-rose-800">
                {deleteError}
              </div>
            )}

            <div className="flex items-center justify-end space-x-2.5 pt-2">
              <button
                onClick={() => setDeleteCandidateId(null)}
                disabled={isDeleting}
                className="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                className="px-3.5 py-1.5 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-lg shadow-rose-900/40 transition-colors flex items-center space-x-1.5"
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
