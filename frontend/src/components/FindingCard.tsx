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
        className="rounded-xl border border-emerald-300 bg-emerald-50/40 p-4 text-xs space-y-3 shadow-sm backdrop-blur-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-200/80 pb-2.5">
          <div className="flex items-center space-x-2">
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center space-x-1.5 shadow-sm"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              <span>NO ISSUE DETECTED</span>
            </span>
            <h4 className="font-serif font-semibold text-slate-900 text-xs">
              {title || "API Call Conforms to Verified Contract Constraints"}
            </h4>
          </div>
          {sourceLine && onJumpToLine && (
            <button
              onClick={() => onJumpToLine(sourceLine)}
              data-testid="jump-to-line-button"
              aria-label={`Jump to line ${sourceLine} in editor`}
              className="text-[10px] font-mono text-[#163A6E] hover:text-[#0f284e] bg-white hover:bg-slate-100 px-2 py-0.5 rounded-md border border-slate-300 flex items-center space-x-1 transition-colors shadow-xs"
            >
              <span>{filePath}:{sourceLine}</span>
              <ArrowRight className="w-2.5 h-2.5 text-[#163A6E]" />
            </button>
          )}
        </div>

        {codeFragment && (
          <div
            data-testid="finding-code-fragment"
            className="p-2.5 rounded-lg bg-white border border-slate-200 font-mono text-[11px] text-slate-800 overflow-x-auto shadow-inner"
          >
            <code>{codeFragment}</code>
          </div>
        )}

        <p className="text-slate-700 text-xs leading-relaxed font-sans">{explanation}</p>

        {/* Requirement 6: Explicitly explain that "no issue detected" covers only the checks performed */}
        <div
          data-testid="scope-limitation-notice"
          className="p-3 rounded-lg bg-white/80 border border-emerald-200 text-[11px] text-slate-700 space-y-2 shadow-xs"
        >
          <div className="flex items-center space-x-1.5 text-emerald-800 font-semibold">
            <Info className="w-3.5 h-3.5 text-emerald-700 shrink-0" />
            <span>Scope of Verification & Disclaimer:</span>
          </div>
          <p className="text-slate-600 text-[11px] leading-relaxed">
            A <strong>"no issue detected"</strong> status indicates strictly that supported static checks found no
            documented contract violations within the analyzed scope. It covers only the checks actually performed and
            does <em>not</em> guarantee runtime correctness, API network reachability, valid credentials, or the absence of
            unrelated bugs.
          </p>
          {checksPerformed.length > 0 && (
            <div className="pt-1.5 border-t border-emerald-200/80">
              <span className="font-semibold text-slate-800 text-[10px] uppercase tracking-wider block mb-1">
                Checks Actively Performed:
              </span>
              <ul className="list-disc list-inside space-y-0.5 text-slate-600 text-[10px]">
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
      ? "border-amber-300 bg-amber-50/30"
      : "border-rose-300 bg-rose-50/20"
    : isUnverified
    ? "border-blue-200 bg-blue-50/30"
    : isRetrievalFailure
    ? "border-rose-300 bg-rose-50/30"
    : "border-slate-200 bg-white";

  return (
    <div
      data-testid={`finding-card-${id}`}
      className={`rounded-xl border ${containerBorder} p-4 text-xs space-y-3 transition-all shadow-sm backdrop-blur-sm`}
    >
      {/* 1. Header Bar: Status Badge, Title, Impact Classification, Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200/80 pb-2.5">
        <div className="flex items-center space-x-2 flex-wrap gap-1.5">
          {/* Confirmed Contract Mismatch (Live & Verified) */}
          {isVerified && !isMock && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300 flex items-center space-x-1 shadow-xs"
            >
              <AlertTriangle className="w-3 h-3 text-rose-600" />
              <span>VERIFIED (CONFIRMED MISMATCH)</span>
            </span>
          )}

          {/* Quarantined Mock Evidence */}
          {isVerified && isMock && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-amber-100 text-amber-900 border border-amber-300 flex items-center space-x-1 shadow-xs"
              title="Quarantined mock evidence cannot produce production verified findings."
            >
              <AlertTriangle className="w-3 h-3 text-amber-700" />
              <span>MOCK QUARANTINE (UNVERIFIED)</span>
            </span>
          )}

          {/* Potential Issue (Requires Review) */}
          {isUnverified && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-blue-100 text-[#163A6E] border border-blue-300 flex items-center space-x-1 shadow-xs"
            >
              <Sparkles className="w-3 h-3 text-[#163A6E]" />
              <span>UNVERIFIED SUGGESTION (REQUIRES REVIEW)</span>
            </span>
          )}

          {/* Documentation Retrieval Failure */}
          {isRetrievalFailure && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300 flex items-center space-x-1 shadow-xs"
              title="Documentation retrieval failed from upstream provider (network error, rate limit, or resource unavailable)."
            >
              <AlertTriangle className="w-3 h-3 text-rose-600" />
              <span>DOCUMENTATION RETRIEVAL FAILURE</span>
            </span>
          )}

          {/* Unable to Verify (Non-Retrieval Failure) */}
          {isUnableToVerify && !isRetrievalFailure && (
            <span
              data-testid="status-badge"
              className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-slate-100 text-slate-700 border border-slate-300 flex items-center space-x-1 shadow-xs"
            >
              <HelpCircle className="w-3 h-3 text-amber-600" />
              <span>UNABLE TO VERIFY</span>
            </span>
          )}

          {/* Provenance: Mock vs Live Documentation Distinction */}
          {isMock || retrievalStatus === "mock" ? (
            <span
              data-testid="provenance-mock-badge"
              className="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-300 flex items-center space-x-1 shadow-xs"
              title="Evidence derived from offline mock fixtures."
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
              <span>OFFLINE MOCK FIXTURE</span>
            </span>
          ) : (retrievalStatus === "success" || retrievalStatus === "live" || sourceUrl || canonicalUrl) ? (
            <span
              data-testid="provenance-live-badge"
              className="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-blue-50 text-[#163A6E] border border-blue-200 flex items-center space-x-1 shadow-xs"
              title="Substantiated by live official documentation retrieved from Stripe/TinyFish."
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#163A6E] inline-block" />
              <span>LIVE OFFICIAL DOCUMENTATION</span>
            </span>
          ) : null}

          {/* Impact Classification (if supported; no invented severity values) */}
          {impactClassification && (
            <span
              data-testid="impact-classification-badge"
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 border border-slate-300"
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
                  ? "bg-rose-100 text-rose-800 border-rose-300"
                  : severity.toLowerCase() === "warning"
                  ? "bg-amber-100 text-amber-800 border-amber-300"
                  : "bg-blue-100 text-blue-800 border-blue-300"
              }`}
            >
              {severity}
            </span>
          )}

          {/* Confidence Level */}
          {confidence && (
            <span
              data-testid="confidence-badge"
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-300"
              title="Confidence classification based on static AST precision and quote verification."
            >
              {confidence}
            </span>
          )}

          {/* Short Finding Title */}
          <h4
            data-testid="finding-title"
            className="font-serif font-semibold text-slate-900 text-xs ml-0.5 tracking-tight"
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
              className="px-3 py-1 rounded-lg bg-[#163A6E] hover:bg-[#0f284e] text-white font-semibold text-[11px] flex items-center space-x-1.5 transition-all shadow-sm"
              title="Propose evidence-gated fix for this finding"
            >
              <Wrench className="w-3.5 h-3.5 text-amber-300" />
              <span>{isProposingFix ? "Evaluating..." : "Propose Fix"}</span>
            </button>
          )}

          {sourceLine && onJumpToLine && (
            <button
              onClick={() => onJumpToLine(sourceLine)}
              data-testid="jump-to-line-button"
              aria-label={`Jump to line ${sourceLine} in editor`}
              className="text-[10px] font-mono text-[#163A6E] hover:text-[#0f284e] bg-slate-100 hover:bg-slate-200 px-2 py-0.5 rounded-md border border-slate-300 flex items-center space-x-1 transition-colors"
              title={`Jump to line ${sourceLine} in editor`}
            >
              <FileCode className="w-3 h-3 text-slate-500" />
              <span>{filePath ? `${filePath}:` : "Line "}{sourceLine}</span>
              <ArrowRight className="w-2.5 h-2.5 text-[#163A6E]" />
            </button>
          )}
        </div>
      </div>

      {/* Provider Retrieval Failure Warning Banner */}
      {isRetrievalFailure && (
        <div
          data-testid="retrieval-failure-notice"
          className="p-3 rounded-lg bg-rose-50 border border-rose-300 text-[11px] text-rose-900 space-y-1.5"
        >
          <div className="flex items-center space-x-2 font-semibold text-rose-800">
            <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
            <span>Upstream Documentation Retrieval Failure</span>
          </div>
          <p className="leading-relaxed text-rose-800/90">
            This issue represents an upstream documentation retrieval failure or network connectivity limitation,
            <strong> not a code-level contract violation</strong>. APICompass abstained from adjudicating your code to prevent false positives.
          </p>
        </div>
      )}

      {/* 2. Relevant Code Fragment */}
      {codeFragment ? (
        <div
          data-testid="finding-code-fragment"
          className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 font-mono text-[11px] text-slate-800 overflow-x-auto shadow-inner"
        >
          <div className="text-[10px] text-slate-500 pb-1 font-sans flex items-center space-x-1.5">
            <span>Evaluated Code Fragment:</span>
            {sourceLine && (
              <span className="text-slate-800 font-mono">
                Line {sourceLine}{sourceCol ? `:${sourceCol}` : ""}
              </span>
            )}
          </div>
          <code>{codeFragment}</code>
        </div>
      ) : sourceLine ? (
        <div className="text-[11px] text-slate-600 font-mono">
          Code location: {filePath}:{sourceLine}
        </div>
      ) : null}

      {/* 3. Explanation of the Suspected Issue */}
      <p
        data-testid="finding-explanation"
        className="text-slate-700 text-xs leading-relaxed font-sans"
      >
        {explanation}
      </p>

      {/* Contract Details Comparison (Observed vs Expected) */}
      {(expectedContract || observedUsage || detectedArgument || detectedCall) && (
        <div
          data-testid="contract-comparison-box"
          className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 space-y-2 text-[11px] shadow-xs"
        >
          <div className="flex items-center space-x-2 text-slate-600 font-semibold text-[10px] uppercase tracking-wider border-b border-slate-200 pb-1">
            <span>Contract Comparison</span>
            {detectedArgument && (
              <span className="text-[#163A6E] font-mono font-normal">
                param: <strong>{detectedArgument}</strong>
              </span>
            )}
          </div>
          {observedUsage && (
            <div className="flex items-start space-x-2">
              <span className="font-semibold text-rose-700 shrink-0">Observed Usage:</span>
              <span className="text-slate-800 font-mono text-[11px]">{observedUsage}</span>
            </div>
          )}
          {expectedContract && (
            <div className="flex items-start space-x-2">
              <span className="font-semibold text-emerald-700 shrink-0">Expected Contract:</span>
              <span className="text-slate-800 leading-relaxed">{expectedContract}</span>
            </div>
          )}
        </div>
      )}

      {/* 4. Relevant Documented API Requirement */}
      {documentedRequirement && (
        <div
          data-testid="finding-documented-requirement"
          className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 text-[11px] text-slate-700 space-y-1 shadow-xs"
        >
          <div className="flex items-center space-x-1.5 text-[#163A6E] font-medium">
            <BookOpen className="w-3.5 h-3.5 text-[#163A6E] shrink-0" />
            <span className="font-semibold">Documented API Requirement:</span>
          </div>
          <p className="text-slate-800 pl-5 leading-relaxed">{documentedRequirement}</p>
        </div>
      )}

      {/* 5. Supporting Evidence Excerpt & Exact Quotation Receipt */}
      {supportingExcerpt ? (
        <div
          data-testid="finding-evidence-receipt"
          className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-2 shadow-xs"
        >
          <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-600 gap-1.5">
            <span className="flex items-center space-x-1.5 text-[#163A6E] font-medium">
              <Quote className="w-3.5 h-3.5 text-[#163A6E]" />
              <span className="font-semibold">Official Documentation Evidence Excerpt:</span>
            </span>
            <div className="flex items-center space-x-1.5 flex-wrap gap-1">
              {quoteKind && (
                <span
                  data-testid="quote-kind-badge"
                  className="text-[10px] px-2 py-0.5 rounded-md bg-amber-50 text-amber-900 border border-amber-300 font-mono shadow-xs"
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
                  className="text-[10px] px-2 py-0.5 rounded-md bg-white text-slate-700 font-mono border border-slate-300 shadow-xs"
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
            className="italic text-slate-800 border-l-2 border-[#163A6E] bg-white/70 p-2.5 rounded-r-md pl-3 text-xs leading-relaxed font-sans shadow-xs"
          >
            "{supportingExcerpt}"
          </blockquote>

          {/* Evidence Rationale */}
          {evidenceRationale && (
            <p className="text-[11px] text-slate-600 pl-3">
              <span className="font-semibold text-slate-800">Rationale: </span>
              {evidenceRationale}
            </p>
          )}

          {/* Usable & Accessible Source Link + Fingerprint + Metadata */}
          <div className="pt-2 border-t border-slate-200 space-y-1.5">
            {(sourceTitle || retrievalStatus || retrievedAt) && (
              <div className="flex flex-wrap items-center justify-between text-[10px] text-slate-600 gap-1.5">
                <div className="flex items-center space-x-2 flex-wrap">
                  {sourceTitle && (
                    <span className="font-semibold text-slate-700">
                      Doc Title: <span className="text-slate-900 font-normal">{sourceTitle}</span>
                    </span>
                  )}
                  {retrievalStatus && (
                    <span className="px-1.5 py-0.2 rounded bg-white text-slate-700 border border-slate-300 font-mono text-[9px] uppercase">
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
                  className="text-[#163A6E] hover:text-[#0f284e] hover:underline flex items-center space-x-1.5 font-medium transition-colors"
                >
                  <span className="truncate max-w-sm">{canonicalUrl || sourceUrl}</span>
                  <ExternalLink className="w-3 h-3 shrink-0" />
                </a>
              ) : (canonicalUrl || sourceUrl) ? (
                <span
                  data-testid="finding-source-untrusted-link"
                  className="text-amber-700 italic flex items-center space-x-1"
                  title="URL scheme is not recognized as a secure HTTPS documentation link"
                >
                  <AlertTriangle className="w-3 h-3 text-amber-600 shrink-0" />
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
                  className="font-mono text-[10px] text-slate-500"
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
          className="p-2.5 rounded-lg bg-slate-100 border border-slate-200 text-[11px] text-slate-600 italic flex items-center space-x-2"
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
          className="p-2.5 rounded-lg bg-amber-50 border border-amber-300 text-[11px] text-amber-900 flex items-start space-x-2"
        >
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <span className="font-semibold text-amber-900">
              {isUnverified ? "What Remains Unverified: " : "Uncertainty & Limitations: "}
            </span>
            <span className="text-amber-800 leading-relaxed">{uncertaintyOrLimitations}</span>
          </div>
        </div>
      )}

      {/* 7. Suggested Correction (if available) */}
      {suggestedCorrection && (
        <div
          data-testid="finding-suggested-correction"
          className="p-2.5 rounded-lg bg-violet-50 border border-violet-200 text-[11px] text-violet-900 flex items-start space-x-2"
        >
          <Wrench className="w-3.5 h-3.5 text-[#163A6E] shrink-0 mt-0.5" />
          <div>
            <strong className="text-violet-900 font-semibold">Suggested Correction: </strong>
            <span className="text-slate-700">{suggestedCorrection}</span>
          </div>
        </div>
      )}

      {/* 8. Suggested Next Action (Developer Guidance) */}
      {suggestedAction && suggestedAction !== suggestedCorrection && (
        <div
          data-testid="finding-suggested-action"
          className="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-[11px] text-emerald-900 flex items-start space-x-2"
        >
          <ArrowRight className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" />
          <div>
            <strong className="text-emerald-900 font-semibold">Actionable Next Step: </strong>
            <span className="text-slate-700">{suggestedAction}</span>
          </div>
        </div>
      )}
    </div>
  );
};

