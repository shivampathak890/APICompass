"""Pydantic schemas for real-time scan progress over Server-Sent Events (SSE)."""

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.evidence import AnalysisReport

ScanStageType = Literal[
    "accepted",
    "static_analysis_started",
    "static_analysis_completed",
    "ai_reasoning_started",
    "ai_reasoning_completed",
    "documentation_retrieval_started",
    "doc_search_started",
    "doc_search_completed",
    "doc_fetch_started",
    "doc_fetch_completed",
    "documentation_retrieval_completed",
    "evidence_verification_started",
    "evidence_verification_completed",
    "persistence_started",
    "persistence_completed",
    "completed",
    "failed",
]


class ScanProgressEvent(BaseModel):
    """Structured progress update emitted during streaming analysis."""
    model_config = ConfigDict(extra="forbid")

    event_version: str = Field(default="1.0.0", description="Schema version of the progress event")
    scan_id: Optional[str] = Field(default=None, description="Scan identifier if available")
    stage: ScanStageType = Field(..., description="Current operational pipeline stage")
    message: str = Field(..., description="Human-readable status description of current work")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of the event")
    progress_percent: Optional[int] = Field(
        default=None, 
        ge=0, 
        le=100, 
        description="Optional truthful progress percentage when computable, otherwise None for indeterminate"
    )
    error_code: Optional[str] = Field(
        default=None, 
        description="Safe machine-readable error code if stage is 'failed'"
    )
    report: Optional[AnalysisReport] = Field(
        default=None, 
        description="Final complete AnalysisReport payload when stage is 'completed'"
    )
