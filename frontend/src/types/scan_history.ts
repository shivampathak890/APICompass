import { VerdictType, EvidenceTrustType, VerifiedIssue, AISuggestion } from "./evidence";
import { NormalizedEvidence } from "./docs";

export interface ScanSummaryItem {
  scan_id: string;
  created_at: string;
  verdict: VerdictType;
  ecosystem: string;
  filename: string;
  source_sha256: string;
  source_length: number;
  evidence_trust: EvidenceTrustType;
  is_mock: boolean;
  candidates_count: number;
  issues_count: number;
  evidence_count: number;
  suggestions_count: number;
  summary: string;
  status: string;
}

export interface ScanListResponse {
  items: ScanSummaryItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ProjectFileDetailSummary {
  file_path: string;
  source_sha256: string;
  source_length: number;
  parse_status: string;
  candidates_count: number;
  syntax_error?: string | null;
}

export interface HistoricalScanDetail {
  scan_id: string;
  is_historical: boolean;
  schema_version: number;
  created_at: string;
  completed_at?: string | null;
  status: string;
  verdict: VerdictType;
  ecosystem: string;
  filename: string;
  source_sha256: string;
  source_length: number;
  pipeline_version: string;
  evidence_trust: EvidenceTrustType;
  is_mock: boolean;
  llm_reasoning_status: string;
  summary: string;
  abstention_reason?: string | null;
  checks_performed: string[];
  verified_issues: VerifiedIssue[];
  ai_suggestions: AISuggestion[];
  evidence_items: NormalizedEvidence[];
  limitations_and_caveats: string[];
  disclaimer: string;
  integrity_hash: string;
  project_files?: ProjectFileDetailSummary[] | null;
}

export interface DeleteScanResponse {
  success: boolean;
  scan_id: string;
  deleted_at: string;
}

