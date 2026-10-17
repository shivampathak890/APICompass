"""Security audit and defense-in-depth test suite for APICompass.

Verifies:
1. HTTP Security Response Headers (nosniff, DENY, strict-origin, CSP, Permissions-Policy).
2. Request Payload Size Limits & Denial of Service Protection (HTTP 413 on oversized payloads).
3. Client Request Rate Limiting & Abuse Controls (HTTP 429 on rate limit exhaustion).
4. SSRF Protection & Destination Allowlisting (prohibition of loopback, private IPs, metadata endpoints).
5. Safe Zero-Execution AST Parsing (no subprocess, eval, or exec).
6. Secret & Key Scrubbing in errors, logs, and prompt reasoning.
7. SQL Injection Immunity across repository queries.
"""

import ast
import json
from unittest.mock import patch
import httpx
import pytest

from app.config import settings
from app.main import create_app, rate_limiter
from app.services.documentation.security import (
    validate_destination_url,
    is_private_or_restricted_ip,
)
from app.services.llm.secret_scrubber import scrub_secrets
from app.services.python_ast_analyzer import analyze_python_source
from app.repositories.scan_repository import ScanRepository


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter state before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


# ---------------------------------------------------------------------------
# 1. HTTP Security Response Headers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_security_headers_present_on_api_responses():
    """Verify that all responses include strict defense-in-depth HTTP security headers."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    headers = resp.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers.get("Permissions-Policy", "")
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# 2. Request Payload Size Limits (Resource Exhaustion Defense)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_oversized_payload_rejected_with_413():
    """Verify that oversized request bodies are rejected with HTTP 413 before in-memory buffering."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    oversized_length = settings.MAX_REQUEST_BODY_BYTES + 5000
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/analyze",
            content=b"{}",
            headers={"Content-Length": str(oversized_length), "Content-Type": "application/json"},
        )

    assert resp.status_code == 413
    data = resp.json()
    assert data["error_code"] == "PAYLOAD_TOO_LARGE"
    assert "exceeds maximum permitted limit" in data["detail"]


# ---------------------------------------------------------------------------
# 3. Rate Limiting & Abuse Controls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limiter_blocks_abusive_client():
    """Verify that exceeding rate limits returns HTTP 429 with Retry-After headers."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    abusive_ip = "198.51.100.99"

    with patch.object(settings, "RATE_LIMIT_ENABLED", True), \
         patch.object(settings, "RATE_LIMIT_PER_MINUTE", 3):

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"X-Forwarded-For": abusive_ip}

            # First 3 requests succeed
            for _ in range(3):
                r = await client.post("/api/v1/identify/python", json={"source": "import stripe"}, headers=headers)
                assert r.status_code in (200, 422)

            # 4th request must be blocked by rate limiter
            blocked = await client.post("/api/v1/identify/python", json={"source": "import stripe"}, headers=headers)
            assert blocked.status_code == 429
            data = blocked.json()
            assert data["error_code"] == "RATE_LIMITED"
            assert "Retry-After" in blocked.headers
            assert blocked.headers.get("X-RateLimit-Remaining") == "0"


# ---------------------------------------------------------------------------
# 4. SSRF Protection & External Destination Allowlisting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("malicious_url,expected_reason", [
    ("http://169.254.169.254/latest/meta-data/", "Insecure scheme"),
    ("https://169.254.169.254/latest/meta-data/", "cloud metadata"),
    ("https://127.0.0.1/api/v1/keys", "private/loopback"),
    ("https://localhost/evil", "resolves to loopback"),
    ("https://127.0.0.1:8000/api/v1/keys", "port 8000 is not permitted"),
    ("https://localhost:5173/evil", "port 5173 is not permitted"),
    ("https://metadata.google.internal/computeMetadata/v1/", "cloud metadata"),
    ("https://admin:secret@docs.stripe.com/api", "Embedded credentials"),
    ("https://docs.stripe.com:8443/api", "Port 8443 is not permitted"),
    ("https://api.stripe.com/v1/charges", "API/dashboard service endpoint"),
    ("https://attacker-domain.com/docs", "not in approved documentation allowlist"),
    ("javascript:alert(1)", "Insecure scheme"),
    ("data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", "Insecure scheme"),
])
def test_ssrf_destination_validation_rejects_malicious_urls(malicious_url, expected_reason):
    """Verify SSRF validator blocks cloud metadata, local IPs, embedded credentials, and arbitrary domains."""
    is_valid, canonical, err = validate_destination_url(malicious_url)
    assert is_valid is False
    assert err is not None
    assert expected_reason.lower() in err.lower()


def test_ssrf_private_ip_detection():
    """Verify is_private_or_restricted_ip detects loopback, private subnets, and link-local addresses."""
    assert is_private_or_restricted_ip("127.0.0.1") is True
    assert is_private_or_restricted_ip("10.0.0.1") is True
    assert is_private_or_restricted_ip("192.168.1.1") is True
    assert is_private_or_restricted_ip("172.16.0.1") is True
    assert is_private_or_restricted_ip("169.254.169.254") is True
    assert is_private_or_restricted_ip("::1") is True
    # Public IPs return False
    assert is_private_or_restricted_ip("8.8.8.8") is False
    assert is_private_or_restricted_ip("1.1.1.1") is False


# ---------------------------------------------------------------------------
# 5. Safe Zero-Execution AST Parsing
# ---------------------------------------------------------------------------
def test_ast_parser_never_executes_submitted_code(tmp_path):
    """Verify that submitted code with malicious side-effects is only statically analyzed."""
    canary_file = tmp_path / "should_not_exist.txt"
    malicious_code = (
        "import os\n"
        f"os.system('touch {canary_file}')\n"
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd')\n"
    )

    result = analyze_python_source(source=malicious_code, filename="malicious.py")

    # AST parsing succeeded statically
    assert result.status == "success"
    assert len(result.calls) >= 1
    # Canary file must NOT be created on disk!
    assert not canary_file.exists(), "Code execution detected! Source was executed instead of statically parsed."


# ---------------------------------------------------------------------------
# 6. Secret & Key Scrubbing in Errors and LLM Integration
# ---------------------------------------------------------------------------
def test_secret_scrubber_redacts_keys_and_tokens():
    """Verify that secret_scrubber detects and redacts Stripe keys, bearer tokens, and credentials."""
    raw_code = (
        "stripe.api_key = '" + "sk" + "_live_51ABCDEF1234567890abcdefghijklmnopqrstuvwxyz'\n"
        "test_key = 'sk_test_51XYZ0987654321fedcba0987654321'\n"
        "auth_header = 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token'\n"
        "secret = 'super_secret_password_123'\n"
    )

    scrubbed, count = scrub_secrets(raw_code)

    assert count >= 4
    assert "sk_live_" not in scrubbed
    assert "sk_test_" not in scrubbed
    assert "super_secret_password_123" not in scrubbed
    assert "[REDACTED_STRIPE_LIVE_KEY]" in scrubbed or "[REDACTED_STRIPE_KEY]" in scrubbed


@pytest.mark.asyncio
async def test_error_handlers_never_leak_secrets():
    """Verify that exception handlers redact sensitive API keys in the error response."""
    from fastapi import HTTPException
    app = create_app()
    raw_secret_key = "sk" + "_live_VERY_SENSITIVE_KEY_12345678901234567890"

    @app.get("/test-secret-error")
    async def secret_error():
        raise HTTPException(status_code=400, detail=f"Bad request with {raw_secret_key}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Custom HTTPException with secret
        resp = await client.get("/test-secret-error")
        assert resp.status_code == 400
        data = resp.json()
        assert raw_secret_key not in json.dumps(data)
        assert "[REDACTED_STRIPE_LIVE_KEY]" in json.dumps(data)

        # 2. Pydantic Request validation error
        resp2 = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import stripe",
                "filename": "test.py",
                "ecosystem": f"stripe_{raw_secret_key}",  # Will fail regex pattern
            },
        )
        assert resp2.status_code == 422
        data2 = resp2.json()
        assert raw_secret_key not in json.dumps(data2)


# ---------------------------------------------------------------------------
# 7. SQL Injection Immunity
# ---------------------------------------------------------------------------
def test_sql_injection_immunity_in_scan_repository(tmp_path):
    """Verify that SQL injection payloads in query parameters are safely parameterized without syntax errors."""
    from app.db import init_db
    test_db = str(tmp_path / "sql_test.db")
    init_db(test_db)

    repo = ScanRepository(db_path_override=test_db)

    # Malicious injection strings
    sql_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE scans; --",
        "\" UNION SELECT 1, 2, 3 --",
        "' AND 1=0 UNION ALL SELECT scan_id FROM scans --",
    ]

    for payload in sql_payloads:
        # Query scans with SQL injection payload in filter fields
        items, count = repo.list_scans(verdict=payload, ecosystem=payload, limit=10)
        assert isinstance(items, list)
        assert count == 0  # Safely parameterized, returns zero matching rows

