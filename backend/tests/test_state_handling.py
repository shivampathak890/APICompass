"""Tests for APICompass frontend and backend state handling, failures, and recovery paths."""

import asyncio
import pytest
from app.schemas.evidence import AnalysisRequest
from app.schemas.documentation import NormalizedEvidence
from app.services.evidence.adjudicator import adjudicator
from app.services.evidence.stream_adjudicator import stream_adjudicator
from app.services.python_ast_analyzer import analyze_python_source


@pytest.mark.asyncio
async def test_empty_code_submission_handling():
    """Empty or whitespace source code must be safely parsed without runtime execution."""
    res = analyze_python_source("", "empty.py")
    assert res.status == "success"
    assert res.total_lines == 0
    assert len(res.candidates) == 0

    req = AnalysisRequest(source="   \n   \t  ", filename="empty.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req)
    assert report.verdict == "unable_to_verify"
    assert "no supported in-scope api calls detected" in report.summary.lower()


@pytest.mark.asyncio
async def test_syntax_error_reporting_preserves_coordinates():
    """Syntax errors must preserve exact line, column, and error message without crashing."""
    broken_code = "def invalid_func(\n  stripe.Charge.create("
    req = AnalysisRequest(source=broken_code, filename="broken.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req)

    assert report.verdict == "unable_to_verify"
    assert report.syntax_error is not None
    assert report.syntax_error.lineno is not None
    assert "syntax error" in report.summary.lower()
    assert any("invalid python syntax" in c.lower() for c in report.limitations_and_caveats)


@pytest.mark.asyncio
async def test_no_in_scope_candidates_abstention():
    """Valid Python code with 0 in-scope Stripe calls must abstain and explain scope."""
    non_api_code = "def calculate_fibonacci(n):\n    return n if n <= 1 else calculate_fibonacci(n-1) + calculate_fibonacci(n-2)\n"
    req = AnalysisRequest(source=non_api_code, filename="math_ops.py", ecosystem="stripe")
    report = await adjudicator.adjudicate(req)

    assert report.verdict == "unable_to_verify"
    assert len(report.candidate_assessments) == 0
    assert "no supported in-scope api calls detected" in report.summary.lower()
    assert any("NO_IN_SCOPE_CANDIDATES" in c for c in report.limitations_and_caveats)


@pytest.mark.asyncio
async def test_stream_emits_search_and_fetch_stages():
    """Streaming adjudication must emit truthful doc_search_started and doc_fetch_started stages."""
    code = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_123')\n"
    req = AnalysisRequest(source=code, filename="charge.py", ecosystem="stripe", force_mock=True)

    stages = []
    messages = []
    async for event in stream_adjudicator.stream_adjudicate(req):
        stages.append(event.stage)
        messages.append(event.message)

    assert "accepted" in stages
    assert "static_analysis_started" in stages
    assert "static_analysis_completed" in stages
    assert "doc_search_started" in stages
    assert "doc_search_completed" in stages
    assert "doc_fetch_started" in stages
    assert "doc_fetch_completed" in stages
    assert "evidence_verification_started" in stages
    assert "completed" in stages


@pytest.mark.asyncio
async def test_tinyfish_auth_failure_disclosed_without_secret_leakage():
    """Upstream TinyFish authentication failure (401/403) must be disclosed with recovery instructions."""
    code = "import stripe\nstripe.PaymentIntent.create(amount=5000, currency='usd')\n"
    req = AnalysisRequest(source=code, filename="payment.py", ecosystem="stripe")

    # Inject simulated auth failure evidence
    auth_err_ev = NormalizedEvidence(
        evidence_id="auth_err_1",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        content_excerpt="",
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="unavailable",
        is_mock=False,
        source_trust="official",
        error_code="AUTHENTICATION_FAILED",
        error_message="TinyFish authentication failed. Check TINYFISH_API_KEY.",
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[auth_err_ev])
    assert report.verdict == "unable_to_verify"
    assert any("TINYFISH_AUTH_FAILURE" in c for c in report.limitations_and_caveats)
    # Ensure no secret keys leaked
    for caveat in report.limitations_and_caveats:
        assert "sk_live" not in caveat
        assert "sec_" not in caveat


@pytest.mark.asyncio
async def test_tinyfish_rate_limit_and_timeout_disclosures():
    """Rate limits (429) and timeouts must be clearly flagged as external provider conditions."""
    code = "import stripe\nstripe.PaymentIntent.create(amount=5000, currency='usd')\n"
    req = AnalysisRequest(source=code, filename="payment.py", ecosystem="stripe")

    rate_limit_ev = NormalizedEvidence(
        evidence_id="rate_err_1",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        content_excerpt="",
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="unavailable",
        is_mock=False,
        source_trust="official",
        error_code="RATE_LIMITED",
        error_message="TinyFish rate limit reached. Please retry later.",
    )

    report = await adjudicator.adjudicate(req, _internal_evidence=[rate_limit_ev])
    assert report.verdict == "unable_to_verify"
    assert any("TINYFISH_RATE_LIMITED" in c for c in report.limitations_and_caveats)


@pytest.mark.asyncio
async def test_stream_cancellation_honored():
    """When client disconnects or aborts, stream adjudicator terminates without continuing."""
    code = "import stripe\nstripe.PaymentIntent.create(amount=5000, currency='usd')\n"
    req = AnalysisRequest(source=code, filename="payment.py", ecosystem="stripe", force_mock=True)

    # Disconnected callback returns True after 2nd event
    call_count = 0
    async def is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    events = []
    async for event in stream_adjudicator.stream_adjudicate(req, is_disconnected=is_disconnected):
        events.append(event)

    # Must have terminated early without emitting completed
    assert len(events) < 8
    assert not any(e.stage == "completed" for e in events)

