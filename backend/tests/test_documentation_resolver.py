"""Automated test suite for documentation target resolver.

Tests:
1. Known symbols (fast-path registry hit, confidence=1.0, search not called)
2. Normalized symbol aliases (PascalCase, methods, plural/singular)
3. Unknown symbols (search fallback, dynamic candidate ranking)
4. Ambiguous symbols (multiple candidate pages preserved, confidence discounted)
5. Stale / inactive mappings (bypasses fast path, falls back to search)
6. Invalid mappings (rejected by registry security validator)
7. Irrelevant / unapproved search results (SSRF/domain filter, rejected)
8. Generic landing page deprioritization (prefers specific contract pages)
9. Generic landing page false-mapping avoidance (does not map unknown APIs to /api)
10. Search failures (HTTP error, timeout, circuit breaker - graceful abstention)
11. Maintainable registry registration helper (clean extensibility)
12. Backward-compatible 3-tuple unpacking
13. Explicit target URL validation (approved vs unapproved)
"""

from typing import List
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.schemas.documentation import (
    DocSearchRequest,
    DocSearchResponse,
    SearchResultItem,
)
from app.services.documentation.registry import (
    ApiSymbolMapping,
    ResolutionResult,
    get_approved_source,
    normalize_api_symbol,
    register_symbol_mapping,
    resolve_documentation_target,
    resolve_documentation_target_async,
    resolve_from_registry,
    resolve_with_search,
    validate_registry_mapping,
    STRIPE_REGISTRY_MAPPINGS,
    STRIPE_SYMBOL_URL_MAP,
)


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def make_search_item(
    url: str,
    title: str = "Doc Page",
    relevance_score: float = 0.85,
    is_approved_domain: bool = True,
) -> SearchResultItem:
    return SearchResultItem(
        url=url,
        canonical_url=url,
        title=title,
        snippet="Official Stripe documentation snippet preview",
        site_name="docs.stripe.com",
        position=1,
        relevance_score=relevance_score,
        is_approved_domain=is_approved_domain,
    )


def make_search_response(
    query: str,
    results: List[SearchResultItem],
    status: str = "success",
    error_message: str = None,
) -> DocSearchResponse:
    return DocSearchResponse(
        query=query,
        ecosystem="stripe",
        provider="tinyfish_live",
        is_mock=False,
        status=status,
        total_results=len(results),
        results=results,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# 1. Known Symbols & Registry Fast Path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_known_symbols_registry_fast_path() -> None:
    """Known API symbols resolve via registry fast path with 1.0 confidence without calling search."""
    mock_search = AsyncMock()

    # Exact canonical symbol
    res = await resolve_documentation_target_async(
        query="charge.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is True
    assert res.canonical_url == "https://docs.stripe.com/api/charges/create"
    assert res.strategy == "registry_exact"
    assert res.confidence == 1.0
    assert "Matched exact registered API symbol" in res.selection_reason
    assert res.candidate_urls == ["https://docs.stripe.com/api/charges/create"]

    # Search provider was NEVER invoked (fast path invariant)
    mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_symbol_normalization_and_aliases() -> None:
    """Python AST notations and aliases normalize to registered Stripe endpoints."""
    mock_search = AsyncMock()

    # PascalCase with module prefix: stripe.PaymentIntent.create
    res = await resolve_documentation_target_async(
        query="stripe.PaymentIntent.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )
    assert res.is_valid is True
    assert res.canonical_url == "https://docs.stripe.com/api/payment_intents/create"
    assert res.strategy in ("registry_exact", "registry_alias")
    assert res.confidence == 1.0

    # Plural alias: charges.create
    res_alias = await resolve_documentation_target_async(
        query="charges.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )
    assert res_alias.is_valid is True
    assert res_alias.canonical_url == "https://docs.stripe.com/api/charges/create"
    assert res_alias.strategy == "registry_alias"

    mock_search.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Unknown Symbols & Search Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_symbol_falls_back_to_search() -> None:
    """Unregistered symbol queries TinyFish Search and ranks official candidates."""
    hit = make_search_item(
        url="https://docs.stripe.com/api/customer_portal/sessions/create",
        title="Create a portal session | Stripe API Reference",
        relevance_score=0.91,
    )
    mock_search = AsyncMock(return_value=make_search_response("stripe.BillingPortal.Session.create", [hit]))

    res = await resolve_documentation_target_async(
        query="stripe.BillingPortal.Session.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is True
    assert res.canonical_url == "https://docs.stripe.com/api/customer_portal/sessions/create"
    assert res.strategy == "search_fallback"
    assert res.confidence == 0.91
    assert "Resolved via TinyFish Search top match" in res.selection_reason
    assert res.candidate_urls == ["https://docs.stripe.com/api/customer_portal/sessions/create"]
    mock_search.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Ambiguous Symbols
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ambiguous_symbols_preserves_multiple_candidates() -> None:
    """Ambiguous query with multiple close-scoring candidates preserves all candidates and discounts confidence."""
    hit1 = make_search_item(
        url="https://docs.stripe.com/api/refunds/create",
        title="Create a refund | Stripe API Reference",
        relevance_score=0.86,
    )
    hit2 = make_search_item(
        url="https://docs.stripe.com/api/refunds/cancel",
        title="Cancel a refund | Stripe API Reference",
        relevance_score=0.83,
    )
    mock_search = AsyncMock(return_value=make_search_response("stripe.Refund.ambiguous_op", [hit1, hit2]))

    res = await resolve_documentation_target_async(
        query="stripe.Refund.ambiguous_op",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is True
    assert res.strategy == "ambiguous_candidates"
    # Multiple candidates preserved in candidate_urls
    assert len(res.candidate_urls) == 2
    assert "https://docs.stripe.com/api/refunds/create" in res.candidate_urls
    assert "https://docs.stripe.com/api/refunds/cancel" in res.candidate_urls
    # Selected highest-scoring candidate deterministically
    assert res.canonical_url == "https://docs.stripe.com/api/refunds/create"
    # Confidence discounted due to ambiguity
    assert res.confidence < 0.86
    assert "Ambiguous documentation candidates" in res.selection_reason


# ---------------------------------------------------------------------------
# 4. Stale or Inactive Mappings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_mapping_bypasses_fast_path_and_falls_back_to_search() -> None:
    """Stale/inactive mapping is bypassed in fast path and falls back to dynamic search."""
    stale_mapping = ApiSymbolMapping(
        symbol="charges.legacy_capture",
        canonical_url="https://docs.stripe.com/api/charges/capture",
        is_active=False,
        description="Deprecated capture endpoint",
    )
    register_symbol_mapping(stale_mapping, validate=False)

    # Fast path rejects inactive mapping
    reg_res = resolve_from_registry("charges.legacy_capture")
    assert reg_res.is_valid is False
    assert "marked stale/inactive" in reg_res.error_reason

    # Two-stage resolver falls back to search
    modern_hit = make_search_item(
        url="https://docs.stripe.com/api/payment_intents/capture",
        title="Capture a PaymentIntent",
        relevance_score=0.88,
    )
    mock_search = AsyncMock(return_value=make_search_response("charges.legacy_capture", [modern_hit]))

    res = await resolve_documentation_target_async(
        query="charges.legacy_capture",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is True
    assert res.canonical_url == "https://docs.stripe.com/api/payment_intents/capture"
    assert res.strategy == "search_fallback"
    mock_search.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Invalid Mappings & Security Validation
# ---------------------------------------------------------------------------

def test_invalid_mapping_rejected_by_registry_validator() -> None:
    """Mapping with unapproved host or non-official prefix is rejected by validator."""
    source = get_approved_source("stripe")
    assert source is not None

    # Host not in approved list
    bad_host_mapping = ApiSymbolMapping(
        symbol="custom.bad_host",
        canonical_url="https://evil-stripe-docs.com/api/charges",
    )
    is_valid, err = validate_registry_mapping(bad_host_mapping, source)
    assert is_valid is False
    assert "failed security validation" in err

    # Host approved but unapproved prefix
    bad_prefix_mapping = ApiSymbolMapping(
        symbol="custom.bad_prefix",
        canonical_url="https://docs.stripe.com/internal-admin/secret",
    )
    is_valid, err = validate_registry_mapping(bad_prefix_mapping, source)
    assert is_valid is False
    assert "does not start with an approved prefix" in err


# ---------------------------------------------------------------------------
# 6. Irrelevant & Malicious Search Results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_irrelevant_and_unapproved_search_results_rejected() -> None:
    """Search results with unapproved external domains or SSRF targets are rejected."""
    bad_hit1 = make_search_item(
        url="https://stackoverflow.com/questions/12345/stripe-error",
        title="StackOverflow Discussion",
        relevance_score=0.99,
        is_approved_domain=False,
    )
    bad_hit2 = make_search_item(
        url="http://169.254.169.254/latest/meta-data/",
        title="AWS Metadata Service",
        relevance_score=0.95,
        is_approved_domain=False,
    )
    mock_search = AsyncMock(return_value=make_search_response("stripe.Unknown", [bad_hit1, bad_hit2]))

    res = await resolve_documentation_target_async(
        query="stripe.Unknown",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is False
    assert res.canonical_url is None
    assert res.strategy == "unresolved"
    assert "No approved official documentation URLs found" in res.error_reason


# ---------------------------------------------------------------------------
# 7. Generic Landing Page Deprioritization & Avoidance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generic_landing_page_deprioritized_when_specific_page_exists() -> None:
    """When both specific contract page and generic /api overview exist, specific page is preferred."""
    generic_hit = make_search_item(
        url="https://docs.stripe.com/api",
        title="Stripe API Reference",
        relevance_score=0.88,
    )
    specific_hit = make_search_item(
        url="https://docs.stripe.com/api/payment_methods/create",
        title="Create a PaymentMethod",
        relevance_score=0.84,
    )
    mock_search = AsyncMock(return_value=make_search_response("payment_methods", [generic_hit, specific_hit]))

    res = await resolve_documentation_target_async(
        query="stripe.PaymentMethod.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is True
    # The specific contract page is selected despite generic /api having higher raw score
    assert res.canonical_url == "https://docs.stripe.com/api/payment_methods/create"
    assert "payment_methods/create" in res.canonical_url


@pytest.mark.asyncio
async def test_generic_landing_page_avoided_for_undocumented_or_unknown_apis() -> None:
    """Unknown specific API symbol returning only generic /api is NOT falsely mapped."""
    generic_only = make_search_item(
        url="https://docs.stripe.com/api",
        title="Stripe API Reference",
        relevance_score=0.40,
    )
    mock_search = AsyncMock(return_value=make_search_response("stripe.CompletelyFakeService.do_work", [generic_only]))

    res = await resolve_documentation_target_async(
        query="stripe.CompletelyFakeService.do_work",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    # Safe abstention: do not invent mapping to /api
    assert res.is_valid is False
    assert res.canonical_url is None
    assert res.strategy == "unresolved"
    assert "avoiding false mapping" in res.error_reason


# ---------------------------------------------------------------------------
# 8. Search Outages & Failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_failure_network_exception_handled_safely() -> None:
    """Network timeouts or connection exceptions in search fallback do not crash application."""
    mock_search = AsyncMock(side_effect=httpx.ConnectTimeout("Connection to TinyFish timed out"))

    res = await resolve_documentation_target_async(
        query="stripe.UnknownService.create",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is False
    assert res.canonical_url is None
    assert res.strategy == "unresolved"
    assert res.confidence == 0.0
    assert "Documentation search failed" in res.error_reason


@pytest.mark.asyncio
async def test_search_failure_circuit_breaker_or_rate_limit() -> None:
    """When search reports circuit open or rate limit, resolver cleanly abstains."""
    resp = make_search_response(
        query="stripe.Unknown",
        results=[],
        status="unavailable",
        error_message="TinyFish circuit breaker is OPEN",
    )
    mock_search = AsyncMock(return_value=resp)

    res = await resolve_documentation_target_async(
        query="stripe.Unknown",
        target_url=None,
        ecosystem="stripe",
        search_fn=mock_search,
    )

    assert res.is_valid is False
    assert res.strategy == "unresolved"
    assert "circuit breaker is OPEN" in res.error_reason


# ---------------------------------------------------------------------------
# 9. Maintainable Registry Registration
# ---------------------------------------------------------------------------

def test_register_symbol_mapping_maintainability() -> None:
    """New mappings can be registered easily without duplicating validation or alias logic."""
    custom_mapping = ApiSymbolMapping(
        symbol="subscription.create",
        canonical_url="https://docs.stripe.com/api/subscriptions/create",
        aliases=["subscriptions.create", "subscription_item.create"],
        description="Create subscription endpoint",
    )
    success = register_symbol_mapping(custom_mapping, validate=True)
    assert success is True

    # Resolved via primary symbol
    res1 = resolve_from_registry("subscription.create")
    assert res1.is_valid is True
    assert res1.canonical_url == "https://docs.stripe.com/api/subscriptions/create"

    # Resolved via alias
    res2 = resolve_from_registry("subscriptions.create")
    assert res2.is_valid is True
    assert res2.canonical_url == "https://docs.stripe.com/api/subscriptions/create"

    # Legacy dictionary updated
    assert "subscription.create" in STRIPE_SYMBOL_URL_MAP
    assert STRIPE_SYMBOL_URL_MAP["subscription.create"] == "https://docs.stripe.com/api/subscriptions/create"


# ---------------------------------------------------------------------------
# 10. Backward Compatibility & Tuple Unpacking
# ---------------------------------------------------------------------------

def test_backward_compatible_3_tuple_unpacking() -> None:
    """ResolutionResult unpacks as (is_valid, target_url, err) for 100% legacy compatibility."""
    # Synchronous call
    is_valid, target_url, err = resolve_documentation_target(
        query="stripe.Charge.create",
        target_url=None,
    )
    assert is_valid is True
    assert target_url == "https://docs.stripe.com/api/charges/create"
    assert err is None

    # Attribute access on same object
    res = resolve_documentation_target(query="stripe.Charge.create", target_url=None)
    assert res.strategy == "registry_exact"
    assert res.confidence == 1.0
    assert len(res.candidate_urls) == 1


# ---------------------------------------------------------------------------
# 11. Explicit Target URL Validation
# ---------------------------------------------------------------------------

def test_explicit_target_url_security_enforcement() -> None:
    """Explicit URLs are validated against permitted prefixes and SSRF rules."""
    # Valid explicit URL
    is_valid, url, err = resolve_documentation_target(
        query=None,
        target_url="https://docs.stripe.com/api/charges",
    )
    assert is_valid is True
    assert url == "https://docs.stripe.com/api/charges"
    assert err is None

    # Unapproved external host
    is_valid, url, err = resolve_documentation_target(
        query=None,
        target_url="https://malicious-site.com/docs",
    )
    assert is_valid is False
    assert url is None
    assert err is not None

    # SSRF / private IP
    is_valid, url, err = resolve_documentation_target(
        query=None,
        target_url="http://127.0.0.1:8000/docs",
    )
    assert is_valid is False
    assert url is None

