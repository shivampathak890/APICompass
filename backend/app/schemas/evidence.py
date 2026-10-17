"""Pydantic schemas for evidence verification, contract matching, and adjudication."""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.ast_analysis import SourceLocation, SyntaxErrorInfo
from app.schemas.contract import (
    ContractFindingCandidate,
    ExtractedContract,
    ParameterConstraint,
    ParameterContract,
)
from app.schemas.documentation import NormalizedEvidence

# Trust and verdict type literals
VerdictType = Literal["clean", "issues_found", "unable_to_verify"]
EvidenceTrustType = Literal["live_official_source", "mock_fixture", "untrusted_or_unavailable"]
MatchMethodType = Literal["exact", "whitespace_normalized", "none"]
CompletenessType = Literal["complete_contract", "excerpt_only", "unrelated", "missing"]
CandidateStatusType = Literal["resolved_clean", "resolved_issue", "unresolved"]
QuoteKindType = Literal["exact_quotation", "paraphrase", "structured_contract", "none"]
VerificationStatusType = Literal["verified", "unverified_suggestion", "unable_to_verify", "no_issue_detected"]


class QuoteVerificationRequest(BaseModel):
    """Request to verify a quotation against official evidence."""
    model_config = ConfigDict(extra="forbid")

    proposed_quote: str = Field(..., min_length=1, description="Proposed quotation to verify")
    evidence_id: str = Field(..., description="ID of evidence record claiming to contain the quote")
    source_url: str = Field(..., description="Source URL of the evidence")


class QuoteVerificationResult(BaseModel):
    """Deterministic result of quotation verification."""
    model_config = ConfigDict(extra="forbid")

    is_verified: bool = Field(..., description="True if quote was found in the evidence text")
    match_method: MatchMethodType = Field(
        ..., 
        description="Exact method used ('exact', 'whitespace_normalized', or 'none')"
    )
    matched_text: Optional[str] = Field(default=None, description="Exact matched string from source")
    evidence_id: str = Field(..., description="Target evidence ID")
    source_url: str = Field(..., description="Canonical source URL")
    content_hash: str = Field(..., description="SHA-256 hash of the stored evidence text")
    quote_kind: QuoteKindType = Field(
        default="exact_quotation",
        description="Classification: 'exact_quotation', 'paraphrase', 'structured_contract', or 'none'",
    )
    is_mock: bool = Field(
        default=False,
        description="True if evidence is from a synthetic mock fixture",
    )
    error_message: Optional[str] = Field(default=None, description="Reason if verification failed")


class EvidenceMatch(BaseModel):
    """Correlation between an AST candidate and a documentation evidence record."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., description="Associated AST candidate ID")
    matched_operation: Optional[str] = Field(default=None, description="Documented operation name")
    evidence_id: Optional[str] = Field(default=None, description="Matched evidence ID")
    source_url: Optional[str] = Field(default=None, description="Official documentation URL")
    canonical_url: Optional[str] = Field(default=None, description="Canonical documentation source URL")
    source_title: Optional[str] = Field(default=None, description="Title of documentation source")
    retrieval_status: Optional[str] = Field(default=None, description="Retrieval status of evidence")
    retrieved_at: Optional[str] = Field(default=None, description="Timestamp of evidence retrieval")
    is_mock: bool = Field(default=False, description="Whether matched evidence is a mock fixture")
    completeness: CompletenessType = Field(
        default="excerpt_only", 
        description="Completeness classification of retrieved evidence"
    )
    is_ambiguous: bool = Field(default=False, description="True if multiple conflicting operations match")
    match_rationale: str = Field(..., description="Explanation of why this evidence was matched")


class VerifiedIssue(BaseModel):
    """An API contract violation established by verified official evidence."""
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(..., description="Unique issue identifier")
    candidate_id: str = Field(..., description="Associated AST candidate ID")
    source_location: SourceLocation = Field(..., description="Line and column location in user code")
    claim_checked: str = Field(..., description="Description of the API usage claim verified")
    violation_type: str = Field(
        ..., 
        description="Classification: 'legacy_deprecated_parameter', 'missing_required_parameter', 'deprecated_api_operation', 'constraint_violation', 'unsupported_parameter'"
    )
    explanation: str = Field(..., description="Detailed explanation of the contract violation")
    supporting_evidence_id: str = Field(..., description="ID of the evidence establishing the violation")
    source_url: str = Field(..., description="Official documentation source URL")
    canonical_url: Optional[str] = Field(default=None, description="Canonical documentation source URL")
    source_title: Optional[str] = Field(default=None, description="Title of official documentation source")
    retrieval_status: Optional[str] = Field(default=None, description="Retrieval status of supporting evidence ('live', 'mock', 'success')")
    retrieved_at: Optional[str] = Field(default=None, description="Timestamp when evidence was retrieved")
    content_sha256: Optional[str] = Field(default=None, description="Cryptographic SHA-256 hash of documentation content")
    is_mock: bool = Field(default=False, description="Whether supporting evidence is a synthetic mock fixture")
    verified_quote: str = Field(..., description="Exact verified quotation establishing the violation")
    match_method: MatchMethodType = Field(default="exact", description="Quote verification match method")
    verification_status: VerificationStatusType = Field(
        default="verified",
        description="Verification state: 'verified', 'unverified_suggestion', 'unable_to_verify', 'no_issue_detected'",
    )
    quote_kind: QuoteKindType = Field(
        default="exact_quotation",
        description="Quotation classification: 'exact_quotation', 'paraphrase', 'structured_contract', or 'none'",
    )
    supporting_excerpt: Optional[str] = Field(
        default=None,
        description="Supporting documentation excerpt text establishing the finding",
    )
    evidence_rationale: Optional[str] = Field(
        default=None,
        description="Explanation of how the evidence supports the specific claim",
    )
    limitations: Optional[str] = Field(default=None, description="Applicability caveats or version limitations")
    file_path: Optional[str] = Field(default=None, description="Source file path for multi-file project analysis")

    # Traceable finding context fields:
    title: Optional[str] = Field(default=None, description="Short human-readable finding title")
    code_fragment: Optional[str] = Field(default=None, description="Relevant code expression from source")
    documented_requirement: Optional[str] = Field(default=None, description="Relevant documented API contract requirement")
    impact_classification: Optional[str] = Field(default=None, description="Impact or contract classification if supported")
    suggested_correction: Optional[str] = Field(default=None, description="Suggested correction or migration direction if available")
    severity: Optional[str] = Field(default="error", description="Severity level: 'error', 'warning', 'info'")
    confidence: Optional[str] = Field(default="verified", description="Confidence level with defined semantics: 'verified', 'probable', 'speculative', 'uncertain'")
    detected_call: Optional[str] = Field(default=None, description="Detected API call expression")
    detected_argument: Optional[str] = Field(default=None, description="Relevant detected parameter or argument name")
    expected_contract: Optional[str] = Field(default=None, description="Expected contract requirement established by documentation")
    observed_usage: Optional[str] = Field(default=None, description="Observed argument or code usage")
    suggested_action: Optional[str] = Field(default=None, description="Suggested next action for developer")

    @model_validator(mode="after")
    def sync_provenance_and_excerpt(self) -> "VerifiedIssue":
        if self.canonical_url is None:
            self.canonical_url = self.source_url
        if self.supporting_excerpt is None:
            self.supporting_excerpt = self.verified_quote
        if self.evidence_rationale is None:
            self.evidence_rationale = (
                f"Official documentation at {self.source_url} substantiates the claim via "
                f"{self.quote_kind.replace('_', ' ')}."
            )
        if self.title is None:
            v_type_clean = self.violation_type.replace('_', ' ').title()
            self.title = f"{v_type_clean}: {self.claim_checked}"
        if self.documented_requirement is None and self.verified_quote:
            self.documented_requirement = f"Official documentation requires: \"{self.verified_quote}\""
        if self.impact_classification is None:
            if "deprecated" in self.violation_type or "legacy" in self.violation_type:
                self.impact_classification = "Breaking API Deprecation"
            elif "missing" in self.violation_type or "required" in self.violation_type:
                self.impact_classification = "API Contract Violation (Missing Argument)"
            elif "unsupported" in self.violation_type:
                self.impact_classification = "API Contract Violation (Unsupported Argument)"
            elif "constraint" in self.violation_type:
                self.impact_classification = "API Contract Violation (Constraint Mismatch)"
        if self.detected_call is None:
            self.detected_call = self.code_fragment
        if self.expected_contract is None:
            self.expected_contract = self.documented_requirement or (f"Official documentation requires: \"{self.verified_quote}\"" if self.verified_quote else None)
        if self.observed_usage is None:
            self.observed_usage = f"Detected call '{self.code_fragment or self.claim_checked}'"
        if self.suggested_action is None:
            self.suggested_action = self.suggested_correction or (
                "Replace the legacy parameter with recommended modern alternatives." if "legacy" in self.violation_type or "deprecated" in self.violation_type
                else f"Supply the required parameter '{self.detected_argument or 'argument'}'." if "missing" in self.violation_type
                else f"Remove unsupported parameter '{self.detected_argument or 'argument'}'." if "unsupported" in self.violation_type
                else "Review documented API parameter constraints."
            )
        if self.severity is None:
            if "deprecated" in self.violation_type or "legacy" in self.violation_type:
                self.severity = "warning"
            else:
                self.severity = "error"
        if self.confidence is None:
            self.confidence = "verified" if self.verification_status == "verified" else "probable"
        return self


class CandidateAssessment(BaseModel):
    """Detailed evaluation of an individual AST candidate."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., description="Candidate identifier")
    target_name: str = Field(..., description="Target function or method name")
    receiver: Optional[str] = Field(default=None, description="Receiver expression")
    call_expr: str = Field(..., description="Full call expression from source")
    source_location: SourceLocation = Field(..., description="Code coordinates")
    status: CandidateStatusType = Field(
        ..., 
        description="Outcome: 'resolved_clean', 'resolved_issue', or 'unresolved'"
    )
    verification_status: VerificationStatusType = Field(
        default="unable_to_verify",
        description="Explicit candidate verification state: 'verified', 'unverified_suggestion', 'unable_to_verify', 'no_issue_detected'",
    )
    evidence_match: Optional[EvidenceMatch] = Field(default=None)
    verified_quotes: List[QuoteVerificationResult] = Field(default_factory=list)
    issues: List[VerifiedIssue] = Field(default_factory=list)
    abstention_reason: Optional[str] = Field(default=None, description="Reason if candidate is unresolved")
    explanation: str = Field(..., description="Human-readable assessment summary")
    file_path: Optional[str] = Field(default=None, description="Source file path for multi-file project analysis")

    # Traceable context fields:
    title: Optional[str] = Field(default=None, description="Short title for candidate assessment")
    documented_requirement: Optional[str] = Field(default=None, description="Relevant documented contract requirement")
    impact_classification: Optional[str] = Field(default=None, description="Impact classification if supported")
    suggested_correction: Optional[str] = Field(default=None, description="Suggested correction or direction")
    severity: Optional[str] = Field(default=None, description="Severity: 'error', 'warning', 'info'")
    confidence: Optional[str] = Field(default=None, description="Confidence: 'verified', 'probable', 'speculative', 'uncertain'")
    detected_call: Optional[str] = Field(default=None, description="Detected API call")
    detected_argument: Optional[str] = Field(default=None, description="Detected argument")
    expected_contract: Optional[str] = Field(default=None, description="Expected contract")
    observed_usage: Optional[str] = Field(default=None, description="Observed usage")
    suggested_action: Optional[str] = Field(default=None, description="Suggested action")
    uncertainty_or_limitations: Optional[str] = Field(default=None, description="Explicit uncertainty or limitation")

    # Source provenance fields:
    source_url: Optional[str] = Field(default=None, description="Official documentation source URL")
    canonical_url: Optional[str] = Field(default=None, description="Canonical documentation source URL")
    source_title: Optional[str] = Field(default=None, description="Title of documentation source")
    retrieval_status: Optional[str] = Field(default=None, description="Retrieval status of supporting evidence")
    retrieved_at: Optional[str] = Field(default=None, description="Timestamp of evidence retrieval")
    content_sha256: Optional[str] = Field(default=None, description="Cryptographic SHA-256 hash of documentation")
    is_mock: bool = Field(default=False, description="Whether candidate assessment relies on mock evidence")

    @model_validator(mode="after")
    def sync_verification_status(self) -> "CandidateAssessment":
        if self.detected_call is None:
            self.detected_call = self.call_expr
        if self.observed_usage is None:
            self.observed_usage = f"Detected call: {self.call_expr}"
        if self.evidence_match is not None:
            if self.source_url is None:
                self.source_url = self.evidence_match.source_url
            if self.canonical_url is None:
                self.canonical_url = self.evidence_match.canonical_url or self.evidence_match.source_url
            if self.source_title is None:
                self.source_title = self.evidence_match.source_title
            if self.retrieval_status is None:
                self.retrieval_status = self.evidence_match.retrieval_status
            if self.retrieved_at is None:
                self.retrieved_at = self.evidence_match.retrieved_at
            if not self.is_mock and self.evidence_match.is_mock:
                self.is_mock = True
        if self.status == "resolved_issue":
            self.verification_status = "verified"
            if self.impact_classification is None:
                self.impact_classification = "API Contract Violation"
            if self.severity is None:
                self.severity = "error"
            if self.confidence is None:
                self.confidence = "verified"
            if self.issues:
                first_iss = self.issues[0]
                if self.expected_contract is None:
                    self.expected_contract = first_iss.expected_contract
                if self.detected_argument is None:
                    self.detected_argument = first_iss.detected_argument
                if self.suggested_action is None:
                    self.suggested_action = first_iss.suggested_action
                if self.uncertainty_or_limitations is None:
                    self.uncertainty_or_limitations = first_iss.limitations
                if self.source_url is None:
                    self.source_url = first_iss.source_url
                if self.canonical_url is None:
                    self.canonical_url = first_iss.canonical_url
                if self.source_title is None:
                    self.source_title = first_iss.source_title
                if self.retrieval_status is None:
                    self.retrieval_status = first_iss.retrieval_status
                if self.retrieved_at is None:
                    self.retrieved_at = first_iss.retrieved_at
                if self.content_sha256 is None:
                    self.content_sha256 = first_iss.content_sha256
        elif self.status == "resolved_clean":
            self.verification_status = "no_issue_detected"
            if self.impact_classification is None:
                self.impact_classification = "Compliant API Usage"
            if self.severity is None:
                self.severity = "info"
            if self.confidence is None:
                self.confidence = "verified"
            if self.expected_contract is None:
                self.expected_contract = self.documented_requirement or "Compliant with documented API contract."
            if self.suggested_action is None:
                self.suggested_action = "No action required; call complies with documented contract."
            if self.uncertainty_or_limitations is None:
                self.uncertainty_or_limitations = "Applies strictly to supported static checks performed; does not guarantee runtime behavior."
        else:
            self.verification_status = "unable_to_verify"
            if self.impact_classification is None:
                self.impact_classification = "Unverified (Abstained)"
            if self.severity is None:
                self.severity = "warning"
            if self.confidence is None:
                self.confidence = "uncertain"
            if self.uncertainty_or_limitations is None:
                self.uncertainty_or_limitations = self.explanation
            if self.suggested_action is None:
                self.suggested_action = "Review official API documentation or verify network/credential settings."

        if self.title is None:
            full_target = f"{self.receiver}.{self.target_name}" if self.receiver else self.target_name
            self.title = f"{full_target} ({self.status.replace('_', ' ').title()})"
        return self


class AISuggestion(BaseModel):
    """An AI-assisted suggestion or hypothesis that has NOT been deterministically verified."""
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(..., description="Unique suggestion identifier")
    candidate_id: str = Field(..., description="Associated AST candidate ID")
    claim_type: str = Field(..., description="Category of suggested issue")
    description: str = Field(..., description="Description of the potential contract concern")
    unverified_aspects: str = Field(
        ..., 
        description="Explicit disclosure of what facts remain unverified by documentation"
    )
    suggested_documentation_queries: List[str] = Field(default_factory=list)
    referenced_evidence_ids: List[str] = Field(default_factory=list)
    confidence: str = Field(default="uncalibrated", description="Qualitative confidence label")
    reasoning_summary: Optional[str] = Field(default=None, description="Concise rationale for suggestion")
    verification_status: VerificationStatusType = Field(
        default="unverified_suggestion",
        description="Explicitly unverified suggestion status",
    )
    label: str = Field(
        default="Unverified suggestion",
        description="Strict non-verified badge label",
    )
    file_path: Optional[str] = Field(default=None, description="Source file path for multi-file project analysis")

    # Traceable suggestion fields:
    title: Optional[str] = Field(default=None, description="Short human-readable finding title")
    source_location: Optional[SourceLocation] = Field(default=None, description="Line and column location in user code")
    code_fragment: Optional[str] = Field(default=None, description="Relevant code expression if known")
    documented_requirement: Optional[str] = Field(default=None, description="Hypothesized documentation requirement")
    source_url: Optional[str] = Field(default=None, description="Suggested documentation source URL if known")
    suggested_correction: Optional[str] = Field(default=None, description="Suggested correction if known")

    @model_validator(mode="after")
    def sync_suggestion_title(self) -> "AISuggestion":
        if self.title is None:
            c_type_clean = self.claim_type.replace('_', ' ').title()
            self.title = f"Unverified Suggestion: {c_type_clean}"
        return self


class AnalysisRequest(BaseModel):
    """Request payload for the unified APICompass analysis endpoint."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        ..., 
        max_length=100_000, 
        description="Python source code text to analyze (max 100 KB)"
    )
    filename: str = Field(default="snippet.py", max_length=255, description="Source filename")
    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target API ecosystem (default: 'stripe')",
    )
    force_mock: bool = Field(default=False, description="Explicitly force mock fixtures")


class AnalysisReport(BaseModel):
    """Unified evidence-based analysis report and final verdict."""
    model_config = ConfigDict(extra="forbid")

    verdict: VerdictType = Field(
        ..., 
        description="Overall verdict: 'clean', 'issues_found', or 'unable_to_verify'"
    )
    result_state: VerificationStatusType = Field(
        default="unable_to_verify",
        description="Explicit overall result state: 'verified', 'unverified_suggestion', 'unable_to_verify', 'no_issue_detected'",
    )
    engine_version: str = Field(default="0.1.0", description="APICompass engine version")
    filename: str = Field(..., description="Analyzed filename")
    total_lines: int = Field(default=0, description="Total source lines analyzed")
    evidence_trust: EvidenceTrustType = Field(
        ..., 
        description="Trust state: 'live_official_source', 'mock_fixture', or 'untrusted_or_unavailable'"
    )
    is_mock: bool = Field(..., description="True if mock fixtures were used in any part of analysis")
    summary: str = Field(..., description="Executive summary of the analysis findings")
    checks_performed: List[str] = Field(default_factory=list, description="List of specific checks performed")
    verified_issues: List[VerifiedIssue] = Field(default_factory=list, description="Confirmed contract violations")
    ai_suggestions: List[AISuggestion] = Field(
        default_factory=list, 
        description="AI-assisted suggestions and potential concerns that remain unverified"
    )
    unresolved_candidates: List[str] = Field(default_factory=list, description="IDs of unresolved candidates")
    candidate_assessments: List[CandidateAssessment] = Field(default_factory=list)
    evidence_items: List[NormalizedEvidence] = Field(default_factory=list)
    limitations_and_caveats: List[str] = Field(default_factory=list)
    syntax_error: Optional[SyntaxErrorInfo] = Field(default=None)
    llm_reasoning_status: str = Field(
        default="disabled", 
        description="Status of LLM reasoning provider: 'disabled', 'mock', 'available', 'unavailable', 'error'"
    )
    llm_reasoning_summary: Optional[str] = Field(
        default=None, 
        description="High-level summary of LLM reasoning (excluding private internal chain of thought)"
    )
    disclaimer: str = Field(
        default=(
            "The model proposes; deterministic code decides. A 'clean' verdict indicates only that "
            "supported checks found no verified contract violations within the analyzed scope. "
            "It does not guarantee absence of other bugs."
        ),
        description="Core integrity guarantee disclaimer"
    )
    scan_id: Optional[str] = Field(
        default=None,
        description="Server-generated unique audit record identifier if scan persistence succeeded"
    )
    persistence_status: Optional[str] = Field(
        default="disabled",
        description="Audit persistence status: 'saved', 'failed', or 'disabled'"
    )

    @model_validator(mode="after")
    def sync_result_state(self) -> "AnalysisReport":
        if self.verdict == "clean":
            self.result_state = "no_issue_detected"
        elif self.verdict == "issues_found":
            self.result_state = "verified"
        else:
            self.result_state = "unable_to_verify"
        return self
