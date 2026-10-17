"""Strengthened Evidence Adjudication & Verification Test Suite.

Verifies:
1. Rejection of unsupported claims.
2. Rejection of wrong/hallucinated quotes.
3. Distinction between exact quotations and paraphrases.
4. Rejection of irrelevant pages/endpoints (resource mismatch).
5. Handling of conflicting documentation (uncertainty preservation).
6. Rejection of findings with missing sources.
7. Strict mock evidence quarantine (never certified as official quotation).
8. Defense against LLM suggestion elevation.
9. Explicit result states ('verified', 'unverified_suggestion', 'unable_to_verify', 'no_issue_detected').
10. Clean scan disclaimer (clean does not imply program correctness).
11. End-to-end provenance integrity.
"""

import pytest
from app.schemas.ast_analysis import ApiCandidate, CallInfo, SourceLocation
from app.schemas.contract import ContractFindingCandidate
from app.schemas.documentation import DocParameter, NormalizedDocPage, NormalizedEvidence
from app.schemas.evidence import (
    AnalysisReport,
    AnalysisRequest,
    CandidateAssessment,
    QuoteVerificationResult,
    VerifiedIssue,
)
from app.services.evidence.adjudicator import adjudicator, is_evidence_relevant
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import compute_content_sha256, quote_verifier
from app.services.llm.reasoning_service import LLMReasoningResponse, LLMReasoningService


@pytest.fixture
def live_charge_evidence() -> NormalizedEvidence:
    """Official live-trust documentation excerpt for Stripe Charges."""
    excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
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
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=excerpt,
        content_sha256=compute_content_sha256(excerpt),
        headings=["Create a charge", "Parameters"],
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False),
            DocParameter(name="source", param_type="string", is_required=False, is_deprecated=True),
        ],
        required_fields=["amount", "currency"],
        deprecation_notices=["The 'source' parameter is considered legacy; PaymentIntents should be used."],
    )


@pytest.fixture
def live_customer_evidence() -> NormalizedEvidence:
    """Official live-trust documentation excerpt for Stripe Customers (irrelevant to Charges)."""
    excerpt = (
        "Creates a new customer object. "
        "Required parameters: none. "
        "Optional parameters: email (string), description (string), source (legacy payment source token)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_customers_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/customers/create",
        canonical_url="https://docs.stripe.com/api/customers/create",
        title="Create a customer | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=excerpt,
        content_sha256=compute_content_sha256(excerpt),
        headings=["Create a customer", "Parameters"],
        parameters=[
            DocParameter(name="email", param_type="string", is_required=False, is_deprecated=False),
            DocParameter(name="description", param_type="string", is_required=False, is_deprecated=False),
            DocParameter(name="source", param_type="string", is_required=False, is_deprecated=False),
        ],
    )


@pytest.fixture
def mock_charge_evidence() -> NormalizedEvidence:
    """Synthetic mock fixture documentation excerpt for Stripe Charges."""
    excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
        "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_charges_mock",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference (Mock)",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_mock",
        status="mock",
        is_mock=True,
        source_trust="mock_fixture",
        doc_version="2024-04-10",
        raw_markdown=excerpt,
        content_sha256=compute_content_sha256(excerpt),
        headings=["Create a charge", "Parameters"],
    )


# 1. Test exact quotation matches and classifications
def test_01_exact_quotation_matches_and_classifies(live_charge_evidence: NormalizedEvidence):
    exact_text = "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods."
    res = quote_verifier.verify_quote(exact_text, live_charge_evidence)
    assert res.is_verified is True
    assert res.quote_kind == "exact_quotation"
    assert res.match_method == "exact"
    assert res.is_mock is False


# 2. Test wrong/hallucinated quotation is rejected
def test_02_wrong_quote_rejected(live_charge_evidence: NormalizedEvidence):
    fake_quote = "Stripe charges are completely disabled and you cannot make charges anymore."
    res = quote_verifier.verify_quote(fake_quote, live_charge_evidence)
    assert res.is_verified is False
    assert res.quote_kind == "none"
    assert "not found" in (res.error_message or "").lower()


# 3. Test distinction between exact quotations and paraphrases
def test_03_paraphrase_detected_and_rejected_as_exact_quotation(live_charge_evidence: NormalizedEvidence):
    # Altered paraphrase with key words matching excerpt
    paraphrase_quote = "The 'source' parameter is deprecated and PaymentIntents must be used for payment methods."
    res = quote_verifier.verify_quote(paraphrase_quote, live_charge_evidence)
    assert res.is_verified is False
    assert res.quote_kind == "paraphrase"
    assert "paraphrase" in (res.error_message or "").lower()

    # Explicitly claimed paraphrase is also rejected from exact quotation certification
    res_explicit = quote_verifier.verify_quote(
        paraphrase_quote,
        live_charge_evidence,
        claimed_quote_kind="paraphrase",
    )
    assert res_explicit.is_verified is False
    assert res_explicit.quote_kind == "paraphrase"


# 4. Test synthetic mock evidence is quarantined and rejected as official quotation
def test_04_synthetic_mock_evidence_quarantine(mock_charge_evidence: NormalizedEvidence):
    exact_text = "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods."
    
    # Raw check records is_mock=True
    res_raw = quote_verifier.verify_quote(exact_text, mock_charge_evidence)
    assert res_raw.is_mock is True

    # Official quote verification strictly rejects mock fixtures
    res_official = quote_verifier.verify_official_quote(exact_text, mock_charge_evidence)
    assert res_official.is_verified is False
    assert res_official.is_mock is True
    assert "mock" in (res_official.error_message or "").lower()


# 5. Test irrelevant pages are rejected by evidence relevance check
def test_05_irrelevant_pages_rejected(live_customer_evidence: NormalizedEvidence):
    candidate = ApiCandidate(
        candidate_id="cand_charge_create",
        expression="stripe.Charge.create(amount=1000, source='tok_visa')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        is_ambiguous=False,
        rationale="Recognized Stripe charge create call",
        location=SourceLocation(lineno=10, col_offset=4),
    )
    finding = ContractFindingCandidate(
        finding_id="find_test",
        candidate_id="cand_charge_create",
        source_location=SourceLocation(lineno=10, col_offset=4),
        violation_type="legacy_deprecated_parameter",
        claim_checked="Deprecated parameter 'source'",
        explanation="The source parameter is deprecated.",
        contract_quote="source (legacy payment source token)",
        supporting_evidence_id="ev_stripe_customers_live",
        source_url="https://docs.stripe.com/api/customers/create",
    )

    is_rel, err = is_evidence_relevant(candidate, finding, live_customer_evidence)
    assert is_rel is False
    assert "irrelevant" in (err or "").lower()


# 6. Test missing sources / missing evidence records are rejected
def test_06_missing_evidence_record_rejected():
    candidate = ApiCandidate(
        candidate_id="cand_charge_create",
        expression="stripe.Charge.create(amount=1000)",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        is_ambiguous=False,
        rationale="Recognized Stripe charge call",
        location=SourceLocation(lineno=10, col_offset=4),
    )
    is_rel, err = is_evidence_relevant(candidate, None, None)
    assert is_rel is False
    assert "missing" in (err or "").lower()


# 7. Test conflicting documentation across retrieved sources preserves uncertainty
def test_07_conflicting_documentation_preserves_uncertainty(live_charge_evidence: NormalizedEvidence):
    # Create conflicting evidence for the same operation where source is marked required
    conflicting_excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code), source (active payment token)."
    )
    conflicting_ev = NormalizedEvidence(
        evidence_id="ev_stripe_charges_conflicting",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference (Conflicting)",
        content_excerpt=conflicting_excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=conflicting_excerpt,
        content_sha256=compute_content_sha256(conflicting_excerpt),
        headings=["Create a charge", "Parameters"],
        parameters=[
            DocParameter(name="amount", is_required=True, is_deprecated=False),
            DocParameter(name="currency", is_required=True, is_deprecated=False),
            DocParameter(name="source", is_required=True, is_deprecated=False),  # Conflicts with deprecated in live_charge_evidence
        ],
        required_fields=["amount", "currency", "source"],
    )

    candidate = ApiCandidate(
        candidate_id="cand_charge_create",
        expression="stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        is_ambiguous=False,
        rationale="Recognized Stripe Charge call",
        location=SourceLocation(lineno=10, col_offset=4),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency", "source"],
        location=SourceLocation(lineno=10, col_offset=4),
    )

    match_record, findings = contract_matcher.match_candidate_to_evidence(
        candidate=candidate,
        call_info=call_info,
        evidence_items=[live_charge_evidence, conflicting_ev],
    )
    assert match_record is not None
    assert match_record.is_ambiguous is True
    assert "conflicting" in match_record.match_rationale.lower()
    assert findings == []


# 8. Test LLM cannot promote an unsupported AI suggestion into a verified result
@pytest.mark.asyncio
async def test_08_llm_cannot_promote_unsupported_suggestion(live_charge_evidence: NormalizedEvidence):
    class MaliciousLLMService(LLMReasoningService):
        async def reason(self, *args, **kwargs):
            from app.schemas.evidence import AISuggestion
            malicious_suggestion = AISuggestion(
                suggestion_id="sug_fake_exploit",
                candidate_id="cand_charge",
                claim_type="security_vulnerability",
                description="The LLM claims this line violates a security rule without proof.",
                unverified_aspects="This was generated by LLM reasoning alone.",
                suggested_documentation_queries=["stripe.Charge.create"],
                confidence="high",
            )
            resp = LLMReasoningResponse(
                status="available",
                provider="adversarial_llm",
                model="adversarial-gpt",
                overall_reasoning_summary="Adversarial suggestion injection test",
            )
            return resp, [malicious_suggestion], []

    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=5000, currency='usd', source='tok_visa')\n"
    )
    req = AnalysisRequest(
        source=source,
        filename="payment.py",
        ecosystem="stripe",
    )

    report = await adjudicator.adjudicate(
        req,
        _internal_evidence=[live_charge_evidence],
        _llm_service_override=MaliciousLLMService(),
    )

    # 1. AI suggestion is preserved under ai_suggestions
    assert len(report.ai_suggestions) == 1
    assert report.ai_suggestions[0].verification_status == "unverified_suggestion"
    assert report.ai_suggestions[0].label == "Unverified suggestion"

    # 2. No AI suggestion is in verified_issues
    for issue in report.verified_issues:
        assert not issue.supporting_evidence_id.startswith("llm_")
        assert issue.verification_status == "verified"
        assert issue.quote_kind in ("exact_quotation", "structured_contract")


# 9. Test clean scan disclaimer and explicit result state
@pytest.mark.asyncio
async def test_09_clean_scan_disclaimer_and_no_issue_detected_state():
    clean_pi_evidence = NormalizedEvidence(
        evidence_id="ev_stripe_pi_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt="Creates a PaymentIntent object. Parameters: amount (integer), currency (string).",
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        headings=["Create a PaymentIntent", "Parameters"],
        parameters=[
            DocParameter(name="amount", is_required=True, is_deprecated=False),
            DocParameter(name="currency", is_required=True, is_deprecated=False),
        ],
        required_fields=["amount", "currency"],
    )

    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.PaymentIntent.create(amount=2000, currency='usd')\n"
    )
    req = AnalysisRequest(source=source, filename="clean_pi.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[clean_pi_evidence])

    assert report.verdict == "clean"
    assert report.result_state == "no_issue_detected"
    assert "No issue detected within the checks performed" in report.summary
    assert "does not certify or imply that the entire program is correct" in report.summary
    assert any("SCOPE_LIMITATION" in c for c in report.limitations_and_caveats)


# 10. Test end-to-end provenance integrity on verified issues
@pytest.mark.asyncio
async def test_10_end_to_end_provenance_intact(live_charge_evidence: NormalizedEvidence):
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=5000, currency='usd', source='tok_visa')\n"
    )
    req = AnalysisRequest(source=source, filename="test_charge.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charge_evidence])

    assert report.verdict == "issues_found"
    assert report.result_state == "verified"
    assert len(report.verified_issues) == 1
    issue: VerifiedIssue = report.verified_issues[0]

    assert issue.verification_status == "verified"
    assert issue.quote_kind == "exact_quotation"
    assert issue.source_url == "https://docs.stripe.com/api/charges/create"
    assert issue.supporting_evidence_id == live_charge_evidence.evidence_id
    assert issue.source_location.lineno == 3
    assert issue.claim_checked != ""
    assert issue.evidence_rationale is not None
    assert "Verified against official documentation" in issue.evidence_rationale
    assert issue.supporting_excerpt == live_charge_evidence.content_excerpt
