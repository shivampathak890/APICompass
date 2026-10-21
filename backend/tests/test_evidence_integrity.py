"""Automated test suite for evidence retrieval, validation, and integrity.

Verifies:
1. Valid evidence satisfies confirmation requirements (CONFIRMED).
2. Missing evidence is never treated as proof of defect (NEEDS_REVIEW / unable_to_verify).
3. Irrelevant evidence is rejected by the relevance guard (NOT_SUPPORTED / abstention).
4. Contradictory evidence preserves uncertainty (NEEDS_REVIEW / CONFLICTING_DOCUMENTATION).
5. Invalid source references (SSRF, unapproved hosts) are rejected by provenance guards.
6. Retrieval failures produce controlled abstentions (NEEDS_REVIEW / unable_to_verify).
7. Unsupported conclusions / fabricated quotes cannot be promoted (NOT_SUPPORTED).
"""

import hashlib
from datetime import datetime, timezone
import pytest
from unittest.mock import patch

from app.config import settings
from app.schemas.ast_analysis import ApiCandidate, CallInfo, SourceLocation
from app.schemas.documentation import DocParameter, NormalizedEvidence
from app.schemas.evidence import AnalysisRequest, AnalysisReport
from app.services.evidence.adjudicator import adjudicator, is_evidence_relevant
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import QuoteVerifier
from app.services.documentation.security import validate_destination_url


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def quote_verifier() -> QuoteVerifier:
    return QuoteVerifier()


@pytest.fixture
def live_official_charge_evidence() -> NormalizedEvidence:
    now_utc = datetime.now(timezone.utc).isoformat()
    content = (
        "You can use the Charges API to accept payments using Stripe. "
        "However, Stripe now recommends using the Payment Intents API, which provides a unified "
        "integration flow and supports dynamic authentication mechanisms. "
        "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods. "
        "Required parameters: amount (positive integer), currency (three-letter ISO code)."
    )
    return NormalizedEvidence(
        evidence_id="ev_stripe_charges_create_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=content,
        content_sha256=compute_sha256(content),
        retrieved_at=now_utc,
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        is_full_page=True,
    )


@pytest.fixture
def live_official_customer_evidence() -> NormalizedEvidence:
    now_utc = datetime.now(timezone.utc).isoformat()
    content = "Creates a new customer object. Parameters: email (string), name (string)."
    return NormalizedEvidence(
        evidence_id="ev_stripe_customers_create_live",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/customers/create",
        canonical_url="https://docs.stripe.com/api/customers/create",
        title="Create a customer | Stripe API Reference",
        content_excerpt=content,
        content_sha256=compute_sha256(content),
        retrieved_at=now_utc,
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        is_full_page=True,
    )


# -----------------------------------------------------------------------------
# 1. Valid Evidence Verification (CONFIRMED)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_evidence_satisfies_confirmation_requirements(
    live_official_charge_evidence: NormalizedEvidence,
):
    """Verify that authentic, live official documentation with matching quote produces CONFIRMED status."""
    code = "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')"
    req = AnalysisRequest(source=code, filename="payment.py", ecosystem="stripe")

    with patch.object(settings, "MOCK_MODE", False):
        report: AnalysisReport = await adjudicator.adjudicate(
            req,
            _internal_evidence=[live_official_charge_evidence],
        )

    assert report.verdict == "issues_found"
    assert report.evidence_trust == "live_official_source"
    assert len(report.verified_issues) >= 1

    issue = report.verified_issues[0]
    assert issue.verification_status == "verified"  # CONFIRMED
    assert issue.violation_type in ("legacy_deprecated_parameter", "deprecated_operation")
    assert issue.source_url == "https://docs.stripe.com/api/charges/create"
    assert "source" in issue.verified_quote.lower()


# -----------------------------------------------------------------------------
# 2. Missing Evidence Verification (NEEDS_REVIEW / unable_to_verify)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_evidence_handled_conservatively_never_false_alarm():
    """Verify that absent documentation results in explicit abstention, never treated as proof of defect."""
    code = "import stripe\nstripe.CustomInternalWidget.execute(param=1)"
    req = AnalysisRequest(source=code, filename="unknown_op.py", ecosystem="stripe")

    with patch.object(settings, "MOCK_MODE", False):
        report: AnalysisReport = await adjudicator.adjudicate(
            req,
            _internal_evidence=[],
        )

    assert report.verdict == "unable_to_verify"  # NEEDS_REVIEW
    assert len(report.verified_issues) == 0  # Missing evidence is NOT proof of a defect!


# -----------------------------------------------------------------------------
# 3. Irrelevant Evidence Verification (NOT_SUPPORTED / Abstention)
# -----------------------------------------------------------------------------
def test_irrelevant_evidence_rejected_by_relevance_guard(
    live_official_customer_evidence: NormalizedEvidence,
):
    """Verify that disjoint resource evidence (Customer docs for Charge call) is rejected."""
    charge_candidate = ApiCandidate(
        candidate_id="cand_charge",
        expression="stripe.Charge.create",
        location=SourceLocation(lineno=1, col_offset=0),
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
        is_ambiguous=False,
    )

    is_rel, reason = is_evidence_relevant(charge_candidate, None, live_official_customer_evidence)
    assert not is_rel  # NOT_SUPPORTED
    assert "relates to 'customer' resource" in reason or "irrelevant" in reason.lower()


# -----------------------------------------------------------------------------
# 4. Contradictory Evidence Verification (NEEDS_REVIEW / Uncertainty)
# -----------------------------------------------------------------------------
def test_contradictory_evidence_preserves_uncertainty(
    live_official_charge_evidence: NormalizedEvidence,
):
    """Verify that conflicting documentation excerpts result in conservative abstention."""
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
        content_sha256=compute_sha256(conflicting_excerpt),
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
        raw_markdown=conflicting_excerpt,
        headings=["Create a charge", "Parameters"],
        parameters=[
            DocParameter(name="amount", is_required=True, is_deprecated=False),
            DocParameter(name="currency", is_required=True, is_deprecated=False),
            DocParameter(name="source", is_required=True, is_deprecated=False),
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
        evidence_items=[live_official_charge_evidence, conflicting_ev],
    )
    assert match_record is not None
    assert match_record.is_ambiguous is True  # NEEDS_REVIEW
    assert "conflicting" in match_record.match_rationale.lower()
    assert findings == []  # No premature violations emitted


# -----------------------------------------------------------------------------
# 5. Invalid Source References & Provenance Guards (SSRF / Unapproved Hosts)
# -----------------------------------------------------------------------------
def test_invalid_source_references_rejected_by_provenance_guard(
    quote_verifier: QuoteVerifier,
):
    """Verify that unapproved hosts, private IPs, and non-HTTPS schemes are rejected."""
    # Untrusted domain
    is_valid, _, err = validate_destination_url("https://malicious-attacker-site.com/api")
    assert not is_valid
    assert "is not in approved documentation allowlist" in err

    # Private IP (SSRF)
    is_valid, _, err = validate_destination_url("http://127.0.0.1:8000/docs")
    assert not is_valid

    # AWS metadata endpoint
    is_valid, _, err = validate_destination_url("http://169.254.169.254/latest/meta-data/")
    assert not is_valid

    # Quote verifier rejects evidence with unapproved source URL
    bad_evidence = NormalizedEvidence(
        evidence_id="ev_bad_url",
        ecosystem="stripe",
        package="stripe",
        source_url="http://untrusted-site.com/doc",
        canonical_url="http://untrusted-site.com/doc",
        title="Fake Doc",
        content_excerpt="The source parameter is deprecated.",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="untrusted",
        is_full_page=True,
    )

    result = quote_verifier.verify_quote("The source parameter is deprecated.", bad_evidence)
    assert not result.is_verified
    assert "provenance failure" in result.error_message.lower()


# -----------------------------------------------------------------------------
# 6. Retrieval Failures Handled with Controlled Abstention
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retrieval_failures_produce_controlled_abstention():
    """Verify that network timeouts and rate-limit errors produce unable_to_verify."""
    fail_evidence = NormalizedEvidence(
        evidence_id="ev_rate_limit",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/refunds/create",
        canonical_url="https://docs.stripe.com/api/refunds/create",
        title="TinyFish Rate Limited",
        content_excerpt="",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        provider="tinyfish_live",
        status="unavailable",
        is_mock=False,
        source_trust="untrusted",
        error_code="RATE_LIMITED",
        error_message="HTTP 429: Rate limit exceeded",
    )

    code = "import stripe\nstripe.Refund.create(charge='ch_123')"
    req = AnalysisRequest(source=code, filename="refund.py", ecosystem="stripe")

    with patch.object(settings, "MOCK_MODE", False):
        report: AnalysisReport = await adjudicator.adjudicate(
            req,
            _internal_evidence=[fail_evidence],
        )

    assert report.verdict == "unable_to_verify"  # NEEDS_REVIEW
    assert len(report.verified_issues) == 0


# -----------------------------------------------------------------------------
# 7. Unsupported Conclusions & Fabricated Quotes Rejected
# -----------------------------------------------------------------------------
def test_unsupported_conclusions_and_fabricated_quotes_rejected(
    quote_verifier: QuoteVerifier,
    live_official_charge_evidence: NormalizedEvidence,
):
    """Verify that an AI-hallucinated quote absent from official docs is rejected."""
    hallucinated_quote = "Stripe has permanently deleted the Charge object in version 2026."
    res = quote_verifier.verify_quote(hallucinated_quote, live_official_charge_evidence)

    assert not res.is_verified  # NOT_SUPPORTED
    assert res.match_method == "none"
    assert res.matched_text is None
