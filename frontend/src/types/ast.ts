export interface SourceLocation {
  lineno: number;
  col_offset: number;
  end_lineno?: number | null;
  end_col_offset?: number | null;
}

export interface ImportInfo {
  module: string;
  name?: string | null;
  alias?: string | null;
  is_from: boolean;
  level: number;
  location: SourceLocation;
}

export interface ParameterInfo {
  name: string;
  category: "posonly" | "standard" | "kwonly" | "vararg" | "kwarg" | string;
  has_default: boolean;
  default_repr?: string | null;
  type_annotation?: string | null;
}

export interface FunctionInfo {
  name: string;
  is_async: boolean;
  parameters: ParameterInfo[];
  decorators: string[];
  return_annotation?: string | null;
  enclosing_scope?: string | null;
  location: SourceLocation;
}

export interface ClassInfo {
  name: string;
  bases: string[];
  decorators: string[];
  methods: string[];
  enclosing_scope?: string | null;
  location: SourceLocation;
}

export interface CallArgument {
  name?: string | null;
  position?: number | null;
  value_repr: string;
  value_type: string;
  is_literal: boolean;
  literal_value?: unknown;
  location: SourceLocation;
}

export interface CallInfo {
  call_expr: string;
  receiver?: string | null;
  method?: string | null;
  is_attribute_call: boolean;
  positional_args_count: number;
  keyword_args: string[];
  arguments?: CallArgument[];
  enclosing_scope?: string | null;
  location: SourceLocation;
}

export interface ApiCandidate {
  candidate_id: string;
  expression: string;
  receiver?: string | null;
  target_name: string;
  normalized_target?: string | null;
  is_ambiguous?: boolean;
  kind: string;
  confidence: "heuristic" | string;
  rationale: string;
  enclosing_scope?: string | null;
  location: SourceLocation;
}

export interface RelevantLiteral {
  value: string;
  kind: "http_method" | "endpoint_path" | "api_url" | "api_version" | string;
  reason: string;
  location: SourceLocation;
}

export interface SyntaxErrorInfo {
  message: string;
  lineno?: number | null;
  col_offset?: number | null;
  text?: string | null;
}

export interface AnalyzePythonRequest {
  source: string;
  filename?: string;
}

export interface AnalyzePythonResponse {
  status: "success" | "syntax_error" | "source_too_large" | "complexity_limit_exceeded" | string;
  engine_version: string;
  filename: string;
  total_lines: number;
  imports: ImportInfo[];
  functions: FunctionInfo[];
  classes: ClassInfo[];
  calls: CallInfo[];
  candidates: ApiCandidate[];
  relevant_literals: RelevantLiteral[];
  syntax_error?: SyntaxErrorInfo | null;
  disclaimer: string;
}

