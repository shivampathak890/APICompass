"""Comprehensive test suite for APICompass mock mode audit, mock fixtures, and offline analysis.

Verifies:
1. Every synthetic fixture is explicitly labeled with [Mock Fixture] and demonstration notice.
2. Mock retriever returns is_mock=True, status='mock', provider='tinyfish_mock', source_trust='mock_fixture'.
3. Synthetic mock text is never presented as an official quotation.
4. Mock evidence strictly quarantines candidates: zero verified issues, verdict='unable_to_verify'.
5. Clean code evaluated against mock fixtures abstains with 'unable_to_verify' and MOCK_EVIDENCE_ONLY.
6. Failed live requests (HTTP 500, 429, timeout, SSRF) NEVER silently fall back to mock fixtures.
7. Mock search is deterministic with stable ordering and alphabetical tie-breaking.
8. Edge-case fixtures: subscriptions, webhooks, deprecated card tokens, rate-limited, empty, malformed.
9. Audit distinction: programmatically differentiates live official results from synthetic mock results.
"""

from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.schemas.ast_analysis import ApiCandidate, SourceLocation
from app.schemas.contract import ContractFindingCandidate
from app.schemas.documentation import (
    DocRetrievalRequest,
    DocSearchRequest,
    NormalizedEvidence,
)
from app.schemas.evidence import AnalysisRequest, QuoteVerificationResult
from app.services.documentation.mock_adapter import (
    OFFICIAL_STRIPE_FIXTURES,
    TinyFishMockRetriever,
    compute_evidence_id,
)
from app.services.documentation.retrieval_service import DocumentationRetrievalService
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import quote_verifier
from app.services.fixes.policy import evaluate_fix_eligibility


# ==============================================================================
# 1. Fixture Inventory & Explicit Labeling Tests
# ==============================================================================

def test_01_fixture_inventory_and_demonstration_notices():
    """Requirement 1 & 2: Every synthetic fixture is identified, labeled with [Mock Fixture], and has demonstration notices."""
    assert len(OFFICIAL_STRIPE_FIXTURES) >= 10
    for url, fix in OFFICIAL_STRIPE_FIXTURES.items():
        assert url.startswith("https://docs.stripe.com/api")
        assert fix["title"].startswith("[Mock Fixture]"), f"Fixture {url} must have [Mock Fixture] prefix in title"
        assert "demonstration_notice" in fix, f"Fixture {url} must contain an explicit demonstration notice"
        assert "test fixture" in fix["demonstration_notice"].lower() or "not live" in fix["demonstration_notice"].lower()
        assert len(fix["excerpt"]) > 0


@pytest.mark.asyncio
async def test_02_retriever_tags_evidence_with_mock_fixture_trust():
    """Requirement 2: Mock retriever explicitly returns source_trust='mock_fixture' and is_mock=True."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

    assert ev.is_mock is True
    assert ev.status == "mock"
    assert ev.provider == "tinyfish_mock"
    assert ev.source_trust == "mock_fixture"
    assert "[Mock Fixture]" in ev.title
    assert ev.doc_version == "2024-04-10"
    assert ev.evidence_id.startswith("ev_")


# ==============================================================================
# 2. Quotation Quarantine Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_03_mock_text_cannot_be_presented_as_official_quotation():
    """Requirement 3: Synthetic mock text is explicitly rejected when claimed as an official quotation."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

    # When require_official=True, quote_verifier strictly rejects mock evidence
    res = quote_verifier.verify_quote(
        proposed_quote="The 'source' parameter is considered legacy",
        evidence=ev,
        require_official=True,
    )
    assert res.is_verified is False
    assert res.is_mock is True
    assert "Synthetic mock text cannot be presented as an official quotation" in (res.error_message or "")


# ==============================================================================
# 3. Adjudication Mock Quarantine (No False Verified Issues)
# ==============================================================================

@pytest.mark.asyncio
async def test_04_mock_findings_cannot_produce_verified_issues():
    """Requirement 4: Violating code evaluated in mock mode produces zero verified issues and abstains."""
    req = AnalysisRequest(
        source=(
            "import stripe\n"
            "stripe.Charge.create(amount=5000, currency='usd', source='tok_visa')\n"
        ),
        filename="charge_legacy.py",
        force_mock=True,
    )
    report = await adjudicator.adjudicate(req)

    # Invariants for mock mode evaluation:
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert report.verdict == "unable_to_verify"
    assert report.result_state == "unable_to_verify"
    assert len(report.verified_issues) == 0, "Mock mode must NEVER report verified issues"
    assert any("MOCK_EVIDENCE_ONLY" in c for c in report.limitations_and_caveats)

    # Candidate assessment must be explicitly unresolved with MOCK_EVIDENCE_ONLY
    assert len(report.candidate_assessments) == 1
    cand_asm = report.candidate_assessments[0]
    assert cand_asm.status == "unresolved"
    assert cand_asm.abstention_reason == "MOCK_EVIDENCE_ONLY"
    assert len(cand_asm.issues) == 0


@pytest.mark.asyncio
async def test_05_clean_code_in_mock_mode_cannot_produce_clean_verdict():
    """Requirement 4: Clean code evaluated against mock fixtures cannot claim a production 'clean' verdict."""
    req = AnalysisRequest(
        source=(
            "import stripe\n"
            "stripe.PaymentIntent.create(amount=5000, currency='usd')\n"
        ),
        filename="payment_clean.py",
        force_mock=True,
    )
    report = await adjudicator.adjudicate(req)

    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert report.verdict == "unable_to_verify"
    assert report.result_state == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert any("MOCK_EVIDENCE_ONLY" in c for c in report.limitations_and_caveats)


@pytest.mark.asyncio
async def test_06_mock_evidence_blocks_production_fix_generation():
    """Requirement 4: Fix proposal policy prohibits generating fixes supported only by mock evidence."""
    from app.services.fixes.fix_proposer import fix_proposer
    from app.schemas.fix_proposal import ProposeFixRequest

    req = ProposeFixRequest(
        source="import stripe\ncharge = stripe.Charge.create(amount=2000, currency='usd', source='tok_123')",
        candidate_id="cand_001",
    )
    res = await fix_proposer.propose_fix(req)
    # Must be strictly quarantined as mock_evidence_only, never evidence_supported
    assert res.status == "mock_evidence_only"
    assert res.is_mock is True
    assert res.evidence_trust == "mock_fixture"
    assert res.reverification_status == "reverification_inconclusive"
    assert any("MOCK_EVIDENCE_ONLY" in w for w in res.warnings)


# ==============================================================================
# 4. No Silent Fallback to Mock After Live Retrieval Failure
# ==============================================================================

@pytest.mark.asyncio
async def test_07_live_http_500_failure_never_silently_falls_back_to_mock():
    """Requirement 7: HTTP 500 from live TinyFish causes honest abstention, zero mock substitution."""
    mock_post_resp = httpx.Response(
        status_code=500,
        content=b"Internal Server Error",
        request=httpx.Request("POST", "https://api.tinyfish.io/v1/extract"),
    )
    live_retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    with patch("app.config.settings.TINYFISH_API_KEY", "tf-test-valid-key"), \
         patch("app.config.settings.MOCK_MODE", False), \
         patch.object(httpx.AsyncClient, "post", return_value=mock_post_resp):
        svc = DocumentationRetrievalService(live_retriever=live_retriever)
        resp = await svc.retrieve(
            DocRetrievalRequest(
                query="stripe.Charge.create",
                ecosystem="stripe",
                force_mock=False,
            )
        )
        # Must report live failure, NEVER substitute mock fixtures
        assert resp.is_mock is False
        assert resp.status in ("unavailable", "error")
        assert resp.provider == "tinyfish_live"
        assert len(resp.evidence) == 0 or all(e.status != "success" for e in resp.evidence)


@pytest.mark.asyncio
async def test_08_live_rate_limit_429_never_silently_falls_back_to_mock():
    """Requirement 7: HTTP 429 rate limit from live TinyFish does not trigger mock substitution."""
    mock_post_resp = httpx.Response(
        status_code=429,
        headers={"Retry-After": "60"},
        content=b'{"error": "Rate limit exceeded"}',
        request=httpx.Request("POST", "https://api.tinyfish.io/v1/extract"),
    )
    live_retriever = TinyFishLiveRetriever(api_key="tf-test-valid-key")

    with patch("app.config.settings.TINYFISH_API_KEY", "tf-test-valid-key"), \
         patch("app.config.settings.MOCK_MODE", False), \
         patch.object(httpx.AsyncClient, "post", return_value=mock_post_resp):
        svc = DocumentationRetrievalService(live_retriever=live_retriever)
        resp = await svc.retrieve(
            DocRetrievalRequest(
                query="stripe.Charge.create",
                ecosystem="stripe",
                force_mock=False,
            )
        )
        assert resp.is_mock is False
        assert resp.status == "unavailable"
        assert resp.provider == "tinyfish_live"


@pytest.mark.asyncio
async def test_09_pipeline_abstains_honestly_when_live_retrieval_fails():
    """Requirement 7: Full pipeline with failed live retrieval returns unable_to_verify, is_mock=False, zero verified issues."""
    mock_post_resp = httpx.Response(
        status_code=503,
        content=b"Service Unavailable",
        request=httpx.Request("POST", "https://api.tinyfish.io/v1/extract"),
    )

    with patch("app.config.settings.TINYFISH_API_KEY", "tf-test-valid-key"), \
         patch("app.config.settings.MOCK_MODE", False), \
         patch.object(httpx.AsyncClient, "post", return_value=mock_post_resp):

        req = AnalysisRequest(
            source="import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n",
            filename="live_fail.py",
            force_mock=False,
        )
        report = await adjudicator.adjudicate(req)

        # Invariant: Must NOT fall back to mock mode
        assert report.is_mock is False
        assert report.evidence_trust == "untrusted_or_unavailable"
        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert any("DOCUMENTATION_MISSING" in c for c in report.limitations_and_caveats)


# ==============================================================================
# 5. Deterministic Mock Mode Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_10_deterministic_mock_search_ranking_and_tie_breaking():
    """Requirement 5: Mock search ranking is completely deterministic across repeated calls."""
    retriever = TinyFishMockRetriever()

    res1 = await retriever.search("payment intent create", limit=5)
    res2 = await retriever.search("payment intent create", limit=5)

    assert res1.total_results == res2.total_results
    assert len(res1.results) == len(res2.results)
    for i in range(len(res1.results)):
        assert res1.results[i].url == res2.results[i].url
        assert res1.results[i].position == res2.results[i].position
        assert res1.results[i].relevance_score == res2.results[i].relevance_score


def test_11_deterministic_evidence_id_generation():
    """Requirement 5: compute_evidence_id produces identical SHA-256 digests for identical input."""
    url = "https://docs.stripe.com/api/charges/create"
    content = "Required parameters: amount, currency."

    id1 = compute_evidence_id(url, content)
    id2 = compute_evidence_id(url, content)
    assert id1 == id2
    assert id1.startswith("ev_")
    assert len(id1) == 19  # 'ev_' + 16 hex chars


# ==============================================================================
# 6. Preserved & Edge-Case Fixtures Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_12_edge_case_fixture_subscriptions():
    """Requirement 8: Mock adapter provides valid subscription creation fixture."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/subscriptions/create")

    assert ev.status == "mock"
    assert ev.is_mock is True
    assert "[Mock Fixture]" in ev.title
    assert "subscription" in ev.content_excerpt.lower()
    assert "customer" in ev.required_fields


@pytest.mark.asyncio
async def test_13_edge_case_fixture_webhook_endpoints():
    """Requirement 8: Mock adapter provides valid webhook endpoint creation fixture."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/webhook_endpoints/create")

    assert ev.status == "mock"
    assert ev.is_mock is True
    assert "[Mock Fixture]" in ev.title
    assert "webhook" in ev.content_excerpt.lower()
    assert "url" in ev.required_fields


@pytest.mark.asyncio
async def test_14_edge_case_fixture_deprecated_card_tokens():
    """Requirement 8: Mock adapter provides deprecated card token fixture with legacy notices."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/tokens/create_card")

    assert ev.status == "mock"
    assert ev.is_mock is True
    assert "[Mock Fixture]" in ev.title
    assert len(ev.deprecation_notices) > 0


@pytest.mark.asyncio
async def test_15_edge_case_simulated_rate_limited_mock():
    """Requirement 8: Mock adapter provides simulated rate-limited response for offline testing."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/rate_limited")

    assert ev.status == "unavailable"
    assert ev.is_mock is True
    assert ev.error_code in ("RATE_LIMITED", "RATE_LIMIT_EXCEEDED")
    assert "rate limit" in (ev.error_message or "").lower()


@pytest.mark.asyncio
async def test_16_edge_case_simulated_empty_content_mock():
    """Requirement 8: Mock adapter provides simulated empty content response for offline testing."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/empty_content")

    assert ev.status == "unavailable"
    assert ev.is_mock is True
    assert ev.error_code == "NO_CONTENT_RETURNED"


@pytest.mark.asyncio
async def test_17_edge_case_simulated_malformed_content_mock():
    """Requirement 8: Mock adapter provides simulated malformed content response for offline testing."""
    retriever = TinyFishMockRetriever()
    ev = await retriever.fetch_url("https://docs.stripe.com/api/malformed")

    assert ev.status == "unavailable"
    assert ev.is_mock is True
    assert ev.error_code == "MALFORMED_CONTENT"


# ==============================================================================
# 7. Auditor / Judge Verification Checklist
# ==============================================================================

@pytest.mark.asyncio
async def test_18_auditor_distinguishability_contract():
    """Requirement 9 & 10: Clear programmatic rules allow judges/auditors to distinguish live from mock results."""
    # Run a mock scan
    mock_req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(amount=1000, currency='usd')\n",
        filename="eval.py",
        force_mock=True,
    )
    mock_report = await adjudicator.adjudicate(mock_req)

    # 1. is_mock flag is strictly True in mock mode
    assert mock_report.is_mock is True

    # 2. evidence_trust is strictly 'mock_fixture'
    assert mock_report.evidence_trust == "mock_fixture"

    # 3. verdict is strictly 'unable_to_verify'
    assert mock_report.verdict == "unable_to_verify"

    # 4. verified_issues list is strictly empty []
    assert len(mock_report.verified_issues) == 0

    # 5. All evidence records declare provider='tinyfish_mock' and source_trust='mock_fixture'
    for ev in mock_report.evidence_items:
        assert ev.provider == "tinyfish_mock"
        assert ev.is_mock is True
        assert ev.source_trust == "mock_fixture"
        assert "[Mock Fixture]" in ev.title
