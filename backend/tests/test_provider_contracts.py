"""External Provider Contract Tests.

Deterministic contract and safety invariant tests for:
1. TinyFish documentation retrieval adapter (HTTP 200, empty, malformed, 401/403, 429, 500/502/503, timeouts, SSRF/redirects, missing keys).
2. OpenAI API reasoning provider adapter (structured completion, candidate pruning, evidence sanitization, auth, rate-limit, timeout, 500, malformed JSON).
3. Evidence Court safety invariants (mock quarantine, provider-failure abstention, advisory-only AI, provenance rejection, secret sanitization).
4. Live-test isolation and no-silent-substitution guarantee.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from openai import (
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    APIStatusError,
)

from app.config import settings
from app.schemas.evidence import AnalysisRequest
from app.schemas.ast_analysis import ApiCandidate, ImportInfo, SourceLocation
from app.schemas.documentation import (
    DocRetrievalRequest,
    DocRetrievalResponse,
    NormalizedEvidence,
)
from app.services.documentation.retrieval_service import DocumentationRetrievalService
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.documentation.security import APPROVED_CANONICAL_HOSTS
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.quote_verifier import QuoteVerifier
from app.services.llm.base import BaseLLMProvider
from app.services.llm.provider import OpenAILLMProvider
from app.services.llm.reasoning_service import LLMReasoningService
from app.services.llm.schemas import (
    CandidateReasoning,
    LLMReasoningRequest,
    LLMReasoningResponse,
    ProposedClaim,
)


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_candidate(cand_id: str = "cand_001", expr: str = "stripe.Charge.create(amount=2000)") -> ApiCandidate:
    """Helper to construct a typed ApiCandidate."""
    return ApiCandidate(
        candidate_id=cand_id,
        expression=expr,
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="Stripe Charge call",
        location=SourceLocation(lineno=2, col_offset=0),
    )


def make_request(source: str = "import stripe\nstripe.Charge.create(amount=2000)\n") -> AnalysisRequest:
    """Helper to construct an AnalysisRequest."""
    return AnalysisRequest(
        source=source,
        filename="test_snippet.py",
        ecosystem="stripe",
    )


# ==============================================================================
# 1. TinyFish Documentation Retrieval Contract Tests
# ==============================================================================

class TestTinyFishLiveAdapterContracts:
    """Verifies TinyFish documentation retrieval contracts against mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_tinyfish_successful_fetch_contract(self) -> None:
        """Contract: HTTP 200 with valid results array produces authoritative official evidence."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        target_url = "https://docs.stripe.com/api/charges/create"

        synthetic_payload = {
            "results": [
                {
                    "url": "https://docs.stripe.com/api/charges/create",
                    "title": "Create a charge | Stripe API Reference",
                    "text": "To charge a credit card or other payment source, you create a Charge object.",
                }
            ]
        }
        mock_resp = httpx.Response(
            200,
            json=synthetic_payload,
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp) as mock_post:
            evidence = await retriever.fetch_url(target_url)

            # Verify request contract
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert kwargs["headers"]["X-API-Key"] == "tf-test-key-valid"
            assert kwargs["headers"]["Content-Type"] == "application/json"
            assert kwargs["json"] == {"urls": [target_url]}

            # Verify response mapping contract
            assert evidence.status == "success"
            assert evidence.is_mock is False
            assert evidence.source_trust == "official"
            assert evidence.canonical_url == target_url
            assert evidence.title == "Create a charge | Stripe API Reference"
            assert "To charge a credit card" in evidence.content_excerpt
            assert evidence.error_code is None
            assert evidence.error_message is None
            assert evidence.evidence_id.startswith("ev_") and len(evidence.evidence_id) == 19

    @pytest.mark.asyncio
    async def test_tinyfish_empty_results_contract(self) -> None:
        """Contract: HTTP 200 with an empty results list maps to NO_CONTENT_RETURNED."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        mock_resp = httpx.Response(
            200,
            json={"results": []},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "NO_CONTENT_RETURNED"
            assert evidence.content_excerpt == ""
            assert evidence.is_mock is False

    @pytest.mark.asyncio
    async def test_tinyfish_missing_results_key_contract(self) -> None:
        """Contract: HTTP 200 with missing or non-list results key maps to NO_CONTENT_RETURNED."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        mock_resp = httpx.Response(
            200,
            json={"message": "ok", "data": None},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "NO_CONTENT_RETURNED"

    @pytest.mark.asyncio
    async def test_tinyfish_malformed_json_contract(self) -> None:
        """Contract: HTTP 200 with non-JSON body (e.g. HTML gateway page) maps to INVALID_RESPONSE_JSON."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        mock_resp = httpx.Response(
            200,
            text="<html><body>502 Bad Gateway</body></html>",
            headers={"Content-Type": "text/html"},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "INVALID_RESPONSE_JSON"
            assert evidence.content_excerpt == ""

    @pytest.mark.asyncio
    async def test_tinyfish_truncated_json_contract(self) -> None:
        """Contract: Truncated JSON stream maps to INVALID_RESPONSE_JSON safely without crashing."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        mock_resp = httpx.Response(
            200,
            text='{"results": [{"url": "https://docs.stripe.com',
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "INVALID_RESPONSE_JSON"

    @pytest.mark.asyncio
    async def test_tinyfish_null_and_missing_item_fields(self) -> None:
        """Contract: Response items with null title or null text are handled gracefully."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key-valid")
        synthetic_payload = {
            "results": [
                {
                    "url": None,
                    "title": None,
                    "text": None,
                }
            ]
        }
        mock_resp = httpx.Response(
            200,
            json=synthetic_payload,
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "success"
            assert evidence.title is None
            assert evidence.content_excerpt == ""
            assert evidence.canonical_url == "https://docs.stripe.com/api/charges/create"

    @pytest.mark.asyncio
    async def test_tinyfish_auth_failure_401_403(self) -> None:
        """Contract: HTTP 401 and 403 map to AUTHENTICATION_FAILED without leaking keys."""
        retriever = TinyFishLiveRetriever(api_key="secret-api-key-12345")
        for status_code in [401, 403]:
            mock_resp = httpx.Response(
                status_code,
                json={"error": "Unauthorized"},
                request=httpx.Request("POST", retriever.fetch_base_url),
            )
            with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
                evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
                assert evidence.status == "unavailable"
                assert evidence.error_code == "AUTHENTICATION_FAILED"
                assert "secret-api-key-12345" not in (evidence.error_message or "")

    @pytest.mark.asyncio
    async def test_tinyfish_rate_limited_429(self) -> None:
        """Contract: HTTP 429 maps to RATE_LIMITED."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")
        mock_resp = httpx.Response(
            429,
            json={"error": "Too Many Requests"},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_tinyfish_provider_errors_500_502_503(self) -> None:
        """Contract: HTTP 500, 502, and 503 map to PROVIDER_ERROR with status code logged."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")
        for code in [500, 502, 503]:
            mock_resp = httpx.Response(
                code,
                text="Upstream Error",
                request=httpx.Request("POST", retriever.fetch_base_url),
            )
            with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
                evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
                assert evidence.status == "unavailable"
                assert evidence.error_code == "PROVIDER_ERROR"
                assert str(code) in (evidence.error_message or "")

    @pytest.mark.asyncio
    async def test_tinyfish_timeout_exception(self) -> None:
        """Contract: httpx.TimeoutException maps to TIMEOUT status."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key", timeout_seconds=5.0)

        with patch.object(httpx.AsyncClient, "post", side_effect=httpx.TimeoutException("Read timed out")):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "TIMEOUT"
            assert "5.0s" in (evidence.error_message or "")

    @pytest.mark.asyncio
    async def test_tinyfish_connection_error(self) -> None:
        """Contract: Network connection error maps to NETWORK_ERROR without crashing."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")

        with patch.object(httpx.AsyncClient, "post", side_effect=httpx.ConnectError("Failed to resolve host")):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "NETWORK_ERROR"

    @pytest.mark.asyncio
    async def test_tinyfish_preflight_ssrf_rejection(self) -> None:
        """Contract: SSRF targets are rejected pre-flight without initiating an HTTP request."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")
        invalid_urls = [
            "https://evil-unapproved.com/api/docs",
            "https://169.254.169.254/latest/meta-data",
            "http://docs.stripe.com/insecure-http",
            "https://127.0.0.1/admin",
        ]

        with patch.object(httpx.AsyncClient, "post") as mock_post:
            for url in invalid_urls:
                evidence = await retriever.fetch_url(url)
                assert evidence.status == "rejected"
                assert evidence.source_trust == "untrusted"
                assert evidence.error_code == "SSRF_POLICY_VIOLATION"
            mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_tinyfish_postfetch_redirect_escape_rejection(self) -> None:
        """Contract: Upstream redirect to unapproved or private destination is rejected."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")
        malicious_redirect_payload = {
            "results": [
                {
                    "url": "https://malicious-redirect-target.com/exploit",
                    "title": "Exploit",
                    "text": "Injected content",
                }
            ]
        }
        mock_resp = httpx.Response(
            200,
            json=malicious_redirect_payload,
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "rejected"
            assert evidence.source_trust == "untrusted"
            assert evidence.error_code == "REDIRECT_ESCAPE_VIOLATION"
            assert evidence.content_excerpt == ""

    @pytest.mark.asyncio
    async def test_tinyfish_missing_credentials_contract(self) -> None:
        """Contract: Missing credentials returns CREDENTIALS_MISSING without network calls."""
        retriever = TinyFishLiveRetriever(api_key=None)

        with patch.object(httpx.AsyncClient, "post") as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "CREDENTIALS_MISSING"

            resp = await retriever.retrieve(
                DocRetrievalRequest(ecosystem="stripe", target_url="https://docs.stripe.com/api/charges")
            )
            assert resp.status == "unavailable"
            assert resp.total_results == 0
            assert resp.evidence == []
            mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_tinyfish_content_normalization_and_truncation(self) -> None:
        """Contract: Retrieved text is normalized (whitespace collapsed) and capped at 8000 chars."""
        retriever = TinyFishLiveRetriever(api_key="tf-test-key")
        oversized_text = "word \n\t " * 3000  # > 15,000 characters with chaotic whitespace
        synthetic_payload = {
            "results": [
                {
                    "url": "https://docs.stripe.com/api/charges",
                    "title": "Normalized Doc",
                    "text": oversized_text,
                }
            ]
        }
        mock_resp = httpx.Response(
            200,
            json=synthetic_payload,
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "success"
            assert len(evidence.content_excerpt) <= 8000
            assert "  " not in evidence.content_excerpt  # Double spaces collapsed
            assert "\n" not in evidence.content_excerpt  # Newlines normalized


# ==============================================================================
# 2. OpenAI Reasoning Provider Contract Tests
# ==============================================================================

class TestOpenAIProviderContracts:
    """Verifies OpenAI reasoning provider contract mapping against mocked completions."""

    @pytest.mark.asyncio
    async def test_openai_successful_structured_reasoning_contract(self) -> None:
        """Contract: Valid JSON completion maps accurately to typed CandidateReasoning models."""
        provider = OpenAILLMProvider(api_key="sk-test-key", model="gpt-4o-mini")
        cand = make_candidate("cand_001")
        req = LLMReasoningRequest(
            source="import stripe\nstripe.Charge.create()",
            filename="test.py",
            ecosystem="stripe",
            candidates=[cand],
            imports=[],
            existing_evidence_ids=["ev_charges_01"],
        )

        payload = {
            "overall_reasoning_summary": "Identified legacy Stripe Charge call",
            "suggested_documentation_urls": ["https://docs.stripe.com/api/charges"],
            "candidate_reasonings": [
                {
                    "candidate_id": "cand_001",
                    "interpretation": "Creates a one-time charge",
                    "risk_category": "deprecated_api",
                    "confidence": "high",
                    "uncertainties": ["Payment method support"],
                    "reasoning_summary": "Charge API is considered legacy compared to PaymentIntents",
                    "suggested_documentation_queries": ["charges create"],
                    "referenced_evidence_ids": ["ev_charges_01"],
                    "proposed_claims": [
                        {
                            "claim_type": "deprecated_api",
                            "affected_candidate_id": "cand_001",
                            "description": "stripe.Charge.create is legacy",
                            "referenced_evidence_ids": ["ev_charges_01"],
                            "unverified_aspects": "Documentation evidence required for deprecation verification",
                        }
                    ],
                }
            ],
        }

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]

        with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_completion
            resp = await provider.reason_about_candidates(req)

            assert resp.status == "available"
            assert resp.provider == "openai"
            assert resp.model == "gpt-4o-mini"
            assert len(resp.candidate_reasonings) == 1
            cr = resp.candidate_reasonings[0]
            assert cr.candidate_id == "cand_001"
            assert cr.risk_category == "deprecated_api"
            assert len(cr.proposed_claims) == 1
            assert cr.proposed_claims[0].claim_type == "deprecated_api"

    @pytest.mark.asyncio
    async def test_openai_hallucinated_candidate_ids_discarded(self) -> None:
        """Contract: Model output referencing unknown candidate IDs is safely discarded."""
        provider = OpenAILLMProvider(api_key="sk-test-key")
        cand = make_candidate("cand_real")
        req = LLMReasoningRequest(
            source="import stripe\nstripe.Charge.create()",
            filename="test.py",
            ecosystem="stripe",
            candidates=[cand],
            imports=[],
        )

        payload = {
            "overall_reasoning_summary": "Summary",
            "suggested_documentation_urls": [],
            "candidate_reasonings": [
                {
                    "candidate_id": "cand_real",
                    "interpretation": "Real candidate",
                    "risk_category": "general_guidance",
                    "confidence": "low",
                    "uncertainties": [],
                    "reasoning_summary": "Real",
                    "suggested_documentation_queries": [],
                    "referenced_evidence_ids": [],
                    "proposed_claims": [],
                },
                {
                    "candidate_id": "cand_hallucinated_999",
                    "interpretation": "Hallucinated",
                    "risk_category": "deprecated_api",
                    "confidence": "high",
                    "uncertainties": [],
                    "reasoning_summary": "Fake",
                    "suggested_documentation_queries": [],
                    "referenced_evidence_ids": [],
                    "proposed_claims": [],
                },
            ],
        }

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]

        with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_completion):
            resp = await provider.reason_about_candidates(req)
            assert len(resp.candidate_reasonings) == 1
            assert resp.candidate_reasonings[0].candidate_id == "cand_real"

    @pytest.mark.asyncio
    async def test_openai_unknown_evidence_ids_sanitized(self) -> None:
        """Contract: Referenced evidence IDs unknown to the system are pruned."""
        provider = OpenAILLMProvider(api_key="sk-test-key")
        cand = make_candidate("cand_001")
        req = LLMReasoningRequest(
            source="import stripe\nstripe.Charge.create()",
            filename="test.py",
            ecosystem="stripe",
            candidates=[cand],
            imports=[],
            existing_evidence_ids=["ev_real_allowed"],
        )

        payload = {
            "candidate_reasonings": [
                {
                    "candidate_id": "cand_001",
                    "interpretation": "Test",
                    "risk_category": "general_guidance",
                    "confidence": "low",
                    "uncertainties": [],
                    "reasoning_summary": "Test",
                    "suggested_documentation_queries": [],
                    "referenced_evidence_ids": ["ev_real_allowed", "ev_fake_hallucinated"],
                    "proposed_claims": [
                        {
                            "claim_type": "general_guidance",
                            "affected_candidate_id": "cand_001",
                            "description": "Test claim",
                            "referenced_evidence_ids": ["ev_real_allowed", "ev_fake_hallucinated"],
                            "unverified_aspects": "Unverified",
                        }
                    ],
                }
            ]
        }

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]

        with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_completion):
            resp = await provider.reason_about_candidates(req)
            cr = resp.candidate_reasonings[0]
            assert cr.referenced_evidence_ids == ["ev_real_allowed"]
            assert cr.proposed_claims[0].referenced_evidence_ids == ["ev_real_allowed"]

    @pytest.mark.asyncio
    async def test_openai_malformed_json_completion(self) -> None:
        """Contract: Non-JSON completion maps to status='error' with sanitized error message."""
        provider = OpenAILLMProvider(api_key="sk-test-key")
        cand = make_candidate("cand_001")
        req = LLMReasoningRequest(
            source="import stripe\nstripe.Charge.create()",
            filename="test.py",
            ecosystem="stripe",
            candidates=[cand],
            imports=[],
        )

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content="Here is the output: {broken json"))]

        with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_completion):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "error"
            assert "Malformed structured output" in (resp.error_message or "")

    @pytest.mark.asyncio
    async def test_openai_exceptions_mapping(self) -> None:
        """Contract: OpenAI SDK exceptions map to documented status and messages."""
        provider = OpenAILLMProvider(api_key="sk-test-key", timeout_seconds=12.0)
        cand = make_candidate("cand_001")
        req = LLMReasoningRequest(
            source="import stripe\nstripe.Charge.create()",
            filename="test.py",
            ecosystem="stripe",
            candidates=[cand],
            imports=[],
        )

        # 1. AuthenticationError -> unavailable
        with patch.object(
            provider._client.chat.completions,
            "create",
            side_effect=AuthenticationError(
                message="Invalid API Key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            ),
        ):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "unavailable"
            assert "invalid API key" in (resp.error_message or "")

        # 2. RateLimitError -> unavailable
        with patch.object(
            provider._client.chat.completions,
            "create",
            side_effect=RateLimitError(
                message="Quota exceeded",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            ),
        ):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "unavailable"
            assert "rate limit or quota" in (resp.error_message or "")

        # 3. APITimeoutError -> unavailable
        with patch.object(
            provider._client.chat.completions,
            "create",
            side_effect=APITimeoutError(request=MagicMock()),
        ):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "unavailable"
            assert "12.0s" in (resp.error_message or "")

        # 4. APIConnectionError -> unavailable
        with patch.object(
            provider._client.chat.completions,
            "create",
            side_effect=APIConnectionError(request=MagicMock()),
        ):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "unavailable"
            assert "connection error" in (resp.error_message or "")

        # 5. APIStatusError (500) -> error
        with patch.object(
            provider._client.chat.completions,
            "create",
            side_effect=APIStatusError(
                message="Server Error",
                response=MagicMock(status_code=500, headers={}),
                body=None,
            ),
        ):
            resp = await provider.reason_about_candidates(req)
            assert resp.status == "error"
            assert "500" in (resp.error_message or "")

    def test_openai_empty_key_rejected_at_construction(self) -> None:
        """Contract: Initializing OpenAILLMProvider with empty API key raises ValueError immediately."""
        with pytest.raises(ValueError, match="requires a non-empty API key"):
            OpenAILLMProvider(api_key="")


# ==============================================================================
# 3. Evidence Safety & Adjudication Gating Invariants
# ==============================================================================

class TestEvidenceSafetyInvariants:
    """Verifies that provider failures and mock evidence never compromise Evidence Court integrity."""

    @pytest.mark.asyncio
    async def test_mock_evidence_quarantine_cannot_produce_clean(self) -> None:
        """Invariant: Mock evidence mode strictly forbids a 'clean' verdict."""
        req = make_request("import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        with patch.object(settings, "MOCK_MODE", True), patch.object(settings, "LLM_PROVIDER", "mock"):
            report = await adjudicator.adjudicate(req)
            assert report.verdict == "unable_to_verify"
            assert report.is_mock is True
            assert report.evidence_trust == "mock_fixture"
            assert report.verified_issues == []
            assert any("MOCK_EVIDENCE_ONLY" in c for c in report.limitations_and_caveats)

    @pytest.mark.asyncio
    async def test_mock_evidence_quarantine_cannot_produce_verified_violations(self) -> None:
        """Invariant: Mock evidence mode strictly forbids emitting verified production violations."""
        # Intentionally invalid parameters according to Stripe Charge contract
        req = make_request("import stripe\nstripe.Charge.create(amount='not_an_int', invalid_param=True)\n")
        with patch.object(settings, "MOCK_MODE", True):
            report = await adjudicator.adjudicate(req)
            assert report.verdict == "unable_to_verify"
            assert report.verified_issues == []  # Quarantined: 0 verified issues permitted

    @pytest.mark.asyncio
    async def test_provider_failure_leads_to_safe_abstention(self) -> None:
        """Invariant: External provider failure or missing evidence leads to safe abstention (never 'clean')."""
        unavailable_evidence = NormalizedEvidence(
            evidence_id="ev_failed_001",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title=None,
            content_excerpt="",  # Empty because retrieval failed
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="unavailable",
            is_mock=False,
            source_trust="official",
            error_code="PROVIDER_ERROR",
            error_message="TinyFish 500 error",
        )

        req = make_request("import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[unavailable_evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert len(report.unresolved_candidates) == 1
        assert report.candidate_assessments[0].status == "unresolved"

    def test_untrusted_url_provenance_rejected_by_quote_verifier(self) -> None:
        """Invariant: Quotations claimed from untrusted or unapproved hosts fail provenance validation."""
        fake_evidence = NormalizedEvidence(
            evidence_id="ev_fake_001",
            ecosystem="stripe",
            package="stripe",
            source_url="https://unapproved-hacker-site.com/docs/charges",
            canonical_url="https://unapproved-hacker-site.com/docs/charges",
            title="Fake Docs",
            content_excerpt="To charge a card, specify amount in cents.",
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="success",
            is_mock=False,
            source_trust="untrusted",
        )

        result = QuoteVerifier.verify_quote(
            proposed_quote="To charge a card, specify amount in cents.",
            evidence=fake_evidence,
        )
        assert result.is_verified is False
        assert "Evidence provenance failure" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_llm_suggestions_cannot_alter_deterministic_verdict(self) -> None:
        """Invariant: Model-proposed concerns cannot create verified findings without documentation."""
        class SuggestiveLLMProvider(BaseLLMProvider):
            @property
            def name(self) -> str:
                return "suggestive"

            async def reason_about_candidates(self, request: LLMReasoningRequest) -> LLMReasoningResponse:
                return LLMReasoningResponse(
                    status="available",
                    provider="suggestive",
                    model="test",
                    candidate_reasonings=[
                        CandidateReasoning(
                            candidate_id="cand_001",
                            interpretation="Critical violation proposed by model",
                            risk_category="deprecated_api",
                            confidence="high",
                            uncertainties=[],
                            reasoning_summary="Model believes this API is strictly forbidden",
                            suggested_documentation_queries=[],
                            referenced_evidence_ids=[],
                            proposed_claims=[
                                ProposedClaim(
                                    claim_type="deprecated_api",
                                    affected_candidate_id="cand_001",
                                    description="CRITICAL: Model claims this API is deprecated!",
                                    referenced_evidence_ids=[],
                                    unverified_aspects="Not verified by official documentation evidence",
                                )
                            ],
                        )
                    ],
                )

        svc = LLMReasoningService(override_provider=SuggestiveLLMProvider())
        req = make_request("import stripe\nstripe.Charge.create(amount=2000)\n")
        report = await adjudicator.adjudicate(req, _llm_service_override=svc)

        # The model's concern appears only as an advisory AI suggestion, NEVER a verified issue
        assert report.verdict == "unable_to_verify"
        assert report.verified_issues == []
        assert len(report.ai_suggestions) == 1
        assert report.ai_suggestions[0].label == "AI suggestion — not verified"
        assert "CRITICAL: Model claims" in report.ai_suggestions[0].description

    @pytest.mark.asyncio
    async def test_secrets_sanitization_in_provider_errors(self) -> None:
        """Invariant: Configured secrets and tokens in upstream error messages are never leaked in reports."""
        canary_secret = "sk-live-canary-secret-token-998877665544332211"
        mock_provider = AsyncMock(spec=BaseLLMProvider)
        mock_provider.name = "openai"
        mock_provider.reason_about_candidates.side_effect = AuthenticationError(
            message=f"Authentication failed with key: {canary_secret}",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )

        svc = LLMReasoningService(override_provider=mock_provider)
        req = make_request()
        report = await adjudicator.adjudicate(req, _llm_service_override=svc)

        # Confirm report does not leak the secret token in any field
        assert canary_secret not in report.summary
        assert canary_secret not in (report.llm_reasoning_summary or "")
        for caveat in report.limitations_and_caveats:
            assert canary_secret not in caveat


# ==============================================================================
# 4. Live Isolation & Gating Invariants
# ==============================================================================

class TestLiveIsolationGating:
    """Verifies that default test execution runs fully offline without network or credentials."""

    def test_default_test_suite_requires_no_network_or_keys(self) -> None:
        """Contract: Default test environment runs in MOCK_MODE without external network dependencies."""
        assert settings.MOCK_MODE is True
        assert "stripe.com" in APPROVED_CANONICAL_HOSTS

    @pytest.mark.asyncio
    async def test_retrieval_service_never_silently_substitutes_mock_for_live_failure(self) -> None:
        """Contract: Live retrieval failures must NOT silently fall back to mock data."""
        mock_live_retriever = AsyncMock()
        mock_live_retriever.retrieve.return_value = DocRetrievalResponse(
            status="unavailable",
            provider="tinyfish_live",
            is_mock=False,
            total_results=0,
            evidence=[],
            message="Live upstream failure",
        )
        mock_mock_retriever = AsyncMock()

        svc = DocumentationRetrievalService(
            live_retriever=mock_live_retriever,
            mock_retriever=mock_mock_retriever,
        )

        with patch.object(settings, "MOCK_MODE", False):
            req = DocRetrievalRequest(ecosystem="stripe", target_url="https://docs.stripe.com/api/charges")
            resp = await svc.retrieve(req)

            # Live retriever was called, mock retriever was NEVER called
            mock_live_retriever.retrieve.assert_called_once()
            mock_mock_retriever.retrieve.assert_not_called()
            # Response explicitly reports failure, NOT mock fallback
            assert resp.status == "unavailable"
            assert resp.is_mock is False
            assert resp.provider == "tinyfish_live"
