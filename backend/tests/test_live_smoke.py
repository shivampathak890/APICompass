"""Opt-In Live Provider Smoke Tests.

Explicitly gated, opt-in smoke tests for verifying real external provider connectivity:
1. TinyFish documentation retrieval adapter.
2. OpenAI API reasoning provider adapter.

Mandatory Safety Guarantees:
- Live smoke tests are STRICTLY DISABLED BY DEFAULT.
- Require APICOMPASS_LIVE_SMOKE_TESTS=1.
- Require APICOMPASS_LIVE_PROVIDER to select 'tinyfish', 'openai', or 'all'.
- Require genuine non-empty API credentials in the environment.
- Pre-flight validate opt-in gate BEFORE constructing clients or issuing requests.
- Zero secret leakage in logs, skip messages, or representations.
- Smallest safe requests (official Stripe docs URL, single minimal static candidate).
- Normal test suite runs (pytest -W error backend/tests) MUST NEVER execute live calls.
"""

import os
from typing import Optional, Tuple
from unittest.mock import patch

import pytest

from app.config import settings
from app.schemas.ast_analysis import ApiCandidate, SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisRequest
from app.services.documentation.mock_adapter import TinyFishMockRetriever
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.adjudicator import adjudicator
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.provider import OpenAILLMProvider
from app.services.llm.schemas import LLMReasoningRequest, LLMReasoningResponse


# ==============================================================================
# Opt-In Gate Helper Functions
# ==============================================================================

def mask_secret(secret: Optional[str]) -> str:
    """Safely redact a secret key for reporting without leaking contents."""
    if not secret or not secret.strip():
        return "[none]"
    clean = secret.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:3]}...{clean[-3:]} (len: {len(clean)})"


def get_provider_key(provider: str) -> Optional[str]:
    """Retrieve stripped API key for the requested provider without logging it."""
    prov = provider.strip().lower()
    if prov == "tinyfish":
        raw = os.environ.get("TINYFISH_API_KEY") or settings.TINYFISH_API_KEY
    elif prov == "openai":
        raw = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or settings.LLM_API_KEY
        )
    else:
        raw = None

    if raw and raw.strip():
        return raw.strip()
    return None


def check_live_opt_in(provider: str) -> Tuple[bool, str]:
    """Pre-flight check whether live smoke testing is explicitly enabled and configured.

    Returns:
        (is_enabled: bool, reason: str)
    """
    opt_in_flag = os.environ.get("APICOMPASS_LIVE_SMOKE_TESTS", "").strip()
    if opt_in_flag != "1":
        return (
            False,
            "Live smoke tests are disabled by default. Set APICOMPASS_LIVE_SMOKE_TESTS=1 to enable.",
        )

    raw_selected = os.environ.get("APICOMPASS_LIVE_PROVIDER", "").strip().lower()
    if raw_selected not in ("tinyfish", "openai", "all"):
        return (
            False,
            f"APICOMPASS_LIVE_PROVIDER must be 'tinyfish', 'openai', or 'all' (got: {raw_selected!r}).",
        )

    target_prov = provider.strip().lower()
    if target_prov not in ("tinyfish", "openai"):
        return (False, f"Unknown live provider target: {target_prov!r}.")

    if raw_selected != "all" and raw_selected != target_prov:
        return (
            False,
            f"{target_prov.capitalize()} smoke test not selected by APICOMPASS_LIVE_PROVIDER='{raw_selected}'.",
        )

    key = get_provider_key(target_prov)
    if not key:
        env_var_name = "TINYFISH_API_KEY" if target_prov == "tinyfish" else "LLM_API_KEY / OPENAI_API_KEY"
        return (
            False,
            f"{target_prov.capitalize()} live smoke test skipped: {env_var_name} is missing or empty.",
        )

    return (True, f"Live smoke testing enabled for provider '{target_prov}'.")


# ==============================================================================
# Live Smoke Tests (Marked with @pytest.mark.live_smoke)
# ==============================================================================

@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_tinyfish_live_retrieval_smoke() -> None:
    """Live smoke test: TinyFish documentation retrieval.

    Requires:
        APICOMPASS_LIVE_SMOKE_TESTS=1
        APICOMPASS_LIVE_PROVIDER=tinyfish or all
        TINYFISH_API_KEY=<real_key>

    Verifies live connectivity to official Stripe documentation without executing code.
    """
    is_enabled, reason = check_live_opt_in("tinyfish")
    if not is_enabled:
        pytest.skip(reason)

    api_key = get_provider_key("tinyfish")
    assert api_key is not None, "Pre-flight gate check guaranteed key presence"

    # Use production TinyFishLiveRetriever with bounded 15s timeout
    retriever = TinyFishLiveRetriever(api_key=api_key, timeout_seconds=15.0)
    target_url = "https://docs.stripe.com/api/charges/create"

    evidence = await retriever.fetch_url(target_url)

    # Core response contract assertions
    assert isinstance(evidence, NormalizedEvidence), f"Expected NormalizedEvidence, got {type(evidence)}"
    assert evidence.provider == "tinyfish_live"
    assert evidence.is_mock is False
    assert evidence.canonical_url == target_url

    # Zero credential leakage verification
    assert api_key not in (evidence.error_message or ""), "Credential leaked in error message"
    assert api_key not in (evidence.content_excerpt or ""), "Credential leaked in content excerpt"
    assert api_key not in repr(evidence), "Credential leaked in evidence representation"

    if evidence.status == "success":
        assert evidence.error_code is None
        assert isinstance(evidence.content_excerpt, str)
        assert len(evidence.content_excerpt) > 0, "Expected non-empty documentation excerpt on success"
        assert evidence.source_trust == "official"
    else:
        # Provider may encounter rate limits or temporary upstream service outages
        assert evidence.status in ("unavailable", "rejected")
        assert evidence.error_code in (
            "RATE_LIMITED",
            "PROVIDER_ERROR",
            "TIMEOUT",
            "CIRCUIT_OPEN",
            "AUTHENTICATION_FAILED",
            "NO_CONTENT_RETURNED",
            "NETWORK_ERROR",
        )


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_tinyfish_live_pipeline_adjudication_smoke() -> None:
    """Live smoke test: End-to-end evidence adjudication using live TinyFish retrieval."""
    is_enabled, reason = check_live_opt_in("tinyfish")
    if not is_enabled:
        pytest.skip(reason)

    req = AnalysisRequest(
        source='import stripe\ncharge = stripe.Charge.create(amount=2000, currency="usd")\n',
        filename="live_pipeline_smoke.py",
        ecosystem="stripe",
        force_mock=False,
    )

    with patch.object(settings, "MOCK_MODE", False):
        report = await adjudicator.adjudicate(req)

    assert report.is_mock is False
    assert report.evidence_trust in ("live_official_source", "untrusted_or_unavailable")
    if report.evidence_items:
        for ev in report.evidence_items:
            assert ev.provider == "tinyfish_live"
            assert ev.is_mock is False
            assert ev.canonical_url.startswith("https://")


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_openai_live_reasoning_smoke() -> None:
    """Live smoke test: OpenAI API advisory reasoning.

    Requires:
        APICOMPASS_LIVE_SMOKE_TESTS=1
        APICOMPASS_LIVE_PROVIDER=openai or all
        LLM_API_KEY or OPENAI_API_KEY=<real_key>

    Verifies live connectivity using minimal single-candidate prompt.
    """
    is_enabled, reason = check_live_opt_in("openai")
    if not is_enabled:
        pytest.skip(reason)

    api_key = get_provider_key("openai")
    assert api_key is not None, "Pre-flight gate check guaranteed key presence"

    model = settings.LLM_MODEL or "gpt-4o-mini"
    provider = OpenAILLMProvider(api_key=api_key, model=model, timeout_seconds=15.0)

    # Construct single minimal static candidate (never executed)
    candidate = ApiCandidate(
        candidate_id="cand_live_smoke_1",
        expression="stripe.Charge.create(amount=2000, currency=\"usd\")",
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="Minimal live smoke test call",
        location=SourceLocation(lineno=2, col_offset=0),
    )

    req = LLMReasoningRequest(
        source='import stripe\nstripe.Charge.create(amount=2000, currency="usd")\n',
        filename="smoke_test.py",
        ecosystem="stripe",
        candidates=[candidate],
        existing_evidence_ids=[],
    )

    response = await provider.reason_about_candidates(req)

    # Core response contract assertions
    assert isinstance(response, LLMReasoningResponse), f"Expected LLMReasoningResponse, got {type(response)}"
    assert response.provider == "openai"
    assert response.model == model

    # Zero credential leakage verification
    assert api_key not in (response.error_message or ""), "Credential leaked in error message"
    assert api_key not in repr(response), "Credential leaked in response representation"

    if response.status == "available":
        assert response.error_message is None
        assert isinstance(response.candidate_reasonings, list)
        if len(response.candidate_reasonings) > 0:
            first = response.candidate_reasonings[0]
            assert first.candidate_id == "cand_live_smoke_1", "Model must only analyze provided candidate IDs"
    else:
        # Provider may encounter rate limits, quota exhaustion, or temporary outage
        assert response.status == "unavailable"
        assert response.error_message is not None
        assert len(response.error_message) > 0


# ==============================================================================
# Opt-In Gate Enforcement Unit Tests (Runs during normal test suite with 0 network calls)
# ==============================================================================

class TestLiveSmokeOptInGates:
    """Deterministic tests proving live smoke tests NEVER make network calls unless explicitly opted in."""

    def test_gate_disabled_by_default(self) -> None:
        """With default clean environment, all live smoke checks return False."""
        with patch.dict(os.environ, {}, clear=True):
            tf_enabled, tf_reason = check_live_opt_in("tinyfish")
            assert tf_enabled is False
            assert "disabled by default" in tf_reason

            oa_enabled, oa_reason = check_live_opt_in("openai")
            assert oa_enabled is False
            assert "disabled by default" in oa_reason

    @pytest.mark.parametrize("falsy_val", ["0", "false", "False", "no", "arbitrary", "true", "2", ""])
    def test_gate_disabled_with_falsy_or_arbitrary_opt_in_values(self, falsy_val: str) -> None:
        """Only exact string '1' enables the opt-in gate; all other values disable it."""
        with patch.dict(os.environ, {"APICOMPASS_LIVE_SMOKE_TESTS": falsy_val}, clear=True):
            enabled, reason = check_live_opt_in("tinyfish")
            assert enabled is False
            assert "disabled by default" in reason

    def test_gate_skips_when_provider_env_unset_or_invalid(self) -> None:
        """When opt-in is 1 but APICOMPASS_LIVE_PROVIDER is unset or invalid, tests skip safely."""
        with patch.dict(os.environ, {"APICOMPASS_LIVE_SMOKE_TESTS": "1"}, clear=True):
            enabled, reason = check_live_opt_in("tinyfish")
            assert enabled is False
            assert "APICOMPASS_LIVE_PROVIDER must be" in reason

        with patch.dict(os.environ, {"APICOMPASS_LIVE_SMOKE_TESTS": "1", "APICOMPASS_LIVE_PROVIDER": "anthropic"}, clear=True):
            enabled, reason = check_live_opt_in("tinyfish")
            assert enabled is False
            assert "anthropic" in reason

    def test_gate_provider_isolation_tinyfish_only(self) -> None:
        """When APICOMPASS_LIVE_PROVIDER=tinyfish, TinyFish is enabled but OpenAI is skipped."""
        env = {
            "APICOMPASS_LIVE_SMOKE_TESTS": "1",
            "APICOMPASS_LIVE_PROVIDER": "tinyfish",
            "TINYFISH_API_KEY": "valid_test_key_tf",
            "LLM_API_KEY": "valid_test_key_oa",
        }
        with patch.dict(os.environ, env, clear=True):
            tf_enabled, _ = check_live_opt_in("tinyfish")
            assert tf_enabled is True

            oa_enabled, oa_reason = check_live_opt_in("openai")
            assert oa_enabled is False
            assert "Openai smoke test not selected" in oa_reason

    def test_gate_provider_isolation_openai_only(self) -> None:
        """When APICOMPASS_LIVE_PROVIDER=openai, OpenAI is enabled but TinyFish is skipped."""
        env = {
            "APICOMPASS_LIVE_SMOKE_TESTS": "1",
            "APICOMPASS_LIVE_PROVIDER": "openai",
            "TINYFISH_API_KEY": "valid_test_key_tf",
            "LLM_API_KEY": "valid_test_key_oa",
        }
        with patch.dict(os.environ, env, clear=True):
            oa_enabled, _ = check_live_opt_in("openai")
            assert oa_enabled is True

            tf_enabled, tf_reason = check_live_opt_in("tinyfish")
            assert tf_enabled is False
            assert "Tinyfish smoke test not selected" in tf_reason

    def test_gate_provider_selection_all(self) -> None:
        """When APICOMPASS_LIVE_PROVIDER=all, both providers are enabled if keys exist."""
        env = {
            "APICOMPASS_LIVE_SMOKE_TESTS": "1",
            "APICOMPASS_LIVE_PROVIDER": "all",
            "TINYFISH_API_KEY": "valid_test_key_tf",
            "LLM_API_KEY": "valid_test_key_oa",
        }
        with patch.dict(os.environ, env, clear=True):
            tf_enabled, _ = check_live_opt_in("tinyfish")
            assert tf_enabled is True

            oa_enabled, _ = check_live_opt_in("openai")
            assert oa_enabled is True

    def test_gate_skips_when_credentials_missing_or_empty(self) -> None:
        """When opted in but credentials are empty or whitespace, skips with informative reason."""
        env_tf_empty = {
            "APICOMPASS_LIVE_SMOKE_TESTS": "1",
            "APICOMPASS_LIVE_PROVIDER": "all",
            "TINYFISH_API_KEY": "   ",
            "LLM_API_KEY": "valid_key",
        }
        with patch.dict(os.environ, env_tf_empty, clear=True), patch.object(settings, "TINYFISH_API_KEY", None):
            tf_enabled, tf_reason = check_live_opt_in("tinyfish")
            assert tf_enabled is False
            assert "TINYFISH_API_KEY is missing or empty" in tf_reason

        env_oa_empty = {
            "APICOMPASS_LIVE_SMOKE_TESTS": "1",
            "APICOMPASS_LIVE_PROVIDER": "all",
            "TINYFISH_API_KEY": "valid_key",
            "LLM_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env_oa_empty, clear=True), patch.object(settings, "LLM_API_KEY", None):
            oa_enabled, oa_reason = check_live_opt_in("openai")
            assert oa_enabled is False
            assert "LLM_API_KEY / OPENAI_API_KEY is missing or empty" in oa_reason

    def test_secret_masking_never_leaks_raw_token(self) -> None:
        """Verify mask_secret redacts securely and never exposes full tokens."""
        canary = "sk-live-super-secret-production-token-1234567890"
        masked = mask_secret(canary)
        assert canary not in masked
        assert masked.startswith("sk-")
        assert masked.endswith("890 (len: 48)")

        assert mask_secret("") == "[none]"
        assert mask_secret(None) == "[none]"
        assert mask_secret("short") == "***"

    def test_mock_isolation_unaffected_by_live_gate(self) -> None:
        """Mock components remain completely unaffected by live smoke opt-in settings."""
        with patch.object(settings, "MOCK_MODE", True):
            retriever = TinyFishMockRetriever()
            assert retriever is not None
            mock_llm = MockLLMProvider()
            assert mock_llm.name == "mock"

    @pytest.mark.asyncio
    async def test_live_smoke_functions_skip_without_network_when_opt_in_disabled(self) -> None:
        """Executing the smoke test functions directly in disabled env raises pytest.skip immediately."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(pytest.skip.Exception) as exc_tf:
                await test_tinyfish_live_retrieval_smoke()
            assert "disabled by default" in str(exc_tf.value)

            with pytest.raises(pytest.skip.Exception) as exc_oa:
                await test_openai_live_reasoning_smoke()
            assert "disabled by default" in str(exc_oa.value)
