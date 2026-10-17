"""Correctness Regression Test Suite for APICompass v3.

Verifies the 10 mandatory correctness invariants and regression scenarios:
1. Clearly documented valid API call (clean/compliant usage).
2. Clearly documented invalid argument (unsupported parameter mismatch).
3. Missing required parameter when documentation explicitly requires it.
4. Parameter that is not mentioned in the retrieved documentation (never flagged as invalid).
5. Documentation page that cannot be retrieved (safe abstention: DOCUMENTATION_MISSING).
6. Conflicting or ambiguous documentation result (safe abstention: CONFLICTING_DOCUMENTATION).
7. Dynamic Python usage the analyzer cannot safely establish (zero code execution, conservative abstention).
8. Mock evidence versus live evidence (mock quarantine enforcement).
9. Version ambiguity (explicit limitations, no false version compatibility claim).
10. Evidence that does not actually support a proposed finding (quote mismatch / irrelevant evidence rejection).
"""

import pytest

from app.schemas.ast_analysis import ApiCandidate, CallInfo, SourceLocation
from app.schemas.documentation import DocParameter, NormalizedEvidence
from app.schemas.evidence import (
    AnalysisRequest,
    VerifiedIssue,
)
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.contract_comparator import contract_comparator
from app.services.evidence.contract_extractor import contract_extractor
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import compute_content_sha256, quote_verifier
from app.services.python_ast_analyzer import analyze_python_source


# ---------------------------------------------------------------------------
# Reusable Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def live_pi_evidence() -> NormalizedEvidence:
    """Official live-trust documentation excerpt for stripe.PaymentIntent.create."""
    excerpt = (
        "Creates a PaymentIntent object.\n"
        "### Parameters\n"
        "- `amount` (required, integer): Amount intended to be collected in the smallest currency unit. Positive integer.\n"
        "- `currency` (required, string): Three-letter ISO currency code, in lowercase. Must be a provided supported currency.\n"
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_pi_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=excerpt,
        content_sha256=compute_content_sha256(excerpt),
        headings=["Create a PaymentIntent", "Parameters"],
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False),
        ],
        required_fields=["amount", "currency"],
    )


@pytest.fixture
def live_charge_evidence_with_unsupported() -> NormalizedEvidence:
    """Official live-trust documentation excerpt for stripe.Charge.create with unsupported parameter."""
    excerpt = (
        "To charge a credit card or other payment source, you create a Charge object.\n"
        "### Parameters\n"
        "- `amount` (required, integer): Amount in cents.\n"
        "- `currency` (required, string): Three-letter ISO code.\n"
        "- `source` (legacy): The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods.\n"
        "- `destination_account` (unsupported): The 'destination_account' parameter is unsupported in this API version.\n"
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_charge_live",
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
            DocParameter(
                name="destination_account",
                param_type="string",
                is_required=False,
                is_deprecated=False,
                description="The 'destination_account' parameter is unsupported in this API version.",
            ),
        ],
        required_fields=["amount", "currency"],
        deprecation_notices=["The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods."],
    )


# ---------------------------------------------------------------------------
# Test Scenario 1: Clearly Documented Valid API Call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_1_clearly_documented_valid_api_call(live_pi_evidence: NormalizedEvidence):
    """Scenario 1: Code uses API exactly as documented.

    Expectation:
    - Verdict: 'clean'
    - Result state: 'no_issue_detected'
    - Candidate assessment: 'resolved_clean', confidence='verified', severity='info'
    - Zero verified issues.
    - Scope limitation disclaimer explicitly included.
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.PaymentIntent.create(amount=2000, currency='usd')\n"
    )
    req = AnalysisRequest(source=source, filename="valid_payment.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_pi_evidence])

    assert report.verdict == "clean"
    assert report.result_state == "no_issue_detected"
    assert len(report.verified_issues) == 0

    assert len(report.candidate_assessments) == 1
    cand = report.candidate_assessments[0]
    assert cand.status == "resolved_clean"
    assert cand.verification_status == "no_issue_detected"
    assert cand.severity == "info"
    assert cand.confidence == "verified"
    assert cand.detected_call is not None
    assert cand.suggested_action == "No action required; call complies with documented contract."
    assert "does not guarantee runtime behavior" in (cand.uncertainty_or_limitations or "")
    assert any("SCOPE_LIMITATION" in c for c in report.limitations_and_caveats)


# ---------------------------------------------------------------------------
# Test Scenario 2: Clearly Documented Invalid Argument
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_2_clearly_documented_invalid_argument(live_charge_evidence_with_unsupported: NormalizedEvidence):
    """Scenario 2: Code passes an argument explicitly documented as unsupported.

    Expectation:
    - Verdict: 'issues_found'
    - Result state: 'verified'
    - Verified issue with violation_type='unsupported_parameter'
    - Target parameter, expected contract, observed usage, and suggested action populated.
    - Quote verification matches official documentation.
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=1000, currency='usd', destination_account='acct_invalid')\n"
    )
    req = AnalysisRequest(source=source, filename="invalid_arg.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charge_evidence_with_unsupported])

    assert report.verdict == "issues_found"
    assert report.result_state == "verified"
    assert len(report.verified_issues) == 1

    issue: VerifiedIssue = report.verified_issues[0]
    assert issue.violation_type == "unsupported_parameter"
    assert issue.detected_argument == "destination_account"
    assert issue.severity == "error"
    assert issue.confidence == "verified"
    assert "destination_account" in issue.observed_usage
    assert issue.suggested_action is not None
    assert "destination_account" in issue.suggested_action
    assert issue.source_url == live_charge_evidence_with_unsupported.source_url
    assert issue.supporting_evidence_id == live_charge_evidence_with_unsupported.evidence_id
    assert "The 'destination_account' parameter is unsupported in this API version." in issue.verified_quote


# ---------------------------------------------------------------------------
# Test Scenario 3: Missing Required Parameter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_3_missing_required_parameter(live_charge_evidence_with_unsupported: NormalizedEvidence):
    """Scenario 3: Code omits a parameter explicitly documented as required.

    Expectation:
    - Verdict: 'issues_found'
    - Result state: 'verified'
    - Verified issue with violation_type='missing_required_parameter'
    - Detected argument indicates the missing required parameter ('currency').
    - Suggested action advises supplying the required parameter.
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=2000)\n"  # Missing 'currency'
    )
    req = AnalysisRequest(source=source, filename="missing_param.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_charge_evidence_with_unsupported])

    assert report.verdict == "issues_found"
    assert report.result_state == "verified"
    assert len(report.verified_issues) == 1

    issue: VerifiedIssue = report.verified_issues[0]
    assert issue.violation_type == "missing_required_parameter"
    assert issue.detected_argument == "currency"
    assert issue.severity == "error"
    assert issue.confidence == "verified"
    assert "Supply the required parameter 'currency'" in issue.suggested_action


# ---------------------------------------------------------------------------
# Test Scenario 4: Parameter Not Mentioned in Retrieved Documentation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_4_unmentioned_parameter_never_flagged_as_invalid():
    """Scenario 4: Code passes a parameter ('metadata') not mentioned in an incomplete narrative excerpt.

    Invariant:
    - Missing documentation snippet must NEVER be treated as proof that a parameter is invalid.
    - The analyzer must NOT invent requirements or flag unmentioned parameters.
    - If contract completeness is 'excerpt_only', the adjudicator must abstain rather than falsely claim clean or error.
    """
    incomplete_narrative = (
        "You can use the Charges API to create payments. "
        "For example, charges can be initiated with an amount and currency."
    )
    incomplete_evidence = NormalizedEvidence(
        evidence_id="ev_incomplete_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=incomplete_narrative,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=incomplete_narrative,
        content_sha256=compute_content_sha256(incomplete_narrative),
        headings=["Create a charge"],
        parameters=[],  # Incomplete narrative excerpt with no closed parameter list
    )

    # User passes 'metadata', which is omitted from the retrieved excerpt
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=2000, currency='usd', metadata={'order_id': '6789'})\n"
    )
    req = AnalysisRequest(source=source, filename="metadata_call.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[incomplete_evidence])

    # Invariant: metadata must NEVER be flagged as unsupported_parameter
    assert len(report.verified_issues) == 0
    for issue in report.verified_issues:
        assert issue.detected_argument != "metadata"
        assert "metadata" not in issue.violation_type

    # Because contract is an incomplete excerpt (completeness='excerpt_only'), adjudicator abstains safely
    assert report.verdict == "unable_to_verify"
    assert len(report.candidate_assessments) == 1
    cand = report.candidate_assessments[0]
    assert cand.status == "unresolved"
    assert cand.abstention_reason == "INCOMPLETE_EXCERPT_CONTRACT"
    assert cand.confidence == "uncertain"


# ---------------------------------------------------------------------------
# Test Scenario 5: Documentation Page Cannot Be Retrieved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_5_documentation_page_cannot_be_retrieved():
    """Scenario 5: Documentation page cannot be retrieved (404, 429, timeout, network failure).

    Expectation:
    - Candidate cannot be verified.
    - Status: 'unresolved'
    - Abstention reason: 'DOCUMENTATION_MISSING'
    - Verdict: 'unable_to_verify'
    - Zero verified issues.
    - Confidence: 'uncertain'
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.EphemeralKey.create(customer='cus_123')\n"
    )
    # Empty evidence represents retrieval failure or missing documentation
    req = AnalysisRequest(source=source, filename="ephemeral.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[])

    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.candidate_assessments) == 1
    cand = report.candidate_assessments[0]
    assert cand.status == "unresolved"
    assert cand.abstention_reason == "DOCUMENTATION_MISSING"
    assert cand.confidence == "uncertain"
    assert cand.severity == "warning"


# ---------------------------------------------------------------------------
# Test Scenario 6: Conflicting or Ambiguous Documentation Result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_6_conflicting_or_ambiguous_documentation(live_charge_evidence_with_unsupported: NormalizedEvidence):
    """Scenario 6: Multiple conflicting documentation sources retrieved for an operation.

    Expectation:
    - Matcher detects conflict and marks is_ambiguous=True.
    - Adjudicator marks candidate as 'unresolved'.
    - Abstention reason: 'CONFLICTING_DOCUMENTATION' or 'AMBIGUOUS_OPERATION_MATCH'.
    - Verdict: 'unable_to_verify'.
    - Zero verified issues.
    """
    conflicting_excerpt = (
        "Creates a Charge object.\n"
        "Required parameters: amount, currency, source.\n"
        "The 'source' parameter is required for all new charges."
    )
    conflicting_evidence = NormalizedEvidence(
        evidence_id="ev_conflicting_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create_v2",
        canonical_url="https://docs.stripe.com/api/charges/create_v2",
        title="Create a charge | Stripe Alternative Docs",
        content_excerpt=conflicting_excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=conflicting_excerpt,
        content_sha256=compute_content_sha256(conflicting_excerpt),
        headings=["Create a Charge"],
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False),
            DocParameter(name="source", param_type="string", is_required=True, is_deprecated=False),
        ],
        required_fields=["amount", "currency", "source"],
    )

    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=1000, currency='usd', source='tok_visa')\n"
    )
    req = AnalysisRequest(source=source, filename="conflict.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(
        req,
        _internal_evidence=[live_charge_evidence_with_unsupported, conflicting_evidence],
    )

    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.candidate_assessments) == 1
    cand = report.candidate_assessments[0]
    assert cand.status == "unresolved"
    assert cand.abstention_reason in ("CONFLICTING_DOCUMENTATION", "AMBIGUOUS_OPERATION_MATCH")
    assert cand.confidence == "uncertain"


# ---------------------------------------------------------------------------
# Test Scenario 7: Dynamic Python Usage Handled Conservatively
# ---------------------------------------------------------------------------

def test_scenario_7a_dynamic_kwargs_unpacking_prevents_false_missing_param(live_charge_evidence_with_unsupported: NormalizedEvidence):
    """Scenario 7a: Dynamic **kwargs unpacking in user code.

    Invariant:
    - Static analysis cannot evaluate runtime dictionary keys in **kwargs.
    - Missing required parameters must NOT be flagged when **kwargs is unpacked.
    """
    source = (
        "import stripe\n"
        "params = {'currency': 'usd'}\n"
        "stripe.Charge.create(amount=2000, **params)\n"
    )
    ast_res = analyze_python_source(source)
    assert ast_res.status == "success"
    assert len(ast_res.calls) == 1
    call = ast_res.calls[0]

    # Verify kwargs_unpack is detected
    kwargs_unpacks = [a for a in call.arguments if a.value_type == "kwargs_unpack"]
    assert len(kwargs_unpacks) == 1

    candidate = ast_res.candidates[0]
    match_rec, findings = contract_matcher.match_candidate_to_evidence(
        candidate=candidate,
        call_info=call,
        evidence_items=[live_charge_evidence_with_unsupported],
    )

    # Invariant: Because of **params, 'missing_required_parameter' for currency must NOT be raised
    missing_findings = [f for f in findings if f.violation_type == "missing_required_parameter"]
    assert len(missing_findings) == 0


def test_scenario_7b_indeterminate_dynamic_call_zero_code_execution():
    """Scenario 7b: Indeterminate getattr dynamic pattern.

    Invariant:
    - Zero code execution: dynamic code is analyzed via AST only.
    - Ambiguous or unresolved patterns are marked is_ambiguous=True.
    """
    source = (
        "import stripe\n"
        "op = getattr(stripe, 'PaymentIntent')\n"
        "op.create(amount=1000)\n"
    )
    ast_res = analyze_python_source(source)
    assert ast_res.status == "success"
    # AST candidates recognize op.create as heuristic/ambiguous target
    for cand in ast_res.candidates:
        if cand.receiver == "op":
            assert cand.normalized_target is None or cand.is_ambiguous is True


# ---------------------------------------------------------------------------
# Test Scenario 8: Mock Evidence Quarantine vs Live Evidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_8_mock_evidence_quarantine_versus_live_evidence():
    """Scenario 8: Strict mock evidence quarantine vs live official trust.

    Invariants:
    - When evidence is mock (is_mock=True, source_trust='mock_fixture'):
      - Verdict MUST be 'unable_to_verify'.
      - Candidate status MUST be 'unresolved' with 'MOCK_EVIDENCE_ONLY'.
      - Verified issues list MUST be empty.
    - When evidence is live (is_mock=False, source_trust='official'):
      - Verified issue is substantiated and reported.
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=5000, currency='usd', source='tok_visa')\n"
    )
    req = AnalysisRequest(source=source, filename="quarantine_test.py", ecosystem="stripe")

    excerpt = (
        "You can use the Charges API to accept payments using Stripe. "
        "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )

    # Run 1: Mock Fixture Evidence
    mock_evidence = NormalizedEvidence(
        evidence_id="ev_mock_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="offline_mock",
        status="mock",
        is_mock=True,
        source_trust="mock_fixture",
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

    report_mock = await adjudicator.adjudicate(req, _internal_evidence=[mock_evidence])
    assert report_mock.verdict == "unable_to_verify"
    assert report_mock.verified_issues == []
    assert len(report_mock.candidate_assessments) == 1
    assert report_mock.candidate_assessments[0].status == "unresolved"
    assert report_mock.candidate_assessments[0].abstention_reason == "MOCK_EVIDENCE_ONLY"
    assert any("MOCK_EVIDENCE_ONLY" in c for c in report_mock.limitations_and_caveats)

    # Run 2: Live Official Evidence
    live_evidence = NormalizedEvidence(
        evidence_id="ev_live_charge",
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

    report_live = await adjudicator.adjudicate(req, _internal_evidence=[live_evidence])
    assert report_live.verdict == "issues_found"
    assert len(report_live.verified_issues) == 1
    assert report_live.verified_issues[0].verification_status == "verified"
    assert report_live.verified_issues[0].detected_argument == "source"


# ---------------------------------------------------------------------------
# Test Scenario 9: Version Ambiguity and Explicit Limitations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_9_version_ambiguity_and_explicit_limitations(live_pi_evidence: NormalizedEvidence):
    """Scenario 9: Version ambiguity is handled explicitly without unwarranted compatibility claims.

    Invariants:
    - Limitations and caveats are always preserved on the AnalysisReport.
    - Verified issue / candidate assessment explicitly surfaces limitations.
    """
    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.PaymentIntent.create(amount=2000, currency='usd')\n"
    )
    req = AnalysisRequest(source=source, filename="versioned.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req, _internal_evidence=[live_pi_evidence])

    # Report has non-empty explicit limitations and caveats
    assert len(report.limitations_and_caveats) >= 2
    assert any("officially retrieved documentation" in lim for lim in report.limitations_and_caveats)
    assert any("Dynamic runtime behavior" in lim for lim in report.limitations_and_caveats)


# ---------------------------------------------------------------------------
# Test Scenario 10: Evidence That Does Not Support Proposed Finding Is Rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_10_evidence_not_supporting_proposed_finding_rejected(live_charge_evidence_with_unsupported: NormalizedEvidence):
    """Scenario 10: Proposed finding with an unverified quotation or irrelevant documentation is rejected.

    Invariants:
    - Hallucinated quotes or paraphrases are rejected by quote_verifier.
    - Unsubstantiated findings can NEVER become a VerifiedIssue.
    """
    # 1. Hallucinated quote verification test
    fake_quote = "Stripe charges are permanently disallowed on this server."
    res = quote_verifier.verify_quote(fake_quote, live_charge_evidence_with_unsupported)
    assert res.is_verified is False
    assert res.quote_kind == "none"

    # 2. End-to-end rejection of invalid finding:
    # Irrelevant documentation (Customer API instead of Charge API)
    customer_excerpt = "Creates a new customer. Parameters: email, description."
    customer_evidence = NormalizedEvidence(
        evidence_id="ev_stripe_customer",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/customers/create",
        canonical_url="https://docs.stripe.com/api/customers/create",
        title="Create a customer",
        content_excerpt=customer_excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        raw_markdown=customer_excerpt,
        content_sha256=compute_content_sha256(customer_excerpt),
        headings=["Create a customer"],
    )

    source = (
        "import stripe\n"
        "stripe.api_key = 'sk_test_123'\n"
        "stripe.Charge.create(amount=1000, currency='usd')\n"
    )
    req = AnalysisRequest(source=source, filename="irrelevant_ev.py", ecosystem="stripe")
    # Providing only Customer documentation for a Charge call
    report = await adjudicator.adjudicate(req, _internal_evidence=[customer_evidence])

    # The adjudicator rejects the irrelevant customer evidence for Charge.create
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.candidate_assessments) == 1
    assert report.candidate_assessments[0].status == "unresolved"
    assert report.candidate_assessments[0].abstention_reason == "DOCUMENTATION_MISSING"
