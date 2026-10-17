import { AnalysisReport } from "./evidence";

export type ScanStage =
  | "accepted"
  | "static_analysis_started"
  | "static_analysis_completed"
  | "ai_reasoning_started"
  | "ai_reasoning_completed"
  | "documentation_retrieval_started"
  | "doc_search_started"
  | "doc_search_completed"
  | "doc_fetch_started"
  | "doc_fetch_completed"
  | "documentation_retrieval_completed"
  | "evidence_verification_started"
  | "evidence_verification_completed"
  | "persistence_started"
  | "persistence_completed"
  | "completed"
  | "failed";

export interface ScanProgressEvent {
  event_version: string;
  scan_id?: string | null;
  stage: ScanStage;
  message: string;
  timestamp: string;
  progress_percent?: number | null;
  error_code?: string | null;
  report?: AnalysisReport | null;
}
