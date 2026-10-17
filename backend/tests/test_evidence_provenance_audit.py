"""Regression tests for evidence quality, source provenance, and traceability.

Tests explicitly evaluate the 7 requirements from the Evidence Provenance Audit:
1. Fabricated evidence rejection.
2. Unrelated excerpt rejection.
3. Missing or untrusted source URL rejection.
4. Treating search snippets as proof (must be rejected).
5. Retrieval failures resulting in unable_to_verify, not contract violations.
6. Ambiguous sources handled conservatively.
7. Valid evidence accepted with full provenance preservation (canonical URL,
   title, retrieval status, timestamp, SHA-256 fingerprint).
"""

import pytest
from app.schemas.ast_analysis import ApiCandidate, SourceLocation
from app.schemas.contract import ContractFindingCandidate
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisRequest, EvidenceMatch, VerifiedIssue, CandidateAssessment
from app.services.evidence.adjudicator import EvidenceAdjudicator, is_evidence_relevant
from app.services.evidence.contract_matcher import ContractMatcher
from app.services.evidence.quote_verifier import QuoteVerifier
from app.services.documentation.security import validate_destination_url


@pytest.fixture
def adjudicator() -> EvidenceAdjudicator:
    return EvidenceAdjudicator()


@pytest.fixture
def quote_verifier() -> QuoteVerifier:
    return QuoteVerifier()


@pytest.fixture
def matcher() -> ContractMatcher:
    return ContractMatcher()


# -------------------------------------------------------------------------
# 1. Fabricated evidence rejection
# -------------------------------------------------------------------------
def test_fabricated_quote_rejected_by_quote_verifier(quote_verifier: QuoteVerifier):
    """Quoting text that does not exist in the official documentation excerpt must fail verification."""
    ev = NormalizedEvidence(
        evidence_id="ev_stripe_charges",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt="Creates a new charge object. Required parameters: amount, currency. Legacy parameter: source.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        content_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        is_full_page=True,
    )

    # Hallucinated quote
    res = quote_verifier.verify_quote(
        proposed_quote="The source parameter is strictly forbidden and deletes your account.",
        evidence=ev,
        claimed_quote_kind="exact_quotation",
    )
    assert res.is_verified is False
    assert res.match_method == "none"
    assert res.matched_text is None
    assert "not found" in (res.error_message or "").lower()


@pytest.mark.asyncio
async def test_fabricated_quote_not_emitted_as_verified_issue(adjudicator: EvidenceAdjudicator):
    """An ungrounded claim where quote verification fails must never produce a VerifiedIssue."""
    source_code = "import stripe\nstripe.Charge.create(amount=2000, currency='usd', source='tok_visa')\n"
    req = AnalysisRequest(source=source_code, filename="charge.py", ecosystem="stripe")

    # Synthetic evidence missing the specific deprecation phrase
    ev = NormalizedEvidence(
        evidence_id="ev_clean_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt="Creates a charge object. Required parameters: amount, currency. All parameters accepted.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        content_sha256="abc111222333444555666777888999000111222333444555666777888999000a",
        is_full_page=True,
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[ev])
    # Must not contain any verified issues claiming 'source' is deprecated based on non-existent text
    assert len(report.verified_issues) == 0


# -------------------------------------------------------------------------
# 2. Unrelated excerpt rejection
# -------------------------------------------------------------------------
def test_unrelated_excerpt_rejected_by_relevance_guard():
    """Customer documentation provided for a Charge call must be rejected as irrelevant."""
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(amount=1000)",
        location=SourceLocation(lineno=2, col_offset=0),
        target_name="create",
        receiver="stripe.Charge",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
    )
    finding = ContractFindingCandidate(
        finding_id="find_1",
        candidate_id="cand_1",
        source_location=cand.location,
        violation_type="legacy_deprecated_parameter",
        claim_checked="Check parameter usage",
        explanation="Legacy parameter detected",
        contract_quote="Deprecated customer token",
        supporting_evidence_id="ev_customer",
        source_url="https://docs.stripe.com/api/customers/create",
    )
    ev_cust = NormalizedEvidence(
        evidence_id="ev_customer",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/customers/create",
        canonical_url="https://docs.stripe.com/api/customers/create",
        title="Create a customer | Stripe API Reference",
        content_excerpt="Creates a new customer object. Required parameters: none. Parameters: email, name.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=True,
    )

    is_rel, err = is_evidence_relevant(cand, finding, ev_cust)
    assert is_rel is False
    assert "relates to 'customer' resource" in (err or "") or "does not contain any reference" in (err or "")


@pytest.mark.asyncio
async def test_unrelated_excerpt_results_in_abstention_not_violation(adjudicator: EvidenceAdjudicator):
    """When only unrelated documentation is retrieved, the adjudicator must abstain (unable_to_verify)."""
    source_code = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_123')\n"
    req = AnalysisRequest(source=source_code, filename="charge.py", ecosystem="stripe")

    ev_unrelated = NormalizedEvidence(
        evidence_id="ev_tax_rate",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/tax_rates/create",
        canonical_url="https://docs.stripe.com/api/tax_rates/create",
        title="Create a tax rate | Stripe API Reference",
        content_excerpt="Creates a new tax rate object. Required parameters: display_name, inclusive, percentage.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=True,
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[ev_unrelated])
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.unresolved_candidates) > 0


# -------------------------------------------------------------------------
# 3. Missing source URL / untrusted domain rejection
# -------------------------------------------------------------------------
def test_untrusted_destination_url_rejected():
    """Security allowlist must reject non-official or malicious domains."""
    is_valid, _, err = validate_destination_url("https://malicious-stripe-clone.com/api/charges")
    assert is_valid is False
    assert "not in approved documentation allowlist" in (err or "")

    is_valid, _, err = validate_destination_url("http://docs.stripe.com/insecure")
    assert is_valid is False
    assert "only HTTPS is permitted" in (err or "")

    is_valid, _, err = validate_destination_url("ftp://docs.stripe.com/api")
    assert is_valid is False
    assert "only HTTPS is permitted" in (err or "")


def test_empty_or_untrusted_source_trust_rejected_in_relevance():
    """Evidence with untrusted or rejected source_trust must be rejected."""
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(amount=1000)",
        location=SourceLocation(lineno=1, col_offset=0),
        target_name="create",
        receiver="stripe.Charge",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
    )
    ev_untrusted = NormalizedEvidence(
        evidence_id="ev_untrusted",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Unofficial blog post",
        content_excerpt="Some unofficial documentation text.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="rejected",
        is_mock=False,
        source_trust="untrusted",
        is_full_page=True,
    )

    is_rel, err = is_evidence_relevant(cand, None, ev_untrusted)
    assert is_rel is False
    assert "untrusted or failed" in (err or "").lower()


# -------------------------------------------------------------------------
# 4. Search snippet rejection (must not prove contract violations)
# -------------------------------------------------------------------------
def test_search_snippet_rejected_from_proving_violations():
    """Search snippets with is_full_page=False must be rejected by relevance checking."""
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(amount=1000, source='tok_123')",
        location=SourceLocation(lineno=1, col_offset=0),
        target_name="create",
        receiver="stripe.Charge",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
    )
    snippet_ev = NormalizedEvidence(
        evidence_id="ev_snippet",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe Documentation Preview",
        content_excerpt="Create a charge... Required parameters: amount, currency. Legacy parameter: source is deprecated.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=False,  # Explicit search preview snippet
    )

    is_rel, err = is_evidence_relevant(cand, None, snippet_ev)
    assert is_rel is False
    assert "Search snippets cannot be treated as authoritative proof" in (err or "")


def test_ranking_prefers_full_page_over_search_snippet(matcher: ContractMatcher):
    """ContractMatcher multi-result ranking must prioritize full pages over search snippets."""
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(amount=1000)",
        location=SourceLocation(lineno=1, col_offset=0),
        target_name="create",
        receiver="stripe.Charge",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
    )

    snippet_ev = NormalizedEvidence(
        evidence_id="ev_snippet",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Charge preview",
        content_excerpt="Required parameters: amount. parameters: source",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=False,
    )

    full_page_ev = NormalizedEvidence(
        evidence_id="ev_full_page",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Full Official Reference",
        content_excerpt="Required parameters: amount, currency. Legacy parameter: source.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=True,
    )

    # Supply snippet first, full page second
    match, _ = matcher.match_candidate_to_evidence(cand, None, [snippet_ev, full_page_ev])
    assert match is not None
    assert match.evidence_id == "ev_full_page"


# -------------------------------------------------------------------------
# 5. Retrieval failures resulting in unable_to_verify, not violations
# -------------------------------------------------------------------------
@pytest.mark.parametrize("failed_status", ["unavailable", "rate_limited", "rejected", "auth_failed"])
@pytest.mark.asyncio
async def test_retrieval_failure_produces_unable_to_verify_never_violation(
    adjudicator: EvidenceAdjudicator, failed_status: str
):
    """When documentation retrieval fails (timeout, 404, rate limit), result must be unable_to_verify."""
    source_code = "import stripe\nstripe.Charge.create(amount=1000, source='tok_123')\n"
    req = AnalysisRequest(source=source_code, filename="charge.py", ecosystem="stripe")

    ev_failed = NormalizedEvidence(
        evidence_id=f"ev_{failed_status}",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title=None,
        content_excerpt="",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status=failed_status,
        is_mock=False,
        source_trust="official",
        error_code="UPSTREAM_FAILURE",
        error_message=f"Simulated {failed_status} from provider",
        is_full_page=True,
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[ev_failed])
    assert report.verdict == "unable_to_verify"
    assert len(report.verified_issues) == 0
    assert len(report.unresolved_candidates) == 1
    assessment = report.candidate_assessments[0]
    assert assessment.status == "unresolved"
    assert assessment.abstention_reason in ("DOCUMENTATION_MISSING", "RETRIEVAL_FAILED")


# -------------------------------------------------------------------------
# 6. Ambiguous sources handled conservatively
# -------------------------------------------------------------------------
def test_conflicting_documentation_handled_conservatively(matcher: ContractMatcher):
    """When multiple retrieved sources give contradictory requirements, matcher marks ambiguous."""
    cand = ApiCandidate(
        candidate_id="cand_1",
        expression="stripe.Charge.create(amount=1000, source='tok_123')",
        location=SourceLocation(lineno=1, col_offset=0),
        target_name="create",
        receiver="stripe.Charge",
        normalized_target="stripe.Charge.create",
        rationale="API call candidate",
    )

    ev_modern = NormalizedEvidence(
        evidence_id="ev_modern",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Modern API",
        content_excerpt="Required parameters: amount. Legacy parameter: source is deprecated.",
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=True,
    )

    ev_conflicting = NormalizedEvidence(
        evidence_id="ev_conflicting",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Conflicting Variant",
        content_excerpt="Required parameters: amount, source.",  # Marks source as required!
        retrieved_at="2026-10-18T12:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        is_full_page=True,
    )

    match, findings = matcher.match_candidate_to_evidence(cand, None, [ev_modern, ev_conflicting])
    assert match is not None
    assert match.is_ambiguous is True
    assert "Conflicting documentation detected" in match.match_rationale
    assert len(findings) == 0


# -------------------------------------------------------------------------
# 7. Valid evidence accepted with full provenance preservation
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_provenance_preservation_end_to_end(adjudicator: EvidenceAdjudicator):
    """Valid live documentation must preserve canonical URL, title, retrieval status,
    retrieval timestamp, and SHA-256 fingerprint on both VerifiedIssue and CandidateAssessment."""
    source_code = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_123')\n"
    req = AnalysisRequest(source=source_code, filename="charge.py", ecosystem="stripe")

    sha256_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    retrieval_ts = "2026-10-18T12:34:56Z"
    canonical_url = "https://docs.stripe.com/api/charges/create"
    doc_title = "Create a charge | Stripe Official API Reference"

    ev_valid = NormalizedEvidence(
        evidence_id="ev_charge_live_valid",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url=canonical_url,
        title=doc_title,
        content_excerpt="Creates a new charge. Required parameters: amount, currency. Legacy parameter: source is deprecated.",
        retrieved_at=retrieval_ts,
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="official",
        content_sha256=sha256_hash,
        is_full_page=True,
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[ev_valid])
    assert report.verdict == "issues_found"
    assert len(report.verified_issues) == 1

    issue: VerifiedIssue = report.verified_issues[0]
    assert issue.canonical_url == canonical_url
    assert issue.source_title == doc_title
    assert issue.retrieval_status == "success"
    assert issue.retrieved_at == retrieval_ts
    assert issue.content_sha256 == sha256_hash
    assert issue.is_mock is False
    assert issue.verification_status == "verified"
    assert issue.match_method in ("exact", "whitespace_normalized")

    assessment: CandidateAssessment = report.candidate_assessments[0]
    assert assessment.status == "resolved_issue"
    assert assessment.verification_status == "verified"
    assert assessment.canonical_url == canonical_url
    assert assessment.source_title == doc_title
    assert assessment.retrieval_status == "success"
    assert assessment.retrieved_at == retrieval_ts
    assert assessment.content_sha256 == sha256_hash
    assert assessment.is_mock is False

