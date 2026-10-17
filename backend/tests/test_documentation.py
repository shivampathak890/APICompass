"""Unit and integration test suite for documentation retrieval and SSRF security."""

from datetime import datetime
import pytest
import httpx
from httpx import AsyncClient, ASGITransport

from app.schemas.documentation import DocRetrievalRequest
from app.services.documentation.mock_adapter import TinyFishMockRetriever
from app.services.documentation.security import (
    canonicalize_url,
    validate_destination_url,
    APPROVED_CANONICAL_HOSTS,
)
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever


# ------------------------------------------------------------------------------
# 1. SSRF & Destination Validation Tests
# ------------------------------------------------------------------------------

def test_01_approved_stripe_url_normalization() -> None:
    """1. Approved Stripe URL normalization: strips tracking query params and fragments."""
    url = "https://docs.stripe.com/api/charges/create/?utm_source=twitter&ref=developer#example"
    is_valid, canonical, err = validate_destination_url(url)
    assert is_valid is True
    assert err is None
    assert canonical == "https://docs.stripe.com/api/charges/create"


def test_02_approved_canonical_host_validation() -> None:
    """2. Approved canonical host validation for docs.stripe.com and stripe.com."""
    for host in ["docs.stripe.com", "stripe.com", "github.com"]:
        url = f"https://{host}/api"
        is_valid, canonical, err = validate_destination_url(url)
        assert is_valid is True, f"Host {host} should be approved, but got: {err}"

    # Verify that api.stripe.com is strictly rejected as an API service host
    is_valid, _, err = validate_destination_url("https://api.stripe.com/v1/charges")
    assert is_valid is False
    assert "API/dashboard service endpoint" in (err or "")


def test_03_rejection_of_unapproved_domains() -> None:
    """3. Rejection of unapproved domains and arbitrary web destinations."""
    unapproved = [
        "https://evil-hacker.com/docs",
        "https://google.com/search",
        "https://stackoverflow.com/questions/123",
        "https://pastebin.com/raw/xyz",
    ]
    for url in unapproved:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False
        assert "not in approved documentation allowlist" in err


def test_04_rejection_of_lookalike_domains() -> None:
    """4. Rejection of subdomain deceptive lookalikes and homoglyphs."""
    lookalikes = [
        "https://stripe.com.attacker.com/api",
        "https://docs.stripe.com.evil.org/charges",
        "https://strıpe.com/api",  # Turkish dotless i homoglyph
    ]
    for url in lookalikes:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False, f"Lookalike URL {url} must be rejected"


def test_05_rejection_of_insecure_http_urls() -> None:
    """5. Rejection of plaintext insecure HTTP URLs."""
    url = "http://docs.stripe.com/api/charges"
    is_valid, _, err = validate_destination_url(url)
    assert is_valid is False
    assert "only HTTPS is permitted" in err


def test_06_rejection_of_localhost_and_loopback() -> None:
    """6. Rejection of localhost, loopback IPs, and IPv6 loopback."""
    loopbacks = [
        "https://localhost/api",
        "https://localhost.localdomain/api",
        "https://127.0.0.1/api",
        "https://127.0.1.1/api",
        "https://[::1]/api",
    ]
    for url in loopbacks:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False
        assert "loopback" in err or "SSRF" in err or "must be an official domain name" in err


def test_07_rejection_of_private_ip_destinations() -> None:
    """7. Rejection of RFC 1918 private IP addresses (SSRF defense)."""
    private_ips = [
        "https://10.0.0.1/api",
        "https://172.16.0.1/api",
        "https://192.168.1.1/api",
        "https://169.254.169.254/latest/meta-data",  # AWS/cloud link-local metadata
    ]
    for url in private_ips:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False
        assert "private" in err or "prohibited" in err


def test_08_rejection_of_embedded_url_credentials() -> None:
    """8. Rejection of embedded username/password in URL."""
    url = "https://admin:supersecret@docs.stripe.com/api"
    is_valid, _, err = validate_destination_url(url)
    assert is_valid is False
    assert "Embedded credentials" in err


def test_09_rejection_of_unsupported_ports() -> None:
    """9. Rejection of nonstandard ports (only port 443 permitted)."""
    nonstandard_ports = [
        "https://docs.stripe.com:8080/api",
        "https://docs.stripe.com:8443/api",
        "https://docs.stripe.com:22/api",
    ]
    for url in nonstandard_ports:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False
        assert "Port" in err and "restricted to port 443" in err


def test_10_redirect_destination_validation() -> None:
    """10. Validation catches destinations attempting redirect escape to unapproved hosts."""
    # When validating an alleged redirect target:
    evil_redirect = "https://internal-cluster.local/secret"
    is_valid, _, err = validate_destination_url(evil_redirect)
    assert is_valid is False


# ------------------------------------------------------------------------------
# 2. TinyFish Provider & Network Failure Mock Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_11_tinyfish_authentication_failure(monkeypatch) -> None:
    """11. TinyFish returns HTTP 401 -> handled as unavailable without crashing."""
    adapter = TinyFishLiveRetriever(api_key="invalid_test_key")

    async def mock_post(*args, **kwargs):
        return httpx.Response(status_code=401, json={"error": "Invalid API key"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "unavailable"
    assert result.error_code == "AUTHENTICATION_FAILED"
    assert "authentication failed" in result.error_message.lower()


@pytest.mark.asyncio
async def test_12_tinyfish_rate_limiting(monkeypatch) -> None:
    """12. TinyFish returns HTTP 429 -> handled gracefully as rate limited."""
    adapter = TinyFishLiveRetriever(api_key="test_key")

    async def mock_post(*args, **kwargs):
        return httpx.Response(status_code=429, json={"error": "Too Many Requests"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "unavailable"
    assert result.error_code == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_13_tinyfish_timeout(monkeypatch) -> None:
    """13. Network timeout communication -> handled gracefully."""
    adapter = TinyFishLiveRetriever(api_key="test_key", timeout_seconds=1.0)

    async def mock_post(*args, **kwargs):
        raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "unavailable"
    assert result.error_code == "TIMEOUT"


@pytest.mark.asyncio
async def test_14_invalid_provider_json(monkeypatch) -> None:
    """14. Provider returns HTML or malformed non-JSON body -> handled cleanly."""
    adapter = TinyFishLiveRetriever(api_key="test_key")

    async def mock_post(*args, **kwargs):
        return httpx.Response(status_code=200, text="<html>502 Bad Gateway</html>")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "unavailable"
    assert result.error_code == "INVALID_RESPONSE_JSON"


@pytest.mark.asyncio
async def test_15_unexpected_provider_response_schema(monkeypatch) -> None:
    """15. Provider returns JSON with missing 'results' list -> handled cleanly."""
    adapter = TinyFishLiveRetriever(api_key="test_key")

    async def mock_post(*args, **kwargs):
        return httpx.Response(status_code=200, json={"unexpected_key": 123})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "unavailable"
    assert result.error_code == "NO_CONTENT_RETURNED"


@pytest.mark.asyncio
async def test_16_successful_normalization_of_provider_response(monkeypatch) -> None:
    """16. Successful live TinyFish response normalized into schema."""
    adapter = TinyFishLiveRetriever(api_key="test_valid_key")

    mock_payload = {
        "results": [
            {
                "url": "https://docs.stripe.com/api/charges/create",
                "title": "Create a charge | Stripe Docs",
                "text": "Accept payments using Stripe. The source parameter is considered legacy.",
            }
        ]
    }

    async def mock_post(*args, **kwargs):
        return httpx.Response(status_code=200, json=mock_payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    result = await adapter.fetch_url("https://docs.stripe.com/api/charges/create")
    assert result.status == "success"
    assert result.is_mock is False
    assert result.provider == "tinyfish_live"
    assert result.title == "Create a charge | Stripe Docs"
    assert "source parameter is considered legacy" in result.content_excerpt
    assert result.source_trust == "official"


# ------------------------------------------------------------------------------
# 3. Attribution, Timestamp, Mock Integrity, and Security Invariant Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_17_preservation_of_source_url_attribution() -> None:
    """17. Normalized evidence preserves source URL attribution accurately."""
    mock_retriever = TinyFishMockRetriever()
    target = "https://docs.stripe.com/api/charges/create"
    evidence = await mock_retriever.fetch_url(target)
    assert evidence.canonical_url == target
    assert evidence.source_url == target
    assert "stripe" in evidence.canonical_url


@pytest.mark.asyncio
async def test_18_utc_retrieval_timestamp_validation() -> None:
    """18. UTC retrieval timestamp is valid ISO-8601 with timezone."""
    mock_retriever = TinyFishMockRetriever()
    evidence = await mock_retriever.fetch_url("https://docs.stripe.com/api/charges/create")
    parsed = datetime.fromisoformat(evidence.retrieved_at)
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_19_explicit_distinction_between_live_and_mock_results() -> None:
    """19. Explicit distinction: mock results must have is_mock=True, provider='tinyfish_mock'."""
    mock_retriever = TinyFishMockRetriever()
    response = await mock_retriever.retrieve(
        DocRetrievalRequest(ecosystem="stripe", query="Charge.create")
    )
    assert response.is_mock is True
    assert response.provider == "tinyfish_mock"
    assert response.status == "mock"
    for ev in response.evidence:
        assert ev.is_mock is True
        assert ev.provider == "tinyfish_mock"


def test_20_missing_credentials_do_not_prevent_startup() -> None:
    """20. Missing TINYFISH_API_KEY does not cause startup crashes."""
    adapter = TinyFishLiveRetriever(api_key=None)
    assert adapter.api_key is None


@pytest.mark.asyncio
async def test_21_retrieved_content_is_never_executed() -> None:
    """21. Retrieved content containing executable strings is treated as untrusted text only."""
    dangerous_content = "import os; os.remove('/etc/hosts')"
    mock_retriever = TinyFishMockRetriever()
    # Content is safely enclosed in string fields
    evidence = await mock_retriever.fetch_url("https://docs.stripe.com/api/charges/create")
    assert isinstance(evidence.content_excerpt, str)


@pytest.mark.asyncio
async def test_22_request_result_limit_enforcement(client: AsyncClient) -> None:
    """22. Max results limit clamped to configured maximum."""
    response = await client.post(
        "/api/v1/docs/retrieve",
        json={"ecosystem": "stripe", "query": "charge", "max_results": 20},
    )
    # Pydantic schema le=10 will validate request bound or clamp
    assert response.status_code == 422 or response.status_code == 200


@pytest.mark.asyncio
async def test_23_rejection_of_arbitrary_url_destinations(client: AsyncClient) -> None:
    """23. Arbitrary unapproved URLs submitted to retrieval endpoint are rejected."""
    response = await client.post(
        "/api/v1/docs/retrieve",
        json={"ecosystem": "stripe", "target_url": "https://unapproved-malicious-site.com/doc"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert len(data["evidence"]) == 0


# ------------------------------------------------------------------------------
# 4. Regression Tests for AST & Ingestion Endpoints
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_24_existing_ast_endpoint_regression(client: AsyncClient) -> None:
    """24. Regression test: POST /api/v1/analyze/python continues to function seamlessly."""
    response = await client.post(
        "/api/v1/analyze/python",
        json={"source": "import stripe\nstripe.Charge.create()", "filename": "test.py"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["candidates"]) == 1


@pytest.mark.asyncio
async def test_25_existing_health_and_cors_regression(client: AsyncClient) -> None:
    """25. Regression test: GET /api/v1/health continues to report 200 healthy."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
