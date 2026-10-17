"""Hardened Test Suite — Evidence Court.

Tests all core and hardened invariants:
1. Exact quotation matches
2. Missing quotation fails verification
3. Similar but nonidentical wording does not count as exact match
4. Whitespace-normalized matches are labeled distinctly
5. Evidence hashes are deterministic
6. Missing provenance prevents a verified source claim
7. A relevant but incomplete excerpt does not establish a violation
8. A complete documented contract can support a specific parameter violation
9. An undocumented method alone does not establish an error
10. Ambiguous operation matching leads to abstention
11. Missing documentation leads to abstention
12. Provider unavailable leads to abstention
13. Mock evidence cannot produce a production clean verdict
14. Mock evidence cannot produce a production issues_found verdict (verified_issues must be empty)
15. A valid live-trust synthetic evidence fixture can support a clean result via internal injection
16. A valid live-trust synthetic evidence fixture can support an issues_found result via internal injection
17. An unresolved candidate is preserved when another candidate has a confirmed issue
18. Invalid Python produces a structured analysis result
19. Dangerous-looking source calls are never executed
20. Evidence from an unapproved domain is not trusted
21. A quotation attributed to the wrong source is rejected
22. A stale or version-inapplicable document leads to abstention
23. Overall verdict precedence behaves as documented
24. The unified endpoint works with mock mode and truthfully abstains
25. Existing AST endpoint regression
26. Existing documentation retrieval endpoint regression
27. Existing health and CORS regressions
28. Oversized request rejection
29. Hardened Invariant: Mock retrieval cannot produce verified issues
30. Hardened Invariant: Client cannot elevate evidence trust via HTTP request body
31. Hardened Invariant: Unknown trust injection fields are rejected by schema
32. Hardened Invariant: Zero recognized API candidates does not certify clean (NO_IN_SCOPE_CANDIDATES)
33. Hardened Invariant: Unsupported API ecosystem does not certify clean
34. Hardened Invariant: Unrecognized dynamic API call does not certify clean
35. Hardened Invariant: Internal analysis failure does not produce clean
36. Hardened Invariant: Supported call with complete live contract produces clean
37. Hardened Invariant: api.stripe.com is strictly rejected as a documentation host
38. Hardened Invariant: Mixed evidence quarantine prevents upgrading mock claims
39. Hardened Invariant: Fake official-looking lookalike URL is rejected
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from app.main import app
from app.schemas.ast_analysis import ApiCandidate, CallInfo, SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import (
    AnalysisRequest,
    QuoteVerificationRequest,
)
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import compute_content_sha256, quote_verifier
from app.services.documentation.security import validate_destination_url


@pytest.fixture
def sample_evidence() -> NormalizedEvidence:
    """Fixture providing authentic Stripe Charges documentation evidence (mock)."""
    excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
        "However, Stripe now recommends using the Payment Intents API, which provides a unified "
        "integration flow and supports dynamic authentication mechanisms. "
        "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_charges_create",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_mock",
        status="mock",
        is_mock=True,
        source_trust="official",
        doc_version="2024-04-10",
        error_code=None,
        error_message=None,
    )


@pytest.fixture
def live_charges_evidence() -> NormalizedEvidence:
    """Fixture providing authentic live-trust Stripe documentation evidence."""
    excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
        "However, Stripe now recommends using the Payment Intents API, which provides a unified "
        "integration flow and supports dynamic authentication mechanisms. "
        "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_charges_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        error_code=None,
        error_message=None,
    )


@pytest.fixture
def live_payment_intent_evidence() -> NormalizedEvidence:
    """Fixture providing authentic live-trust Stripe PaymentIntents documentation evidence."""
    excerpt = (
        "Creates a PaymentIntent object. A PaymentIntent guides you through the process of collecting "
        "a payment from your customer. We recommend using PaymentIntents for all new integrations. "
        "Parameters: amount (integer in cents), currency (three-letter ISO currency code), "
        "automatic_payment_methods (dictionary enabling automated payment method selection)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_pi_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        error_code=None,
        error_message=None,
    )


# 1. Exact quotation matches
def test_01_exact_quotation_matches(sample_evidence: NormalizedEvidence):
    exact_quote = "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods."
    res = quote_verifier.verify_quote(exact_quote, sample_evidence)
    assert res.is_verified is True
    assert res.match_method == "exact"
    assert res.matched_text == exact_quote
    assert res.evidence_id == sample_evidence.evidence_id
    assert res.source_url == sample_evidence.canonical_url
    assert res.error_message is None


# 2. Missing quotation fails verification
def test_02_missing_quotation_fails_verification(sample_evidence: NormalizedEvidence):
    fake_quote = "This non-existent quote does not appear anywhere in the official documentation."
    res = quote_verifier.verify_quote(fake_quote, sample_evidence)
    assert res.is_verified is False
    assert res.match_method == "none"
    assert res.matched_text is None
    assert "not found" in (res.error_message or "").lower()


# 3. Similar but nonidentical wording does not count as an exact match
def test_03_similar_nonidentical_wording_fails_exact_match(sample_evidence: NormalizedEvidence):
    similar_quote = "The 'source' parameter is deprecated and PaymentIntents must always be used."
    res = quote_verifier.verify_quote(similar_quote, sample_evidence)
    assert res.is_verified is False
    assert res.match_method == "none"


# 4. Whitespace-normalized matches are labeled distinctly
def test_04_whitespace_normalized_matches_labeled_distinctly(sample_evidence: NormalizedEvidence):
    whitespace_quote = "The   'source'   parameter\n  is considered legacy;   PaymentIntents should be used"
    res = quote_verifier.verify_quote(whitespace_quote, sample_evidence, allow_whitespace_normalization=True)
    assert res.is_verified is True
    assert res.match_method == "whitespace_normalized"
    assert "The 'source' parameter is considered legacy; PaymentIntents should be used" in res.matched_text


# 5. Evidence hashes are deterministic
def test_05_evidence_hashes_are_deterministic(sample_evidence: NormalizedEvidence):
    hash1 = compute_content_sha256(sample_evidence.content_excerpt)
    hash2 = compute_content_sha256(sample_evidence.content_excerpt)
    assert hash1 == hash2
    assert len(hash1) == 64
    assert compute_content_sha256("different content") != hash1


# 6. Missing provenance prevents a verified source claim
def test_06_missing_provenance_prevents_verified_source_claim(sample_evidence: NormalizedEvidence):
    unapproved_ev = sample_evidence.model_copy(
        update={"canonical_url": "https://attacker.evil.com/fake-stripe-docs"}
    )
    res = quote_verifier.verify_quote("You can use the Charges API", unapproved_ev)
    assert res.is_verified is False
    assert "provenance" in (res.error_message or "").lower()


# 7. A relevant but incomplete excerpt does not establish a violation
def test_07_relevant_but_incomplete_excerpt_does_not_establish_violation():
    incomplete_ev = NormalizedEvidence(
        evidence_id="ev_incomplete",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges",
        canonical_url="https://docs.stripe.com/api/charges",
        title="Charge Object",
        content_excerpt="The Charge object represents a single payment attempt in Stripe.",
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(custom_param='val')",
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(custom_param='val')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["custom_param"],
        location=SourceLocation(lineno=1, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, call_info, [incomplete_ev])
    assert match_record is not None
    assert match_record.completeness == "excerpt_only"
    assert len(issues) == 0


# 8. A complete documented contract can support a specific parameter violation
def test_08_complete_documented_contract_supports_parameter_violation(live_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_charge_missing_amount",
        expression="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=2, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["currency"],
        location=SourceLocation(lineno=2, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, call_info, [live_charges_evidence])
    assert match_record is not None
    assert match_record.completeness == "complete_contract"
    assert len(issues) == 1
    assert issues[0].violation_type == "missing_required_parameter"
    assert "amount" in issues[0].explanation.lower()


# 9. An undocumented method alone does not establish an error
def test_09_undocumented_method_alone_does_not_establish_error(live_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_unknown_method",
        expression="stripe.CustomHelper.perform_action()",
        receiver="stripe.CustomHelper",
        target_name="perform_action",
        kind="method_call",
        confidence="heuristic",
        rationale="Unknown API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.CustomHelper.perform_action()",
        receiver="stripe.CustomHelper",
        method="perform_action",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=[],
        location=SourceLocation(lineno=1, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, call_info, [live_charges_evidence])
    assert match_record.completeness == "missing"
    assert len(issues) == 0


# 10. Ambiguous operation matching leads to abstention
def test_10_ambiguous_operation_matching_leads_to_abstention():
    ev_charge = NormalizedEvidence(
        evidence_id="ev_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges",
        canonical_url="https://docs.stripe.com/api/charges",
        title="Charge",
        content_excerpt="Charge documentation excerpt.",
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
    )
    ev_refund = NormalizedEvidence(
        evidence_id="ev_refund",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/refunds",
        canonical_url="https://docs.stripe.com/api/refunds",
        title="Refund",
        content_excerpt="Refund documentation excerpt.",
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
    )
    cand = ApiCandidate(
        candidate_id="cand_ambiguous",
        expression="stripe.process_charge_refund()",
        receiver="stripe",
        target_name="process_charge_refund",
        kind="method_call",
        confidence="heuristic",
        rationale="Ambiguous call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, None, [ev_charge, ev_refund])
    assert match_record.is_ambiguous is True
    assert len(issues) == 0


# 11. Missing documentation leads to abstention
@pytest.mark.asyncio
async def test_11_missing_documentation_leads_to_abstention():
    req = AnalysisRequest(
        source="import stripe\nstripe.NonExistentService.action()\n",
    )
    report = await adjudicator.adjudicate(req)
    assert report.verdict == "unable_to_verify"
    assert len(report.unresolved_candidates) > 0


# 12. Provider unavailable leads to abstention
@pytest.mark.asyncio
async def test_12_provider_unavailable_leads_to_abstention():
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(amount=1000, currency='usd')\n",
        force_mock=False,
    )
    report = await adjudicator.adjudicate(req)
    assert report.verdict == "unable_to_verify"


# 13. Mock evidence cannot produce a production clean verdict
@pytest.mark.asyncio
async def test_13_mock_evidence_cannot_produce_production_clean_verdict():
    req = AnalysisRequest(
        source="import stripe\nstripe.PaymentIntent.create(amount=2000, currency='usd')\n",
        force_mock=True,
    )
    report = await adjudicator.adjudicate(req)
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    assert report.verdict == "unable_to_verify"
    assert "MOCK_EVIDENCE_ONLY" in report.limitations_and_caveats[0]


# 14. Mock evidence cannot produce a production issues_found verdict (Finding 1 & 4)
@pytest.mark.asyncio
async def test_14_mock_evidence_cannot_produce_production_issues_found_verdict():
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n",
        force_mock=True,
    )
    report = await adjudicator.adjudicate(req)
    assert report.is_mock is True
    assert report.evidence_trust == "mock_fixture"
    # Strict mock quarantine: Must be unable_to_verify, and verified_issues MUST BE EMPTY!
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert "MOCK_EVIDENCE_ONLY" in report.limitations_and_caveats[0]


# 15. A valid live-trust synthetic evidence fixture can support a clean result via internal test injection
@pytest.mark.asyncio
async def test_15_live_trust_synthetic_evidence_can_support_clean_result(live_payment_intent_evidence: NormalizedEvidence):
    req = AnalysisRequest(
        source="import stripe\nstripe.PaymentIntent.create(amount=2000, currency='usd')\n",
    )
    # Synthetic live evidence injected internally (cannot be sent via HTTP)
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_payment_intent_evidence])
    assert report.evidence_trust == "live_official_source"
    assert report.is_mock is False
    assert report.verdict == "clean"
    assert len(report.verified_issues) == 0
    assert len(report.unresolved_candidates) == 0


# 16. A valid live-trust synthetic evidence fixture can support an issues_found result via internal test injection
@pytest.mark.asyncio
async def test_16_live_trust_synthetic_evidence_can_support_issues_found_result(live_charges_evidence: NormalizedEvidence):
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n",
    )
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charges_evidence])
    assert report.evidence_trust == "live_official_source"
    assert report.is_mock is False
    assert report.verdict == "issues_found"
    assert len(report.verified_issues) == 1
    assert report.verified_issues[0].violation_type == "legacy_deprecated_parameter"
    assert report.verified_issues[0].verified_quote != ""


# 17. An unresolved candidate is preserved when another candidate has a confirmed issue
@pytest.mark.asyncio
async def test_17_unresolved_candidate_preserved_when_another_has_confirmed_issue(live_charges_evidence: NormalizedEvidence):
    source = (
        "import stripe\n"
        "stripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n"
        "stripe.UnknownApi.unsupported_operation()\n"
    )
    req = AnalysisRequest(source=source)
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charges_evidence])
    assert report.verdict == "issues_found"
    assert len(report.verified_issues) == 1
    assert len(report.unresolved_candidates) == 1


# 18. Invalid Python produces a structured analysis result
@pytest.mark.asyncio
async def test_18_invalid_python_produces_structured_analysis_result():
    bad_python = "def broken_code(:\n    pass"
    req = AnalysisRequest(source=bad_python, filename="broken.py")
    report = await adjudicator.adjudicate(req)
    assert report.verdict == "unable_to_verify"
    assert report.syntax_error is not None
    assert report.syntax_error.lineno == 1


# 19. Dangerous-looking source calls are never executed
@pytest.mark.asyncio
async def test_19_dangerous_calls_are_never_executed():
    dangerous_code = "import os\nos.system('echo dangerous_call_marker')\n"
    req = AnalysisRequest(source=dangerous_code)
    report = await adjudicator.adjudicate(req)
    assert report is not None
    assert report.filename == "snippet.py"


# 20. Evidence from an unapproved domain is not trusted
def test_20_evidence_from_unapproved_domain_not_trusted():
    untrusted_ev = NormalizedEvidence(
        evidence_id="ev_fake",
        ecosystem="stripe",
        package="stripe",
        source_url="https://fake-stripe-docs.com/charges",
        canonical_url="https://fake-stripe-docs.com/charges",
        title="Fake Docs",
        content_excerpt="The source parameter is legacy.",
        retrieved_at="2026-10-17T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="untrusted",
    )
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(source='tok_visa')",
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, None, [untrusted_ev])
    assert match_record.completeness == "missing"
    assert len(issues) == 0


# 21. A quotation attributed to the wrong source is rejected
def test_21_quote_attributed_to_wrong_source_rejected(sample_evidence: NormalizedEvidence):
    res = quote_verifier.verify_quote(
        proposed_quote="The 'source' parameter is considered legacy",
        evidence=sample_evidence,
        expected_url="https://docs.stripe.com/api/payment_intents/create",
    )
    assert res.is_verified is False
    assert "mismatch" in (res.error_message or "").lower()


# 22. A stale or version-inapplicable document leads to abstention
def test_22_stale_or_version_inapplicable_document_leads_to_abstention(sample_evidence: NormalizedEvidence):
    stale_ev = sample_evidence.model_copy(update={"doc_version": "2015-01-01"})
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(source='tok_visa')",
        receiver="stripe.Charge",
        target_name="create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    match_record, issues = contract_matcher.match_candidate_to_evidence(cand, None, [stale_ev])
    assert match_record.completeness == "missing"
    assert len(issues) == 0


# 23. Overall verdict precedence behaves as documented
@pytest.mark.asyncio
async def test_23_overall_verdict_precedence_behaves_as_documented(live_charges_evidence: NormalizedEvidence):
    # Syntax error takes top precedence
    req_syntax = AnalysisRequest(source="def bad(:\n")
    report_syntax = await adjudicator.adjudicate(req_syntax)
    assert report_syntax.verdict == "unable_to_verify"
    assert report_syntax.syntax_error is not None

    # Issues found takes precedence over unresolved in live mode
    req_issues = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(source='tok_123')\nstripe.Unknown.call()\n",
    )
    report_issues = await adjudicator.adjudicate(req_issues, _internal_evidence=[live_charges_evidence])
    assert report_issues.verdict == "issues_found"
    assert len(report_issues.unresolved_candidates) == 1


# 24. The unified endpoint works with mock mode and truthfully abstains
@pytest.mark.asyncio
async def test_24_unified_endpoint_works_with_mock_mode_and_truthfully_abstains():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_123')\n",
                "filename": "checkout.py",
                "force_mock": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "unable_to_verify"
        assert data["is_mock"] is True
        assert data["evidence_trust"] == "mock_fixture"
        assert len(data["verified_issues"]) == 0
        assert "MOCK MODE" in data["summary"]


# 25. Existing AST endpoint regression
@pytest.mark.asyncio
async def test_25_existing_ast_endpoint_regression():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze/python",
            json={"source": "import stripe\nstripe.Charge.create(amount=1000)\n"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["calls"]) == 1


# 26. Existing documentation retrieval endpoint regression
@pytest.mark.asyncio
async def test_26_existing_documentation_retrieval_endpoint_regression():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/docs/retrieve",
            json={"target_url": "https://docs.stripe.com/api/charges/create", "force_mock": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "mock"
        assert len(data["evidence"]) >= 1


# 27. Existing health and CORS regressions
@pytest.mark.asyncio
async def test_27_existing_health_and_cors_regression():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


# 28. Oversized request rejection
@pytest.mark.asyncio
async def test_28_oversized_request_rejection():
    oversized_source = "x = 1\n" * 30_000
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            json={"source": oversized_source},
        )
        assert response.status_code == 422


# 29. Hardened Invariant: Mock retrieval cannot produce verified issues (Finding 1)
@pytest.mark.asyncio
async def test_29_mock_retrieval_cannot_produce_verified_issues():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n",
                "force_mock": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "unable_to_verify"
        # Invariant 2 & 5: verified_issues MUST BE EMPTY under mock evidence
        assert data["verified_issues"] == []
        assert data["candidate_assessments"][0]["status"] == "unresolved"
        assert data["candidate_assessments"][0]["abstention_reason"] == "MOCK_EVIDENCE_ONLY"


# 30. Hardened Invariant: Client cannot elevate evidence trust via HTTP request body (Finding 2)
@pytest.mark.asyncio
async def test_30_client_cannot_elevate_evidence_trust_via_http():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Client attempts to send the removed 'test_trust_override' field to bypass quarantine
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n",
                "test_trust_override": "live_official_source",
            },
        )
        # extra="forbid" rejects the attempt with 422 Unprocessable Entity
        assert response.status_code == 422


# 31. Hardened Invariant: Unknown trust injection fields are rejected by schema (Finding 2)
@pytest.mark.asyncio
async def test_31_unknown_trust_injection_fields_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for forbidden_field in ["trust_level", "is_trusted", "override_trust", "mock_bypass"]:
            response = await client.post(
                "/api/v1/analyze",
                json={
                    "source": "import stripe\nstripe.PaymentIntent.create(amount=1000, currency='usd')\n",
                    forbidden_field: True,
                },
            )
            assert response.status_code == 422


# 32. Hardened Invariant: Zero recognized API candidates does not certify clean (Finding 3)
@pytest.mark.asyncio
async def test_32_zero_candidates_does_not_certify_clean():
    # Valid Python file with no API calls
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "x = 1\ny = 2\ndef add(a, b):\n    return a + b\nresult = add(x, y)\n",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Must be unable_to_verify, NEVER clean!
        assert data["verdict"] == "unable_to_verify"
        assert "NO_IN_SCOPE_CANDIDATES" in data["limitations_and_caveats"][0]
        assert "No supported in-scope API calls detected" in data["summary"]


# 33. Hardened Invariant: Unsupported API ecosystem does not certify clean (Finding 3)
@pytest.mark.asyncio
async def test_33_unsupported_ecosystem_does_not_certify_clean():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case A: Unsupported ecosystem explicitly specified
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import boto3\ns3 = boto3.client('s3')\ns3.get_object(Bucket='my-bucket', Key='data.csv')\n",
                "ecosystem": "aws",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "unable_to_verify"
        assert "UNSUPPORTED_ECOSYSTEM" in data["limitations_and_caveats"][0]

        # Case B: Code using unsupported library submitted under default Stripe ecosystem
        response2 = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import boto3\ns3 = boto3.client('s3')\ns3.get_object(Bucket='my-bucket', Key='data.csv')\n",
            },
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["verdict"] == "unable_to_verify"
        assert data2["candidate_assessments"][0]["status"] == "unresolved"


# 34. Hardened Invariant: Unrecognized dynamic API call does not certify clean (Finding 3)
@pytest.mark.asyncio
async def test_34_unrecognized_dynamic_call_does_not_certify_clean():
    # Dynamic reflection call that AST visitor cannot statically identify as a supported candidate
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/analyze",
            json={
                "source": "import stripe\ngetattr(stripe, 'Charge').__dict__['create'](amount=100)\n",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "unable_to_verify"


# 35. Hardened Invariant: Internal analysis failure does not produce clean (Finding 3)
@pytest.mark.asyncio
async def test_35_internal_analysis_failure_does_not_produce_clean():
    with patch("app.services.evidence.adjudicator.analyze_python_source", side_effect=RuntimeError("Simulated AST failure")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/analyze",
                json={"source": "import stripe\nstripe.Charge.create(amount=1000)\n"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["verdict"] == "unable_to_verify"
            assert "ANALYSIS_FAILURE" in data["limitations_and_caveats"][0]


# 36. Hardened Invariant: Supported call with complete live contract produces clean (Finding 3)
@pytest.mark.asyncio
async def test_36_supported_call_with_complete_live_contract_produces_clean(live_payment_intent_evidence: NormalizedEvidence):
    req = AnalysisRequest(
        source="import stripe\nstripe.PaymentIntent.create(amount=2000, currency='usd')\n",
    )
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_payment_intent_evidence])
    assert report.verdict == "clean"
    assert report.is_mock is False
    assert len(report.verified_issues) == 0
    assert len(report.candidate_assessments) == 1
    assert report.candidate_assessments[0].status == "resolved_clean"


# 37. Hardened Invariant: api.stripe.com is strictly rejected as a documentation host (Finding 5)
@pytest.mark.asyncio
async def test_37_rejection_of_api_stripe_com():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/docs/retrieve",
            json={"target_url": "https://api.stripe.com/v1/charges"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert "API/dashboard service endpoint" in data["message"]


# 38. Hardened Invariant: Mixed evidence quarantine prevents upgrading mock claims (Finding 1)
@pytest.mark.asyncio
async def test_38_mixed_evidence_quarantine(sample_evidence: NormalizedEvidence, live_charges_evidence: NormalizedEvidence):
    # Charge matches live, but overview matches mock
    mock_overview = sample_evidence.model_copy(
        update={"canonical_url": "https://docs.stripe.com/api", "is_mock": True, "provider": "tinyfish_mock"}
    )
    req = AnalysisRequest(
        source="import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n",
    )
    # Mixed evidence list containing mock items
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charges_evidence, mock_overview])
    # The presence of mock evidence contaminates the session: cannot claim live verification
    assert report.is_mock is True
    assert report.verdict == "unable_to_verify"


# 39. Hardened Invariant: Fake official-looking lookalike URL is rejected (Finding 5)
def test_39_fake_official_lookalike_url_rejected():
    lookalikes = [
        "https://docs.stripe.com.evil.com/api",
        "https://stripe.com.attacker.org/docs",
        "https://docs-stripe.com/api",
        "https://d0cs.stripe.com/api",
    ]
    for url in lookalikes:
        is_valid, _, err = validate_destination_url(url)
        assert is_valid is False
        assert "not in approved documentation allowlist" in (err or "")
