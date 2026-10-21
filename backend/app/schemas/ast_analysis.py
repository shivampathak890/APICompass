"""Pydantic schemas for static Python AST analysis."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_safe_filename(filename: str) -> str:
    """Validate and sanitize a single-file virtual filename.

    Security rules:
    - Rejects empty or whitespace-only filenames.
    - Rejects NUL bytes (prevents C-string truncation attacks).
    - Rejects carriage returns and newlines (prevents CWE-117 log injection).
    - Rejects path traversal components ('..').
    - Rejects absolute paths (leading '/' or '\\') and drive letters ('C:').
    - Enforces maximum length of 255 characters.
    - Preserves safe relative subpaths (e.g. 'services/payment.py').
    """
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Filename cannot be empty.")
    clean = filename.strip()
    if "\0" in clean:
        raise ValueError("Filename contains prohibited NUL character.")
    if "\n" in clean or "\r" in clean:
        raise ValueError("Filename contains prohibited newline or carriage return character.")
    if len(clean) > 255:
        raise ValueError("Filename exceeds maximum permitted length of 255 characters.")
    if clean.startswith("/") or clean.startswith("\\"):
        raise ValueError("Absolute file paths are not permitted in filename.")
    if re.match(r"^[a-zA-Z]:", clean):
        raise ValueError("Drive-qualified paths are not permitted in filename.")

    parts = clean.replace("\\", "/").split("/")
    for part in parts:
        if part == "..":
            raise ValueError("Path traversal component ('..') is prohibited in filename.")

    return clean


class SourceLocation(BaseModel):
    """Source code line and column coordinates."""
    model_config = ConfigDict(extra="forbid")

    lineno: int = Field(..., description="1-indexed line number")
    col_offset: int = Field(..., description="0-indexed column offset")
    end_lineno: Optional[int] = Field(default=None, description="Ending line number")
    end_col_offset: Optional[int] = Field(default=None, description="Ending column offset")


class ImportInfo(BaseModel):
    """Information about an imported module or symbol."""
    model_config = ConfigDict(extra="forbid")

    module: str = Field(..., description="Module path (e.g., 'stripe' or 'os.path')")
    name: Optional[str] = Field(default=None, description="Imported symbol name if from-import")
    alias: Optional[str] = Field(default=None, description="Local alias (as name) if used")
    is_from: bool = Field(default=False, description="True for 'from X import Y'")
    level: int = Field(default=0, description="Relative import level (number of leading dots)")
    location: SourceLocation


class ParameterInfo(BaseModel):
    """Function or method parameter metadata."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Parameter name")
    category: str = Field(
        ..., 
        description="Category: 'posonly', 'standard', 'kwonly', 'vararg', or 'kwarg'"
    )
    has_default: bool = Field(default=False, description="True if a default expression exists")
    default_repr: Optional[str] = Field(
        default=None, 
        description="Text representation of default value (not evaluated)"
    )
    type_annotation: Optional[str] = Field(
        default=None, 
        description="Type hint expression text if annotated"
    )


class FunctionInfo(BaseModel):
    """Function or async function definition details."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Function name")
    is_async: bool = Field(default=False, description="True if async def")
    parameters: List[ParameterInfo] = Field(default_factory=list)
    decorators: List[str] = Field(default_factory=list, description="Decorator expressions as text")
    return_annotation: Optional[str] = Field(default=None, description="Return type hint as text")
    enclosing_scope: Optional[str] = Field(default=None, description="Enclosing class or function name")
    location: SourceLocation


class ClassInfo(BaseModel):
    """Class definition details."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Class identifier")
    bases: List[str] = Field(default_factory=list, description="Base classes as text expressions")
    decorators: List[str] = Field(default_factory=list, description="Class decorators as text")
    methods: List[str] = Field(default_factory=list, description="Declared method names")
    enclosing_scope: Optional[str] = Field(default=None, description="Enclosing scope name")
    location: SourceLocation


class CallArgument(BaseModel):
    """Structured representation of a positional or keyword call argument."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, description="Keyword argument name, or None if positional")
    position: Optional[int] = Field(default=None, description="0-indexed positional index, or None if keyword")
    value_repr: str = Field(..., description="Source code text representation of the argument expression")
    value_type: str = Field(
        ..., 
        description="Classified argument type: 'literal_str', 'literal_int', 'literal_float', 'literal_bool', 'literal_none', 'literal_list', 'literal_dict', 'identifier', 'call', 'attribute', 'starred', 'kwargs_unpack', 'binary_op', 'expression'"
    )
    is_literal: bool = Field(..., description="True only if statically determined to be a compile-time literal constant")
    literal_value: Optional[Any] = Field(default=None, description="Evaluated literal value if is_literal=True, else None")
    location: SourceLocation


class CallInfo(BaseModel):
    """Call expression extraction."""
    model_config = ConfigDict(extra="forbid")

    call_expr: str = Field(..., description="Function or method call expression as source text")
    receiver: Optional[str] = Field(default=None, description="Receiver expression for attribute calls")
    method: Optional[str] = Field(default=None, description="Method identifier for attribute calls")
    is_attribute_call: bool = Field(default=False, description="True if call is an attribute access (e.g. obj.method())")
    positional_args_count: int = Field(default=0, description="Count of positional arguments")
    keyword_args: List[str] = Field(default_factory=list, description="Keyword argument names")
    arguments: List[CallArgument] = Field(default_factory=list, description="Structured call arguments")
    enclosing_scope: Optional[str] = Field(default=None, description="Enclosing scope name")
    location: SourceLocation


class ApiCandidate(BaseModel):
    """Heuristic candidate for potential API interaction."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., description="Unique deterministic candidate ID")
    expression: str = Field(..., description="Call expression text")
    receiver: Optional[str] = Field(default=None, description="Caller object/class expression")
    target_name: str = Field(..., description="Invoked function or method name")
    normalized_target: Optional[str] = Field(default=None, description="Canonical normalized target identifier (e.g. 'stripe.Charge.create')")
    is_ambiguous: bool = Field(default=False, description="True if call pattern is ambiguous, generic, or unresolved")
    kind: str = Field(default="method_call", description="Candidate kind: 'method_call', 'direct_call', or 'attribute_access'")
    confidence: str = Field(default="heuristic", description="Confidence label: 'heuristic' (unverified)")
    rationale: str = Field(..., description="Explanation of why this candidate was selected")
    enclosing_scope: Optional[str] = Field(default=None, description="Enclosing function or class")
    location: SourceLocation

    @property
    def call_expr(self) -> str:
        """Alias for expression for compatibility with call descriptors."""
        return self.expression


class RelevantLiteral(BaseModel):
    """String literal identified as a potential HTTP method, endpoint, or API version."""
    model_config = ConfigDict(extra="forbid")

    value: str = Field(..., description="Literal string value")
    kind: str = Field(..., description="Category: 'http_method', 'endpoint_path', 'api_url', or 'api_version'")
    reason: str = Field(..., description="Heuristic rationale for selection")
    location: SourceLocation


class SyntaxErrorInfo(BaseModel):
    """Structured information for Python syntax errors."""
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="Syntax error explanation")
    lineno: Optional[int] = Field(default=None, description="Line number of syntax error")
    col_offset: Optional[int] = Field(default=None, description="Column offset of syntax error")
    text: Optional[str] = Field(default=None, description="Source line containing the error")


class AnalyzePythonRequest(BaseModel):
    """Request payload for static Python AST analysis."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        ..., 
        max_length=100_000, 
        description="Python source code text to analyze (max 100 KB)"
    )
    filename: str = Field(
        default="<unknown>", 
        max_length=255, 
        description="Optional source file identifier"
    )

    @field_validator("filename")
    @classmethod
    def validate_filename_security(cls, v: str) -> str:
        return validate_safe_filename(v)


class AnalyzePythonResponse(BaseModel):
    """Response payload for static Python AST analysis."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="Analysis status: 'success', 'syntax_error', 'source_too_large', or 'complexity_limit_exceeded'")
    engine_version: str = Field(default="0.1.0", description="AST analyzer engine version")
    filename: str = Field(..., description="Filename analyzed")
    total_lines: int = Field(default=0, description="Total source lines")
    imports: List[ImportInfo] = Field(default_factory=list)
    functions: List[FunctionInfo] = Field(default_factory=list)
    classes: List[ClassInfo] = Field(default_factory=list)
    calls: List[CallInfo] = Field(default_factory=list)
    candidates: List[ApiCandidate] = Field(default_factory=list)
    relevant_literals: List[RelevantLiteral] = Field(default_factory=list)
    syntax_error: Optional[SyntaxErrorInfo] = Field(default=None)
    disclaimer: str = Field(
        default="Heuristic candidates are statically extracted from code structure and are not verified against official documentation.",
        description="Static analysis heuristic disclaimer"
    )
