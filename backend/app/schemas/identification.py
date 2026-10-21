"""Pydantic schemas for structured API call identification."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.ast_analysis import CallArgument, SourceLocation, SyntaxErrorInfo, validate_safe_filename


class IdentifiedApiCall(BaseModel):
    """Structured representation of an identified API call."""
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(..., description="Unique deterministic identifier for this call instance")
    sdk_or_library: str = Field(..., description="Detected SDK or library name (e.g. 'stripe', 'requests', 'unknown')")
    api_resource: Optional[str] = Field(
        default=None, 
        description="Canonical Stripe or API resource name (e.g., 'Charge', 'PaymentIntent', 'Customer', 'Refund')"
    )
    operation: Optional[str] = Field(
        default=None, 
        description="Identified operation verb (e.g., 'create', 'retrieve', 'update', 'delete', 'cancel', 'capture', 'confirm')"
    )
    symbol: str = Field(..., description="Canonical or raw symbol identifier (e.g., 'stripe.Charge.create')")
    raw_expression: str = Field(..., description="Full source code expression of the call")
    positional_arguments: List[CallArgument] = Field(default_factory=list, description="Positional argument details")
    keyword_arguments: Dict[str, CallArgument] = Field(default_factory=dict, description="Keyword arguments keyed by argument name")
    location: SourceLocation = Field(..., description="Source code coordinate span")
    confidence: str = Field(
        ..., 
        description="Identification confidence: 'confirmed', 'ambiguous', 'unsupported', 'uncertain_receiver'"
    )
    is_ambiguous: bool = Field(default=False, description="True if identification has unresolved ambiguity")
    unresolved_ambiguity: Optional[str] = Field(
        default=None, 
        description="Detailed explanation of any unresolved ambiguity preventing confident attribution"
    )
    doc_query: Optional[str] = Field(
        default=None, 
        description="Normalized symbol key for documentation registry lookup (e.g., 'charge.create')"
    )
    canonical_doc_url: Optional[str] = Field(
        default=None, 
        description="Verified official documentation URL if resolved via documentation registry"
    )
    matching_strategy: str = Field(
        default="rule_based",
        description="Strategy used for identification ('registry_exact', 'sdk_alias', 'client_instance', 'uncertain_receiver', 'non_stripe_receiver', 'rule_based')"
    )


class IdentifyApiCallsRequest(BaseModel):
    """Request payload for API call identification."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., max_length=100_000, description="Python source code text to analyze (max 100 KB)")
    filename: str = Field(default="<unknown>", max_length=255, description="Source filename")
    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target API ecosystem (default: 'stripe')",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename_security(cls, v: str) -> str:
        return validate_safe_filename(v)


class IdentifyApiCallsResponse(BaseModel):
    """Response payload for API call identification."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="Analysis status: 'success', 'syntax_error', 'source_too_large', 'complexity_limit_exceeded'")
    filename: str = Field(..., description="Filename analyzed")
    total_calls_detected: int = Field(default=0, description="Total calls detected in AST")
    identified_calls: List[IdentifiedApiCall] = Field(default_factory=list, description="Structured identified API calls")
    confirmed_count: int = Field(default=0, description="Number of confidently confirmed API calls")
    ambiguous_count: int = Field(default=0, description="Number of calls with unresolved ambiguity")
    unsupported_count: int = Field(default=0, description="Number of unsupported operations")
    syntax_error: Optional[SyntaxErrorInfo] = Field(default=None, description="Syntax error details if status is 'syntax_error'")

