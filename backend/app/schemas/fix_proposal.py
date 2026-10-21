"""Pydantic schemas for Evidence-Gated Fix Proposals and Safe Re-Verification."""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ast_analysis import validate_safe_filename
from app.schemas.evidence import EvidenceTrustType

FixProposalStatusType = Literal[
    "evidence_supported",
    "insufficient_evidence",
    "mock_evidence_only",
    "unsupported_candidate",
    "proposal_invalid",
    "syntax_check_failed",
    "reverification_inconclusive",
]

FixProposalType = Literal["verified_correction", "suggested_patch", "ineligible"]

ReverificationStatusType = Literal[
    "verified_resolved",
    "partially_resolved",
    "concern_persists",
    "reverification_inconclusive",
    "syntax_invalid",
    "not_attempted",
]


class ProposeFixRequest(BaseModel):
    """Request payload to propose an evidence-gated fix for an API candidate or issue."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        ...,
        max_length=100_000,
        description="Original Python source code text (max 100 KB)",
    )
    candidate_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Target candidate ID from analysis report (e.g. 'cand_001')",
    )
    filename: str = Field(
        default="snippet.py",
        max_length=255,
        description="Source filename for error and diff reporting",
    )
    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target API ecosystem (default: 'stripe')",
    )
    issue_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Optional verified issue ID to resolve",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename_security(cls, v: str) -> str:
        return validate_safe_filename(v)


class FixProposalResponse(BaseModel):
    """Server-issued, evidence-gated fix proposal and static re-verification result."""
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(
        ...,
        description="Server-generated unique identifier for this proposal",
    )
    candidate_id: str = Field(
        ...,
        description="Target candidate ID being addressed",
    )
    status: FixProposalStatusType = Field(
        ...,
        description="Eligibility status: 'evidence_supported', 'insufficient_evidence', 'mock_evidence_only', etc.",
    )
    proposal_type: FixProposalType = Field(
        default="suggested_patch",
        description="Classification: 'verified_correction' (evidence-supported & verified resolved), 'suggested_patch' (advisory/mock), or 'ineligible'",
    )
    summary: str = Field(
        ...,
        description="Concise description of the proposed migration or fix",
    )
    reasoning: str = Field(
        ...,
        description="Detailed explanation justifying the edit based on authoritative evidence",
    )
    original_excerpt: Optional[str] = Field(
        default=None,
        description="Original source line(s) targeted for modification",
    )
    proposed_excerpt: Optional[str] = Field(
        default=None,
        description="Proposed replacement line(s)",
    )
    unified_diff: Optional[str] = Field(
        default=None,
        description="Standard unified diff between original and proposed source",
    )
    proposed_source: Optional[str] = Field(
        default=None,
        description="Complete modified source code (in-memory only; never written to disk)",
    )
    supporting_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Server-verified evidence IDs directly supporting this proposal",
    )
    supporting_quotes: List[str] = Field(
        default_factory=list,
        description="Deterministic verified quotations from official documentation",
    )
    source_urls: List[str] = Field(
        default_factory=list,
        description="Canonical URLs of official documentation sources",
    )
    evidence_trust: EvidenceTrustType = Field(
        ...,
        description="Trust classification: 'live_official_source', 'mock_fixture', or 'untrusted_or_unavailable'",
    )
    is_mock: bool = Field(
        ...,
        description="True if offline mock fixtures were used; mock evidence CANNOT produce production verified fixes",
    )
    is_ai_generated: bool = Field(
        default=False,
        description="True if an LLM was involved in drafting the edit",
    )
    syntax_valid: bool = Field(
        default=False,
        description="True if proposed source parses successfully with Python AST parser",
    )
    reverification_status: ReverificationStatusType = Field(
        default="not_attempted",
        description="Result of static re-verification against evidence engine",
    )
    remaining_uncertainties: List[str] = Field(
        default_factory=list,
        description="Explicit caveats regarding unverified runtime behavior",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Safety warnings, policy notices, or error explanations",
    )
    disclaimer: str = Field(
        default=(
            "A fix proposal is an evidence-backed suggestion, not a guarantee of runtime correctness. "
            "Static re-verification tests AST syntax and documented contract schemas only. "
            "User source code is never executed and local files are never automatically overwritten."
        ),
        description="Core integrity guarantee disclaimer",
    )
