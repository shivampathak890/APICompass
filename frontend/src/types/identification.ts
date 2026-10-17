import { CallArgument, SourceLocation, SyntaxErrorInfo } from "./ast";

export interface IdentifiedApiCall {
  call_id: string;
  sdk_or_library: string;
  api_resource?: string | null;
  operation?: string | null;
  symbol: string;
  raw_expression: string;
  positional_arguments: CallArgument[];
  keyword_arguments: Record<string, CallArgument>;
  location: SourceLocation;
  confidence: "confirmed" | "ambiguous" | "unsupported" | "uncertain_receiver" | string;
  is_ambiguous: boolean;
  unresolved_ambiguity?: string | null;
  doc_query?: string | null;
  canonical_doc_url?: string | null;
  matching_strategy: string;
}

export interface IdentifyApiCallsRequest {
  source: string;
  filename?: string;
  ecosystem?: string;
}

export interface IdentifyApiCallsResponse {
  status: "success" | "syntax_error" | "source_too_large" | "complexity_limit_exceeded" | string;
  filename: string;
  total_calls_detected: number;
  identified_calls: IdentifiedApiCall[];
  confirmed_count: number;
  ambiguous_count: number;
  unsupported_count: number;
  syntax_error?: SyntaxErrorInfo | null;
}

