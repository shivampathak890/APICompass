"""Pydantic schemas for documentation retrieval and normalized evidence records."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocSection(BaseModel):
    """Structured section of a documentation page."""
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(..., description="Section heading or title")
    level: int = Field(default=1, ge=1, le=6, description="Markdown heading level (1-6)")
    content: str = Field(..., description="Cleaned section text content")


class DocParameter(BaseModel):
    """Extracted API parameter contract specification."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Parameter name")
    param_type: Optional[str] = Field(default=None, description="Documented type (e.g. 'integer', 'string')")
    is_required: bool = Field(default=False, description="Whether parameter is documented as required")
    is_deprecated: bool = Field(default=False, description="Whether parameter is marked deprecated or legacy")
    description: Optional[str] = Field(default=None, description="Documented parameter description")


class NormalizedDocPage(BaseModel):
    """Normalized representation of a fetched documentation page suitable for contract comparison.

    Preserves source URL, page title, structured sections, code examples,
    parameter contracts, deprecation notices, required-field definitions,
    and cryptographic SHA-256 provenance.
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="Requested documentation URL")
    final_url: str = Field(..., description="Canonical final URL after redirects")
    title: Optional[str] = Field(default=None, description="Page title")
    doc_version: Optional[str] = Field(default=None, description="API version context")
    content: str = Field(..., description="Normalized document content")
    content_sha256: str = Field(..., description="Cryptographic SHA-256 hash of normalized content")
    headings: List[str] = Field(default_factory=list, description="Preserved heading hierarchy")
    sections: List[DocSection] = Field(default_factory=list, description="Extracted document sections")
    parameters: List[DocParameter] = Field(default_factory=list, description="Structured parameter contracts")
    required_fields: List[str] = Field(default_factory=list, description="Identified required parameter names")
    deprecation_notices: List[str] = Field(default_factory=list, description="Identified deprecation/legacy warnings")
    code_examples: List[str] = Field(default_factory=list, description="Preserved code example snippets")
    is_mock: bool = Field(default=False, description="Whether content originates from mock fixture")
    provider: str = Field(default="tinyfish_live", description="Provider identifier")
    retrieved_at: str = Field(..., description="ISO-8601 UTC timestamp")
    is_full_page: bool = Field(
        default=True,
        description="Explicit indicator that this is full fetched page content, not a search preview",
    )


class NormalizedEvidence(BaseModel):
    """Traceable, normalized evidence record from official technical documentation."""
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., description="Stable deterministic evidence identifier")
    ecosystem: str = Field(..., description="API ecosystem (e.g., 'stripe')")
    package: str = Field(..., description="Package identifier (e.g., 'stripe')")
    source_url: str = Field(..., description="Original source URL")
    canonical_url: str = Field(..., description="Canonicalized and validated source URL")
    title: Optional[str] = Field(default=None, description="Page or section title")
    content_excerpt: str = Field(..., description="Sanitized, normalized documentation excerpt")
    retrieved_at: str = Field(..., description="ISO-8601 UTC timestamp of retrieval")
    provider: str = Field(..., description="Retrieval provider ('tinyfish_live', 'tinyfish_mock')")
    status: str = Field(
        ..., 
        description="Retrieval status: 'success', 'partial', 'unavailable', 'rejected', or 'mock'"
    )
    is_mock: bool = Field(..., description="Explicit flag indicating mock fixture vs live retrieval")
    source_trust: str = Field(default="official", description="Source trust level ('official', 'mock_fixture', 'untrusted', 'rejected')")
    doc_version: Optional[str] = Field(default=None, description="Documented API version if available")
    error_code: Optional[str] = Field(default=None, description="Error classification code if failed")
    error_message: Optional[str] = Field(default=None, description="Sanitized error description")
    # Extended normalized documentation fields (all have defaults for full backward compatibility)
    raw_markdown: Optional[str] = Field(default=None, description="Raw or formatted extracted markdown content")
    content_sha256: Optional[str] = Field(default=None, description="Cryptographic SHA-256 hash of fetched content")
    headings: List[str] = Field(default_factory=list, description="Preserved document headings")
    parameters: List[DocParameter] = Field(default_factory=list, description="Extracted parameter specifications")
    required_fields: List[str] = Field(default_factory=list, description="Identified required parameter names")
    deprecation_notices: List[str] = Field(default_factory=list, description="Identified deprecation/legacy warnings")
    code_examples: List[str] = Field(default_factory=list, description="Preserved code example snippets")
    page_data: Optional[NormalizedDocPage] = Field(default=None, description="Detailed normalized document model")
    is_full_page: bool = Field(
        default=True,
        description="Explicit indicator that this is full fetched documentation, not a search preview",
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid_statuses = {"success", "partial", "unavailable", "rejected", "mock", "empty", "auth_failed", "rate_limited", "live"}
        if v not in valid_statuses:
            raise ValueError(f"Invalid evidence status '{v}'. Must be one of {valid_statuses}")
        return v


class DocRetrievalRequest(BaseModel):
    """Request payload for documentation retrieval."""
    model_config = ConfigDict(extra="forbid")

    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target ecosystem (default: 'stripe')",
    )
    package: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target package name (default: 'stripe')",
    )
    query: Optional[str] = Field(
        default=None, 
        max_length=200, 
        description="Target search query or API symbol (e.g. 'stripe.Charge.create')"
    )
    target_url: Optional[str] = Field(
        default=None, 
        max_length=500, 
        description="Optional specific approved documentation URL to fetch"
    )
    max_results: int = Field(
        default=3, 
        ge=1, 
        le=10, 
        description="Maximum number of evidence items to return (1-10)"
    )
    force_mock: bool = Field(
        default=False, 
        description="Explicitly force mock fixtures even if live credentials are configured"
    )


class DocRetrievalResponse(BaseModel):
    """Response payload containing normalized documentation evidence."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        ..., 
        description="Overall retrieval status: 'success', 'partial', 'unavailable', 'rejected', or 'mock'"
    )
    provider: str = Field(..., description="Active provider identifier")
    is_mock: bool = Field(..., description="Explicitly labels whether results are from mock fixtures")
    total_results: int = Field(default=0, description="Count of returned evidence items")
    evidence: List[NormalizedEvidence] = Field(default_factory=list)
    message: Optional[str] = Field(default=None, description="Human-readable status or guidance message")
    disclaimer: str = Field(
        default="Official documentation evidence retrieved for verification. Does not imply code has been modified.",
        description="Documentation integrity disclaimer"
    )


class SearchResultItem(BaseModel):
    """Normalized candidate documentation search hit from TinyFish Search API.

    INVARIANT: Search result snippets are indexing previews only and cannot be used
    as verified evidence of API contract violations. Full official documentation must
    be retrieved via the Fetch API and validated by the QuoteVerifier with SHA-256 hashing.
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="Target documentation URL")
    canonical_url: str = Field(..., description="Canonicalized and validated documentation URL")
    title: Optional[str] = Field(default=None, description="Page title")
    snippet: Optional[str] = Field(default=None, description="Preview text snippet (indexing preview only)")
    site_name: Optional[str] = Field(default=None, description="Publisher or domain name")
    position: int = Field(default=1, description="Rank position (1-indexed)")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Computed relevance score (0.0 to 1.0)")
    is_approved_domain: bool = Field(default=True, description="Whether URL host is in approved documentation allowlist")


class DocSearchRequest(BaseModel):
    """Request payload for searching candidate documentation pages."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=200, description="Search query or API symbol")
    ecosystem: str = Field(
        default="stripe",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Target ecosystem (default: 'stripe')",
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of candidate URLs to return (1-10)")
    force_mock: bool = Field(default=False, description="Explicitly force mock fixtures even if live credentials configured")


class DocSearchResponse(BaseModel):
    """Response payload containing ranked documentation search hits."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="Executed search query")
    ecosystem: str = Field(default="stripe", description="Target ecosystem")
    provider: str = Field(..., description="Active provider identifier ('tinyfish_live', 'tinyfish_mock')")
    is_mock: bool = Field(..., description="Explicit flag indicating whether results are from mock fixtures")
    status: str = Field(..., description="Search status: 'success', 'empty', 'unavailable', 'rate_limited', 'auth_failed'")
    total_results: int = Field(default=0, description="Count of returned candidate results")
    results: List[SearchResultItem] = Field(default_factory=list, description="Ranked candidate documentation results")
    message: Optional[str] = Field(default=None, description="Human-readable status or guidance message")
    error_code: Optional[str] = Field(default=None, description="Error classification code if failed")
    error_message: Optional[str] = Field(default=None, description="Sanitized error description")
    disclaimer: str = Field(
        default="Search results provide candidate documentation URLs only. Snippets are not verified evidence.",
        description="Search result usage constraint disclaimer"
    )

