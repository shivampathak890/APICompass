"""Tests for APICompass findings data models, traceability fields, and cautious state representations."""

import pytest
from app.schemas.ast_analysis import SourceLocation
from app.schemas.evidence import (
    AISuggestion,
    AnalysisReport,
    CandidateAssessment,
    EvidenceMatch,
    QuoteVerificationResult,
    VerifiedIssue,
)


def test_verified_issue_full_fields():
    """Verify that a VerifiedIssue includes all traceability fields without invented severity."""
    issue = VerifiedIssue(
        issue_id="iss_test_01",
        candidate_id="cand_test_01",
        source_location=SourceLocation(lineno=10, col_offset=4),
        claim_checked="The parameter 'source' is legacy/deprecated",
        violation_type="legacy_deprecated_parameter",
        explanation="Use of 'source' token is deprecated; use PaymentMethods instead.",
        supporting_evidence_id="sha256_mock_hash_12345",
        source_url="https://docs.stripe.com/api/charges/create",
        verified_quote="The parameter source is deprecated in modern Stripe APIs.",
        match_method="exact",
        verification_status="verified",
        quote_kind="exact_quotation",
        limitations="Applies to Stripe Python SDK v5+.",
        code_fragment="stripe.Charge.create(amount=1000, source='tok_123')",
        documented_requirement="Stripe documentation requires using 'payment_method' rather than 'source'.",
        impact_classification="Breaking API Deprecation",
        suggested_correction="Replace 'source' with 'payment_method'.",
    )

    assert issue.issue_id == "iss_test_01"
    assert issue.verification_status == "verified"
    assert issue.impact_classification == "Breaking API Deprecation"
    assert issue.code_fragment == "stripe.Charge.create(amount=1000, source='tok_123')"
    assert issue.title == "Legacy Deprecated Parameter: The parameter 'source' is legacy/deprecated"
    assert issue.source_location.lineno == 10
    assert issue.supporting_excerpt == "The parameter source is deprecated in modern Stripe APIs."


def test_verified_issue_partial_evidence_defaults():
    """Verify safe fallbacks when optional fields and excerpts are omitted."""
    issue = VerifiedIssue(
        issue_id="iss_partial_02",
        candidate_id="cand_test_02",
        source_location=SourceLocation(lineno=25, col_offset=0),
        claim_checked="The parameter 'currency' is required",
        violation_type="missing_required_parameter",
        explanation="Required parameter 'currency' was not provided.",
        supporting_evidence_id="hash_currency_req",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        verified_quote="currency is required",
    )

    # Defaults should be populated deterministically
    assert issue.verification_status == "verified"
    assert issue.supporting_excerpt == "currency is required"
    assert "Missing Required Parameter" in issue.title
    assert issue.impact_classification == "API Contract Violation (Missing Argument)"
    assert "Official documentation at https://docs.stripe.com" in issue.evidence_rationale
    assert issue.code_fragment is None
    assert issue.limitations is None


def test_ai_suggestion_distinguished_from_confirmed_bug():
    """Verify that an AISuggestion is explicitly unverified and uncalibrated, never a confirmed bug."""
    sug = AISuggestion(
        suggestion_id="sug_ai_01",
        candidate_id="cand_test_03",
        claim_type="missing_idempotency_key",
        description="Consider supplying an idempotency key to prevent double charging.",
        unverified_aspects="Idempotency header usage is recommended by conventions but not strictly required by method signature.",
        suggested_documentation_queries=["stripe idempotency keys"],
        confidence="uncalibrated",
    )

    assert sug.verification_status == "unverified_suggestion"
    assert sug.label == "Unverified suggestion"
    assert sug.confidence == "uncalibrated"
    assert "Idempotency header usage" in sug.unverified_aspects
    assert sug.title == "Unverified Suggestion: Missing Idempotency Key"


def test_candidate_assessment_statuses_sync():
    """Verify CandidateAssessment maps status to exact backend verification_status values."""
    # 1. Clean candidate -> no_issue_detected
    clean_cand = CandidateAssessment(
        candidate_id="cand_clean",
        target_name="stripe.PaymentIntent.create",
        call_expr="stripe.PaymentIntent.create(amount=2000, currency='usd')",
        source_location=SourceLocation(lineno=15, col_offset=0),
        status="resolved_clean",
        explanation="PaymentIntent create call conforms to required parameters.",
    )
    assert clean_cand.verification_status == "no_issue_detected"
    assert clean_cand.impact_classification == "Compliant API Usage"

    # 2. Issue candidate -> verified
    issue_cand = CandidateAssessment(
        candidate_id="cand_issue",
        target_name="stripe.Charge.create",
        call_expr="stripe.Charge.create(amount=1000)",
        source_location=SourceLocation(lineno=18, col_offset=0),
        status="resolved_issue",
        explanation="Missing required parameter 'currency'.",
    )
    assert issue_cand.verification_status == "verified"
    assert issue_cand.impact_classification == "API Contract Violation"

    # 3. Unresolved candidate -> unable_to_verify
    unresolved_cand = CandidateAssessment(
        candidate_id="cand_unresolved",
        target_name="custom_api_helper",
        call_expr="custom_api_helper()",
        source_location=SourceLocation(lineno=30, col_offset=0),
        status="unresolved",
        abstention_reason="AMBIGUOUS_OPERATION_MATCH",
        explanation="Operation is not an official Stripe API call.",
    )
    assert unresolved_cand.verification_status == "unable_to_verify"
    assert unresolved_cand.impact_classification == "Unverified (Abstained)"


def test_analysis_report_result_states():
    """Verify AnalysisReport synchronizes verdict to explicit result_state."""
    # 1. Clean report
    clean_report = AnalysisReport(
        verdict="clean",
        filename="checkout.py",
        total_lines=50,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="No contract violations detected in examined calls.",
        checks_performed=["Required Parameters", "Deprecation Check"],
    )
    assert clean_report.result_state == "no_issue_detected"
    assert "indicates only that supported checks" in clean_report.disclaimer

    # 2. Issues found report
    issues_report = AnalysisReport(
        verdict="issues_found",
        filename="checkout.py",
        total_lines=50,
        evidence_trust="live_official_source",
        is_mock=False,
        summary="1 verified issue detected.",
    )
    assert issues_report.result_state == "verified"

    # 3. Unable to verify report
    abstained_report = AnalysisReport(
        verdict="unable_to_verify",
        filename="checkout.py",
        total_lines=50,
        evidence_trust="mock_fixture",
        is_mock=True,
        summary="Quarantined mock mode.",
    )
    assert abstained_report.result_state == "unable_to_verify"


def test_structured_severity_and_confidence_in_schemas():
    """Ensure that severity uses defined semantics ('error', 'warning', 'info') and confidence levels."""
    issue = VerifiedIssue(
        issue_id="iss_03",
        candidate_id="cand_03",
        source_location=SourceLocation(lineno=5, col_offset=0),
        claim_checked="Constraint check",
        violation_type="constraint_violation",
        explanation="Amount must be positive.",
        supporting_evidence_id="hash_constraint",
        source_url="https://docs.stripe.com",
        verified_quote="amount must be a positive integer",
    )

    issue_dict = issue.model_dump()
    # Severity should have defined semantics
    assert issue.severity in ("error", "warning", "info")
    # Confidence should not be an arbitrary numeric percentage score
    assert "confidence_score" not in issue_dict
    assert issue.confidence in ("verified", "probable", "speculative", "uncertain")
    assert issue.impact_classification == "API Contract Violation (Constraint Mismatch)"
    # Required finding fields present
    assert issue.issue_id is not None
    assert issue.violation_type is not None
    assert issue.source_location is not None
    assert issue.expected_contract is not None
    assert issue.observed_usage is not None
    assert issue.suggested_action is not None
