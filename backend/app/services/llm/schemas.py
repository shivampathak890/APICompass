"""Pydantic schemas for LLM-assisted candidate reasoning.

Defines structured, validated outputs for LLM interpretation, proposed claims,
suggested documentation queries, and uncertainty disclosures.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.ast_analysis import ApiCandidate, ImportInfo

RiskCategoryType = Literal[
    "deprecated_api",
    "parameter_mismatch",
    "missing_argument",
    "type_mismatch",
    "version_sensitive",
    "general_guidance",
]

ConfidenceLevelType = Literal["low", "medium", "high", "uncalibrated"]
LLMProviderStatusType = Literal["disabled", "mock", "available", "unavailable", "error"]


class ProposedClaim(BaseModel):
    """A structured contract hypothesis proposed by the LLM (requires verification)."""
    model_config = ConfigDict(extra="forbid")

    claim_type: RiskCategoryType = Field(
        ..., 
        description="Category: 'deprecated_api', 'parameter_mismatch', etc."
    )
    affected_candidate_id: str = Field(
        ..., 
        description="AST candidate ID to which this claim applies"
    )
    description: str = Field(
        ..., 
        max_length=500, 
        description="Concise description of the potential contract concern"
    )
    referenced_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Evidence IDs supplied to the model that inform this claim"
    )
    unverified_aspects: str = Field(
        ..., 
        max_length=500,
        description="Clear disclosure of what facts remain unverified by official documentation"
    )


class CandidateReasoning(BaseModel):
    """Structured LLM interpretation of an individual AST candidate in context."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., description="Target AST candidate ID")
    interpretation: str = Field(
        ..., 
        max_length=1000, 
        description="Contextual interpretation of the operation performed"
    )
    proposed_claims: List[ProposedClaim] = Field(
        default_factory=list,
        description="List of proposed claims/hypotheses for this candidate"
    )
    suggested_documentation_queries: List[str] = Field(
        default_factory=list,
        description="Targeted search queries or canonical doc URLs to retrieve"
    )
    referenced_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Evidence IDs referenced by the model"
    )
    risk_category: RiskCategoryType = Field(
        default="general_guidance",
        description="Primary risk classification"
    )
    confidence: ConfidenceLevelType = Field(
        default="uncalibrated",
        description="Uncalibrated qualitative confidence indicator"
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="Explicit uncertainties identified by the model"
    )
    reasoning_summary: str = Field(
        ..., 
        max_length=1000,
        description="Observable facts and rationale (excluding private chain-of-thought)"
    )


class LLMReasoningRequest(BaseModel):
    """Input payload provided to the LLM reasoning provider."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="Bounded user source code snippet")
    filename: str = Field(default="snippet.py")
    ecosystem: str = Field(default="stripe")
    candidates: List[ApiCandidate] = Field(..., description="Extracted AST API candidates")
    imports: List[ImportInfo] = Field(default_factory=list)
    existing_evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of official evidence items already retrieved"
    )


class LLMReasoningResponse(BaseModel):
    """Normalized response from an LLM reasoning provider."""
    model_config = ConfigDict(extra="forbid")

    status: LLMProviderStatusType = Field(..., description="Provider operational status")
    provider: str = Field(..., description="Provider name (e.g. 'disabled', 'mock', 'openai')")
    model: str = Field(..., description="Model identifier used")
    candidate_reasonings: List[CandidateReasoning] = Field(
        default_factory=list,
        description="Structured reasoning per candidate"
    )
    suggested_documentation_urls: List[str] = Field(
        default_factory=list,
        description="Suggested documentation URLs (subject to allowlist validation)"
    )
    overall_reasoning_summary: Optional[str] = Field(
        default=None,
        description="Summary of overall API usage patterns observed"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error description if status is 'unavailable' or 'error'"
    )
