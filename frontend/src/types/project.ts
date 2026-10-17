import {
  ApiCandidate,
  CallInfo,
  ClassInfo,
  FunctionInfo,
  ImportInfo,
  RelevantLiteral,
  SourceLocation,
  SyntaxErrorInfo,
} from "./ast";
import { NormalizedEvidence } from "./docs";
import {
  AISuggestion,
  CandidateAssessment,
  EvidenceTrustType,
  VerdictType,
  VerifiedIssue,
} from "./evidence";

export interface ProjectFileItem {
  path: string;
  content: string;
}

export interface ProjectAnalysisRequest {
  project_name?: string;
  ecosystem?: string;
  files: ProjectFileItem[];
  force_mock?: boolean;
}

export type RelationshipType = "file_imports_file" | "file_imports_external" | "symbol_reference";
export type ResolutionStatus = "resolved" | "unresolved" | "ambiguous" | "external";

export interface ProjectRelationship {
  source_file: string;
  target: string;
  target_file?: string | null;
  relationship_type: RelationshipType;
  imported_symbol?: string | null;
  alias?: string | null;
  status: ResolutionStatus;
  reason: string;
  location: SourceLocation;
}

export interface ProjectFileAnalysisResult {
  path: string;
  parse_status: "success" | "syntax_error";
  total_lines: number;
  syntax_error?: SyntaxErrorInfo | null;
  imports: ImportInfo[];
  functions: FunctionInfo[];
  classes: ClassInfo[];
  calls: CallInfo[];
  candidates: ApiCandidate[];
  relevant_literals: RelevantLiteral[];
  defined_symbols: string[];
}

export interface ProjectAnalysisReport {
  project_name: string;
  verdict: VerdictType;
  engine_version: string;
  total_files: number;
  total_lines: number;
  parsed_files_count: number;
  syntax_errors_count: number;
  total_candidates: number;
  resolved_imports_count: number;
  unresolved_imports_count: number;
  ambiguous_imports_count: number;
  external_imports_count: number;
  evidence_trust: EvidenceTrustType;
  is_mock: boolean;
  summary: string;
  checks_performed: string[];
  relationships: ProjectRelationship[];
  files: ProjectFileAnalysisResult[];
  verified_issues: VerifiedIssue[];
  ai_suggestions: AISuggestion[];
  unresolved_candidates: string[];
  candidate_assessments: CandidateAssessment[];
  evidence_items: NormalizedEvidence[];
  limitations_and_caveats: string[];
  disclaimer: string;
  scan_id?: string | null;
  persistence_status?: "saved" | "failed" | "disabled" | null;
}
