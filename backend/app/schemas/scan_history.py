"""Pydantic schemas for SQLite scan audit repository and history API."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.evidence import (
    VerdictType,
    EvidenceTrustType,
    VerifiedIssue,
    AISuggestion,
)
from app.schemas.documentation import NormalizedEvidence


class ScanSummaryItem(BaseModel):
    """Lightweight summary of a historical scan for list views."""
    model_config = ConfigDict(extra="forbid")

    scan_id: str = Field(..., description="Unique server-generated scan identifier")
    created_at: str = Field(..., description="UTC ISO-8601 timestamp of scan creation")
    verdict: VerdictType = Field(..., description="Original adjudication verdict")
    ecosystem: str = Field(..., description="Target API ecosystem (e.g. 'stripe')")
    filename: str = Field(..., description="Source filename (untrusted display metadata)")
    source_sha256: str = Field(..., description="SHA-256 fingerprint of analyzed source code")
    source_length: int = Field(..., description="Character length of analyzed source code")
    evidence_trust: EvidenceTrustType = Field(..., description="Original evidence trust classification")
    is_mock: bool = Field(..., description="True if analysis relied on offline mock fixtures")
    candidates_count: int = Field(default=0, description="Number of AST candidates evaluated")
    issues_count: int = Field(default=0, description="Number of verified contract issues")
    evidence_count: int = Field(default=0, description="Number of documentation evidence items")
    suggestions_count: int = Field(default=0, description="Number of advisory AI suggestions")
    summary: str = Field(..., description="Executive summary of the scan")
    status: str = Field(default="completed", description="Execution status ('completed', 'partial', 'failed')")


class ScanListResponse(BaseModel):
    """Paginated response containing historical scan summaries."""
    model_config = ConfigDict(extra="forbid")

    items: List[ScanSummaryItem] = Field(default_factory=list, description="Page of scan summaries")
    total: int = Field(..., ge=0, description="Total matching scan records")
    limit: int = Field(..., ge=1, le=100, description="Maximum items per page")
    offset: int = Field(..., ge=0, description="Offset index from start of matching records")
    has_more: bool = Field(..., description="True if subsequent pages of records exist")


class ProjectFileDetailSummary(BaseModel):
    """Audit summary of an individual file within a stored project scan."""
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(..., description="Project-relative file path")
    source_sha256: str = Field(..., description="SHA-256 fingerprint of file source")
    source_length: int = Field(..., description="Character length of file source")
    parse_status: str = Field(..., description="Parse status ('success', 'syntax_error')")
    candidates_count: int = Field(default=0, description="Number of candidates found in this file")
    syntax_error: Optional[str] = Field(default=None, description="Syntax error message if parsing failed")

    @field_validator("parse_status")
    @classmethod
    def validate_parse_status(cls, v: str) -> str:
        if v not in {"success", "syntax_error"}:
            raise ValueError(f"Invalid parse_status '{v}'. Must be 'success' or 'syntax_error'")
        return v


class HistoricalScanDetail(BaseModel):
    """Complete historical snapshot of a stored scan and its audit trail."""
    model_config = ConfigDict(extra="forbid")

    scan_id: str = Field(..., description="Unique server-generated scan identifier")
    is_historical: bool = Field(
        default=True,
        description="Explicit flag distinguishing historical snapshots from live analysis"
    )
    schema_version: int = Field(default=1, description="Database schema version at time of storage")
    created_at: str = Field(..., description="UTC ISO-8601 timestamp of scan analysis")
    completed_at: Optional[str] = Field(default=None, description="UTC ISO-8601 timestamp of completion")
    status: str = Field(default="completed", description="Scan completion status")
    verdict: VerdictType = Field(..., description="Original adjudication verdict")
    ecosystem: str = Field(..., description="Target API ecosystem")
    filename: str = Field(..., description="Original source filename (untrusted metadata)")
    source_sha256: str = Field(..., description="SHA-256 fingerprint of analyzed source code")
    source_length: int = Field(..., description="Character length of analyzed source code")
    pipeline_version: str = Field(default="0.1.0", description="APICompass engine version at analysis time")
    evidence_trust: EvidenceTrustType = Field(..., description="Original evidence trust classification")
    is_mock: bool = Field(..., description="True if offline mock fixtures were used")
    llm_reasoning_status: str = Field(default="disabled", description="LLM provider status at analysis time")
    summary: str = Field(..., description="Original analysis executive summary")
    abstention_reason: Optional[str] = Field(default=None, description="Abstention reason if inconclusive")
    checks_performed: List[str] = Field(default_factory=list, description="Original checks performed")
    verified_issues: List[VerifiedIssue] = Field(
        default_factory=list,
        description="Verified contract violations with quote receipts"
    )
    ai_suggestions: List[AISuggestion] = Field(
        default_factory=list,
        description="Original advisory AI suggestions (labeled 'AI suggestion — not verified')"
    )
    evidence_items: List[NormalizedEvidence] = Field(
        default_factory=list,
        description="Retrieved documentation evidence receipts with provenance"
    )
    limitations_and_caveats: List[str] = Field(
        default_factory=list,
        description="Limitations and caveats recorded at time of analysis"
    )
    disclaimer: str = Field(
        ...,
        description="Integrity disclaimer explaining audit snapshot boundaries"
    )
    integrity_hash: str = Field(
        ...,
        description="Cryptographic SHA-256 audit fingerprint of canonical stored report data"
    )
    project_files: Optional[List[ProjectFileDetailSummary]] = Field(
        default=None,
        description="Per-file audit metadata if this record represents a multi-file project scan"
    )


class DeleteScanResponse(BaseModel):
    """Response returned upon explicit deletion of a historical scan record."""
    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="True if scan and dependent records were deleted")
    scan_id: str = Field(..., description="ID of deleted scan record")
    deleted_at: str = Field(..., description="UTC ISO-8601 timestamp of deletion")
