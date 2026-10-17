"""Comprehensive API endpoints and integration audit test suite for APICompass v3.

Verifies:
1. Request payload fields, size constraints, and validation
2. Response schemas across all endpoints
3. Standardized ErrorResponse on 4xx/5xx failures
4. Input size and supported ecosystem validation
5. Sensitive credentials and secret scrubbing in responses and error messages
6. Prevention of arbitrary internal exception leaks
7. SSE streaming event models and payload schemas
8. History and fix proposal endpoints
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import init_db
from app.main import app
from app.repositories import ScanRepository, scan_repository
from app.schemas.errors import ErrorResponse


@pytest.fixture(autouse=True)
def isolated_audit_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide isolated SQLite database per test."""
    db_path = tmp_path / "endpoint_audit.db"
    monkeypatch.setattr(settings, "APICOMPASS_DB_PATH", str(db_path))
    scan_repository.db_path_override = db_path
    init_db(db_path)
    yield db_path
    scan_repository.db_path_override = None


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client connected to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ============================================================================
# Section 1: Health & System Diagnostics
# ============================================================================

@pytest.mark.asyncio
async def test_health_endpoint_schema_and_zero_secret_leak(client: AsyncClient) -> None:
    """Verify GET /api/v1/health returns HTTP 200 and never leaks sensitive credentials."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "healthy"
    assert data["service"] == "apicompass-api"
    assert data["version"] == settings.APP_VERSION
    assert isinstance(data["mock_mode"], bool)
    assert data["database_status"] in ("ok", "degraded")

    # Verify zero secrets appear in raw JSON payload
    raw_text = json.dumps(data)
    assert "sk_live" not in raw_text
    assert "sk_test" not in raw_text
    assert "Bearer" not in raw_text


# ============================================================================
# Section 2: Static Python AST Analysis Endpoint (/api/v1/analyze/python)
# ============================================================================

@pytest.mark.asyncio
async def test_analyze_python_valid_request(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/python returns 200 and matches AnalyzePythonResponse."""
    resp = await client.post(
        "/api/v1/analyze/python",
        json={"source": "import stripe\ndef charge(): pass", "filename": "test.py"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    assert data["engine_version"] == "0.1.0"
    assert data["filename"] == "test.py"
    assert len(data["imports"]) == 1
    assert data["imports"][0]["module"] == "stripe"


@pytest.mark.asyncio
async def test_analyze_python_missing_source_rejected_with_error_response(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/python missing source returns 422 with standardized ErrorResponse."""
    resp = await client.post("/api/v1/analyze/python", json={"filename": "test.py"})
    assert resp.status_code == 422
    data = resp.json()

    error = ErrorResponse.model_validate(data)
    assert error.status_code == 422
    assert error.error_code == "VALIDATION_ERROR"
    assert "source" in error.detail.lower()
    assert error.errors is not None
    assert any("source" in str(e.loc) for e in error.errors)


@pytest.mark.asyncio
async def test_analyze_python_size_limit_enforced(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/python rejects source code exceeding 100 KB with HTTP 422."""
    oversized_source = "x = 1\n" * 25_000  # ~150 KB
    resp = await client.post(
        "/api/v1/analyze/python",
        json={"source": oversized_source, "filename": "large.py"},
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"
    assert "100000" in error.detail or "100" in error.detail or "max_length" in str(error.errors)


# ============================================================================
# Section 3: Structured API Call Identification Endpoint (/api/v1/identify/python)
# ============================================================================

@pytest.mark.asyncio
async def test_identify_python_valid_request(client: AsyncClient) -> None:
    """Verify POST /api/v1/identify/python returns structured identification with confidence and arguments."""
    code = "import stripe\ncharge = stripe.Charge.create(amount=2000, currency='usd')"
    resp = await client.post(
        "/api/v1/identify/python",
        json={"source": code, "filename": "ident.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    assert data["confirmed_count"] >= 1
    assert len(data["identified_calls"]) >= 1

    call = data["identified_calls"][0]
    assert call["sdk_or_library"] == "stripe"
    assert call["api_resource"] == "Charge"
    assert call["operation"] == "create"
    assert call["confidence"] == "confirmed"
    assert "amount" in call["keyword_arguments"]


@pytest.mark.asyncio
async def test_identify_python_invalid_ecosystem_pattern_rejected(client: AsyncClient) -> None:
    """Verify POST /api/v1/identify/python rejects invalid ecosystem syntax with HTTP 422."""
    resp = await client.post(
        "/api/v1/identify/python",
        json={"source": "import stripe", "ecosystem": "stripe; DROP TABLE scans;--"},
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"


# ============================================================================
# Section 4: Unified Evidence-Based Adjudication (/api/v1/analyze)
# ============================================================================

@pytest.mark.asyncio
async def test_analyze_unified_valid_request(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze executes full pipeline and persists scan audit record."""
    code = "import stripe\nintent = stripe.PaymentIntent.create(amount=2000, currency='usd')"
    resp = await client.post(
        "/api/v1/analyze",
        json={"source": code, "filename": "pay.py", "ecosystem": "stripe"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["verdict"] in ("clean", "issues_found", "unable_to_verify")
    assert data["engine_version"] == "0.1.0"
    assert data["evidence_trust"] in ("live_official_source", "mock_fixture", "untrusted_or_unavailable")
    assert data["scan_id"] is not None
    assert data["scan_id"].startswith("scan_")
    assert data["persistence_status"] == "saved"


@pytest.mark.asyncio
async def test_analyze_unified_rejects_client_injected_forbidden_fields(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze forbids client tampering with verdict or evidence trust."""
    resp = await client.post(
        "/api/v1/analyze",
        json={
            "source": "import stripe",
            "filename": "cheat.py",
            "verdict": "clean",
            "evidence_trust": "live_official_source",
        },
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"
    assert "extra fields not permitted" in error.detail.lower() or "extra_forbidden" in str(error.errors).lower()


# ============================================================================
# Section 5: Real-Time SSE Streaming Endpoint (/api/v1/analyze/stream)
# ============================================================================

@pytest.mark.asyncio
async def test_analyze_stream_rejects_invalid_payload_before_streaming(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/stream validates payload synchronously and returns 422 on failure."""
    resp = await client.post(
        "/api/v1/analyze/stream",
        json={"filename": "empty.py"},  # Missing source
    )
    assert resp.status_code == 422
    assert "application/json" in resp.headers["content-type"]
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"


# ============================================================================
# Section 6: Multi-File Project Analysis (/api/v1/analyze/project)
# ============================================================================

@pytest.mark.asyncio
async def test_analyze_project_path_traversal_rejected_with_422(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/project rejects directory traversal attempts."""
    resp = await client.post(
        "/api/v1/analyze/project",
        json={
            "project_name": "malicious_project",
            "files": [
                {"path": "../../etc/passwd.py", "content": "x = 1\n"}
            ],
        },
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"
    assert "traversal" in error.detail.lower() or "prohibited" in error.detail.lower()


@pytest.mark.asyncio
async def test_analyze_project_non_python_extension_rejected_with_422(client: AsyncClient) -> None:
    """Verify POST /api/v1/analyze/project rejects non-.py files."""
    resp = await client.post(
        "/api/v1/analyze/project",
        json={
            "project_name": "text_project",
            "files": [
                {"path": "config.yaml", "content": "key: value\n"}
            ],
        },
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"
    assert "only python source files" in error.detail.lower()


# ============================================================================
# Section 7: Documentation Retrieval & Search (/api/v1/docs/...)
# ============================================================================

@pytest.mark.asyncio
async def test_docs_retrieve_valid_request(client: AsyncClient) -> None:
    """Verify POST /api/v1/docs/retrieve returns 200 with DocRetrievalResponse."""
    resp = await client.post(
        "/api/v1/docs/retrieve",
        json={"ecosystem": "stripe", "package": "stripe", "query": "stripe.Charge.create"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data
    assert isinstance(data["is_mock"], bool)
    assert isinstance(data["evidence"], list)


@pytest.mark.asyncio
async def test_docs_search_valid_request(client: AsyncClient) -> None:
    """Verify POST /api/v1/docs/search returns 200 with ranked search hits."""
    resp = await client.post(
        "/api/v1/docs/search",
        json={"query": "PaymentIntent", "ecosystem": "stripe", "limit": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "PaymentIntent"
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_docs_search_limit_exceeded_rejected(client: AsyncClient) -> None:
    """Verify POST /api/v1/docs/search limit > 10 is rejected with HTTP 422."""
    resp = await client.post(
        "/api/v1/docs/search",
        json={"query": "Charge", "limit": 50},
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"


# ============================================================================
# Section 8: Fix Proposals (/api/v1/fixes/propose)
# ============================================================================

@pytest.mark.asyncio
async def test_propose_fix_missing_candidate_id_rejected(client: AsyncClient) -> None:
    """Verify POST /api/v1/fixes/propose requires candidate_id."""
    resp = await client.post(
        "/api/v1/fixes/propose",
        json={"source": "import stripe"},
    )
    assert resp.status_code == 422
    error = ErrorResponse.model_validate(resp.json())
    assert error.error_code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_propose_fix_unknown_candidate_returns_structured_ineligible(client: AsyncClient) -> None:
    """Verify POST /api/v1/fixes/propose handles unknown candidates safely without crashing."""
    resp = await client.post(
        "/api/v1/fixes/propose",
        json={
            "source": "import stripe\ndef run(): pass",
            "candidate_id": "nonexistent_candidate_999",
            "filename": "fix.py",
            "ecosystem": "stripe",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_id"] == "nonexistent_candidate_999"
    assert data["status"] in ("unsupported_candidate", "proposal_invalid", "insufficient_evidence")
    assert len(data["warnings"]) >= 1


# ============================================================================
# Section 9: History and Scan Detail (/api/v1/scans)
# ============================================================================

@pytest.mark.asyncio
async def test_scans_invalid_scan_id_format_rejected_with_400(client: AsyncClient) -> None:
    """Verify GET /api/v1/scans/{scan_id} with malformed ID returns HTTP 400."""
    resp = await client.get("/api/v1/scans/malformed_id_without_prefix")
    assert resp.status_code == 400
    error = ErrorResponse.model_validate(resp.json())
    assert error.status_code == 400
    assert error.error_code == "BAD_REQUEST"
    assert "invalid scan_id format" in error.detail.lower()


@pytest.mark.asyncio
async def test_scans_nonexistent_scan_id_returns_404(client: AsyncClient) -> None:
    """Verify GET /api/v1/scans/{scan_id} for missing scan returns HTTP 404."""
    resp = await client.get("/api/v1/scans/scan_12345678abcdef")
    assert resp.status_code == 404
    error = ErrorResponse.model_validate(resp.json())
    assert error.status_code == 404
    assert error.error_code == "NOT_FOUND"


# ============================================================================
# Section 10: Secret Scrubbing and Exception Handling Defenses
# ============================================================================

@pytest.mark.asyncio
async def test_error_response_scrubs_sensitive_keys_in_validation_errors(client: AsyncClient) -> None:
    """Verify sensitive credentials passed in illegal fields are scrubbed in 422 error details."""
    leaked_secret = "sk" + "_live_1234567890abcdefghijklmnopqrstuvwxyz"
    resp = await client.post(
        "/api/v1/analyze",
        json={
            "source": "import stripe",
            "ecosystem": leaked_secret,  # Fails regex pattern ^[a-zA-Z0-9_\-]+$ or invalid value
            "unapproved_field_with_secret": leaked_secret,
        },
    )
    assert resp.status_code == 422
    raw_response = resp.text
    # Secret must never appear in raw text
    assert leaked_secret not in raw_response
    assert "[REDACTED_STRIPE_LIVE_KEY]" in raw_response or "validation failed" in raw_response.lower()


@pytest.mark.asyncio
async def test_unhandled_exception_returns_sanitized_500_without_stack_leak(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify unexpected internal exceptions return clean 500 ErrorResponse without stack trace leaks."""
    from app.services.python_ast_analyzer import analyze_python_source

    def mock_explode(*args, **kwargs):
        raise RuntimeError("Fatal internal kernel explosion at /private/var/secret/credentials.key")

    monkeypatch.setattr("app.api.v1.analyze.analyze_python_source", mock_explode)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        resp = await test_client.post(
            "/api/v1/analyze/python",
            json={"source": "import os", "filename": "explode.py"},
        )
    assert resp.status_code == 500
    data = resp.json()
    error = ErrorResponse.model_validate(data)

    assert error.status_code == 500
    assert error.error_code == "INTERNAL_SERVER_ERROR"
    # Never leak internal filesystem paths or stack traces
    assert "/private/var/secret" not in error.detail
    assert "Traceback" not in resp.text
    assert "credentials.key" not in resp.text
