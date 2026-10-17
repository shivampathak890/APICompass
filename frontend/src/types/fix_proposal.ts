import { EvidenceTrustType } from "./evidence";

export type FixProposalStatusType =
  | "evidence_supported"
  | "insufficient_evidence"
  | "mock_evidence_only"
  | "unsupported_candidate"
  | "proposal_invalid"
  | "syntax_check_failed"
  | "reverification_inconclusive";

export type ReverificationStatusType =
  | "verified_resolved"
  | "partially_resolved"
  | "concern_persists"
  | "reverification_inconclusive"
  | "syntax_invalid"
  | "not_attempted";

export type FixProposalType =
  | "verified_correction"
  | "suggested_patch"
  | "ineligible";

export interface ProposeFixRequest {
  source: string;
  candidate_id: string;
  filename?: string;
  ecosystem?: string;
  issue_id?: string;
}

export interface FixProposalResponse {
  proposal_id: string;
  candidate_id: string;
  status: FixProposalStatusType;
  proposal_type?: FixProposalType;
  summary: string;
  reasoning: string;
  original_excerpt?: string | null;
  proposed_excerpt?: string | null;
  unified_diff?: string | null;
  proposed_source?: string | null;
  supporting_evidence_ids: string[];
  supporting_quotes: string[];
  source_urls: string[];
  evidence_trust: EvidenceTrustType;
  is_mock: boolean;
  is_ai_generated: boolean;
  syntax_valid: boolean;
  reverification_status: ReverificationStatusType;
  remaining_uncertainties: string[];
  warnings: string[];
  disclaimer: string;
}
