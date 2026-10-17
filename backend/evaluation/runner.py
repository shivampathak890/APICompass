"""Repeatable evaluation runner for APICompass Python and Stripe analysis.

Executes each curated evaluation case against the authoritative analysis pipeline,
compares actual behavior with expected behavior, and reports metrics.
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from unittest.mock import patch

from app.config import settings
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisReport, AnalysisRequest
from app.schemas.fix_proposal import FixProposalResponse, ProposeFixRequest
from app.services.documentation.normalizer import normalize_documentation_content
from app.services.evidence.adjudicator import adjudicator
from app.services.fixes.fix_proposer import FixProposer
from evaluation.dataset import EVALUATION_CASES, EvaluationCase, get_evaluation_dataset

logger = logging.getLogger("apicompass.evaluation.runner")


class CaseResult(BaseModel):
    """Result of running a single evaluation case."""
    model_config = ConfigDict(extra="forbid")

    case_id: str
    name: str
    category: str
    passed: bool
    expected_verdict: str
    actual_verdict: str
    expected_finding_category: Optional[str] = None
    actual_finding_category: Optional[str] = None
    expected_verification_status: str
    actual_verification_status: str
    failure_reasons: List[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)


class EvaluationSuiteReport(BaseModel):
    """Aggregated evaluation suite execution report."""
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate_percentage: float
    results: List[CaseResult]


def build_evidence_from_case(case: EvaluationCase) -> Optional[NormalizedEvidence]:
    """Construct a NormalizedEvidence record for a test case."""
    if not case.relevant_doc_source or not case.relevant_doc_excerpt:
        return None

    clean_url = case.relevant_doc_source.split("#")[0].rstrip("/")
    now_utc = datetime.now(timezone.utc).isoformat()
    raw_text = case.relevant_doc_excerpt
    
    # Generate authentic documentation page title from source URL path
    if case.relevant_doc_source:
        path_slug = case.relevant_doc_source.rstrip("/").split("/")[-1].replace("_", " ").title()
        title = f"{path_slug} | Stripe API Reference"
    else:
        title = "Stripe API Reference"
    if case.doc_is_synthetic:
        title = f"[Mock Fixture] {title}"

    provider = "tinyfish_mock" if case.doc_is_synthetic else "tinyfish_live"
    status = "mock" if case.doc_is_synthetic else "success"
    source_trust = "mock_fixture" if case.doc_is_synthetic else "official"

    page_model, cleaned_excerpt = normalize_documentation_content(
        raw_text=raw_text,
        url=case.relevant_doc_source,
        final_url=clean_url,
        title=title,
        doc_version="2024-04-10",
        provider=provider,
        is_mock=case.doc_is_synthetic,
        retrieved_at=now_utc,
    )

    ev_id = f"ev_{hashlib.sha256(f'{clean_url}:{cleaned_excerpt}'.encode('utf-8')).hexdigest()[:16]}"

    return NormalizedEvidence(
        evidence_id=ev_id,
        ecosystem=case.ecosystem,
        package="stripe",
        source_url=case.relevant_doc_source,
        canonical_url=clean_url,
        title=title,
        content_excerpt=cleaned_excerpt,
        retrieved_at=now_utc,
        provider=provider,
        status=status,
        is_mock=case.doc_is_synthetic,
        source_trust=source_trust,
        doc_version="2024-04-10",
        error_code=None,
        error_message=None,
        raw_markdown=page_model.content,
        content_sha256=page_model.content_sha256,
        headings=page_model.headings,
        parameters=page_model.parameters,
        required_fields=page_model.required_fields,
        deprecation_notices=page_model.deprecation_notices,
        code_examples=page_model.code_examples,
        page_data=page_model,
    )


async def execute_case(case: EvaluationCase) -> CaseResult:
    """Execute a single evaluation case and compare actual results with expected results."""
    start_time = time.perf_counter()
    failure_reasons: List[str] = []

    actual_verdict = "unknown"
    actual_finding_category: Optional[str] = None
    actual_verification_status = "unknown"
    details: Dict[str, Any] = {}

    try:
        # Special Case 14: Fix Proposal Syntax Error Evaluation
        if case.is_fix_proposal_case:
            fix_proposer = FixProposer(adjudicator)
            fix_req = ProposeFixRequest(
                source=case.input_code,
                filename=case.filename,
                candidate_id="cand_001",
                ecosystem=case.ecosystem,
            )

            # Custom generator that injects a syntax error in the proposed replacement
            def syntax_breaking_generator(source: str, cand: Any, issue: Any) -> Tuple[str, str, str, Optional[str]]:
                lines = source.splitlines(keepends=True)
                start_line = cand.source_location.lineno
                end_line = cand.source_location.end_lineno or start_line
                original_chunk = "".join(lines[start_line - 1 : end_line])
                bad_replacement = original_chunk.rstrip().rstrip(")")
                prop_lines = list(lines)
                prop_lines[start_line - 1 : end_line] = [bad_replacement + "\n"]
                broken_source = "".join(prop_lines)
                return original_chunk, bad_replacement, broken_source, None

            # Setup live evidence for initial analysis
            ev_item = build_evidence_from_case(case)
            internal_ev = [ev_item] if ev_item else None

            proposal_res: FixProposalResponse = await fix_proposer.propose_fix(
                fix_req,
                _internal_evidence=internal_ev,
                _test_edit_generator=syntax_breaking_generator,
            )

            actual_verdict = "issues_found"
            actual_finding_category = proposal_res.status
            actual_verification_status = "unable_to_verify" if not proposal_res.syntax_valid else "verified"

            details["proposal_status"] = proposal_res.status
            details["syntax_valid"] = proposal_res.syntax_valid
            details["reverification_status"] = proposal_res.reverification_status

            if proposal_res.syntax_valid is not False:
                failure_reasons.append(f"Expected syntax_valid=False, got {proposal_res.syntax_valid}")
            if proposal_res.status != case.expected_finding_category:
                failure_reasons.append(
                    f"Expected status '{case.expected_finding_category}', got '{proposal_res.status}'"
                )
            if proposal_res.reverification_status != "syntax_invalid":
                failure_reasons.append(
                    f"Expected reverification_status='syntax_invalid', got '{proposal_res.reverification_status}'"
                )

        else:
            # Standard Evaluation Cases (1-13, 15-18)
            internal_evidence: Optional[List[NormalizedEvidence]] = None

            # Case 11: Build conflicting documentation evidence
            if case.category == "ambiguous_documentation":
                now_utc = datetime.now(timezone.utc).isoformat()
                ev_a = NormalizedEvidence(
                    evidence_id="ev_conflict_a",
                    ecosystem="stripe",
                    package="stripe",
                    source_url="https://docs.stripe.com/api/charges/create",
                    canonical_url="https://docs.stripe.com/api/charges/create",
                    title="Charge Create Spec A",
                    content_excerpt="You can use the Charges API. Required parameters: amount, currency, capture.",
                    retrieved_at=now_utc,
                    provider="tinyfish_live",
                    status="success",
                    is_mock=False,
                    source_trust="official",
                    doc_version="2024-04-10",
                )
                ev_b = NormalizedEvidence(
                    evidence_id="ev_conflict_b",
                    ecosystem="stripe",
                    package="stripe",
                    source_url="https://docs.stripe.com/api/charges/create/v2",
                    canonical_url="https://docs.stripe.com/api/charges/create",
                    title="Charge Create Spec B",
                    content_excerpt="You can use the Charges API. The 'capture' parameter is deprecated.",
                    retrieved_at=now_utc,
                    provider="tinyfish_live",
                    status="success",
                    is_mock=False,
                    source_trust="official",
                    doc_version="2024-04-10",
                )
                internal_evidence = [ev_a, ev_b]

            # Case 12: Build retrieval failure evidence
            elif case.category == "retrieval_failure":
                now_utc = datetime.now(timezone.utc).isoformat()
                ev_fail = NormalizedEvidence(
                    evidence_id="ev_rate_limit",
                    ecosystem="stripe",
                    package="stripe",
                    source_url=case.relevant_doc_source or "https://docs.stripe.com/api/refunds/create",
                    canonical_url="https://docs.stripe.com/api/refunds/create",
                    title="TinyFish Rate Limited",
                    content_excerpt="",
                    retrieved_at=now_utc,
                    provider="tinyfish_live",
                    status="unavailable",
                    is_mock=False,
                    source_trust="untrusted",
                    error_code="RATE_LIMITED",
                    error_message="HTTP 429: Rate limit exceeded",
                )
                internal_evidence = [ev_fail]
            # Multi-call cases with multiple distinct API evidence items
            elif case.category in ("multiple_api_calls_clean", "multiple_api_calls_mixed"):
                now_utc = datetime.now(timezone.utc).isoformat()
                ev_cust = NormalizedEvidence(
                    evidence_id="ev_customer_create_multi",
                    ecosystem="stripe",
                    package="stripe",
                    source_url="https://docs.stripe.com/api/customers/create",
                    canonical_url="https://docs.stripe.com/api/customers/create",
                    title="Create a customer | Stripe API Reference",
                    content_excerpt="Creates a new customer object. Parameters: email (string), name (string).",
                    retrieved_at=now_utc,
                    provider="tinyfish_live",
                    status="success",
                    is_mock=False,
                    source_trust="official",
                    doc_version="2024-04-10",
                )
                if case.category == "multiple_api_calls_clean":
                    ev_pi = NormalizedEvidence(
                        evidence_id="ev_payment_intent_create_multi",
                        ecosystem="stripe",
                        package="stripe",
                        source_url="https://docs.stripe.com/api/payment_intents/create",
                        canonical_url="https://docs.stripe.com/api/payment_intents/create",
                        title="Create a PaymentIntent | Stripe API Reference",
                        content_excerpt=(
                            "Creates a PaymentIntent object. Required parameters: amount (integer in cents), "
                            "currency (three-letter ISO currency code)."
                        ),
                        retrieved_at=now_utc,
                        provider="tinyfish_live",
                        status="success",
                        is_mock=False,
                        source_trust="official",
                        doc_version="2024-04-10",
                    )
                    internal_evidence = [ev_cust, ev_pi]
                else:
                    ev_charge = NormalizedEvidence(
                        evidence_id="ev_charge_create_multi",
                        ecosystem="stripe",
                        package="stripe",
                        source_url="https://docs.stripe.com/api/charges/create",
                        canonical_url="https://docs.stripe.com/api/charges/create",
                        title="Create a charge | Stripe API Reference",
                        content_excerpt=(
                            "You can use the Charges API to accept payments using Stripe. "
                            "Required parameters: amount (positive integer), currency (three-letter ISO code)."
                        ),
                        retrieved_at=now_utc,
                        provider="tinyfish_live",
                        status="success",
                        is_mock=False,
                        source_trust="official",
                        doc_version="2024-04-10",
                    )
                    internal_evidence = [ev_cust, ev_charge]

            # Normal case with documentation
            elif case.relevant_doc_source and case.relevant_doc_excerpt:
                ev_item = build_evidence_from_case(case)
                if ev_item:
                    internal_evidence = [ev_item]
            else:
                # Explicit empty evidence for cases without documentation (prevents mock fallback)
                internal_evidence = []

            # Run deterministic adjudication
            req = AnalysisRequest(
                source=case.input_code,
                filename=case.filename,
                ecosystem=case.ecosystem,
            )
            with patch.object(settings, "MOCK_MODE", case.doc_is_synthetic):
                report: AnalysisReport = await adjudicator.adjudicate(
                    req,
                    _internal_evidence=internal_evidence,
                )

            actual_verdict = report.verdict
            details["verdict"] = report.verdict
            details["checks_performed"] = report.checks_performed
            details["verified_issues_count"] = len(report.verified_issues)
            details["candidate_assessments_count"] = len(report.candidate_assessments)
            details["evidence_trust"] = report.evidence_trust
            details["is_mock"] = report.is_mock

            if report.verified_issues:
                actual_finding_category = report.verified_issues[0].violation_type
                actual_verification_status = "verified"
            elif report.candidate_assessments:
                cand = report.candidate_assessments[0]
                actual_verification_status = cand.verification_status
                if cand.issues:
                    actual_finding_category = cand.issues[0].violation_type
            elif report.syntax_error:
                actual_verification_status = "unable_to_verify"
                details["syntax_error"] = report.syntax_error.message
            else:
                actual_verification_status = "unable_to_verify"

            # Check 1: Verdict match
            if report.verdict != case.expected_verdict:
                failure_reasons.append(
                    f"Verdict mismatch: expected '{case.expected_verdict}', got '{report.verdict}'"
                )

            # Check 2: Finding category match
            if case.expected_finding_category:
                if not report.verified_issues:
                    failure_reasons.append(
                        f"Expected finding '{case.expected_finding_category}', but no verified issues were reported."
                    )
                else:
                    found_categories = [i.violation_type for i in report.verified_issues]
                    if case.expected_finding_category not in found_categories:
                        failure_reasons.append(
                            f"Expected category '{case.expected_finding_category}', got {found_categories}"
                        )
            else:
                if report.verified_issues and case.category != "fix_syntax_error":
                    failure_reasons.append(
                        f"Expected zero verified issues, but found {len(report.verified_issues)}: "
                        f"{[i.violation_type for i in report.verified_issues]}"
                    )

            # Check 3: Abstention reason match if specified
            if case.expected_abstention_reason:
                matched_abstention = False
                if report.syntax_error and case.expected_abstention_reason in ("SYNTAX_ERROR", "invalid_syntax"):
                    matched_abstention = True
                elif report.candidate_assessments:
                    matched_abstention = any(
                        ca.abstention_reason == case.expected_abstention_reason
                        for ca in report.candidate_assessments
                    )
                if not matched_abstention:
                    # Check in caveats or summary
                    all_text = " ".join(report.limitations_and_caveats) + " " + report.summary
                    matched_abstention = case.expected_abstention_reason in all_text

                if not matched_abstention:
                    failure_reasons.append(
                        f"Expected abstention reason '{case.expected_abstention_reason}' not found in candidate assessments or report."
                    )

    except Exception as exc:
        logger.error("Exception during evaluation case %s: %s", case.case_id, exc, exc_info=True)
        failure_reasons.append(f"Unhandled exception: {type(exc).__name__}: {str(exc)}")

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    passed = len(failure_reasons) == 0

    return CaseResult(
        case_id=case.case_id,
        name=case.name,
        category=case.category,
        passed=passed,
        expected_verdict=case.expected_verdict,
        actual_verdict=actual_verdict,
        expected_finding_category=case.expected_finding_category,
        actual_finding_category=actual_finding_category,
        expected_verification_status=case.expected_verification_status,
        actual_verification_status=actual_verification_status,
        failure_reasons=failure_reasons,
        execution_time_ms=execution_time_ms,
        details=details,
    )


async def run_evaluation_suite(
    cases: Optional[List[EvaluationCase]] = None,
) -> EvaluationSuiteReport:
    """Run all evaluation cases and return an aggregated EvaluationSuiteReport."""
    dataset = cases or get_evaluation_dataset()
    results: List[CaseResult] = []

    for case in dataset:
        res = await execute_case(case)
        results.append(res)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    pass_rate = round((passed_count / len(results)) * 100, 2) if results else 0.0

    return EvaluationSuiteReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_cases=len(results),
        passed_cases=passed_count,
        failed_cases=failed_count,
        pass_rate_percentage=pass_rate,
        results=results,
    )


def print_suite_report(report: EvaluationSuiteReport) -> None:
    """Print an ASCII table and execution summary of the evaluation suite."""
    print("=" * 95)
    print("                APICOMPASS CURATED EVALUATION SUITE REPORT")
    print(f" Timestamp: {report.timestamp}")
    print(f" Summary:   {report.passed_cases}/{report.total_cases} Passed ({report.pass_rate_percentage}%)")
    print("=" * 95)
    print(f"{'Case ID':<9} | {'Category':<26} | {'Expected':<16} | {'Actual':<16} | {'Status':<6}")
    print("-" * 95)

    for r in report.results:
        exp = f"{r.expected_verdict}" + (f" ({r.expected_finding_category})" if r.expected_finding_category else "")
        act = f"{r.actual_verdict}" + (f" ({r.actual_finding_category})" if r.actual_finding_category else "")
        status_tag = "PASS" if r.passed else "FAIL"
        print(f"{r.case_id:<9} | {r.category[:26]:<26} | {exp[:16]:<16} | {act[:16]:<16} | {status_tag:<6}")
        if not r.passed:
            for reason in r.failure_reasons:
                print(f"   └── ERROR: {reason}")

    print("=" * 95)


def main() -> None:
    """CLI entrypoint for running the curated evaluation suite."""
    report = asyncio.run(run_evaluation_suite())
    print_suite_report(report)
    if report.failed_cases > 0:
        exit(1)


if __name__ == "__main__":
    main()
