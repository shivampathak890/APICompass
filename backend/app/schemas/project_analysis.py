"""Pydantic schemas and path-safety validators for multi-file Python project analysis."""

import posixpath
import re
from typing import List, Literal, Optional, Set
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.ast_analysis import (
    ApiCandidate,
    CallInfo,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    RelevantLiteral,
    SourceLocation,
    SyntaxErrorInfo,
)
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import (
    AISuggestion,
    CandidateAssessment,
    EvidenceTrustType,
    VerdictType,
    VerifiedIssue,
)

# Project constraints & boundaries
MAX_PROJECT_FILES: int = 20
MAX_FILE_SIZE_BYTES: int = 100_000        # 100 KB per individual file
MAX_COMBINED_SIZE_BYTES: int = 500_000    # 500 KB total project source size
MAX_PATH_LENGTH: int = 255                # Max path length in characters


def normalize_and_validate_project_path(path: str) -> str:
    """Validate and normalize a project-relative Python file path.
    
    Security rules:
    - Rejects empty paths or whitespace-only paths.
    - Rejects NUL bytes.
    - Rejects paths exceeding MAX_PATH_LENGTH.
    - Rejects absolute paths (leading '/' or '\\').
    - Rejects drive-qualified paths (e.g. 'C:', 'D:').
    - Rejects path traversal components ('..').
    - Strips redundant current-directory markers ('./').
    - Normalizes path separators to forward slash '/'.
    - Enforces .py file extension (case-insensitive) and rejects bare '.py'.
    
    Raises:
        ValueError: If any security or path validation rule is violated.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("File path cannot be empty.")
    
    clean_raw = path.strip()
    if "\0" in clean_raw:
        raise ValueError("File path contains prohibited NUL character.")
    if len(clean_raw) > MAX_PATH_LENGTH:
        raise ValueError(
            f"File path exceeds maximum permitted length of {MAX_PATH_LENGTH} characters ({len(clean_raw)})."
        )
    
    if clean_raw.startswith("//") or clean_raw.startswith("\\\\"):
        raise ValueError("UNC paths are not permitted in project analysis.")
    if clean_raw.startswith("/") or clean_raw.startswith("\\"):
        raise ValueError("Absolute file paths are not permitted in project analysis.")
    if re.match(r"^[a-zA-Z]:", clean_raw) or ":" in clean_raw:
        raise ValueError("Drive-qualified paths are not permitted in project analysis.")
    
    # Normalize slashes to POSIX style (backslashes '\' are normalized to POSIX forward slashes '/')
    unified = clean_raw.replace("\\", "/")
    parts = unified.split("/")
    clean_parts: List[str] = []
    
    for part in parts:
        if part == "" or part == ".":
            continue
        if part == "..":
            raise ValueError("Path traversal component ('..') is strictly prohibited.")
        clean_parts.append(part)
        
    if not clean_parts:
        raise ValueError("File path cannot be empty.")
        
    normalized = "/".join(clean_parts)
    lower_norm = normalized.lower()
    
    if not lower_norm.endswith(".py") or lower_norm == ".py":
        raise ValueError(
            f"Unsupported file type for '{normalized}'. Only Python source files (.py) are supported."
        )
        
    return normalized


class ProjectFileItem(BaseModel):
    """An individual Python source file within a project submission."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Normalized relative path to the Python file (e.g. 'services/payment.py')",
    )
    content: str = Field(
        ...,
        max_length=MAX_FILE_SIZE_BYTES,
        description="Python source code text (max 100 KB in UTF-8 bytes)",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return normalize_and_validate_project_path(v)

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: str) -> str:
        encoded_bytes = len(v.encode("utf-8"))
        if encoded_bytes > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File content exceeds maximum limit of {MAX_FILE_SIZE_BYTES} bytes ({encoded_bytes} bytes)."
            )
        return v


class ProjectAnalysisRequest(BaseModel):
    """Request payload for multi-file Python project analysis."""
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(
        default="python_project",
        max_length=100,
        description="Optional human-readable project identifier",
    )
    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target API ecosystem for evidence verification (default: 'stripe')",
    )
    files: List[ProjectFileItem] = Field(
        ...,
        min_length=1,
        max_length=MAX_PROJECT_FILES,
        description=f"Collection of Python files to analyze (1 to {MAX_PROJECT_FILES} files)",
    )
    force_mock: bool = Field(
        default=False,
        description="Explicitly force mock fixtures during evidence retrieval",
    )

    @model_validator(mode="after")
    def validate_project_constraints(self) -> "ProjectAnalysisRequest":
        seen_paths: Set[str] = set()
        total_size = 0

        for file_item in self.files:
            lower_path = file_item.path.lower()
            if lower_path in seen_paths:
                raise ValueError(
                    f"Duplicate file path '{file_item.path}' detected after path normalization."
                )
            seen_paths.add(lower_path)
            total_size += len(file_item.content.encode("utf-8"))

        if total_size > MAX_COMBINED_SIZE_BYTES:
            raise ValueError(
                f"Combined project source size exceeds maximum limit of {MAX_COMBINED_SIZE_BYTES} bytes ({total_size} bytes)."
            )

        return self


# Relationship types for cross-file dependency graph
RelationshipType = Literal["file_imports_file", "file_imports_external", "symbol_reference"]
ResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "external"]


class ProjectRelationship(BaseModel):
    """A statically resolved or unresolved dependency between project files or symbols."""
    model_config = ConfigDict(extra="forbid")

    source_file: str = Field(..., description="Relative path of the importing/referencing file")
    target: str = Field(..., description="Target file path, external module, or symbol")
    target_file: Optional[str] = Field(
        default=None,
        description="Resolved project-relative file path if internal",
    )
    relationship_type: RelationshipType = Field(..., description="Type of relationship")
    imported_symbol: Optional[str] = Field(
        default=None,
        description="Imported symbol name if from-import",
    )
    alias: Optional[str] = Field(default=None, description="Import alias name if used")
    status: ResolutionStatus = Field(
        ...,
        description="Resolution status ('resolved', 'unresolved', 'ambiguous', 'external')",
    )
    reason: str = Field(
        ...,
        description="Detailed explanation of the resolution or why it is unresolved",
    )
    location: SourceLocation = Field(..., description="Source location of the import statement")


class ProjectFileAnalysisResult(BaseModel):
    """Static AST analysis results for an individual file in the project."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Relative file path")
    parse_status: Literal["success", "syntax_error"] = Field(..., description="Parse status")
    total_lines: int = Field(default=0, description="Total source lines")
    syntax_error: Optional[SyntaxErrorInfo] = Field(
        default=None,
        description="Syntax error details if parsing failed",
    )
    imports: List[ImportInfo] = Field(default_factory=list, description="Imports declared in this file")
    functions: List[FunctionInfo] = Field(default_factory=list, description="Functions defined in this file")
    classes: List[ClassInfo] = Field(default_factory=list, description="Classes defined in this file")
    calls: List[CallInfo] = Field(default_factory=list, description="Call expressions in this file")
    candidates: List[ApiCandidate] = Field(default_factory=list, description="API candidates found in this file")
    relevant_literals: List[RelevantLiteral] = Field(default_factory=list, description="Relevant string literals")
    defined_symbols: List[str] = Field(
        default_factory=list,
        description="Top-level functions, classes, and assigned variable identifiers defined in this file",
    )


class ProjectAnalysisReport(BaseModel):
    """Comprehensive project-level analysis report across all submitted files."""
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(..., description="Project identifier")
    verdict: VerdictType = Field(
        ...,
        description="Project-level adjudication verdict: 'clean', 'issues_found', or 'unable_to_verify'",
    )
    engine_version: str = Field(default="0.1.0", description="APICompass engine version")
    total_files: int = Field(..., description="Total files analyzed in the project")
    total_lines: int = Field(..., description="Total combined source lines")
    parsed_files_count: int = Field(..., description="Count of successfully parsed files")
    syntax_errors_count: int = Field(..., description="Count of files with syntax errors")
    total_candidates: int = Field(..., description="Total API candidates extracted across all files")
    resolved_imports_count: int = Field(..., description="Count of resolved project-internal imports")
    unresolved_imports_count: int = Field(..., description="Count of unresolved project-internal imports")
    ambiguous_imports_count: int = Field(..., description="Count of ambiguous project-internal imports")
    external_imports_count: int = Field(default=0, description="Count of external library imports")
    evidence_trust: EvidenceTrustType = Field(..., description="Evidence trust classification")
    is_mock: bool = Field(..., description="True if mock fixtures were used")
    summary: str = Field(..., description="Executive project-level verification summary")
    checks_performed: List[str] = Field(
        default_factory=list,
        description="Checks performed across the project",
    )
    relationships: List[ProjectRelationship] = Field(
        default_factory=list,
        description="Cross-file relationships and imports",
    )
    files: List[ProjectFileAnalysisResult] = Field(
        default_factory=list,
        description="Per-file analysis details",
    )
    verified_issues: List[VerifiedIssue] = Field(
        default_factory=list,
        description="Verified API contract violations across project",
    )
    ai_suggestions: List[AISuggestion] = Field(
        default_factory=list,
        description="Advisory AI suggestions",
    )
    unresolved_candidates: List[str] = Field(
        default_factory=list,
        description="IDs of unresolved candidates",
    )
    candidate_assessments: List[CandidateAssessment] = Field(
        default_factory=list,
        description="Assessments for each evaluated candidate across project files",
    )
    evidence_items: List[NormalizedEvidence] = Field(
        default_factory=list,
        description="Retrieved official documentation evidence",
    )
    limitations_and_caveats: List[str] = Field(
        default_factory=list,
        description="Static analysis limitations and caveats",
    )
    disclaimer: str = Field(
        default=(
            "Multi-file project analysis is strictly static and does not execute submitted code. "
            "A 'clean' verdict applies only to in-scope API calls verified against official contracts "
            "and does not certify total project correctness, runtime behavior, or absence of other bugs."
        ),
        description="Integrity disclaimer",
    )
    scan_id: Optional[str] = Field(default=None, description="Stored audit record ID if persisted")
    persistence_status: Optional[str] = Field(default="disabled", description="Audit persistence status")
