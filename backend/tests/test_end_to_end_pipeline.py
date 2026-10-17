"""Comprehensive End-to-End Integration Test Suite for APICompass.

Verifies the complete 10-step pipeline workflow:
1. Receive Python source code.
2. Parse the code safely without executing it (AST analysis only).
3. Identify supported Stripe API calls.
4. Resolve relevant documentation through the Two-Stage Resolver (Registry fast-path or TinyFish Search).
5. Fetch the selected documentation via TinyFish Fetch API (or offline fixtures in mock mode).
6. Extract relevant contract information (headings, parameters, required fields, deprecation notices, SHA-256).
7. Compare detected calls against the extracted contract.
8. Produce proposed findings.
9. Verify each finding against source evidence using verbatim quote verification and hash verification.
10. Return findings, source links, and explicit verification states.

Enforces all system invariants:
- A live retrieval failure must not be reported as a verified issue.
- Mock evidence must never be presented as live official evidence.
- Unsupported or ambiguous APIs must be reported honestly.
- Findings must preserve all evidence needed by the frontend.
- API contracts and schemas remain backward-compatible.
- Safe AST parsing guarantees zero user code execution.
- LLM suggestions are strictly advisory and cannot create verified issues independently.
"""

import json
import os
import sqlite3
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.db import init_db
from app.config import settings
from app.main import app
from app.schemas.documentation import DocRetrievalRequest, DocSearchResponse, SearchResultItem
from app.schemas.evidence import AnalysisRequest, AnalysisReport, AISuggestion
from app.services.documentation.retrieval_service import DocumentationRetrievalService
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.adjudicator import EvidenceAdjudicator
from app.services.evidence.stream_adjudicator import stream_adjudicator
from app.services.llm.reasoning_service import LLMReasoningResponse, LLMReasoningService


# ---------------------------------------------------------------------------
# Synthetic Official Documentation Fixtures for Live Pipeline Testing
# ---------------------------------------------------------------------------

LIVE_CHARGES_DOC_MARKDOWN = """# Create a charge
`POST https://api.stripe.com/v1/charges`

To charge a credit card or other payment source, you create a Charge object.
If your API key is in test mode, the supplied card won't actually be charged.

### Parameters
- `amount` (required, integer): Amount intended to be collected in cents.
- `currency` (required, string): Three-letter ISO currency code.
- `source` (legacy): A payment source to be charged. The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods.
- `customer` (optional, string): The ID of an existing customer.

Required parameters: amount, currency.
Use the Payment Intents API instead of Charges for modern dynamic payment flows.
"""

LIVE_PAYMENT_INTENTS_DOC_MARKDOWN = """# Create a PaymentIntent
`POST https://api.stripe.com/v1/payment_intents`

Creates a PaymentIntent object. A PaymentIntent guides you through the process of collecting a payment from your customer.
We recommend using PaymentIntents for all new integrations.

### Parameters
- `amount` (required, integer): Amount intended to be collected in cents.
- `currency` (required, string): Three-letter ISO currency code.
- `automatic_payment_methods` (optional, dictionary): Automatic payment methods configuration.

Required parameters: amount (positive integer), currency (three-letter ISO code).
"""

LIVE_CUSTOMER_PORTAL_DOC_MARKDOWN = """# Create a portal session
`POST https://api.stripe.com/v1/billing_portal/sessions`

Creates a session of the customer portal where customers can manage their subscriptions and billing details.

### Parameters
- `customer` (required, string): The ID of an existing customer to create a portal session for.
- `return_url` (optional, string): The default URL to redirect customers to after they have finished.

Required parameters: customer (non-empty string).
"""


# ---------------------------------------------------------------------------
# Test 1: Full End-to-End Workflow with Registry Fast Path & Live TinyFish Fetch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_01_e2e_pipeline_with_registry_fast_path_and_verified_issue():
    """Verify complete 10-step pipeline detecting a real Stripe issue via live documentation."""
    source_code = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "charge = stripe.Charge.create(\n"
        "    amount=2000,\n"
        "    currency='usd',\n"
        "    source='tok_visa'\n"
        ")\n"
    )

    fetch_response_payload = {
        "status": "success",
        "results": [
            {
                "url": "https://docs.stripe.com/api/charges/create",
                "final_url": "https://docs.stripe.com/api/charges/create",
                "title": "Create a charge | Stripe API Reference",
                "format": "markdown",
                "text": LIVE_CHARGES_DOC_MARKDOWN,
                "status": "completed",
                "doc_version": "2024-04-10",
            }
        ],
        "errors": [],
    }

    mock_response = httpx.Response(
        status_code=200,
        json=fetch_response_payload,
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="checkout_flow.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        # 1. Pipeline produces an issues_found verdict
        assert report.verdict == "issues_found"
        assert report.evidence_trust == "live_official_source"
        assert report.is_mock is False
        assert report.filename == "checkout_flow.py"

        # 2. Checks performed confirm the 10-step pipeline execution
        assert "Python AST syntax validation" in report.checks_performed
        assert "Python AST call graph extraction" in report.checks_performed
        assert "API candidate identification" in report.checks_performed
        assert "Documentation evidence retrieval" in report.checks_performed
        assert "API contract matching" in report.checks_performed
        assert "Deterministic quotation verification" in report.checks_performed

        # 3. Verified issue contains authentic quote from fetched documentation
        assert len(report.verified_issues) == 1
        issue = report.verified_issues[0]
        assert issue.violation_type == "legacy_deprecated_parameter"
        assert issue.source_url == "https://docs.stripe.com/api/charges/create"
        assert "source" in issue.claim_checked.lower()
        assert "legacy" in issue.verified_quote.lower() or "paymentintent" in issue.verified_quote.lower()
        assert issue.supporting_evidence_id is not None
        assert issue.match_method in ("exact", "normalized_whitespace")

        # 4. Evidence items preserve required metadata for frontend rendering
        assert len(report.evidence_items) >= 1
        ev = report.evidence_items[0]
        assert ev.canonical_url == "https://docs.stripe.com/api/charges/create"
        assert ev.provider == "tinyfish_live"
        assert ev.source_trust == "official"
        assert ev.is_mock is False
        assert ev.content_sha256 is not None
        assert len(ev.parameters) > 0
        assert "amount" in [p.name for p in ev.parameters]


# ---------------------------------------------------------------------------
# Test 2: Clean Code Verification against Live Official Documentation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_02_e2e_pipeline_clean_code_verified_clean():
    """Verify compliant code produces a clean verdict against live documentation."""
    source_code = (
        "import stripe\n"
        "stripe.PaymentIntent.create(\n"
        "    amount=5000,\n"
        "    currency='usd'\n"
        ")\n"
    )

    fetch_response_payload = {
        "status": "success",
        "results": [
            {
                "url": "https://docs.stripe.com/api/payment_intents/create",
                "final_url": "https://docs.stripe.com/api/payment_intents/create",
                "title": "Create a PaymentIntent | Stripe API Reference",
                "format": "markdown",
                "text": LIVE_PAYMENT_INTENTS_DOC_MARKDOWN,
                "status": "completed",
                "doc_version": "2024-04-10",
            }
        ],
        "errors": [],
    }

    mock_response = httpx.Response(
        status_code=200,
        json=fetch_response_payload,
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="modern_payment.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        assert report.verdict == "clean"
        assert report.evidence_trust == "live_official_source"
        assert report.is_mock is False
        assert len(report.verified_issues) == 0
        assert len(report.unresolved_candidates) == 0
        assert "verified clean against official documentation" in report.summary.lower()


# ---------------------------------------------------------------------------
# Test 3: Two-Stage Dynamic Search Fallback for Unmapped API Symbol
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_03_e2e_pipeline_dynamic_search_fallback():
    """Verify unknown/unmapped symbols dynamically trigger TinyFish Search fallback."""
    # stripe.BillingPortal.Session.create is not in the initial hardcoded registry
    source_code = (
        "import stripe\n"
        "session = stripe.BillingPortal.Session.create(\n"
        "    customer='cus_999'\n"
        ")\n"
    )

    # Search endpoint returns candidate official Stripe URL
    search_response_payload = {
        "query": "stripe billing_portal session create",
        "results": [
            {
                "position": 1,
                "url": "https://docs.stripe.com/api/customer_portal/sessions/create",
                "title": "Create a portal session | Stripe API Reference",
                "snippet": "Creates a session of the customer portal.",
            }
        ],
    }

    mock_search_resp = httpx.Response(
        200,
        json=search_response_payload,
        request=httpx.Request("GET", "https://api.search.tinyfish.ai"),
    )

    # Fetch endpoint returns documentation for the resolved URL
    fetch_response_payload = {
        "status": "success",
        "results": [
            {
                "url": "https://docs.stripe.com/api/customer_portal/sessions/create",
                "final_url": "https://docs.stripe.com/api/customer_portal/sessions/create",
                "title": "Create a portal session | Stripe API Reference",
                "format": "markdown",
                "text": LIVE_CUSTOMER_PORTAL_DOC_MARKDOWN,
                "status": "completed",
                "doc_version": "2024-04-10",
            }
        ],
        "errors": [],
    }

    mock_fetch_resp = httpx.Response(
        200,
        json=fetch_response_payload,
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_search_resp)), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_fetch_resp)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="portal_flow.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        # Dynamic search fallback successfully found and retrieved the documentation
        assert report.evidence_trust == "live_official_source"
        assert report.is_mock is False
        assert len(report.evidence_items) >= 1
        assert "customer_portal/sessions" in report.evidence_items[0].canonical_url


# ---------------------------------------------------------------------------
# Test 4: Live Retrieval Failure Abstention (Must NOT report verified issues)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_04_e2e_pipeline_live_failure_abstains_without_false_issues():
    """Verify network or provider failure produces unable_to_verify, never false issues."""
    source_code = (
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )

    # Simulate TinyFish Fetch returning 500 Internal Server Error
    mock_500_response = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_500_response)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="failing_fetch.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        # Invariant: Live failure must NEVER report a verified issue
        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert report.evidence_trust == "untrusted_or_unavailable"
        assert len(report.unresolved_candidates) > 0
        assert report.candidate_assessments[0].abstention_reason == "DOCUMENTATION_MISSING"


# ---------------------------------------------------------------------------
# Test 5: Mock Mode Quarantine (Mock evidence can NEVER produce live verdicts)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_05_e2e_pipeline_mock_mode_quarantine_enforced():
    """Verify mock mode is strictly quarantined and cannot produce verified production issues."""
    source_code = (
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )

    adjudicator = EvidenceAdjudicator()
    req = AnalysisRequest(
        source=source_code,
        filename="mock_quarantine.py",
        ecosystem="stripe",
        force_mock=True,
    )

    report = await adjudicator.adjudicate(req)

    # Invariant: Mock evidence must NEVER report verified issues or production clean verdicts
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert "MOCK_EVIDENCE_ONLY" in report.limitations_and_caveats[0]
    assert report.candidate_assessments[0].abstention_reason == "MOCK_EVIDENCE_ONLY"


# ---------------------------------------------------------------------------
# Test 6: Unsupported / Unknown API Calls Reported Honestly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_06_e2e_pipeline_unsupported_api_abstains_honestly():
    """Verify unknown or unresolvable APIs are reported honestly with explicit abstention."""
    source_code = (
        "import stripe\n"
        "stripe.FakeImaginaryService.non_existent_method()\n"
    )

    # Search returns empty results
    search_empty_payload = {
        "query": "stripe fake_imaginary_service non_existent_method",
        "results": [],
    }

    mock_search_response = httpx.Response(
        status_code=200,
        json=search_empty_payload,
        request=httpx.Request("GET", "https://api.search.tinyfish.ai"),
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_search_response)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="unknown_api.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert len(report.unresolved_candidates) == 1
        assessment = report.candidate_assessments[0]
        assert assessment.status == "unresolved"
        assert assessment.abstention_reason == "DOCUMENTATION_MISSING"


# ---------------------------------------------------------------------------
# Test 7: Safe Non-Execution (Malicious / Destructive Code Never Executed)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_07_e2e_pipeline_safe_ast_parsing_zero_execution():
    """Verify dangerous source code is parsed safely without executing system calls or side effects."""
    dangerous_code = (
        "import os, sys\n"
        "os.system('rm -rf /some/dangerous/path')\n"
        "eval('__import__(\"os\").unlink(\"/tmp/fake\")')\n"
        "sys.exit(42)\n"
    )

    adjudicator = EvidenceAdjudicator()
    req = AnalysisRequest(
        source=dangerous_code,
        filename="malicious.py",
        ecosystem="stripe",
        force_mock=True,
    )

    # If code was executed, sys.exit(42) would terminate the Python process!
    report = await adjudicator.adjudicate(req)

    assert report is not None
    assert report.filename == "malicious.py"
    # Static analysis identifies no supported in-scope Stripe calls
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0


# ---------------------------------------------------------------------------
# Test 8: LLM Reasoning Cannot Independently Create Verified Issues
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_08_e2e_pipeline_llm_cannot_independently_create_verified_issue():
    """Verify that even if an LLM claims an issue exists, it is rejected without quote verification."""
    source_code = (
        "import stripe\n"
        "stripe.UnknownOperation.custom_call(foo='bar')\n"
    )

    # Mock an aggressive LLM service that claims a serious issue exists
    mock_llm_service = AsyncMock(spec=LLMReasoningService)
    mock_llm_service.reason.return_value = (
        LLMReasoningResponse(
            provider="openai_mock",
            model="gpt-4o",
            status="available",
            overall_reasoning_summary="LLM hallucination: 'custom_call' is completely forbidden by Stripe.",
            candidate_reasonings=[],
            suggested_documentation_urls=[],
        ),
        [
            AISuggestion(
                suggestion_id="sug_cand_1_1",
                candidate_id="cand_1",
                claim_type="deprecated_api",
                description="Potential deprecation suggested by model",
                unverified_aspects="Official documentation not retrieved",
                label="AI suggestion — not verified",
            )
        ],
        [],
    )

    adjudicator = EvidenceAdjudicator()
    req = AnalysisRequest(
        source=source_code,
        filename="advisory_only.py",
        ecosystem="stripe",
        force_mock=True,
    )

    report = await adjudicator.adjudicate(req, _llm_service_override=mock_llm_service)

    # Invariant: LLM cannot fabricate verified issues. Zero official docs -> unable_to_verify
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert report.llm_reasoning_status == "available"
    assert len(report.ai_suggestions) == 1  # AI suggestions preserved as advisory hints


# ---------------------------------------------------------------------------
# Test 9: Streaming Pipeline SSE Events Compatibility
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_09_e2e_streaming_pipeline_sse_events():
    """Verify the streaming pipeline emits all required stages with compatible schemas."""
    source_code = (
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )

    req = AnalysisRequest(
        source=source_code,
        filename="streaming_test.py",
        ecosystem="stripe",
        force_mock=True,
    )

    events = []
    async for event in stream_adjudicator.stream_adjudicate(req):
        events.append(event)

    stages = [e.stage for e in events]

    assert "accepted" in stages
    assert "static_analysis_started" in stages
    assert "static_analysis_completed" in stages
    assert "documentation_retrieval_started" in stages
    assert "documentation_retrieval_completed" in stages
    assert "evidence_verification_started" in stages
    assert "evidence_verification_completed" in stages
    assert "completed" in stages

    final_event = events[-1]
    assert final_event.stage == "completed"
    assert final_event.report is not None
    report = final_event.report
    assert report.verdict == "unable_to_verify"  # mock quarantine
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert report.verified_issues == []


# ---------------------------------------------------------------------------
# Test 10: Full HTTP API End-to-End Analysis Preserves Locations & URLs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_10_e2e_http_api_preserves_locations_and_source_urls(tmp_path):
    """Verify full HTTP POST /api/v1/analyze flow preserves filenames, line numbers, and doc URLs."""
    test_db = str(tmp_path / "e2e_api_test.db")
    init_db(test_db)
    source_code = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_secret123'\n"
        "\n"
        "intent = stripe.PaymentIntent.create(\n"
        "    amount=2000,\n"
        "    non_existent_field='invalid'\n"
        ")\n"
    )

    fetch_payload = {
        "status": "success",
        "results": [
            {
                "url": "https://docs.stripe.com/api/payment_intents/create",
                "final_url": "https://docs.stripe.com/api/payment_intents/create",
                "title": "Create a PaymentIntent | Stripe API Reference",
                "format": "markdown",
                "text": (
                    "# Create a PaymentIntent\n"
                    "Creates a PaymentIntent object.\n"
                    "### Parameters\n"
                    "- `amount` (required, integer): Amount intended to be collected in cents.\n"
                    "- `currency` (required, string): Three-letter ISO currency code.\n"
                    "- `customer` (optional, string): Customer identifier.\n"
                    "\n"
                    "Required parameters: amount (positive integer), currency (three-letter ISO code).\n"
                ),
                "status": "completed",
                "doc_version": "2024-04-10",
            }
        ],
        "errors": [],
    }

    mock_resp = httpx.Response(
        200,
        json=fetch_payload,
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    orig_post = httpx.AsyncClient.post
    async def selective_post(self, url, *args, **kwargs):
        if "tinyfish" in str(url):
            return mock_resp
        return await orig_post(self, url, *args, **kwargs)

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch.object(settings, "APICOMPASS_DB_PATH", test_db), \
         patch.object(httpx.AsyncClient, "post", selective_post):

        from app.main import create_app
        test_app = create_app()
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/analyze",
                json={
                    "source": source_code,
                    "filename": "services/payments/checkout.py",
                    "ecosystem": "stripe",
                    "force_mock": False,
                },
            )

        assert res.status_code == 200
        data = res.json()

        # 1. Verify top-level payload attributes
        assert data["verdict"] == "issues_found"
        assert data["filename"] == "services/payments/checkout.py"
        assert data["evidence_trust"] == "live_official_source"
        assert data["is_mock"] is False

        # 2. Verify findings preserve exact location and code fragment
        assert len(data["verified_issues"]) >= 1
        issue = data["verified_issues"][0]
        assert issue["source_location"]["lineno"] == 4
        assert issue["source_location"]["col_offset"] == 9
        assert "stripe.PaymentIntent.create" in issue["code_fragment"]
        assert issue["source_url"] == "https://docs.stripe.com/api/payment_intents/create"
        assert issue["supporting_evidence_id"] is not None

        # 3. Verify evidence reached the response with full fidelity
        assert len(data["evidence_items"]) >= 1
        ev = data["evidence_items"][0]
        assert ev["canonical_url"] == "https://docs.stripe.com/api/payment_intents/create"
        assert ev["provider"] == "tinyfish_live"
        assert ev["source_trust"] == "official"
        assert ev["is_mock"] is False
        assert "amount" in [p["name"] for p in ev["parameters"]]

        # 4. Verify database isolation
        assert os.path.exists(test_db)


# ---------------------------------------------------------------------------
# Test 11: End-to-End Handling of Malformed Upstream HTTP Responses
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_response", [
    httpx.Response(200, text="<html>502 Bad Gateway</html>", request=httpx.Request("POST", "https://api.fetch.tinyfish.ai")),
    httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", "https://api.fetch.tinyfish.ai")),
    httpx.Response(200, json={"status": "success", "results": "not-a-list"}, request=httpx.Request("POST", "https://api.fetch.tinyfish.ai")),
    httpx.Response(502, text="Bad Gateway", request=httpx.Request("POST", "https://api.fetch.tinyfish.ai")),
])
async def test_11_e2e_malformed_upstream_responses_handled_gracefully(corrupt_response):
    """Verify that malformed or non-JSON upstream responses never crash the pipeline and abstain safely."""
    source_code = (
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.post", new=AsyncMock(return_value=corrupt_response)):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="corrupt_upstream.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        assert report.verdict == "unable_to_verify"
        assert report.evidence_trust == "untrusted_or_unavailable"
        assert len(report.verified_issues) == 0
        assert len(report.unresolved_candidates) == 1
        assert report.candidate_assessments[0].abstention_reason == "DOCUMENTATION_MISSING"
        assert any("DOCUMENTATION_MISSING" in c for c in report.limitations_and_caveats)


# ---------------------------------------------------------------------------
# Test 12: Invalid Python Syntax Halts Safely with Exact Error Location
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_12_e2e_invalid_syntax_halts_with_exact_location():
    """Verify unparseable Python syntax produces a clean syntax_error report with 0 execution."""
    broken_code = (
        "import stripe\n"
        "\n"
        "stripe.Charge.create(amount=1000, currency='usd',,\n"
    )

    from app.main import create_app
    test_app = create_app()
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/analyze",
            json={
                "source": broken_code,
                "filename": "syntax_error.py",
                "ecosystem": "stripe",
            },
        )

    assert res.status_code == 200
    data = res.json()

    assert data["verdict"] == "unable_to_verify"
    assert data["syntax_error"] is not None
    assert data["syntax_error"]["lineno"] == 3
    assert data["syntax_error"]["col_offset"] is not None
    assert "invalid syntax" in data["syntax_error"]["message"].lower()
    assert data["verified_issues"] == []
    assert data["candidate_assessments"] == []
    assert any("syntax" in c.lower() for c in data["limitations_and_caveats"])


# ---------------------------------------------------------------------------
# Test 13: Non-Stripe Functions & Generic Methods Never Generate False Warnings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_13_e2e_non_stripe_functions_never_generate_false_warnings():
    """Verify that unrelated Python code with common method names (create, delete) never produces Stripe warnings."""
    non_stripe_code = (
        "class DatabaseRepository:\n"
        "    def create(self, table: str, record_id: int):\n"
        "        return {'table': table, 'id': record_id}\n"
        "\n"
        "    def delete(self, record_id: int):\n"
        "        pass\n"
        "\n"
        "db = DatabaseRepository()\n"
        "db.create(table='users', record_id=101)\n"
        "db.delete(record_id=101)\n"
    )

    adjudicator = EvidenceAdjudicator()
    req = AnalysisRequest(
        source=non_stripe_code,
        filename="db_ops.py",
        ecosystem="stripe",
        force_mock=False,
    )

    report = await adjudicator.adjudicate(req)

    # Invariant: Must not fabricate false Stripe issues against local objects
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    for cand in report.candidate_assessments:
        assert cand.status == "unresolved"
        assert cand.abstention_reason in (
            "AMBIGUOUS_OPERATION_MATCH",
            "NO_IN_SCOPE_CANDIDATES",
            "MOCK_EVIDENCE_ONLY",
            "DOCUMENTATION_MISSING",
        )


# ---------------------------------------------------------------------------
# Test 14: Database Isolation & Secrets Never Stored in History
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_14_e2e_database_isolation_and_secret_scrubbing(tmp_path):
    """Verify that test scans write strictly to isolated test databases and never persist raw API keys."""
    test_db = str(tmp_path / "isolated_audit.db")
    init_db(test_db)
    code_with_secret = (
        "import stripe\n"
        "stripe.api_key = '" + "sk" + "_live_SUPER_SECRET_TOKEN_DO_NOT_STORE'\n"
        "intent = stripe.PaymentIntent.create(amount=5000, currency='usd')\n"
    )

    fetch_payload = {
        "status": "success",
        "results": [
            {
                "url": "https://docs.stripe.com/api/payment_intents/create",
                "final_url": "https://docs.stripe.com/api/payment_intents/create",
                "title": "Create a PaymentIntent | Stripe API Reference",
                "format": "markdown",
                "text": LIVE_PAYMENT_INTENTS_DOC_MARKDOWN,
                "status": "completed",
                "doc_version": "2024-04-10",
            }
        ],
        "errors": [],
    }

    mock_resp = httpx.Response(
        200,
        json=fetch_payload,
        request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"),
    )

    orig_post = httpx.AsyncClient.post
    async def selective_post(self, url, *args, **kwargs):
        if "tinyfish" in str(url):
            return mock_resp
        return await orig_post(self, url, *args, **kwargs)

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch.object(settings, "APICOMPASS_DB_PATH", test_db), \
         patch.object(settings, "SOURCE_RETENTION_ENABLED", False), \
         patch.object(httpx.AsyncClient, "post", selective_post):

        from app.main import create_app
        test_app = create_app()
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/analyze",
                json={
                    "source": code_with_secret,
                    "filename": "sensitive_checkout.py",
                    "ecosystem": "stripe",
                    "force_mock": False,
                },
            )

        assert res.status_code == 200

        # Verify DB file exists at the isolated test location
        assert os.path.exists(test_db)
        # Check SQLite table in test_db
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT scan_id, verdict, source_sha256, source_length FROM scans")
        rows = cursor.fetchall()
        assert len(rows) >= 1
        stored_scan_id, stored_verdict, stored_sha256, stored_length = rows[0]
        assert stored_verdict == "clean"
        assert stored_length > 0
        assert len(stored_sha256) == 64

        # Verify the database schema has NO source_code or secret columns
        cursor.execute("PRAGMA table_info(scans)")
        cols = [r[1] for r in cursor.fetchall()]
        conn.close()
        assert "source_code" not in cols
        assert "api_key" not in cols


# ---------------------------------------------------------------------------
# Test 15: Upstream Network Timeouts Produce Honest Uncertainty States
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_15_e2e_upstream_network_timeout_produces_honest_uncertainty():
    """Verify upstream timeouts produce unable_to_verify with honest DOCUMENTATION_MISSING."""
    source_code = (
        "import stripe\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )

    with patch.object(settings, "TINYFISH_API_KEY", "tf_live_key_test_123"), \
         patch.object(settings, "MOCK_MODE", False), \
         patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.TimeoutException("Read timed out"))):

        adjudicator = EvidenceAdjudicator()
        req = AnalysisRequest(
            source=source_code,
            filename="timeout_fetch.py",
            ecosystem="stripe",
            force_mock=False,
        )

        report = await adjudicator.adjudicate(req)

        assert report.verdict == "unable_to_verify"
        assert report.evidence_trust == "untrusted_or_unavailable"
        assert len(report.verified_issues) == 0
        assert report.candidate_assessments[0].abstention_reason == "DOCUMENTATION_MISSING"
        assert any("DOCUMENTATION_MISSING" in c for c in report.limitations_and_caveats)
