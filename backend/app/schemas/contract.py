"""Pydantic schemas for extracted API contracts and candidate contract findings."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.ast_analysis import SourceLocation
from app.schemas.documentation import NormalizedEvidence

# Completeness and match types
CompletenessType = Literal["complete_contract", "excerpt_only", "unrelated", "missing"]
MatchMethodType = Literal["exact", "whitespace_normalized", "none"]


class ParameterConstraint(BaseModel):
    """Statically checkable constraint on a parameter value."""
    model_config = ConfigDict(extra="forbid")

    constraint_type: str = Field(
        ...,
        description="Constraint type: 'positive_integer', 'non_negative_integer', 'iso_currency_code', 'non_empty_str', 'enum_values'",
    )
    description: str = Field(..., description="Documented constraint description")
    allowed_values: Optional[List[Any]] = Field(default=None, description="Enumeration of permitted values")
    min_value: Optional[float] = Field(default=None, description="Minimum numeric value if applicable")
    max_value: Optional[float] = Field(default=None, description="Maximum numeric value if applicable")


class ParameterContract(BaseModel):
    """Specification of a single parameter in an extracted API contract."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Parameter name")
    param_type: Optional[str] = Field(default=None, description="Documented type (e.g. 'integer', 'string')")
    is_required: bool = Field(default=False, description="True if explicitly documented as required")
    is_deprecated: bool = Field(default=False, description="True if marked as deprecated or legacy")
    is_unsupported: bool = Field(default=False, description="True if marked as unsupported for this operation/version")
    description: Optional[str] = Field(default=None, description="Documented parameter description")
    constraints: List[ParameterConstraint] = Field(default_factory=list, description="Extracted parameter constraints")
    deprecation_reason: Optional[str] = Field(default=None, description="Documented reason or migration advice")
    unsupported_reason: Optional[str] = Field(default=None, description="Explanation why parameter is unsupported")


class ExtractedContract(BaseModel):
    """Structured API contract extracted from documentation evidence."""
    model_config = ConfigDict(extra="forbid")

    operation_name: str = Field(..., description="Normalized operation or symbol (e.g. 'stripe.Charge.create')")
    resource: str = Field(..., description="API resource (e.g. 'stripe.Charge')")
    target_method: str = Field(..., description="Invoked method name (e.g. 'create')")
    required_parameters: Dict[str, ParameterContract] = Field(
        default_factory=dict,
        description="Parameters explicitly documented as required",
    )
    optional_parameters: Dict[str, ParameterContract] = Field(
        default_factory=dict,
        description="Parameters documented as optional",
    )
    all_parameters: Dict[str, ParameterContract] = Field(
        default_factory=dict,
        description="All documented parameters for the operation",
    )
    is_operation_deprecated: bool = Field(
        default=False,
        description="True if the entire operation/endpoint is documented as deprecated",
    )
    operation_deprecation_notice: Optional[str] = Field(
        default=None,
        description="Documented deprecation notice or migration recommendation",
    )
    completeness: CompletenessType = Field(
        default="excerpt_only",
        description="Contract completeness: 'complete_contract', 'excerpt_only', or 'missing'",
    )
    is_parameter_list_closed: bool = Field(
        default=False,
        description="True if the documentation specifies an exhaustive closed parameter set",
    )
    doc_version: Optional[str] = Field(default=None, description="Documented API version context")
    sdk_version: Optional[str] = Field(default=None, description="Documented SDK version context")
    source_url: str = Field(..., description="Canonical documentation source URL")
    evidence_id: str = Field(..., description="Source evidence ID")
    raw_excerpt: str = Field(..., description="Original excerpt text from which contract was extracted")


class ContractFindingCandidate(BaseModel):
    """Candidate contract mismatch identified by comparing an API call against extracted documentation.

    Structured candidate findings are returned by the contract matcher before final quote verification
    and trust adjudication.
    """
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., description="Unique deterministic candidate finding identifier")
    candidate_id: str = Field(..., description="Associated AST candidate ID")
    source_location: SourceLocation = Field(..., description="Line and column location in user code")
    claim_checked: str = Field(..., description="Description of the API contract claim checked")
    violation_type: str = Field(
        ...,
        description=(
            "Contract mismatch classification: "
            "'missing_required_parameter', "
            "'unsupported_parameter', "
            "'deprecated_operation', "
            "'legacy_deprecated_parameter', "
            "'constraint_violation'"
        ),
    )
    explanation: str = Field(..., description="Detailed explanation of the contract mismatch")
    parameter_name: Optional[str] = Field(default=None, description="Affected parameter name if applicable")
    supplied_value_repr: Optional[str] = Field(default=None, description="Supplied argument expression text if applicable")
    is_statically_determined: bool = Field(default=True, description="True if value/violation was statically determined")
    supporting_evidence_id: str = Field(..., description="ID of the evidence establishing the contract")
    source_url: str = Field(..., description="Official documentation source URL")
    contract_quote: str = Field(..., description="Exact documentation quotation supporting the claim")
    match_method: MatchMethodType = Field(default="exact", description="Quote verification match method")
    limitations: Optional[str] = Field(default=None, description="Applicability caveats or version limitations")
    contract_version: Optional[str] = Field(default=None, description="API or SDK version context")
    evidence: Optional[NormalizedEvidence] = Field(default=None, description="Attached relevant contract evidence")
    file_path: Optional[str] = Field(default=None, description="Source file path for multi-file project analysis")

    # Source provenance fields:
    canonical_url: Optional[str] = Field(default=None, description="Canonical documentation URL")
    source_title: Optional[str] = Field(default=None, description="Documentation title")
    retrieval_status: Optional[str] = Field(default=None, description="Retrieval status of supporting evidence")
    retrieved_at: Optional[str] = Field(default=None, description="ISO timestamp when evidence was retrieved")
    content_sha256: Optional[str] = Field(default=None, description="Cryptographic SHA-256 hash of documentation content")

    # Compatibility aliases for callers expecting VerifiedIssue shape:
    issue_id: Optional[str] = Field(default=None, description="Compatibility alias for finding_id")
    verified_quote: Optional[str] = Field(default=None, description="Compatibility alias for contract_quote")

    @model_validator(mode="after")
    def sync_compatibility_fields(self) -> "ContractFindingCandidate":
        if self.issue_id is None:
            self.issue_id = self.finding_id
        if self.verified_quote is None:
            self.verified_quote = self.contract_quote
        if self.evidence is not None:
            if self.canonical_url is None:
                self.canonical_url = self.evidence.canonical_url
            if self.source_title is None:
                self.source_title = self.evidence.title
            if self.retrieval_status is None:
                self.retrieval_status = self.evidence.status
            if self.retrieved_at is None:
                self.retrieved_at = self.evidence.retrieved_at
            if self.content_sha256 is None:
                self.content_sha256 = self.evidence.content_sha256
        return self

