"""Comprehensive test suite for APICompass Fix Proposal feature audit and hardening.

Verifies:
1. Valid fix: Evidence-supported verified correction with clean re-verification.
2. Invalid fix: Proposed change introduces syntax error, rejected as syntax_invalid.
3. Ambiguous evidence: Multiple conflicting operations or ambiguous documentation leads to
   abstention with explicit explanation of why automatic fix cannot be safely proposed.
4. Syntax regressions in input: Source code syntax error rejected at step 1.
5. Changes that do not actually address the finding:
   - Violation persists in proposed code -> reverification_status="concern_persists".
   - Candidate bypassed/deleted into non-API call -> reverification_status="reverification_inconclusive".
6. Prohibition on inventing runtime values, credentials, or resource identifiers.
7. Preservation of unrelated logic, indentation, and formatting.
8. Zero automatic code execution guarantee.
9. Clear distinction between verified_correction, suggested_patch, and ineligible.
"""

import re
import pytest
from app.schemas.ast_analysis import ApiCandidate, SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisReport, CandidateAssessment, EvidenceMatch, VerifiedIssue
from app.schemas.fix_proposal import FixProposalResponse, ProposeFixRequest
from app.services.fixes.fix_proposer import FixProposer, fix_proposer
from app.services.fixes.policy import evaluate_fix_eligibility


@pytest.fixture
def live_charges_evidence() -> NormalizedEvidence:
    """Fixture providing authentic live-trust Stripe Charges documentation."""
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
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


@pytest.fixture
def live_payment_intent_evidence() -> NormalizedEvidence:
    """Fixture providing authentic live-trust Stripe PaymentIntents documentation."""
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
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


# 1. Valid Fix: Evidence-Supported Verified Correction
@pytest.mark.asyncio
async def test_01_valid_fix_verified_correction(
    live_charges_evidence: NormalizedEvidence,
    live_payment_intent_evidence: NormalizedEvidence,
):
    source = (
        "import stripe\n"
        "def process_order(cart_id: str):\n"
        "    charge = stripe.Charge.create(\n"
        "        amount=2500,\n"
        "        currency='usd',\n"
        "        source='tok_1234567890',\n"
        "    )\n"
        "    return charge\n"
    )
    req = ProposeFixRequest(
        source=source,
        candidate_id="cand_001",
        filename="checkout.py",
    )

    res = await fix_proposer.propose_fix(
        req,
        _internal_evidence=[live_charges_evidence, live_payment_intent_evidence],
    )

    assert res.status == "evidence_supported"
    assert res.proposal_type == "verified_correction"
    assert res.syntax_valid is True
    assert res.reverification_status == "verified_resolved"
    assert res.is_mock is False
    assert res.evidence_trust == "live_official_source"

    # Verifies the replacement
    assert "PaymentIntent.create" in res.proposed_source
    assert "payment_method=" in res.proposed_source
    assert "source=" not in res.proposed_source

    # Verifies diff and excerpts
    assert res.unified_diff is not None
    assert "-    charge = stripe.Charge.create(" in res.unified_diff
    assert "+    charge = stripe.PaymentIntent.create(" in res.unified_diff

    # Explains why the proposed change addresses the finding
    assert "Payment Methods" in res.reasoning or "payment_method" in res.reasoning
    assert "legacy" in res.reasoning.lower() or "deprecated" in res.reasoning.lower()


# 2. Invalid Fix: Proposed Code Introduces Syntax Error
@pytest.mark.asyncio
async def test_02_invalid_fix_syntax_regression_rejected(
    live_charges_evidence: NormalizedEvidence,
):
    source = "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_123')\n"
    req = ProposeFixRequest(source=source, candidate_id="cand_001")

    # Custom generator that produces broken syntax (missing closing parenthesis)
    def broken_syntax_generator(src, cand, issue):
        orig = "stripe.Charge.create(amount=2000, currency='usd', source='tok_123')"
        broken = "stripe.PaymentIntent.create(amount=2000, currency='usd', payment_method='tok_123'  # MISSING PAREN"
        new_src = src.replace(orig, broken)
        return orig, broken, new_src, None

    res = await fix_proposer.propose_fix(
        req,
        _internal_evidence=[live_charges_evidence],
        _test_edit_generator=broken_syntax_generator,
    )

    assert res.status == "syntax_check_failed"
    assert res.proposal_type == "ineligible"
    assert res.syntax_valid is False
    assert res.reverification_status == "syntax_invalid"
    assert any("SYNTAX_ERROR" in w for w in res.warnings)
    assert "invalid python syntax" in res.reasoning.lower()


# 3. Ambiguous Evidence: Explains Why Fix Cannot Safely Be Proposed
@pytest.mark.asyncio
async def test_03_ambiguous_evidence_abstains_with_clear_explanation():
    # Ambiguous candidate assessment
    ambiguous_cand = CandidateAssessment(
        candidate_id="cand_ambig_1",
        target_name="retrieve",
        receiver="stripe.Webhook",
        call_expr="stripe.Webhook.retrieve('wh_123')",
        source_location=SourceLocation(lineno=1, col_offset=0),
        status="unresolved",
        abstention_reason="AMBIGUOUS_OPERATION_MATCH",
        explanation="Candidate matches both WebhookEndpoint.retrieve and Webhook.construct_event",
        evidence_match=EvidenceMatch(
            candidate_id="cand_ambig_1",
            matched_operation="stripe.Webhook",
            is_ambiguous=True,
            match_rationale="Conflicting documentation found for Webhook vs WebhookEndpoint",
        ),
    )

    status, warnings = evaluate_fix_eligibility(
        candidate=ambiguous_cand,
        verified_issue=None,
        evidence_items=[],
        is_mock=False,
        evidence_trust="live_official_source",
    )

    assert status == "insufficient_evidence"
    assert any("AMBIGUOUS_EVIDENCE" in w for w in warnings)

    # When processed through propose_fix with an ambiguous candidate assessment
    source = "import stripe\nstripe.Webhook.retrieve('wh_123')\n"
    req = ProposeFixRequest(source=source, candidate_id="cand_001")

    class MockAmbiguousAdjudicator:
        async def adjudicate(self, request, _internal_evidence=None):
            return AnalysisReport(
                verdict="unable_to_verify",
                summary="Analysis completed with ambiguous candidate.",
                engine_version="0.1.0",
                filename=request.filename,
                total_lines=2,
                evidence_trust="live_official_source",
                is_mock=False,
                candidate_assessments=[
                    CandidateAssessment(
                        candidate_id="cand_001",
                        target_name="retrieve",
                        receiver="stripe.Webhook",
                        call_expr="stripe.Webhook.retrieve('wh_123')",
                        source_location=SourceLocation(lineno=2, col_offset=0),
                        status="unresolved",
                        abstention_reason="AMBIGUOUS_OPERATION_MATCH",
                        explanation="Candidate matches both WebhookEndpoint.retrieve and Webhook.construct_event",
                        evidence_match=EvidenceMatch(
                            candidate_id="cand_001",
                            matched_operation="stripe.Webhook",
                            is_ambiguous=True,
                            match_rationale="Conflicting documentation found for Webhook vs WebhookEndpoint",
                        ),
                    )
                ],
                verified_issues=[],
                checks_performed=["AST parsing", "Ambiguity check"],
                evidence_items=[],
                limitations_and_caveats=["Ambiguous operation match"],
            )

    ambig_proposer = FixProposer(adjudicator_instance=MockAmbiguousAdjudicator())
    res = await ambig_proposer.propose_fix(req)

    assert res.status == "insufficient_evidence"
    assert res.proposal_type == "ineligible"
    assert res.reverification_status == "not_attempted"
    assert "ambiguous" in res.summary.lower()
    assert "manual developer review is required" in res.reasoning.lower()


# 4. Syntax Regression in Submitted Source Code
@pytest.mark.asyncio
async def test_04_submitted_source_syntax_error_rejected_at_step_one():
    broken_source = "import stripe\ndef invalid_function(:\n    pass\n"
    req = ProposeFixRequest(source=broken_source, candidate_id="cand_001")

    res = await fix_proposer.propose_fix(req)
    assert res.status == "syntax_check_failed"
    assert res.proposal_type == "ineligible"
    assert res.syntax_valid is False
    assert res.reverification_status == "syntax_invalid"
    assert "line 2" in res.reasoning.lower()


# 5. Changes that Do Not Actually Address the Finding (Violation Persists)
@pytest.mark.asyncio
async def test_05_edit_leaves_violation_intact_results_in_concern_persists(
    live_charges_evidence: NormalizedEvidence,
):
    source = "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_123')\n"
    req = ProposeFixRequest(source=source, candidate_id="cand_001")

    # Ineffective generator: alters amount but leaves deprecated 'source' on Charge.create
    def ineffective_generator(src, cand, issue):
        orig = "stripe.Charge.create(amount=2000, currency='usd', source='tok_123')"
        # Changed amount from 2000 to 5000, but legacy Charge.create with source remains!
        ineffective = "stripe.Charge.create(amount=5000, currency='usd', source='tok_123')"
        new_src = src.replace(orig, ineffective)
        return orig, ineffective, new_src, None

    res = await fix_proposer.propose_fix(
        req,
        _internal_evidence=[live_charges_evidence],
        _test_edit_generator=ineffective_generator,
    )

    # Re-verification must catch that the violation persists!
    assert res.reverification_status == "concern_persists"
    assert res.proposal_type == "suggested_patch"  # NOT verified_correction!
    assert any("CONCERN_PERSISTS" in w for w in res.warnings)


# 6. Changes that Eliminate/Bypass Candidate Rather Than Resolving
@pytest.mark.asyncio
async def test_06_edit_bypasses_candidate_results_in_inconclusive(
    live_charges_evidence: NormalizedEvidence,
):
    source = "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_123')\n"
    req = ProposeFixRequest(source=source, candidate_id="cand_001")

    # Bypassing generator: deletes Stripe call and replaces with unrelated local helper
    def bypassing_generator(src, cand, issue):
        orig = "stripe.Charge.create(amount=2000, currency='usd', source='tok_123')"
        bypassed = "local_unrelated_helper()"
        new_src = src.replace(orig, bypassed)
        return orig, bypassed, new_src, None

    res = await fix_proposer.propose_fix(
        req,
        _internal_evidence=[live_charges_evidence],
        _test_edit_generator=bypassing_generator,
    )

    # Merely having 0 verified issues because the call was deleted does NOT make it verified_resolved!
    assert res.reverification_status == "reverification_inconclusive"
    assert res.proposal_type == "suggested_patch"  # NOT verified_correction!
    assert any("DID_NOT_ADDRESS_FINDING" in w for w in res.warnings)


# 7. Prohibition on Inventing Runtime Values, Credentials, or Identifiers (Requirement 4)
def test_07_prohibition_on_inventing_runtime_values_for_missing_parameters():
    cand = CandidateAssessment(
        candidate_id="cand_charge_missing_amount",
        target_name="create",
        receiver="stripe.Charge",
        call_expr="stripe.Charge.create(currency='usd')",
        source_location=SourceLocation(lineno=1, col_offset=0),
        status="resolved_issue",
        explanation="Missing required parameter 'amount'",
        evidence_match=EvidenceMatch(
            candidate_id="cand_charge_missing_amount",
            matched_operation="stripe.Charge.create",
            evidence_id="ev_1",
            completeness="complete_contract",
            match_rationale="Match",
        ),
    )
    issue = VerifiedIssue(
        issue_id="iss_001",
        candidate_id="cand_charge_missing_amount",
        source_location=SourceLocation(lineno=1, col_offset=0),
        claim_checked="Missing required parameter 'amount'",
        violation_type="missing_required_parameter",
        explanation="amount is required",
        supporting_evidence_id="ev_1",
        source_url="https://docs.stripe.com/api/charges/create",
        verified_quote="Required parameters: amount",
        match_method="exact",
    )
    mock_ev = NormalizedEvidence(
        evidence_id="ev_1",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create Charge",
        content_excerpt="Required parameters: amount",
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
    )

    status, warnings = evaluate_fix_eligibility(
        candidate=cand,
        verified_issue=issue,
        evidence_items=[mock_ev],
        is_mock=False,
        evidence_trust="live_official_source",
    )

    assert status == "insufficient_evidence"
    assert any("INVENTED_VALUE_PROHIBITED" in w for w in warnings)


# 8. Preservation of Unrelated Logic and Formatting (Requirement 3)
@pytest.mark.asyncio
async def test_08_preservation_of_unrelated_logic_and_formatting(
    live_charges_evidence: NormalizedEvidence,
    live_payment_intent_evidence: NormalizedEvidence,
):
    source = (
        "# Custom header comment\n"
        "import stripe\n"
        "import math\n\n"
        "DATABASE_PORT = 5432\n\n"
        "def helper_calculation(x: int) -> int:\n"
        "    return int(math.sqrt(x) * 10)\n\n"
        "def process_payment(amount: int, token: str):\n"
        "    # Step 1: initiate charge\n"
        "    res = stripe.Charge.create(\n"
        "        amount=amount,\n"
        "        currency='usd',\n"
        "        source=token,\n"
        "    )\n"
        "    return res\n\n"
        "# Custom footer comment\n"
    )
    req = ProposeFixRequest(source=source, candidate_id="cand_001")
    res = await fix_proposer.propose_fix(
        req,
        _internal_evidence=[live_charges_evidence, live_payment_intent_evidence],
    )

    assert res.status == "evidence_supported"
    assert res.syntax_valid is True

    # Preceding logic preserved
    assert "# Custom header comment" in res.proposed_source
    assert "DATABASE_PORT = 5432" in res.proposed_source
    assert "def helper_calculation(x: int) -> int:" in res.proposed_source
    assert "return int(math.sqrt(x) * 10)" in res.proposed_source

    # Indentation inside function preserved
    assert "    res = stripe.PaymentIntent.create(" in res.proposed_source
    assert "        payment_method=token," in res.proposed_source
    assert "    return res" in res.proposed_source

    # Succeeding logic preserved
    assert "# Custom footer comment" in res.proposed_source


# 9. Zero Automatic Code Execution Guarantee (Requirement 5)
@pytest.mark.asyncio
async def test_09_zero_automatic_execution_guarantee():
    # Submitted source with malicious execution side-effects
    source = (
        "import stripe\n"
        "raise RuntimeError('MALICIOUS_EXECUTION_TRIGGERED')\n"
        "stripe.Charge.create(amount=1000, source='tok_123')\n"
    )
    req = ProposeFixRequest(source=source, candidate_id="cand_001")

    # If code was executed, RuntimeError would crash the test
    res = await fix_proposer.propose_fix(req)
    assert res is not None
    assert "RuntimeError" not in res.warnings
