export interface DocSection {
  heading: string;
  level: number;
  content: string;
}

export interface DocParameter {
  name: string;
  param_type?: string | null;
  is_required: boolean;
  is_deprecated: boolean;
  description?: string | null;
}

export interface NormalizedDocPage {
  url: string;
  final_url: string;
  title?: string | null;
  doc_version?: string | null;
  content: string;
  content_sha256: string;
  headings: string[];
  sections: DocSection[];
  parameters: DocParameter[];
  required_fields: string[];
  deprecation_notices: string[];
  code_examples: string[];
  is_mock: boolean;
  provider: string;
  retrieved_at: string;
  is_full_page: boolean;
}

export interface NormalizedEvidence {
  evidence_id: string;
  ecosystem: string;
  package: string;
  source_url: string;
  canonical_url: string;
  title?: string | null;
  content_excerpt: string;
  retrieved_at: string;
  provider: string;
  status: "success" | "partial" | "unavailable" | "rejected" | "mock" | string;
  is_mock: boolean;
  source_trust: string;
  doc_version?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  raw_markdown?: string | null;
  content_sha256?: string | null;
  headings?: string[];
  parameters?: DocParameter[];
  required_fields?: string[];
  deprecation_notices?: string[];
  code_examples?: string[];
  page_data?: NormalizedDocPage | null;
  is_full_page?: boolean;
}

export interface DocRetrievalRequest {
  ecosystem?: string;
  package?: string;
  query?: string | null;
  target_url?: string | null;
  max_results?: number;
  force_mock?: boolean;
}

export interface DocRetrievalResponse {
  status: "success" | "partial" | "unavailable" | "rejected" | "mock" | string;
  provider: string;
  is_mock: boolean;
  total_results: number;
  evidence: NormalizedEvidence[];
  message?: string | null;
  disclaimer: string;
}

export interface SearchResultItem {
  url: string;
  canonical_url: string;
  title?: string | null;
  snippet?: string | null;
  site_name?: string | null;
  position: number;
  relevance_score: number;
  is_approved_domain: boolean;
}

export interface DocSearchRequest {
  query: string;
  ecosystem?: string;
  limit?: number;
  force_mock?: boolean;
}

export interface DocSearchResponse {
  query: string;
  ecosystem: string;
  provider: string;
  is_mock: boolean;
  status: "success" | "empty" | "unavailable" | "rate_limited" | "auth_failed" | string;
  total_results: number;
  results: SearchResultItem[];
  message?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  disclaimer: string;
}
