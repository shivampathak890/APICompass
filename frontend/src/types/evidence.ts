import { SourceLocation, SyntaxErrorInfo } from "./ast";
import { NormalizedEvidence } from "./docs";

export type VerdictType = "clean" | "issues_found" | "unable_to_verify";
export type EvidenceTrustType = "live_official_source" | "mock_fixture" | "untrusted_or_unavailable";
export type MatchMethodType = "exact" | "whitespace_normalized" | "none";
export type CompletenessType = "complete_contract" | "excerpt_only" | "unrelated" | "missing";
export type CandidateStatusType = "resolved_clean" | "resolved_issue" | "unresolved";
export type QuoteKindType = "exact_quotation" | "paraphrase" | "structured_contract" | "none";
export type VerificationStatusType = "verified" | "unverified_suggestion" | "unable_to_verify" | "no_issue_detected";

export interface QuoteVerificationResult {
  is_verified: boolean;
  match_method: MatchMethodType;
  matched_text?: string | null;
  evidence_id: string;
  source_url: string;
  content_hash: string;
  quote_kind?: QuoteKindType;
  is_mock?: boolean;
  error_message?: string | null;
}

export interface EvidenceMatch {
  candidate_id: string;
  matched_operation?: string | null;
  evidence_id?: string | null;
  source_url?: string | null;
  canonical_url?: string | null;
  source_title?: string | null;
  retrieval_status?: string | null;
  retrieved_at?: string | null;
  is_mock?: boolean;
  completeness: CompletenessType;
  is_ambiguous: boolean;
  match_rationale: string;
}

export interface VerifiedIssue {
  issue_id: string;
  candidate_id: string;
  source_location: SourceLocation;
  claim_checked: string;
  violation_type: string;
  explanation: string;
  supporting_evidence_id: string;
  source_url: string;
  canonical_url?: string | null;
  source_title?: string | null;
  retrieval_status?: string | null;
  retrieved_at?: string | null;
  content_sha256?: string | null;
  is_mock?: boolean;
  verified_quote: string;
  match_method: MatchMethodType;
  verification_status?: VerificationStatusType;
  quote_kind?: QuoteKindType;
  supporting_excerpt?: string | null;
  evidence_rationale?: string | null;
  limitations?: string | null;
  file_path?: string | null;
  title?: string | null;
  code_fragment?: string | null;
  documented_requirement?: string | null;
  impact_classification?: string | null;
  suggested_correction?: string | null;
  severity?: "error" | "warning" | "info" | string | null;
  confidence?: "verified" | "probable" | "speculative" | "uncertain" | string | null;
  detected_call?: string | null;
  detected_argument?: string | null;
  expected_contract?: string | null;
  observed_usage?: string | null;
  suggested_action?: string | null;
}

export interface CandidateAssessment {
  candidate_id: string;
  target_name: string;
  receiver?: string | null;
  call_expr: string;
  source_location: SourceLocation;
  status: CandidateStatusType;
  verification_status?: VerificationStatusType;
  evidence_match?: EvidenceMatch | null;
  verified_quotes: QuoteVerificationResult[];
  issues: VerifiedIssue[];
  abstention_reason?: string | null;
  explanation: string;
  file_path?: string | null;
  title?: string | null;
  documented_requirement?: string | null;
  impact_classification?: string | null;
  suggested_correction?: string | null;
  severity?: "error" | "warning" | "info" | string | null;
  confidence?: "verified" | "probable" | "speculative" | "uncertain" | string | null;
  detected_call?: string | null;
  detected_argument?: string | null;
  expected_contract?: string | null;
  observed_usage?: string | null;
  suggested_action?: string | null;
  uncertainty_or_limitations?: string | null;
  source_url?: string | null;
  canonical_url?: string | null;
  source_title?: string | null;
  retrieval_status?: string | null;
  retrieved_at?: string | null;
  content_sha256?: string | null;
  is_mock?: boolean;
}

export interface AISuggestion {
  suggestion_id: string;
  candidate_id: string;
  claim_type: string;
  description: string;
  unverified_aspects: string;
  suggested_documentation_queries: string[];
  referenced_evidence_ids: string[];
  confidence: string;
  reasoning_summary?: string | null;
  verification_status?: VerificationStatusType;
  label: string;
  file_path?: string | null;
  title?: string | null;
  source_location?: SourceLocation | null;
  code_fragment?: string | null;
  documented_requirement?: string | null;
  source_url?: string | null;
  suggested_correction?: string | null;
}

export interface AnalysisRequest {
  source: string;
  filename?: string;
  ecosystem?: string;
  force_mock?: boolean;
}

export interface AnalysisReport {
  verdict: VerdictType;
  result_state?: VerificationStatusType;
  engine_version: string;
  filename: string;
  total_lines: number;
  evidence_trust: EvidenceTrustType;
  is_mock: boolean;
  summary: string;
  checks_performed: string[];
  verified_issues: VerifiedIssue[];
  ai_suggestions: AISuggestion[];
  unresolved_candidates: string[];
  candidate_assessments: CandidateAssessment[];
  evidence_items: NormalizedEvidence[];
  limitations_and_caveats: string[];
  syntax_error?: SyntaxErrorInfo | null;
  llm_reasoning_status: string;
  llm_reasoning_summary?: string | null;
  disclaimer: string;
  scan_id?: string | null;
  persistence_status?: "saved" | "failed" | "disabled" | null;
}
