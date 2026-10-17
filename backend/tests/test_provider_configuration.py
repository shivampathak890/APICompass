"""Provider Configuration Lifecycle and Failure Handling Tests.

Verifies:
1. Predictable lifecycle states ('disabled', 'missing_credentials', 'configured', 'unavailable').
2. Safe failure handling for missing/whitespace-only/rejected credentials without network calls.
3. Zero credential or canary-secret leakage in returned messages, schemas, or captured logs.
4. Gating invariants: missing or failed credentials strictly cause safe abstention (verdict='unable_to_verify')
   and never produce a false 'clean' or false 'issues_found' production verdict.
5. Verification that diagnostic lifecycle states do not alter evidence trust or create verified findings.
6. Mock mode and quarantine remain completely isolated and intact.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from httpx import AsyncClient
from openai import AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError, APIStatusError

from app.config import settings
from app.schemas.ast_analysis import ApiCandidate, ImportInfo, SourceLocation
from app.schemas.documentation import DocRetrievalRequest, NormalizedEvidence
from app.schemas.evidence import AnalysisRequest
from app.services.documentation.retrieval_service import DocumentationRetrievalService
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.adjudicator import adjudicator
from app.services.llm.base import BaseLLMProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.provider import OpenAILLMProvider
from app.services.llm.reasoning_service import LLMReasoningService
from app.services.llm.schemas import (
    CandidateReasoning,
    LLMReasoningRequest,
    LLMReasoningResponse,
    ProposedClaim,
)
from app.services.providers.status import (
    get_tinyfish_lifecycle_state,
    get_llm_lifecycle_state,
    get_all_provider_lifecycle_states,
)


CANARY_SECRET_KEY = "sk-live-canary-secret-token-998877665544332211"


# ==============================================================================
# 1. Predictable Provider Lifecycle States
# ==============================================================================

class TestProviderLifecycleStates:
    """Verifies that provider states are computed deterministically without network calls."""

    def test_tinyfish_lifecycle_state_disabled_in_mock_mode(self) -> None:
        """In mock mode, live TinyFish retrieval is marked as 'disabled'."""
        with patch.object(settings, "MOCK_MODE", True):
            state = get_tinyfish_lifecycle_state()
            assert state == "disabled"

    def test_tinyfish_lifecycle_state_missing_credentials(self) -> None:
        """In live mode without a key (or with whitespace-only), state is 'missing_credentials'."""
        with patch.object(settings, "MOCK_MODE", False):
            # None key
            with patch.object(settings, "TINYFISH_API_KEY", None):
                assert get_tinyfish_lifecycle_state() == "missing_credentials"

            # Empty string
            with patch.object(settings, "TINYFISH_API_KEY", ""):
                assert get_tinyfish_lifecycle_state() == "missing_credentials"

            # Whitespace-only string
            with patch.object(settings, "TINYFISH_API_KEY", "   \t\n  "):
                assert get_tinyfish_lifecycle_state() == "missing_credentials"

    def test_tinyfish_lifecycle_state_configured(self) -> None:
        """In live mode with a non-empty key, state is 'configured' (unconfirmed until queried)."""
        with patch.object(settings, "MOCK_MODE", False), patch.object(settings, "TINYFISH_API_KEY", "tf-test-configured-key"):
            assert get_tinyfish_lifecycle_state() == "configured"

    def test_tinyfish_lifecycle_state_unavailable_on_runtime_failure(self) -> None:
        """When an upstream failure occurs at runtime, the provider is marked 'unavailable'."""
        assert get_tinyfish_lifecycle_state(runtime_failure=True) == "unavailable"

    def test_llm_lifecycle_state_disabled(self) -> None:
        """When LLM_PROVIDER is 'disabled' or invalid, state is 'disabled'."""
        with patch.object(settings, "LLM_PROVIDER", "disabled"):
            assert get_llm_lifecycle_state() == "disabled"

        with patch.object(settings, "LLM_PROVIDER", "unknown_provider"):
            assert get_llm_lifecycle_state() == "disabled"

    def test_llm_lifecycle_state_mock(self) -> None:
        """When LLM_PROVIDER is 'mock', mock provider is 'configured' for offline analysis."""
        with patch.object(settings, "LLM_PROVIDER", "mock"):
            assert get_llm_lifecycle_state() == "configured"

    def test_llm_lifecycle_state_openai_missing_credentials(self) -> None:
        """When LLM_PROVIDER is 'openai' but key is missing or whitespace-only, state is 'missing_credentials'."""
        with patch.object(settings, "LLM_PROVIDER", "openai"):
            with patch.object(settings, "LLM_API_KEY", None):
                assert get_llm_lifecycle_state() == "missing_credentials"

            with patch.object(settings, "LLM_API_KEY", ""):
                assert get_llm_lifecycle_state() == "missing_credentials"

            with patch.object(settings, "LLM_API_KEY", "   \n\t  "):
                assert get_llm_lifecycle_state() == "missing_credentials"

    def test_llm_lifecycle_state_openai_configured(self) -> None:
        """When LLM_PROVIDER is 'openai' and key is non-empty, state is 'configured'."""
        with patch.object(settings, "LLM_PROVIDER", "openai"), patch.object(settings, "LLM_API_KEY", "sk-test-mock-key"):
            assert get_llm_lifecycle_state() == "configured"

    def test_llm_lifecycle_state_unavailable_on_runtime_failure(self) -> None:
        """When runtime failure occurs (auth, quota, timeout, network), state is 'unavailable'."""
        assert get_llm_lifecycle_state(runtime_failure=True) == "unavailable"

    @pytest.mark.asyncio
    async def test_health_endpoint_exposes_provider_lifecycle_states(self, client: AsyncClient) -> None:
        """GET /api/v1/health exposes diagnostic states without leaking keys, lengths, or env paths."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()

        assert "provider_status" in data
        prov = data["provider_status"]
        assert "tinyfish" in prov
        assert "llm" in prov
        assert prov["tinyfish"] in ("disabled", "missing_credentials", "configured", "unavailable")
        assert prov["llm"] in ("disabled", "missing_credentials", "configured", "unavailable")
        # Ensure zero secret strings appear in the payload
        raw_json = json.dumps(data)
        assert "api_key" not in raw_json.lower()
        assert "sk-" not in raw_json


# ==============================================================================
# 2. Failure Handling and Credential Safety
# ==============================================================================

class TestFailureHandlingAndCredentialSafety:
    """Verifies that malformed, rejected, or missing credentials fail safely without leaking secrets."""

    @pytest.mark.asyncio
    async def test_whitespace_only_tinyfish_key_treated_as_missing(self) -> None:
        """TinyFishLiveRetriever normalizes whitespace-only API keys to None, preventing empty-key requests."""
        retriever = TinyFishLiveRetriever(api_key="   \t\n  ")
        assert retriever.api_key is None

        with patch.object(httpx.AsyncClient, "post") as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "CREDENTIALS_MISSING"
            mock_post.assert_not_called()

    def test_whitespace_only_openai_key_rejected_at_construction(self) -> None:
        """OpenAILLMProvider rejects whitespace-only API keys with ValueError immediately."""
        with pytest.raises(ValueError, match="requires a non-empty API key"):
            OpenAILLMProvider(api_key="   \n\t  ")

    @pytest.mark.asyncio
    async def test_reasoning_service_handles_whitespace_key_as_missing_credentials(self) -> None:
        """LLMReasoningService detects whitespace-only keys and returns unavailable status without crashing."""
        cand = ApiCandidate(
            candidate_id="cand_001",
            expression="stripe.Charge.create()",
            receiver="stripe.Charge",
            target_name="create",
            kind="method_call",
            confidence="heuristic",
            rationale="Test",
            location=SourceLocation(lineno=1, col_offset=0),
        )
        with patch.object(settings, "LLM_PROVIDER", "openai"), patch.object(settings, "LLM_API_KEY", "   \t   "):
            svc = LLMReasoningService()
            resp, suggestions, urls = await svc.reason(
                source="stripe.Charge.create()",
                filename="test.py",
                ecosystem="stripe",
                candidates=[cand],
                imports=[],
            )
            assert resp.status == "unavailable"
            assert resp.error_message == "LLM_API_KEY is not configured."
            assert len(suggestions) == 0

    @pytest.mark.asyncio
    async def test_canary_secret_not_leaked_in_reasoning_service_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        """When an LLM call times out, the canary secret is never leaked in returned messages or logs."""
        mock_provider = AsyncMock(spec=BaseLLMProvider)
        mock_provider.name = "openai"
        mock_provider.reason_about_candidates.side_effect = APITimeoutError(request=MagicMock())

        svc = LLMReasoningService(override_provider=mock_provider)
        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=1000)\n")

        with caplog.at_level(logging.DEBUG):
            report = await adjudicator.adjudicate(req, _llm_service_override=svc)

            assert report.llm_reasoning_status == "unavailable"
            assert CANARY_SECRET_KEY not in report.summary
            assert CANARY_SECRET_KEY not in (report.llm_reasoning_summary or "")
            for caveat in report.limitations_and_caveats:
                assert CANARY_SECRET_KEY not in caveat
            for record in caplog.records:
                assert CANARY_SECRET_KEY not in record.message

    @pytest.mark.asyncio
    async def test_canary_secret_not_leaked_in_reasoning_service_auth_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """When upstream returns 401 containing canary token, the secret is never reflected in report or logs."""
        mock_provider = AsyncMock(spec=BaseLLMProvider)
        mock_provider.name = "openai"
        mock_provider.reason_about_candidates.side_effect = AuthenticationError(
            message=f"Unauthorized: Key {CANARY_SECRET_KEY} is invalid or revoked.",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )

        svc = LLMReasoningService(override_provider=mock_provider)
        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=1000)\n")

        with caplog.at_level(logging.DEBUG):
            report = await adjudicator.adjudicate(req, _llm_service_override=svc)

            assert report.llm_reasoning_status == "unavailable"
            # Canary must NOT appear anywhere in the generated report
            assert CANARY_SECRET_KEY not in report.summary
            assert CANARY_SECRET_KEY not in (report.llm_reasoning_summary or "")
            for caveat in report.limitations_and_caveats:
                assert CANARY_SECRET_KEY not in caveat
            # Canary must NOT appear in application logs
            for record in caplog.records:
                assert CANARY_SECRET_KEY not in record.message

    @pytest.mark.asyncio
    async def test_canary_secret_not_leaked_in_unhandled_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """When an unexpected exception contains canary secret, logger and response sanitize it safely."""
        mock_provider = AsyncMock(spec=BaseLLMProvider)
        mock_provider.name = "openai"
        mock_provider.reason_about_candidates.side_effect = RuntimeError(
            f"Fatal internal connection crash containing {CANARY_SECRET_KEY}"
        )

        svc = LLMReasoningService(override_provider=mock_provider)
        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=1000)\n")

        with caplog.at_level(logging.DEBUG):
            report = await adjudicator.adjudicate(req, _llm_service_override=svc)

            assert report.llm_reasoning_status == "error"
            assert CANARY_SECRET_KEY not in report.summary
            for record in caplog.records:
                assert CANARY_SECRET_KEY not in record.message

    @pytest.mark.asyncio
    async def test_tinyfish_auth_failure_does_not_leak_key_or_raw_body(self, caplog: pytest.LogCaptureFixture) -> None:
        """TinyFish 401 returns a standardized error message and does not log response text containing secrets."""
        retriever = TinyFishLiveRetriever(api_key=CANARY_SECRET_KEY)
        leaky_response_body = {"error": f"API key {CANARY_SECRET_KEY} rejected by gateway."}
        mock_resp = httpx.Response(
            401,
            json=leaky_response_body,
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp), caplog.at_level(logging.DEBUG):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "AUTHENTICATION_FAILED"
            assert CANARY_SECRET_KEY not in (evidence.error_message or "")
            for record in caplog.records:
                assert CANARY_SECRET_KEY not in record.message


# ==============================================================================
# 3. Verification Invariants Under Provider Failure
# ==============================================================================

class TestVerificationInvariantsUnderProviderFailure:
    """Verifies that missing or failing providers cause safe abstention and never emit false clean verdicts."""

    @pytest.mark.asyncio
    async def test_missing_tinyfish_credentials_cannot_produce_clean_verdict(self) -> None:
        """When TinyFish credentials are missing in live mode, candidate is unresolved and verdict is unable_to_verify."""
        retriever = TinyFishLiveRetriever(api_key=None)
        with patch.object(settings, "MOCK_MODE", False):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"

            req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
            report = await adjudicator.adjudicate(req, _internal_evidence=[evidence])

            assert report.verdict == "unable_to_verify"
            assert len(report.verified_issues) == 0
            assert len(report.unresolved_candidates) >= 1
            assert report.candidate_assessments[0].status == "unresolved"

    @pytest.mark.asyncio
    async def test_tinyfish_auth_failure_cannot_produce_clean_verdict(self) -> None:
        """When TinyFish rejects credentials (401), analysis abstains safely as unable_to_verify."""
        failed_evidence = NormalizedEvidence(
            evidence_id="ev_auth_failed",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title=None,
            content_excerpt="",
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="unavailable",
            is_mock=False,
            source_trust="official",
            error_code="AUTHENTICATION_FAILED",
            error_message="Authentication failed",
        )

        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[failed_evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert report.candidate_assessments[0].status == "unresolved"

    @pytest.mark.asyncio
    async def test_tinyfish_rate_limit_causes_safe_abstention(self) -> None:
        """When TinyFish is rate-limited (429), analysis abstains safely without false clean."""
        rate_limited_evidence = NormalizedEvidence(
            evidence_id="ev_rate_limited",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title=None,
            content_excerpt="",
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="unavailable",
            is_mock=False,
            source_trust="official",
            error_code="RATE_LIMITED",
            error_message="Rate limit reached",
        )

        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[rate_limited_evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0

    @pytest.mark.asyncio
    async def test_tinyfish_server_error_causes_safe_abstention(self) -> None:
        """When TinyFish encounters a 500 error, analysis abstains safely without false clean."""
        error_evidence = NormalizedEvidence(
            evidence_id="ev_server_error",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title=None,
            content_excerpt="",
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="unavailable",
            is_mock=False,
            source_trust="official",
            error_code="PROVIDER_ERROR",
            error_message="TinyFish service returned HTTP 500",
        )

        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[error_evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0

    @pytest.mark.asyncio
    async def test_missing_openai_credentials_leaves_verdict_deterministic(self) -> None:
        """Missing OpenAI credentials logs an advisory caveat and preserves deterministic adjudication."""
        with patch.object(settings, "LLM_PROVIDER", "openai"), patch.object(settings, "LLM_API_KEY", None):
            svc = LLMReasoningService()
            req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000)\n")
            report = await adjudicator.adjudicate(req, _llm_service_override=svc)

            assert report.llm_reasoning_status == "unavailable"
            assert any("LLM_REASONING_UNAVAILABLE" in c for c in report.limitations_and_caveats)
            assert report.verdict == "unable_to_verify"
            assert report.verified_issues == []

    @pytest.mark.asyncio
    async def test_diagnostic_state_never_promotes_evidence_trust(self) -> None:
        """A provider lifecycle state of 'configured' does not elevate unverified evidence to 'live_official_source'."""
        with patch.object(settings, "MOCK_MODE", False), patch.object(settings, "TINYFISH_API_KEY", "tf-configured-key"):
            assert get_tinyfish_lifecycle_state() == "configured"

            # Mock evidence submitted during configured mode must remain quarantined
            mock_ev = NormalizedEvidence(
                evidence_id="ev_mock_001",
                ecosystem="stripe",
                package="stripe",
                source_url="https://docs.stripe.com/api/charges/create",
                canonical_url="https://docs.stripe.com/api/charges/create",
                title="Mock Excerpt",
                content_excerpt="Mock charges content",
                retrieved_at="2026-10-17T00:00:00Z",
                provider="tinyfish_mock",
                status="mock",
                is_mock=True,
                source_trust="mock_fixture",
            )

            req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
            report = await adjudicator.adjudicate(req, _internal_evidence=[mock_ev])

            # Trust must NEVER be upgraded to live_official_source merely because a key is configured
            assert report.verdict == "unable_to_verify"
            assert report.is_mock is True
            assert report.evidence_trust == "mock_fixture"
            assert report.verified_issues == []
