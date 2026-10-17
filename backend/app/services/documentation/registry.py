"""Documentation source registry and ecosystem mapping.

Maintains canonical documentation domains, permitted URL prefixes,
verified symbol mappings, and two-stage target resolution rules
for supported API ecosystems.

Two-stage resolution strategy:
1. Fast Path: Look up known, well-supported API symbols in verified registry.
2. Search Fallback: Fall back to TinyFish Search when symbol is unknown,
   ambiguous, or not covered adequately by the registry.
"""

from dataclasses import dataclass, field
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.schemas.documentation import DocSearchRequest, DocSearchResponse, SearchResultItem
from app.services.documentation.security import validate_destination_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentationSource:
    """Descriptor for an approved technical documentation source."""
    ecosystem: str
    package: str
    name: str
    canonical_domain: str
    permitted_prefixes: List[str]
    rationale: str
    trust_level: str = "official"


@dataclass(frozen=True)
class ApiSymbolMapping:
    """Descriptor for a verified API symbol mapping in the registry fast path."""
    symbol: str  # normalized symbol key, e.g. 'charge.create'
    canonical_url: str  # verified official doc URL
    ecosystem: str = "stripe"
    description: str = ""
    is_active: bool = True  # If False, considered stale/deprecated and bypassed in fast path
    aliases: List[str] = field(default_factory=list)  # Invocations mapping to this symbol


@dataclass
class ResolutionResult:
    """Detailed result of documentation target resolution.

    Supports backward-compatible 3-tuple unpacking:
        is_valid, target_url, err = resolve_documentation_target(...)
    while providing structured fields for confidence, strategy, candidate pages,
    and decision rationale.
    """
    is_valid: bool
    canonical_url: Optional[str]
    error_reason: Optional[str]
    candidate_urls: List[str] = field(default_factory=list)
    strategy: str = "unresolved"  # "registry_exact", "registry_alias", "explicit_url", "search_fallback", "ambiguous_candidates", "unresolved"
    confidence: float = 0.0
    selection_reason: str = ""

    def __iter__(self):
        """Enable backward-compatible 3-tuple unpacking."""
        return iter((self.is_valid, self.canonical_url, self.error_reason))


# Registry of approved documentation sources
APPROVED_SOURCES: Dict[str, DocumentationSource] = {
    "stripe": DocumentationSource(
        ecosystem="python",
        package="stripe",
        name="Stripe API Reference & Documentation",
        canonical_domain="docs.stripe.com",
        permitted_prefixes=[
            "https://docs.stripe.com/api",
            "https://docs.stripe.com/payments",
            "https://docs.stripe.com/development",
            "https://stripe.com/docs",
            "https://github.com/stripe/stripe-python",
        ],
        rationale="Official Stripe Developer Documentation and Python SDK Reference",
        trust_level="official",
    )
}

# Generic root URLs to deprioritize when specific contract pages exist
GENERIC_ROOT_URLS: Set[str] = {
    "https://docs.stripe.com/api",
    "https://docs.stripe.com/api/",
    "https://stripe.com/docs",
    "https://stripe.com/docs/",
}


def get_approved_source(ecosystem: str = "stripe") -> Optional[DocumentationSource]:
    """Retrieve approved documentation source configuration by ecosystem."""
    return APPROVED_SOURCES.get(ecosystem.lower())


def pascal_to_snake(s: str) -> str:
    """Convert PascalCase or camelCase segment to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def normalize_api_symbol(symbol: str) -> str:
    """Normalize a Python AST call or query string to a standardized lookup key.

    Examples:
        'stripe.Charge.create' -> 'charge.create'
        'stripe.PaymentIntent.create' -> 'payment_intent.create'
        'PaymentIntent.create()' -> 'payment_intent.create'
        'charges.create' -> 'charges.create'
    """
    cleaned = symbol.strip()
    if "(" in cleaned:
        cleaned = cleaned.split("(", 1)[0].strip()
    if cleaned.lower().startswith("stripe."):
        cleaned = cleaned[7:].strip()
    if cleaned.endswith("()"):
        cleaned = cleaned[:-2].strip()
    parts = cleaned.split(".")
    normalized_parts = [pascal_to_snake(p) for p in parts if p]
    return ".".join(normalized_parts)


def validate_registry_mapping(
    mapping: ApiSymbolMapping,
    source: Optional[DocumentationSource] = None,
) -> Tuple[bool, Optional[str]]:
    """Validate that an ApiSymbolMapping points to an approved official documentation source.

    Verifies domain security (SSRF/private IP prevention) and permitted prefix matching.
    """
    if not source:
        source = get_approved_source(mapping.ecosystem)
    if not source:
        return False, f"Unsupported ecosystem '{mapping.ecosystem}'"

    # Check URL security and canonical domain
    is_valid, canonical, err = validate_destination_url(
        mapping.canonical_url,
        approved_hosts={source.canonical_domain, "stripe.com", "github.com"},
    )
    if not is_valid or not canonical:
        return False, f"Registry mapping for '{mapping.symbol}' failed security validation: {err}"

    # Verify URL starts with an approved prefix
    prefix_matched = any(canonical.startswith(prefix) for prefix in source.permitted_prefixes)
    if not prefix_matched:
        return False, (
            f"Registry mapping for '{mapping.symbol}' URL '{canonical}' does not start with an approved prefix: "
            f"{source.permitted_prefixes}"
        )

    return True, None


# Registry storage
STRIPE_REGISTRY_MAPPINGS: Dict[str, ApiSymbolMapping] = {}
STRIPE_SYMBOL_URL_MAP: Dict[str, str] = {}


def register_symbol_mapping(
    mapping: ApiSymbolMapping,
    validate: bool = True,
) -> bool:
    """Register a verified API symbol mapping into the fast-path registry.

    Validates official documentation source, indexes canonical symbol and all aliases,
    and updates STRIPE_SYMBOL_URL_MAP for backward compatibility.
    """
    if validate:
        is_valid, err = validate_registry_mapping(mapping)
        if not is_valid:
            logger.warning("Rejected invalid registry mapping for '%s': %s", mapping.symbol, err)
            return False

    norm_sym = normalize_api_symbol(mapping.symbol)
    STRIPE_REGISTRY_MAPPINGS[norm_sym] = mapping
    if mapping.is_active:
        STRIPE_SYMBOL_URL_MAP[norm_sym] = mapping.canonical_url

    for alias in mapping.aliases:
        norm_alias = normalize_api_symbol(alias)
        STRIPE_REGISTRY_MAPPINGS[norm_alias] = mapping
        if mapping.is_active:
            STRIPE_SYMBOL_URL_MAP[norm_alias] = mapping.canonical_url

    return True


# Seed initial verified Stripe API mappings
_INITIAL_STRIPE_MAPPINGS: List[ApiSymbolMapping] = [
    ApiSymbolMapping(
        symbol="charge",
        canonical_url="https://docs.stripe.com/api/charges",
        aliases=["charges"],
        description="Stripe Charges API resource overview",
    ),
    ApiSymbolMapping(
        symbol="charge.create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        aliases=["charges.create"],
        description="Create a charge endpoint",
    ),
    ApiSymbolMapping(
        symbol="charge.retrieve",
        canonical_url="https://docs.stripe.com/api/charges/retrieve",
        aliases=["charges.retrieve"],
        description="Retrieve a charge endpoint",
    ),
    ApiSymbolMapping(
        symbol="payment_intent",
        canonical_url="https://docs.stripe.com/api/payment_intents",
        aliases=["paymentintent", "payment_intents", "paymentintents"],
        description="Stripe PaymentIntents API resource overview",
    ),
    ApiSymbolMapping(
        symbol="payment_intent.create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        aliases=["paymentintent.create", "payment_intents.create"],
        description="Create a payment intent endpoint",
    ),
    ApiSymbolMapping(
        symbol="payment_intent.retrieve",
        canonical_url="https://docs.stripe.com/api/payment_intents/retrieve",
        aliases=["paymentintent.retrieve", "payment_intents.retrieve"],
        description="Retrieve a payment intent endpoint",
    ),
    ApiSymbolMapping(
        symbol="customer",
        canonical_url="https://docs.stripe.com/api/customers",
        aliases=["customers"],
        description="Stripe Customers API resource overview",
    ),
    ApiSymbolMapping(
        symbol="customer.create",
        canonical_url="https://docs.stripe.com/api/customers/create",
        aliases=["customers.create"],
        description="Create a customer endpoint",
    ),
    ApiSymbolMapping(
        symbol="customer.retrieve",
        canonical_url="https://docs.stripe.com/api/customers/retrieve",
        aliases=["customers.retrieve"],
        description="Retrieve a customer endpoint",
    ),
    ApiSymbolMapping(
        symbol="refund",
        canonical_url="https://docs.stripe.com/api/refunds",
        aliases=["refunds"],
        description="Stripe Refunds API resource overview",
    ),
    ApiSymbolMapping(
        symbol="refund.create",
        canonical_url="https://docs.stripe.com/api/refunds/create",
        aliases=["refunds.create"],
        description="Create a refund endpoint",
    ),
    ApiSymbolMapping(
        symbol="refund.retrieve",
        canonical_url="https://docs.stripe.com/api/refunds/retrieve",
        aliases=["refunds.retrieve"],
        description="Retrieve a refund endpoint",
    ),
]

for _mapping in _INITIAL_STRIPE_MAPPINGS:
    register_symbol_mapping(_mapping, validate=False)


def resolve_from_registry(
    query: str,
    ecosystem: str = "stripe",
) -> ResolutionResult:
    """Stage 1: Resolve documentation target using the registry fast path.

    Returns ResolutionResult.
    - If exact symbol or alias matches an active, valid registry entry:
        returns ResolutionResult(is_valid=True, strategy="registry_exact"|"registry_alias", confidence=1.0)
    - If symbol matches an inactive/stale registry entry:
        returns ResolutionResult(is_valid=False, error_reason="...", strategy="unresolved")
    - If symbol is not in registry:
        returns ResolutionResult(is_valid=False, error_reason="...", strategy="unresolved")
    """
    source = get_approved_source(ecosystem)
    if not source:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Unsupported ecosystem '{ecosystem}'. Supported: {list(APPROVED_SOURCES.keys())}",
            strategy="unresolved",
            confidence=0.0,
        )

    norm_query = normalize_api_symbol(query)
    mapping = STRIPE_REGISTRY_MAPPINGS.get(norm_query)

    if not mapping:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Symbol '{query}' (normalized: '{norm_query}') not found in {ecosystem} registry.",
            strategy="unresolved",
            confidence=0.0,
        )

    if not mapping.is_active:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Registry mapping for '{mapping.symbol}' is marked stale/inactive.",
            strategy="unresolved",
            confidence=0.0,
            selection_reason=f"Mapping for '{mapping.symbol}' is inactive; falling back to search.",
        )

    # Validate mapping URL security
    is_valid, err = validate_registry_mapping(mapping, source)
    if not is_valid:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Registry mapping for '{mapping.symbol}' is invalid: {err}",
            strategy="unresolved",
            confidence=0.0,
        )

    strategy = "registry_exact" if norm_query == normalize_api_symbol(mapping.symbol) else "registry_alias"
    reason = (
        f"Matched exact registered API symbol '{mapping.symbol}'"
        if strategy == "registry_exact"
        else f"Matched registered alias '{norm_query}' -> '{mapping.symbol}'"
    )

    return ResolutionResult(
        is_valid=True,
        canonical_url=mapping.canonical_url,
        error_reason=None,
        candidate_urls=[mapping.canonical_url],
        strategy=strategy,
        confidence=1.0,
        selection_reason=reason,
    )


async def resolve_with_search(
    query: str,
    search_fn: Any,
    ecosystem: str = "stripe",
    limit: int = 5,
) -> ResolutionResult:
    """Stage 2: Fall back to TinyFish Search when registry has no valid mapping.

    Executes search_fn, verifies returned candidate pages against approved official documentation policy,
    filters out generic landing pages when specific contract pages exist, preserves multiple candidate
    pages on ambiguous queries, and deterministically ranks the best contract match.
    """
    source = get_approved_source(ecosystem)
    if not source:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Unsupported ecosystem '{ecosystem}'",
            strategy="unresolved",
            confidence=0.0,
        )

    if not search_fn:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"No search provider available to resolve unknown symbol '{query}'.",
            strategy="unresolved",
            confidence=0.0,
        )

    # Execute search
    try:
        if callable(search_fn):
            try:
                search_resp = await search_fn(query=query, ecosystem=ecosystem, limit=limit)
            except TypeError:
                search_resp = await search_fn(DocSearchRequest(query=query, ecosystem=ecosystem, limit=limit))
        else:
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=f"Search provider '{type(search_fn)}' is not callable.",
                strategy="unresolved",
                confidence=0.0,
            )
    except Exception as exc:
        logger.warning("TinyFish search fallback failed for query '%s': %s", query, exc)
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Documentation search failed: {str(exc)}",
            strategy="unresolved",
            confidence=0.0,
        )

    # Check search response status
    if not search_resp or not hasattr(search_resp, "status"):
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason="Invalid search response returned by search provider.",
            strategy="unresolved",
            confidence=0.0,
        )

    if search_resp.status != "success" or not search_resp.results:
        err_msg = (
            search_resp.error_message
            or search_resp.message
            or f"No official documentation found for symbol '{query}' via search fallback."
        )
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=err_msg,
            strategy="unresolved",
            confidence=0.0,
        )

    # Filter and validate candidates against security allowlist and approved prefixes
    valid_candidates: List[SearchResultItem] = []
    for item in search_resp.results:
        item_url = item.canonical_url or item.url
        is_safe, canonical, _ = validate_destination_url(
            item_url,
            approved_hosts={source.canonical_domain, "stripe.com", "github.com"},
        )
        if not is_safe or not canonical:
            logger.debug("Filtered out unsafe or unapproved search hit: %s", item_url)
            continue

        prefix_matched = any(canonical.startswith(prefix) for prefix in source.permitted_prefixes)
        if not prefix_matched:
            logger.debug("Filtered out search hit not matching permitted prefixes: %s", canonical)
            continue

        valid_candidates.append(item)

    if not valid_candidates:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"No approved official documentation URLs found in search results for '{query}'.",
            strategy="unresolved",
            confidence=0.0,
        )

    # Separate specific endpoint contract pages from generic root landing pages
    specific_candidates: List[SearchResultItem] = [
        item for item in valid_candidates
        if (item.canonical_url or item.url).rstrip("/") not in {u.rstrip("/") for u in GENERIC_ROOT_URLS}
    ]

    # If specific contract pages exist, prefer them over generic landing pages
    candidates_to_rank = specific_candidates if specific_candidates else valid_candidates

    # If only generic landing pages are returned and the query is an unknown specific symbol,
    # avoid falsely mapping to generic /api with unearned confidence.
    if not specific_candidates and all((item.canonical_url or item.url).rstrip("/") in {u.rstrip("/") for u in GENERIC_ROOT_URLS} for item in valid_candidates):
        cleaned_toks = [t for t in query.lower().replace("stripe.", "").split(".") if t]
        if not any(tok in ("api", "overview", "docs") for tok in cleaned_toks):
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=f"Search returned only generic landing page for specific symbol '{query}'; avoiding false mapping.",
                strategy="unresolved",
                confidence=0.0,
            )

    # Deterministic candidate ranking:
    # Sort by relevance_score DESC, then URL path length DESC (more specific path first), then URL lexicographically
    candidates_to_rank.sort(
        key=lambda it: (-it.relevance_score, -len(it.canonical_url or it.url), (it.canonical_url or it.url))
    )

    all_candidate_urls = [it.canonical_url or it.url for it in candidates_to_rank]
    top_hit = candidates_to_rank[0]
    top_score = top_hit.relevance_score
    top_url = top_hit.canonical_url or top_hit.url

    # Check for ambiguity among top candidates:
    # Ambiguous if there are multiple candidates and difference between top 2 scores is < 0.10, and top_score >= 0.50
    is_ambiguous = False
    if len(candidates_to_rank) > 1:
        second_hit = candidates_to_rank[1]
        score_diff = abs(top_score - second_hit.relevance_score)
        if score_diff < 0.10 and second_hit.relevance_score >= 0.50:
            is_ambiguous = True

    if is_ambiguous:
        confidence = round(max(0.10, top_score * 0.75), 2)
        reason = (
            f"Ambiguous documentation candidates for '{query}' (top scores: {top_score:.2f}, "
            f"{candidates_to_rank[1].relevance_score:.2f}); preserved {len(all_candidate_urls)} candidates. "
            f"Deterministically selected '{top_url}' based on path specificity."
        )
        return ResolutionResult(
            is_valid=True,
            canonical_url=top_url,
            error_reason=None,
            candidate_urls=all_candidate_urls,
            strategy="ambiguous_candidates",
            confidence=confidence,
            selection_reason=reason,
        )

    # Unambiguous search match
    reason = f"Resolved via TinyFish Search top match '{top_hit.title or top_url}' (score: {top_score:.2f})"
    return ResolutionResult(
        is_valid=True,
        canonical_url=top_url,
        error_reason=None,
        candidate_urls=all_candidate_urls,
        strategy="search_fallback",
        confidence=round(top_score, 2),
        selection_reason=reason,
    )


async def resolve_documentation_target_async(
    query: Optional[str],
    target_url: Optional[str],
    ecosystem: str = "stripe",
    search_fn: Optional[Any] = None,
) -> ResolutionResult:
    """Two-stage documentation target resolver.

    1. If target_url provided: validate explicit URL against security and domain rules.
    2. Stage 1 (Fast Path): Look up symbol in verified registry.
    3. Stage 2 (Search Fallback): If unknown, ambiguous, or stale in registry,
       call search_fn to dynamically discover and rank candidate documentation.
    4. Safe Abstention: If no valid documentation is found, return unresolved without inventing URLs.
    """
    source = get_approved_source(ecosystem)
    if not source:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Unsupported ecosystem '{ecosystem}'. Supported: {list(APPROVED_SOURCES.keys())}",
            strategy="unresolved",
            confidence=0.0,
        )

    # Case 1: Explicit target URL provided
    if target_url:
        is_valid, canonical, err = validate_destination_url(
            target_url,
            approved_hosts={source.canonical_domain, "stripe.com", "github.com"},
        )
        if not is_valid or not canonical:
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=err or "Invalid target URL",
                strategy="unresolved",
                confidence=0.0,
            )

        prefix_matched = any(canonical.startswith(prefix) for prefix in source.permitted_prefixes)
        if not prefix_matched:
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=(
                    f"URL '{canonical}' does not match permitted official documentation prefixes for {ecosystem}: "
                    f"{source.permitted_prefixes}"
                ),
                strategy="unresolved",
                confidence=0.0,
            )

        return ResolutionResult(
            is_valid=True,
            canonical_url=canonical,
            error_reason=None,
            candidate_urls=[canonical],
            strategy="explicit_url",
            confidence=1.0,
            selection_reason="Caller-specified target URL validated against official documentation policy",
        )

    # Case 2: Resolve URL from query using two-stage strategy
    if query:
        # Stage 1: Registry fast path
        fast_path_result = resolve_from_registry(query, ecosystem)
        if fast_path_result.is_valid:
            return fast_path_result

        # Stage 2: Fall back to TinyFish Search
        if search_fn:
            return await resolve_with_search(query, search_fn, ecosystem)

        # No search provider available
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=fast_path_result.error_reason or f"Unknown API symbol '{query}' and no search provider available for dynamic resolution.",
            strategy="unresolved",
            confidence=0.0,
            selection_reason="Registry miss and no search provider configured",
        )

    return ResolutionResult(
        is_valid=False,
        canonical_url=None,
        error_reason="Either query or target_url must be provided",
        strategy="unresolved",
        confidence=0.0,
    )


def resolve_documentation_target(
    query: Optional[str],
    target_url: Optional[str],
    ecosystem: str = "stripe",
) -> ResolutionResult:
    """Synchronous resolver for registry fast path and explicit URLs.

    Preserves 100% backward compatibility with:
        is_valid, canonical_url, err = resolve_documentation_target(...)
    """
    source = get_approved_source(ecosystem)
    if not source:
        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=f"Unsupported ecosystem '{ecosystem}'. Supported: {list(APPROVED_SOURCES.keys())}",
            strategy="unresolved",
            confidence=0.0,
        )

    if target_url:
        is_valid, canonical, err = validate_destination_url(
            target_url,
            approved_hosts={source.canonical_domain, "stripe.com", "github.com"},
        )
        if not is_valid or not canonical:
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=err or "Invalid target URL",
                strategy="unresolved",
                confidence=0.0,
            )

        prefix_matched = any(canonical.startswith(prefix) for prefix in source.permitted_prefixes)
        if not prefix_matched:
            return ResolutionResult(
                is_valid=False,
                canonical_url=None,
                error_reason=(
                    f"URL '{canonical}' does not match permitted official documentation prefixes for {ecosystem}: "
                    f"{source.permitted_prefixes}"
                ),
                strategy="unresolved",
                confidence=0.0,
            )

        return ResolutionResult(
            is_valid=True,
            canonical_url=canonical,
            error_reason=None,
            candidate_urls=[canonical],
            strategy="explicit_url",
            confidence=1.0,
            selection_reason="Caller-specified target URL validated against official documentation policy",
        )

    if query:
        res = resolve_from_registry(query, ecosystem)
        if res.is_valid:
            return res

        return ResolutionResult(
            is_valid=False,
            canonical_url=None,
            error_reason=res.error_reason or f"Symbol '{query}' not found in registry fast path.",
            strategy="unresolved",
            confidence=0.0,
            selection_reason="Registry miss without search fallback",
        )

    return ResolutionResult(
        is_valid=False,
        canonical_url=None,
        error_reason="Either query or target_url must be provided",
        strategy="unresolved",
        confidence=0.0,
    )
