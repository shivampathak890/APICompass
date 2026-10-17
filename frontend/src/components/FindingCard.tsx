import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  ExternalLink,
  Quote,
  ArrowRight,
  Wrench,
  BookOpen,
  Info,
  Sparkles,
  FileCode,
} from "lucide-react";
import {
  MatchMethodType,
  QuoteKindType,
  VerificationStatusType,
} from "../types/evidence";

export interface FindingCardProps {
  id: string;
  title?: string | null;
  status: VerificationStatusType;
  isMock?: boolean;
  impactClassification?: string | null;
  filePath?: string | null;
  sourceLine?: number | null;
  sourceCol?: number | null;
  codeFragment?: string | null;
  explanation: string;
  documentedRequirement?: string | null;
  sourceUrl?: string | null;
  supportingExcerpt?: string | null;
  quoteKind?: QuoteKindType | null;
  matchMethod?: MatchMethodType | null;
  evidenceFingerprint?: string | null;
  evidenceRationale?: string | null;
  uncertaintyOrLimitations?: string | null;
  suggestedCorrection?: string | null;
  candidateId?: string | null;
  issueId?: string | null;
  onJumpToLine?: (lineno: number) => void;
  onProposeFix?: (candidateId: string, issueId?: string) => void;
  isProposingFix?: boolean;
  checksPerformed?: string[];
  severity?: "error" | "warning" | "info" | string | null;
  confidence?: "verified" | "probable" | "speculative" | "uncertain" | string | null;
  detectedCall?: string | null;
  detectedArgument?: string | null;
  expectedContract?: string | null;
  observedUsage?: string | null;
  suggestedAction?: string | null;
  abstentionReason?: string | null;
  canonicalUrl?: string | null;
  sourceTitle?: string | null;
  retrievalStatus?: string | null;
  retrievedAt?: string | null;
}

export const FindingCard: React.FC<FindingCardProps> = ({
  id,
  title,
  status,
  isMock = false,
  impactClassification,
  filePath = "payment_handler.py",
  sourceLine,
  sourceCol,
  codeFragment,
  explanation,
  documentedRequirement,
  sourceUrl,
  supportingExcerpt,
  quoteKind = "exact_quotation",
  matchMethod = "exact",
  evidenceFingerprint,
  evidenceRationale,
  uncertaintyOrLimitations,
  suggestedCorrection,
  candidateId,
  issueId,
  onJumpToLine,
  onProposeFix,
  isProposingFix = false,
  checksPerformed = [],
  severity,
  confidence,
  detectedCall,
  detectedArgument,
  expectedContract,
  observedUsage,
  suggestedAction,
  abstentionReason,
  canonicalUrl,
  sourceTitle,
  retrievalStatus,
  retrievedAt,
}) => {
  // Requirement 7: Frontend labels must match backend's actual status values
  // "verified" | "unverified_suggestion" | "unable_to_verify" | "no_issue_detected"

  // Special State: No Issue Detected (Requirement 6)
  if (status === "no_issue_detected") {
    return (
      <div
        data-testid={`finding-card-${id}`}
        className="rounded-lg border border-emerald-800/80 bg-emerald-950/20 p-4 text-xs space-y-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-900/60 pb-2.5">
          <div className="flex items-center space-x-2">
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700/80 flex items-center space-x-1.5 shadow-sm"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>NO ISSUE DETECTED</span>
            </span>
            <h4 className="font-semibold text-emerald-200 text-xs">
              {title || "API Call Conforms to Verified Contract Constraints"}
            </h4>
          </div>
          {sourceLine && onJumpToLine && (
            <button
              onClick={() => onJumpToLine(sourceLine)}
              data-testid="jump-to-line-button"
              aria-label={`Jump to line ${sourceLine} in editor`}
              className="text-[10px] font-mono text-cyan-300 hover:text-cyan-200 bg-slate-800 hover:bg-slate-700 px-2 py-0.5 rounded border border-slate-700 flex items-center space-x-1 transition-colors"
            >
              <span>{filePath}:{sourceLine}</span>
              <ArrowRight className="w-2.5 h-2.5 text-accent-cyan" />
            </button>
          )}
        </div>

        {codeFragment && (
          <div
            data-testid="finding-code-fragment"
            className="p-2.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-emerald-300 overflow-x-auto"
          >
            <code>{codeFragment}</code>
          </div>
        )}

        <p className="text-slate-300 text-xs leading-relaxed">{explanation}</p>

        {/* Requirement 6: Explicitly explain that "no issue detected" covers only the checks performed */}
        <div
          data-testid="scope-limitation-notice"
          className="p-3 rounded-lg bg-slate-950/80 border border-slate-800 text-[11px] text-slate-300 space-y-2"
        >
          <div className="flex items-center space-x-1.5 text-amber-300 font-medium">
            <Info className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <span>Scope of Verification & Disclaimer:</span>
          </div>
          <p className="text-slate-400 text-[11px] leading-relaxed">
            A <strong>"no issue detected"</strong> status indicates strictly that supported static checks found no
            documented contract violations within the analyzed scope. It covers only the checks actually performed and
            does <em>not</em> guarantee runtime correctness, API network reachability, valid credentials, or the absence of
            unrelated bugs.
          </p>
          {checksPerformed.length > 0 && (
            <div className="pt-1.5 border-t border-slate-800/80">
              <span className="font-semibold text-slate-300 text-[10px] uppercase tracking-wider block mb-1">
                Checks Actively Performed:
              </span>
              <ul className="list-disc list-inside space-y-0.5 text-slate-400 text-[10px]">
                {checksPerformed.map((chk, idx) => (
                  <li key={idx}>{chk}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Visual Theme Configuration based on exact backend status
  const isVerified = status === "verified";
  const isUnverified = status === "unverified_suggestion";
  const isUnableToVerify = status === "unable_to_verify";

  const isRetrievalFailure =
    isUnableToVerify &&
    (abstentionReason === "RETRIEVAL_FAILED" ||
      retrievalStatus === "unavailable" ||
      retrievalStatus === "failed" ||
      retrievalStatus === "rate_limited" ||
      retrievalStatus === "rejected" ||
      (abstentionReason === "DOCUMENTATION_MISSING" &&
        explanation.toLowerCase().includes("retriev")));

  const containerBorder = isVerified
    ? isMock
      ? "border-amber-800/80 bg-amber-950/20"
      : "border-rose-800/80 bg-rose-950/20"
    : isUnverified
    ? "border-violet-800/80 bg-violet-950/20"
    : isRetrievalFailure
    ? "border-red-800/80 bg-red-950/20"
    : "border-slate-800 bg-slate-900/60";

  return (
    <div
      data-testid={`finding-card-${id}`}
      className={`rounded-lg border ${containerBorder} p-4 text-xs space-y-3 transition-all`}
    >
      {/* 1. Header Bar: Status Badge, Title, Impact Classification, Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2.5">
        <div className="flex items-center space-x-2 flex-wrap gap-1.5">
          {/* Confirmed Contract Mismatch (Live & Verified) */}
          {isVerified && !isMock && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-700/80 flex items-center space-x-1 shadow-sm"
            >
              <AlertTriangle className="w-3 h-3 text-rose-400" />
              <span>VERIFIED (CONFIRMED MISMATCH)</span>
            </span>
          )}

          {/* Quarantined Mock Evidence */}
          {isVerified && isMock && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-700/80 flex items-center space-x-1 shadow-sm"
              title="Quarantined mock evidence cannot produce production verified findings."
            >
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              <span>MOCK QUARANTINE (UNVERIFIED)</span>
            </span>
          )}

          {/* Potential Issue (Requires Review) */}
          {isUnverified && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-violet-950 text-violet-300 border border-violet-700/80 flex items-center space-x-1 shadow-sm"
            >
              <Sparkles className="w-3 h-3 text-accent-cyan" />
              <span>UNVERIFIED SUGGESTION (REQUIRES REVIEW)</span>
            </span>
          )}

          {/* Documentation Retrieval Failure */}
          {isRetrievalFailure && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-red-950 text-red-300 border border-red-700/80 flex items-center space-x-1 shadow-sm"
              title="Documentation retrieval failed from upstream provider (network error, rate limit, or resource unavailable)."
            >
              <AlertTriangle className="w-3 h-3 text-red-400" />
              <span>DOCUMENTATION RETRIEVAL FAILURE</span>
            </span>
          )}

          {/* Unable to Verify (Non-Retrieval Failure) */}
          {isUnableToVerify && !isRetrievalFailure && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700 flex items-center space-x-1 shadow-sm"
            >
              <HelpCircle className="w-3 h-3 text-amber-400" />
              <span>UNABLE TO VERIFY</span>
            </span>
          )}

          {/* Provenance: Mock vs Live Documentation Distinction */}
          {isMock || retrievalStatus === "mock" ? (
            <span
              data-testid="provenance-mock-badge"
              className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-700/70 flex items-center space-x-1 shadow-sm"
              title="Evidence derived from offline mock fixtures."
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
              <span>OFFLINE MOCK FIXTURE</span>
            </span>
          ) : (retrievalStatus === "success" || retrievalStatus === "live" || sourceUrl || canonicalUrl) ? (
            <span
              data-testid="provenance-live-badge"
              className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-700/70 flex items-center space-x-1 shadow-sm"
              title="Substantiated by live official documentation retrieved from Stripe/TinyFish."
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
              <span>LIVE OFFICIAL DOCUMENTATION</span>
            </span>
          ) : null}

          {/* Impact Classification (if supported; no invented severity values) */}
          {impactClassification && (
            <span
              data-testid="impact-classification-badge"
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700/80"
              title="Contractual impact classification derived deterministically from API documentation."
            >
              {impactClassification}
            </span>
          )}

          {/* Severity Classification */}
          {severity && (
            <span
              data-testid="severity-badge"
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${
                severity.toLowerCase() === "error"
                  ? "bg-rose-950/80 text-rose-300 border-rose-700/80"
                  : severity.toLowerCase() === "warning"
                  ? "bg-amber-950/80 text-amber-300 border-amber-700/80"
                  : "bg-cyan-950/80 text-cyan-300 border-cyan-700/80"
              }`}
            >
              {severity}
            </span>
          )}

          {/* Confidence Level */}
          {confidence && (
            <span
              data-testid="confidence-badge"
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-slate-900/90 text-slate-300 border border-slate-700"
              title="Confidence classification based on static AST precision and quote verification."
            >
              {confidence}
            </span>
          )}

          {/* Short Finding Title */}
          <h4
            data-testid="finding-title"
            className="font-semibold text-slate-200 text-xs ml-0.5"
          >
            {title || (isVerified ? "API Contract Violation" : isUnverified ? "Advisory AI Hypothesis" : "Candidate Assessment")}
          </h4>
        </div>

        {/* Location & Fix Action Buttons */}
        <div className="flex items-center space-x-2">
          {candidateId && onProposeFix && (
            <button
              onClick={() => onProposeFix(candidateId, issueId || undefined)}
              disabled={isProposingFix}
              data-testid="propose-fix-button"
              aria-label={`Propose fix for ${title || "finding"}`}
              className="px-2.5 py-1 rounded bg-violet-900/60 hover:bg-violet-800 text-violet-200 border border-violet-700/60 font-semibold text-[11px] flex items-center space-x-1.5 transition-colors shadow-sm"
              title="Propose evidence-gated fix for this finding"
            >
              <Wrench className="w-3.5 h-3.5 text-accent-cyan" />
              <span>{isProposingFix ? "Evaluating..." : "Propose Fix"}</span>
            </button>
          )}

          {sourceLine && onJumpToLine && (
            <button
              onClick={() => onJumpToLine(sourceLine)}
              data-testid="jump-to-line-button"
              aria-label={`Jump to line ${sourceLine} in editor`}
              className="text-[10px] font-mono text-cyan-300 hover:text-cyan-200 bg-slate-800 hover:bg-slate-700 px-2 py-0.5 rounded border border-slate-700 flex items-center space-x-1 transition-colors"
              title={`Jump to line ${sourceLine} in editor`}
            >
              <FileCode className="w-3 h-3 text-slate-400" />
              <span>{filePath ? `${filePath}:` : "Line "}{sourceLine}</span>
              <ArrowRight className="w-2.5 h-2.5 text-accent-cyan" />
            </button>
          )}
        </div>
      </div>

      {/* Provider Retrieval Failure Warning Banner */}
      {isRetrievalFailure && (
        <div
          data-testid="retrieval-failure-notice"
          className="p-3 rounded-lg bg-red-950/40 border border-red-800/80 text-[11px] text-red-200 space-y-1.5"
        >
          <div className="flex items-center space-x-2 font-semibold text-red-300">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span>Upstream Documentation Retrieval Failure</span>
          </div>
          <p className="leading-relaxed text-red-200/90">
            This issue represents an upstream documentation retrieval failure or network connectivity limitation,
            <strong> not a code-level contract violation</strong>. APICompass abstained from adjudicating your code to prevent false positives.
          </p>
        </div>
      )}

      {/* 2. Relevant Code Fragment */}
      {codeFragment ? (
        <div
          data-testid="finding-code-fragment"
          className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-cyan-300 overflow-x-auto"
        >
          <div className="text-[10px] text-slate-500 pb-1 font-sans flex items-center space-x-1.5">
            <span>Evaluated Code Fragment:</span>
            {sourceLine && (
              <span className="text-slate-400 font-mono">
                Line {sourceLine}{sourceCol ? `:${sourceCol}` : ""}
              </span>
            )}
          </div>
          <code>{codeFragment}</code>
        </div>
      ) : sourceLine ? (
        <div className="text-[11px] text-slate-400 font-mono">
          Code location: {filePath}:{sourceLine}
        </div>
      ) : null}

      {/* 3. Explanation of the Suspected Issue */}
      <p
        data-testid="finding-explanation"
        className="text-slate-300 text-xs leading-relaxed"
      >
        {explanation}
      </p>

      {/* Contract Details Comparison (Observed vs Expected) */}
      {(expectedContract || observedUsage || detectedArgument || detectedCall) && (
        <div
          data-testid="contract-comparison-box"
          className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 space-y-2 text-[11px]"
        >
          <div className="flex items-center space-x-2 text-slate-400 font-semibold text-[10px] uppercase tracking-wider border-b border-slate-900 pb-1">
            <span>Contract Comparison</span>
            {detectedArgument && (
              <span className="text-cyan-300 font-mono font-normal">
                param: <strong>{detectedArgument}</strong>
              </span>
            )}
          </div>
          {observedUsage && (
            <div className="flex items-start space-x-2">
              <span className="font-semibold text-rose-300 shrink-0">Observed Usage:</span>
              <span className="text-slate-300 font-mono text-[11px]">{observedUsage}</span>
            </div>
          )}
          {expectedContract && (
            <div className="flex items-start space-x-2">
              <span className="font-semibold text-emerald-300 shrink-0">Expected Contract:</span>
              <span className="text-slate-300 leading-relaxed">{expectedContract}</span>
            </div>
          )}
        </div>
      )}

      {/* 4. Relevant Documented API Requirement */}
      {documentedRequirement && (
        <div
          data-testid="finding-documented-requirement"
          className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 text-[11px] text-slate-300 space-y-1"
        >
          <div className="flex items-center space-x-1.5 text-cyan-300 font-medium">
            <BookOpen className="w-3.5 h-3.5 text-accent-cyan shrink-0" />
            <span>Documented API Requirement:</span>
          </div>
          <p className="text-slate-300 pl-5 leading-relaxed">{documentedRequirement}</p>
        </div>
      )}

      {/* 5. Supporting Evidence Excerpt & Exact Quotation Receipt */}
      {supportingExcerpt ? (
        <div
          data-testid="finding-evidence-receipt"
          className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2"
        >
          <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-400 gap-1.5">
            <span className="flex items-center space-x-1.5 text-accent-cyan font-medium">
              <Quote className="w-3.5 h-3.5" />
              <span>Official Documentation Evidence Excerpt:</span>
            </span>
            <div className="flex items-center space-x-1.5 flex-wrap gap-1">
              {quoteKind && (
                <span
                  data-testid="quote-kind-badge"
                  className="text-[10px] px-2 py-0.5 rounded bg-cyan-950/70 text-cyan-300 border border-cyan-800/60 font-mono"
                >
                  {quoteKind === "exact_quotation"
                    ? "Exact Quotation"
                    : quoteKind === "structured_contract"
                    ? "Structured Contract"
                    : quoteKind === "paraphrase"
                    ? "Paraphrase"
                    : quoteKind}
                </span>
              )}
              {matchMethod && (
                <span
                  data-testid="match-method-badge"
                  className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono border border-slate-700"
                >
                  {matchMethod === "exact"
                    ? "Exact Substring Match"
                    : matchMethod === "whitespace_normalized"
                    ? "Whitespace-Normalized Match"
                    : "No Direct Match"}
                </span>
              )}
            </div>
          </div>

          <blockquote
            data-testid="finding-evidence-excerpt"
            className="italic text-slate-200 border-l-2 border-accent-cyan pl-3 text-xs leading-relaxed"
          >
            "{supportingExcerpt}"
          </blockquote>

          {/* Evidence Rationale */}
          {evidenceRationale && (
            <p className="text-[11px] text-slate-400 pl-3">
              <span className="font-semibold text-slate-300">Rationale: </span>
              {evidenceRationale}
            </p>
          )}

          {/* Usable & Accessible Source Link + Fingerprint + Metadata */}
          <div className="pt-2 border-t border-slate-900 space-y-1.5">
            {(sourceTitle || retrievalStatus || retrievedAt) && (
              <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-400 gap-1.5">
                <div className="flex items-center space-x-2 flex-wrap">
                  {sourceTitle && (
                    <span className="font-semibold text-slate-300">
                      Doc Title: <span className="text-slate-200 font-normal">{sourceTitle}</span>
                    </span>
                  )}
                  {retrievalStatus && (
                    <span className="px-1.5 py-0.2 rounded bg-slate-900 text-slate-400 border border-slate-800 font-mono text-[9px] uppercase">
                      Status: {retrievalStatus}
                    </span>
                  )}
                  {retrievedAt && (
                    <span className="text-slate-500 font-mono text-[9px]">
                      Retrieved: {retrievedAt.replace("T", " ").replace("Z", "")}
                    </span>
                  )}
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-500 gap-2">
              {(canonicalUrl || sourceUrl) && ((canonicalUrl || sourceUrl)!.startsWith("https://") || (canonicalUrl || sourceUrl)!.startsWith("http://")) ? (
                <a
                  href={canonicalUrl || sourceUrl || ""}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="finding-source-link"
                  aria-label={`View official Stripe documentation at ${canonicalUrl || sourceUrl} (opens in new tab)`}
                  className="text-accent-cyan hover:underline flex items-center space-x-1.5 font-medium transition-colors"
                >
                  <span className="truncate max-w-sm">{canonicalUrl || sourceUrl}</span>
                  <ExternalLink className="w-3 h-3 shrink-0" />
                </a>
              ) : (canonicalUrl || sourceUrl) ? (
                <span
                  data-testid="finding-source-untrusted-link"
                  className="text-amber-400 italic flex items-center space-x-1"
                  title="URL scheme is not recognized as a secure HTTPS documentation link"
                >
                  <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
                  <span className="truncate max-w-sm">{canonicalUrl || sourceUrl} (untrusted protocol)</span>
                </span>
              ) : (
                <span
                  data-testid="finding-source-unavailable"
                  className="text-slate-500 italic flex items-center space-x-1"
                >
                  <Info className="w-3 h-3 text-slate-500 shrink-0" />
                  <span>Official documentation source link unavailable</span>
                </span>
              )}

              {evidenceFingerprint && (
                <span
                  data-testid="finding-evidence-fingerprint"
                  className="font-mono text-[10px] text-slate-400"
                  title="Cryptographic digest of evaluated excerpt. Proves content identity, not publisher authenticity."
                >
                  SHA-256: {evidenceFingerprint}
                </span>
              )}
            </div>
          </div>
        </div>
      ) : (
        // Requirement 8: Handle findings with missing evidence safely
        <div
          data-testid="finding-evidence-missing"
          className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80 text-[11px] text-slate-400 italic flex items-center space-x-2"
        >
          <Info className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <span>
            {isUnverified
              ? "No official documentation excerpt available for this advisory hypothesis."
              : isUnableToVerify
              ? "Official documentation was missing, ambiguous, or incomplete for this candidate."
              : "Official documentation excerpt unavailable."}
          </span>
        </div>
      )}

      {/* 6. Uncertainty or Limitations (Requirement 5) */}
      {uncertaintyOrLimitations && (
        <div
          data-testid="finding-uncertainty-limitations"
          className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-800/60 text-[11px] text-amber-200/90 flex items-start space-x-2"
        >
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <span className="font-semibold text-amber-300">
              {isUnverified ? "What Remains Unverified: " : "Uncertainty & Limitations: "}
            </span>
            <span className="text-amber-200/80 leading-relaxed">{uncertaintyOrLimitations}</span>
          </div>
        </div>
      )}

      {/* 7. Suggested Correction (if available) */}
      {suggestedCorrection && (
        <div
          data-testid="finding-suggested-correction"
          className="p-2.5 rounded-lg bg-violet-950/30 border border-violet-800/60 text-[11px] text-violet-200 flex items-start space-x-2"
        >
          <Wrench className="w-3.5 h-3.5 text-accent-cyan shrink-0 mt-0.5" />
          <div>
            <strong className="text-violet-300 font-semibold">Suggested Correction: </strong>
            <span className="text-slate-300">{suggestedCorrection}</span>
          </div>
        </div>
      )}

      {/* 8. Suggested Next Action (Developer Guidance) */}
      {suggestedAction && suggestedAction !== suggestedCorrection && (
        <div
          data-testid="finding-suggested-action"
          className="p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-800/60 text-[11px] text-emerald-200 flex items-start space-x-2"
        >
          <ArrowRight className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
          <div>
            <strong className="text-emerald-300 font-semibold">Actionable Next Step: </strong>
            <span className="text-slate-300">{suggestedAction}</span>
          </div>
        </div>
      )}
    </div>
  );
};

