"""Automated tests for TinyFish Search API integration in APICompass.

Verifies:
1. Successful search response and normalization
2. Empty search results
3. Malformed JSON / schema responses
4. HTTP errors (500, 502, 503)
5. Timeout handling
6. Authentication failures (401, 403)
7. Rate limit handling (429)
8. Unrelated and suspicious SSRF destinations rejected
9. Mock mode search behavior and separation
10. Missing credentials safe fallback
11. Circuit breaker fast-fail
12. FastApi POST /api/v1/docs/search endpoint
13. Invariant: search snippets cannot verify API contract violations
"""

import httpx
from httpx import AsyncClient, ASGITransport
import pytest
from unittest.mock import patch

from app.main import app
from app.schemas.documentation import (
    DocSearchRequest,
    DocSearchResponse,
    NormalizedEvidence,
    SearchResultItem,
)
from app.services.documentation.circuit_breaker import CircuitBreaker
from app.services.documentation.mock_adapter import TinyFishMockRetriever
from app.services.documentation.retrieval_service import DocumentationRetrievalService
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.quote_verifier import QuoteVerifier


# ==============================================================================
# 1. Successful Live Search & Result Normalization
# ==============================================================================

@pytest.mark.asyncio
async def test_01_successful_live_search_contract() -> None:
    """1. Successful Search response: HTTP 200 with results array normalized and ranked."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")
    query = "stripe.Charge.create"

    synthetic_payload = {
        "query": "stripe charge create",
        "results": [
            {
                "position": 1,
                "site_name": "docs.stripe.com",
                "title": "Create a charge | Stripe API Reference",
                "snippet": "To charge a credit card or other payment source, you create a Charge object. Source is legacy.",
                "url": "https://docs.stripe.com/api/charges/create",
            },
            {
                "position": 2,
                "site_name": "docs.stripe.com",
                "title": "The Charge object | Stripe Docs",
                "snippet": "Overview of the Charge object. Use PaymentIntents instead.",
                "url": "https://docs.stripe.com/api/charges",
            },
        ],
        "total_results": 2,
        "page": 0,
    }

    mock_resp = httpx.Response(
        200,
        json=synthetic_payload,
        request=httpx.Request("GET", retriever.search_base_url),
    )

    with patch.object(httpx.AsyncClient, "get", return_value=mock_resp) as mock_get:
        response = await retriever.search(query=query, limit=5)

        # Assert request contract
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["X-API-Key"] == "tf-test-valid-key"
        assert kwargs["params"]["include_domains"] == "docs.stripe.com,stripe.com"
        assert "charge" in kwargs["params"]["query"]

        # Assert response normalization
        assert response.status == "success"
        assert response.is_mock is False
        assert response.provider == "tinyfish_live"
        assert response.total_results == 2
        assert len(response.results) == 2

        # Assert item fields preserved
        top_hit = response.results[0]
        assert isinstance(top_hit, SearchResultItem)
        assert top_hit.url == "https://docs.stripe.com/api/charges/create"
        assert top_hit.canonical_url == "https://docs.stripe.com/api/charges/create"
        assert top_hit.title == "Create a charge | Stripe API Reference"
        assert "legacy" in (top_hit.snippet or "")
        assert top_hit.site_name == "docs.stripe.com"
        assert top_hit.position == 1
        assert top_hit.relevance_score > 0.50
        assert top_hit.is_approved_domain is True


# ==============================================================================
# 2. Empty Results
# ==============================================================================

@pytest.mark.asyncio
async def test_02_empty_search_results() -> None:
    """2. Empty results: HTTP 200 with empty results list maps to status='empty'."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")
    mock_resp = httpx.Response(
        200,
        json={"query": "unknown_symbol", "results": [], "total_results": 0},
        request=httpx.Request("GET", retriever.search_base_url),
    )

    with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
        response = await retriever.search("unknown_symbol")
        assert response.status == "empty"
        assert response.total_results == 0
        assert response.results == []


# ==============================================================================
# 3. Malformed Response
# ==============================================================================

@pytest.mark.asyncio
async def test_03_malformed_response_json() -> None:
    """3. Malformed JSON or unexpected schema maps to INVALID_RESPONSE_JSON."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    # Non-JSON HTML response
    mock_resp = httpx.Response(
        200,
        text="<html><body>Bad Gateway</body></html>",
        headers={"Content-Type": "text/html"},
        request=httpx.Request("GET", retriever.search_base_url),
    )

    with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
        response = await retriever.search("stripe.Charge.create")
        assert response.status == "unavailable"
        assert response.error_code == "INVALID_RESPONSE_JSON"
        assert response.results == []


# ==============================================================================
# 4. HTTP Error Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_04_http_error_handling() -> None:
    """4. HTTP 500, 502, 503 errors map to PROVIDER_ERROR without crashing."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    for status_code in [500, 502, 503]:
        mock_resp = httpx.Response(
            status_code,
            text=f"Server Error {status_code}",
            request=httpx.Request("GET", retriever.search_base_url),
        )
        with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
            response = await retriever.search("stripe.PaymentIntent.create")
            assert response.status == "unavailable"
            assert response.error_code == "PROVIDER_ERROR"
            assert response.results == []


# ==============================================================================
# 5. Timeout Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_05_timeout_handling() -> None:
    """5. Network timeouts map to TIMEOUT error code."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    with patch.object(httpx.AsyncClient, "get", side_effect=httpx.TimeoutException("Read timed out")):
        response = await retriever.search("stripe.Customer.create")
        assert response.status == "unavailable"
        assert response.error_code == "TIMEOUT"
        assert "timed out" in (response.error_message or "").lower()


# ==============================================================================
# 6. Authentication Failure
# ==============================================================================

@pytest.mark.asyncio
async def test_06_authentication_failure() -> None:
    """6. HTTP 401/403 maps to AUTHENTICATION_FAILED without logging keys."""
    secret_key = "tf-secret-canary-key-999"
    retriever = TinyFishLiveRetriever(api_key=secret_key)

    for status_code in [401, 403]:
        mock_resp = httpx.Response(
            status_code,
            json={"error": "Unauthorized"},
            request=httpx.Request("GET", retriever.search_base_url),
        )
        with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
            response = await retriever.search("stripe.Charge.create")
            assert response.status == "auth_failed"
            assert response.error_code == "AUTHENTICATION_FAILED"
            assert secret_key not in (response.error_message or "")


# ==============================================================================
# 7. Rate Limit Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_07_rate_limit_handling() -> None:
    """7. HTTP 429 maps to RATE_LIMITED status."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")
    mock_resp = httpx.Response(
        429,
        json={"error": "Rate limit exceeded (30 requests/minute)"},
        request=httpx.Request("GET", retriever.search_base_url),
    )

    with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
        response = await retriever.search("stripe.Charge.create")
        assert response.status == "rate_limited"
        assert response.error_code == "RATE_LIMITED"


# ==============================================================================
# 8. Unrelated and Suspicious Destinations Rejected (SSRF Protection)
# ==============================================================================

@pytest.mark.asyncio
async def test_08_unrelated_and_suspicious_urls_rejected() -> None:
    """8. Results with unapproved external domains or private IP destinations are rejected."""
    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    synthetic_payload = {
        "results": [
            {
                "position": 1,
                "title": "Cloud Metadata",
                "snippet": "Internal metadata service",
                "url": "http://169.254.169.254/latest/meta-data",  # Malicious SSRF target
            },
            {
                "position": 2,
                "title": "Attacker Docs",
                "snippet": "Phishing docs",
                "url": "https://evil-attacker.com/stripe",  # Unapproved domain
            },
            {
                "position": 3,
                "title": "Legitimate Stripe Docs",
                "snippet": "Legitimate API docs",
                "url": "https://docs.stripe.com/api/refunds/create",  # Approved
            },
        ],
    }

    mock_resp = httpx.Response(
        200,
        json=synthetic_payload,
        request=httpx.Request("GET", retriever.search_base_url),
    )

    with patch.object(httpx.AsyncClient, "get", return_value=mock_resp):
        response = await retriever.search("stripe.Refund.create")
        assert response.status == "success"
        # Only the legitimate approved Stripe doc should survive
        assert len(response.results) == 1
        assert response.results[0].canonical_url == "https://docs.stripe.com/api/refunds/create"
        assert response.results[0].is_approved_domain is True


# ==============================================================================
# 9. Mock Mode Search & Clean Separation
# ==============================================================================

@pytest.mark.asyncio
async def test_09_mock_mode_search() -> None:
    """9. Mock mode search operates offline, returns verified fixtures, and marks is_mock=True."""
    mock_retriever = TinyFishMockRetriever()
    response = await mock_retriever.search("PaymentIntent.create")

    assert response.is_mock is True
    assert response.provider == "tinyfish_mock"
    assert response.status == "success"
    assert response.total_results > 0

    top_result = response.results[0]
    assert "payment_intent" in top_result.url or "payment_intents" in top_result.url
    assert top_result.site_name == "docs.stripe.com"
    assert top_result.is_approved_domain is True
    assert "Search results provide candidate documentation URLs only" in response.disclaimer


# ==============================================================================
# 10. Missing Credentials Fails Safely
# ==============================================================================

@pytest.mark.asyncio
async def test_10_missing_credentials_fails_safely() -> None:
    """10. TinyFishLiveRetriever with None or whitespace API key fails safely without network."""
    retriever = TinyFishLiveRetriever(api_key="   ")
    response = await retriever.search("stripe.Charge.create")

    assert response.status == "unavailable"
    assert response.error_code == "CREDENTIALS_MISSING"
    assert response.results == []


# ==============================================================================
# 11. Circuit Breaker Fast-Fail
# ==============================================================================

@pytest.mark.asyncio
async def test_11_circuit_breaker_open_rejects_search() -> None:
    """11. When circuit breaker is OPEN, search fast-fails immediately."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=60.0)
    cb.record_failure()
    assert cb.state == "open"

    retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key", circuit_breaker=cb)
    response = await retriever.search("stripe.Charge.create")

    assert response.status == "unavailable"
    assert response.error_code == "CIRCUIT_OPEN"


# ==============================================================================
# 12. FastApi POST /api/v1/docs/search Endpoint
# ==============================================================================

@pytest.mark.asyncio
async def test_12_docs_search_api_endpoint(client: AsyncClient) -> None:
    """12. POST /api/v1/docs/search endpoint validates schema and returns candidate hits."""
    response = await client.post(
        "/api/v1/docs/search",
        json={"query": "Charge.create", "ecosystem": "stripe", "limit": 3, "force_mock": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["is_mock"] is True
    assert data["provider"] == "tinyfish_mock"
    assert len(data["results"]) >= 1
    assert "Search results provide candidate documentation URLs only" in data["disclaimer"]


# ==============================================================================
# 13. Search Snippet Cannot Verify Contract Invariant
# ==============================================================================

def test_13_search_snippet_cannot_verify_contract_invariant() -> None:
    """13. Invariant: Search result snippets cannot produce verified quotes without full fetched content."""
    snippet_item = SearchResultItem(
        url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe Docs",
        snippet="The source parameter is legacy.",
        site_name="docs.stripe.com",
        position=1,
        relevance_score=0.85,
        is_approved_domain=True,
    )

    # Invariant: SearchResultItem cannot be treated as verified NormalizedEvidence
    # Attempting to verify quote against evidence without full content fails
    dummy_evidence = NormalizedEvidence(
        evidence_id="ev_search_preview",
        ecosystem="stripe",
        package="stripe",
        source_url=snippet_item.url,
        canonical_url=snippet_item.canonical_url,
        title=snippet_item.title,
        content_excerpt="",  # Full document not fetched
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="unavailable",
        is_mock=False,
        source_trust="official",
    )

    verifier = QuoteVerifier()
    res = verifier.verify_quote(
        proposed_quote="The source parameter is legacy.",
        evidence=dummy_evidence,
        expected_url=snippet_item.canonical_url,
    )

    assert res.is_verified is False
    assert res.match_method == "none"

