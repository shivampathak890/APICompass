"""Streaming evidence-based adjudication service emitting real-time SSE progress events."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import AsyncGenerator, Callable, Coroutine, Dict, List, Optional, Set

from app.config import settings
from app.repositories.scan_repository import ScanRepository
from app.schemas.ast_analysis import CallInfo
from app.schemas.documentation import DocRetrievalRequest, NormalizedEvidence
from app.schemas.evidence import (
    AnalysisRequest,
    AnalysisReport,
    CandidateAssessment,
    QuoteVerificationResult,
    VerifiedIssue,
)
from app.schemas.stream import ScanProgressEvent
from app.services.documentation.retrieval_service import retrieval_service
from app.services.documentation.security import validate_destination_url
from app.services.evidence.adjudicator import is_evidence_relevant
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import quote_verifier
from app.services.llm.reasoning_service import llm_service
from app.services.python_ast_analyzer import analyze_python_source

logger = logging.getLogger("apicompass.stream_adjudicator")


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def format_sse(event: ScanProgressEvent) -> str:
    """Format a ScanProgressEvent into a standard SSE wire frame."""
    return f"event: {event.stage}\ndata: {event.model_dump_json()}\n\n"


class StreamAdjudicator:
    """Orchestrates real-time streaming adjudication yielding truthful progress events."""

    async def stream_adjudicate(
        self,
        request: AnalysisRequest,
        repo: Optional[ScanRepository] = None,
        is_disconnected: Optional[Callable[[], Coroutine[None, None, bool]]] = None,
        *,
        _internal_evidence: Optional[List[NormalizedEvidence]] = None,
    ) -> AsyncGenerator[ScanProgressEvent, None]:
        """Execute adjudication pipeline step-by-step, emitting real-time typed events."""
        if repo is None:
            repo = ScanRepository()

        # Pre-execution disconnect check
        if is_disconnected and await is_disconnected():
            logger.info("Client already disconnected before stream adjudication began.")
            return

        # Stage 1: Accepted
        yield ScanProgressEvent(
            event_version="1.0.0",
            stage="accepted",
            message=f"Analysis request accepted for {request.filename} ({len(request.source)} characters).",
            timestamp=_now_iso(),
            progress_percent=5,
        )

        try:
            # Check ecosystem support
            if request.ecosystem.lower() != "stripe":
                report = AnalysisReport(
                    verdict="unable_to_verify",
                    engine_version="0.1.0",
                    filename=request.filename,
                    total_lines=0,
                    evidence_trust="untrusted_or_unavailable",
                    is_mock=False,
                    summary=f"Ecosystem '{request.ecosystem}' is not supported. APICompass currently verifies the 'stripe' ecosystem.",
                    checks_performed=["API ecosystem compatibility check"],
                    verified_issues=[],
                    ai_suggestions=[],
                    unresolved_candidates=[],
                    candidate_assessments=[],
                    evidence_items=[],
                    limitations_and_caveats=[
                        f"UNSUPPORTED_ECOSYSTEM: '{request.ecosystem}' is not supported. Supported ecosystem: stripe."
                    ],
                    syntax_error=None,
                    llm_reasoning_status="disabled",
                    llm_reasoning_summary=None,
                    persistence_status="disabled",
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="completed",
                    message=f"Analysis halted: ecosystem '{request.ecosystem}' is not supported.",
                    timestamp=_now_iso(),
                    progress_percent=100,
                    report=report,
                )
                return

            # Stage 2: Static Analysis Started
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="static_analysis_started",
                message="Parsing Python source AST (zero execution)...",
                timestamp=_now_iso(),
                progress_percent=15,
            )

            try:
                ast_result = analyze_python_source(request.source, request.filename)
            except Exception as e:
                logger.error("Analysis exception during AST parse for %s: %s", request.filename, e, exc_info=True)
                report = AnalysisReport(
                    verdict="unable_to_verify",
                    engine_version="0.1.0",
                    filename=request.filename,
                    total_lines=0,
                    evidence_trust="untrusted_or_unavailable",
                    is_mock=False,
                    summary="Internal analysis error encountered during Python code parsing. Analysis halted safely.",
                    checks_performed=["Python AST parsing"],
                    verified_issues=[],
                    ai_suggestions=[],
                    unresolved_candidates=[],
                    candidate_assessments=[],
                    evidence_items=[],
                    limitations_and_caveats=[
                        "ANALYSIS_FAILURE: An internal error occurred while parsing the Python AST. Code execution was strictly prevented."
                    ],
                    syntax_error=None,
                    llm_reasoning_status="disabled",
                    llm_reasoning_summary=None,
                    persistence_status="disabled",
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="completed",
                    message="Analysis halted: internal error during AST parsing.",
                    timestamp=_now_iso(),
                    progress_percent=100,
                    report=report,
                )
                return

            # Handle Syntax Error
            if ast_result.status == "syntax_error" and ast_result.syntax_error:
                report = AnalysisReport(
                    verdict="unable_to_verify",
                    engine_version="0.1.0",
                    filename=request.filename,
                    total_lines=ast_result.total_lines,
                    evidence_trust="untrusted_or_unavailable",
                    is_mock=False,
                    summary=f"Python syntax error on line {ast_result.syntax_error.lineno}: {ast_result.syntax_error.message}",
                    checks_performed=["Python AST syntax validation"],
                    verified_issues=[],
                    ai_suggestions=[],
                    unresolved_candidates=[],
                    candidate_assessments=[],
                    evidence_items=[],
                    limitations_and_caveats=["Analysis halted due to invalid Python syntax."],
                    syntax_error=ast_result.syntax_error,
                    llm_reasoning_status="disabled",
                    llm_reasoning_summary=None,
                    persistence_status="disabled",
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="static_analysis_completed",
                    message=f"Python syntax error on line {ast_result.syntax_error.lineno}: {ast_result.syntax_error.message}",
                    timestamp=_now_iso(),
                    progress_percent=25,
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="completed",
                    message="Analysis halted due to invalid Python syntax.",
                    timestamp=_now_iso(),
                    progress_percent=100,
                    report=report,
                )
                return

            # Handle Zero Candidates / Non-API Code
            if not ast_result.candidates:
                report = AnalysisReport(
                    verdict="unable_to_verify",
                    engine_version="0.1.0",
                    filename=request.filename,
                    total_lines=ast_result.total_lines,
                    evidence_trust="untrusted_or_unavailable",
                    is_mock=False,
                    summary="No supported in-scope API calls detected in the submitted Python source. Verification was not performed.",
                    checks_performed=[
                        "Python AST syntax validation",
                        "Python AST call graph extraction",
                        "API candidate identification",
                    ],
                    verified_issues=[],
                    ai_suggestions=[],
                    unresolved_candidates=[],
                    candidate_assessments=[],
                    evidence_items=[],
                    limitations_and_caveats=[
                        "NO_IN_SCOPE_CANDIDATES: Static AST analysis identified no supported Stripe API calls to verify.",
                        "This does not certify that the submitted code is correct, bug-free, or compliant with third-party libraries outside the supported ecosystem.",
                    ],
                    syntax_error=None,
                    llm_reasoning_status="disabled",
                    llm_reasoning_summary=None,
                    persistence_status="disabled",
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="static_analysis_completed",
                    message="Static AST analysis found 0 in-scope API candidates.",
                    timestamp=_now_iso(),
                    progress_percent=25,
                )
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="completed",
                    message="Analysis complete: no in-scope API calls detected.",
                    timestamp=_now_iso(),
                    progress_percent=100,
                    report=report,
                )
                return

            # AST Analysis Completed
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="static_analysis_completed",
                message=f"Extracted {len(ast_result.candidates)} API candidates and {len(ast_result.calls)} calls across {ast_result.total_lines} lines.",
                timestamp=_now_iso(),
                progress_percent=30,
            )

            # Check Disconnect
            if is_disconnected and await is_disconnected():
                logger.info("Client disconnected after static analysis.")
                return

            checks_performed: List[str] = [
                "Python AST syntax validation",
                "Python AST call graph extraction",
                "API candidate identification",
                "Documentation evidence retrieval",
                "API contract matching",
                "Deterministic quotation verification",
            ]

            call_map: Dict[int, CallInfo] = {c.location.lineno: c for c in ast_result.calls}

            # Stage 3: LLM Candidate Reasoning (if enabled)
            ai_suggestions = []
            suggested_urls: Set[str] = set()
            llm_resp_status = "disabled"
            llm_resp_summary = None
            llm_error_message = None

            if settings.LLM_PROVIDER != "disabled":
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="ai_reasoning_started",
                    message=f"Proposing candidate interpretations via LLM ({settings.LLM_PROVIDER})...",
                    timestamp=_now_iso(),
                    progress_percent=40,
                )

                existing_ev_ids = [e.evidence_id for e in _internal_evidence] if _internal_evidence else []
                llm_resp, ai_suggestions, suggested_urls = await llm_service.reason(
                    source=request.source,
                    filename=request.filename,
                    ecosystem=request.ecosystem,
                    candidates=ast_result.candidates,
                    imports=ast_result.imports,
                    existing_evidence_ids=existing_ev_ids,
                )
                llm_resp_status = llm_resp.status
                llm_resp_summary = llm_resp.overall_reasoning_summary
                llm_error_message = llm_resp.error_message

                if llm_resp.status in ("available", "mock"):
                    checks_performed.append(f"LLM candidate reasoning ({llm_resp.provider})")

                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="ai_reasoning_completed",
                    message=f"LLM reasoning status: {llm_resp.status} ({len(ai_suggestions)} unverified suggestions).",
                    timestamp=_now_iso(),
                    progress_percent=50,
                )

            # Check Disconnect
            if is_disconnected and await is_disconnected():
                logger.info("Client disconnected after LLM reasoning.")
                return

            # Stage 4: Documentation Retrieval (Search & Fetch)
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="documentation_retrieval_started",
                message=f"Retrieving official documentation for {len(ast_result.candidates)} candidate(s)...",
                timestamp=_now_iso(),
                progress_percent=55,
            )

            # Stage 4A: Documentation Search
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="doc_search_started",
                message=f"Searching documentation registry for {len(ast_result.candidates)} candidate operation(s)...",
                timestamp=_now_iso(),
                progress_percent=60,
            )

            evidence_items: List[NormalizedEvidence] = []
            if _internal_evidence is not None:
                evidence_items = _internal_evidence
            else:
                use_mock_retrieval = settings.MOCK_MODE or request.force_mock or not settings.TINYFISH_API_KEY
                seen_queries: Set[str] = set()
                seen_ev_ids: Set[str] = set()

                for cand in ast_result.candidates:
                    if cand.receiver and cand.target_name:
                        query_expr = f"{cand.receiver}.{cand.target_name}"
                    elif cand.expression:
                        query_expr = cand.expression.split("(", 1)[0].strip()
                    else:
                        query_expr = cand.target_name
                    if not query_expr:
                        continue
                    norm_query = query_expr.strip()
                    if norm_query in seen_queries:
                        continue
                    seen_queries.add(norm_query)

                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="doc_search_completed",
                    message=f"Identified documentation targets for {len(seen_queries)} distinct candidate pattern(s).",
                    timestamp=_now_iso(),
                    progress_percent=65,
                )

                # Stage 4B: Documentation Fetch
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="doc_fetch_started",
                    message=f"Fetching and hashing verified documentation page content ({'mock offline mode' if use_mock_retrieval else 'live TinyFish'})...",
                    timestamp=_now_iso(),
                    progress_percent=70,
                )

                for norm_query in seen_queries:
                    if is_disconnected and await is_disconnected():
                        logger.info("Client disconnected during documentation retrieval loop.")
                        return

                    try:
                        retrieval_res = await retrieval_service.retrieve(
                            DocRetrievalRequest(
                                query=norm_query,
                                ecosystem=request.ecosystem,
                                force_mock=use_mock_retrieval,
                                max_results=3,
                            )
                        )
                        if retrieval_res.status in ("live", "success", "mock") and retrieval_res.evidence:
                            for ev in retrieval_res.evidence:
                                if ev.evidence_id not in seen_ev_ids:
                                    is_valid, _, _ = validate_destination_url(ev.canonical_url)
                                    if is_valid:
                                        seen_ev_ids.add(ev.evidence_id)
                                        evidence_items.append(ev)
                        elif retrieval_res.evidence:
                            # Record error evidence items (e.g. auth failure, rate limit) for honest limitation reporting
                            for ev in retrieval_res.evidence:
                                if ev.evidence_id not in seen_ev_ids:
                                    seen_ev_ids.add(ev.evidence_id)
                                    evidence_items.append(ev)
                    except Exception as e:
                        logger.warning("Failed to retrieve docs for query %s: %s", norm_query, e)

                for sug_url in sorted(suggested_urls):
                    if is_disconnected and await is_disconnected():
                        logger.info("Client disconnected during documentation retrieval loop.")
                        return
                    try:
                        retrieval_res = await retrieval_service.retrieve(
                            DocRetrievalRequest(
                                target_url=sug_url,
                                ecosystem=request.ecosystem,
                                force_mock=use_mock_retrieval,
                            )
                        )
                        if retrieval_res.status in ("live", "success", "mock") and retrieval_res.evidence:
                            for ev in retrieval_res.evidence:
                                if ev.evidence_id not in seen_ev_ids:
                                    is_valid, _, _ = validate_destination_url(ev.canonical_url)
                                    if is_valid:
                                        seen_ev_ids.add(ev.evidence_id)
                                        evidence_items.append(ev)
                        elif retrieval_res.evidence:
                            for ev in retrieval_res.evidence:
                                if ev.evidence_id not in seen_ev_ids:
                                    seen_ev_ids.add(ev.evidence_id)
                                    evidence_items.append(ev)
                    except Exception as e:
                        logger.warning("Failed to retrieve docs for URL %s: %s", sug_url, e)

                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="doc_fetch_completed",
                    message=f"Completed documentation fetching ({len(evidence_items)} record(s) retrieved).",
                    timestamp=_now_iso(),
                    progress_percent=73,
                )

            # Determine trust
            if not evidence_items:
                evidence_trust = "untrusted_or_unavailable"
                is_mock = False
            elif any(e.is_mock or e.provider == "tinyfish_mock" or e.source_trust == "mock_fixture" for e in evidence_items):
                evidence_trust = "mock_fixture"
                is_mock = True
            elif any(e.source_trust in ("untrusted", "rejected") or e.status in ("unavailable", "rejected", "error", "rate_limited", "failed") for e in evidence_items):
                evidence_trust = "untrusted_or_unavailable"
                is_mock = False
            else:
                evidence_trust = "live_official_source"
                is_mock = False

            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="documentation_retrieval_completed",
                message=f"Retrieved {len(evidence_items)} documentation records (mode: {'mock' if is_mock else 'live'}).",
                timestamp=_now_iso(),
                progress_percent=75,
            )

            # Check Disconnect
            if is_disconnected and await is_disconnected():
                logger.info("Client disconnected after documentation retrieval.")
                return

            # Stage 5: Evidence Verification & Contract Matching
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="evidence_verification_started",
                message="Verifying quotations with SHA-256 digests and matching API contracts...",
                timestamp=_now_iso(),
                progress_percent=80,
            )

            candidate_assessments: List[CandidateAssessment] = []
            all_verified_issues: List[VerifiedIssue] = []
            unresolved_candidates: List[str] = []

            for cand in ast_result.candidates:
                call_info = call_map.get(cand.location.lineno)
                match_record, issues = contract_matcher.match_candidate_to_evidence(
                    candidate=cand,
                    call_info=call_info,
                    evidence_items=evidence_items,
                )

                verified_quotes: List[QuoteVerificationResult] = []
                verified_issues: List[VerifiedIssue] = []
                for finding in issues:
                    matching_ev = next((e for e in evidence_items if e.evidence_id == finding.supporting_evidence_id), None)
                    if not matching_ev:
                        continue

                    is_rel, rel_err = is_evidence_relevant(cand, finding, matching_ev)
                    if not is_rel:
                        logger.warning("Stream adjudicator rejecting finding %s: %s", finding.finding_id, rel_err)
                        continue

                    q_res = quote_verifier.verify_quote(
                        finding.contract_quote,
                        matching_ev,
                        claimed_quote_kind="exact_quotation",
                    )
                    verified_quotes.append(q_res)
                    if (
                        q_res.is_verified
                        and q_res.quote_kind == "exact_quotation"
                        and not is_mock
                        and not q_res.is_mock
                        and matching_ev.source_trust == "official"
                    ):
                        verified_issues.append(
                            VerifiedIssue(
                                issue_id=finding.finding_id,
                                candidate_id=cand.candidate_id,
                                source_location=cand.location,
                                claim_checked=finding.claim_checked,
                                violation_type=finding.violation_type,
                                explanation=finding.explanation,
                                supporting_evidence_id=finding.supporting_evidence_id,
                                source_url=finding.source_url,
                                verified_quote=q_res.matched_text or finding.contract_quote,
                                match_method=q_res.match_method,
                                verification_status="verified",
                                quote_kind="exact_quotation",
                                supporting_excerpt=matching_ev.content_excerpt,
                                evidence_rationale=(
                                    f"Verified against official documentation at {finding.source_url}. "
                                    f"Exact quotation matches source excerpt via {q_res.match_method} matching."
                                ),
                                limitations=finding.limitations,
                                code_fragment=cand.call_expr,
                                file_path=getattr(cand, "file_path", None),
                            )
                        )

                if is_mock or (match_record and "MOCK FIXTURE" in match_record.match_rationale):
                    cand_status = "unresolved"
                    unresolved_candidates.append(cand.candidate_id)
                    abstention_reason = "MOCK_EVIDENCE_ONLY"
                    explanation = (
                        "Evaluated against offline mock fixtures. In strict adherence to integrity rules, "
                        "mock evidence cannot resolve candidates or establish verified contract violations."
                    )
                    verified_issues = []
                elif verified_issues:
                    cand_status = "resolved_issue"
                    all_verified_issues.extend(verified_issues)
                    explanation = f"Detected {len(verified_issues)} verified API contract violation(s)."
                    abstention_reason = None
                elif match_record and match_record.is_ambiguous:
                    cand_status = "unresolved"
                    unresolved_candidates.append(cand.candidate_id)
                    if "conflicting" in match_record.match_rationale.lower():
                        abstention_reason = "CONFLICTING_DOCUMENTATION"
                        explanation = match_record.match_rationale
                    else:
                        abstention_reason = "AMBIGUOUS_OPERATION_MATCH"
                        explanation = match_record.match_rationale
                elif not match_record or match_record.completeness == "missing":
                    cand_status = "unresolved"
                    unresolved_candidates.append(cand.candidate_id)
                    explanation = (
                        match_record.match_rationale
                        if match_record
                        else f"No official documentation retrieved for '{cand.target_name}'."
                    )
                    abstention_reason = "DOCUMENTATION_MISSING"
                elif match_record.completeness == "excerpt_only":
                    cand_status = "unresolved"
                    unresolved_candidates.append(cand.candidate_id)
                    explanation = (
                        f"Retrieved excerpt from {match_record.source_url} does not establish a complete "
                        "contract schema; abstaining to avoid false inference."
                    )
                    abstention_reason = "INCOMPLETE_EXCERPT_CONTRACT"
                else:
                    cand_status = "resolved_clean"
                    explanation = f"Verified compliance against official contract for {match_record.matched_operation}."
                    abstention_reason = None

                candidate_assessments.append(
                    CandidateAssessment(
                        candidate_id=cand.candidate_id,
                        target_name=cand.target_name,
                        receiver=cand.receiver,
                        call_expr=cand.expression,
                        source_location=cand.location,
                        status=cand_status,
                        evidence_match=match_record,
                        verified_quotes=verified_quotes,
                        issues=verified_issues,
                        abstention_reason=abstention_reason,
                        explanation=explanation,
                    )
                )

            limitations_and_caveats: List[str] = [
                "Contract checks are scoped strictly to officially retrieved documentation.",
                "Dynamic runtime behavior, reflection, and monkey-patching are not evaluated.",
            ]

            if is_mock or evidence_trust == "mock_fixture":
                verdict = "unable_to_verify"
                all_verified_issues = []
                summary = (
                    "Analysis executed in MOCK MODE using offline fixtures. In strict adherence to integrity rules, "
                    "mock evidence cannot produce verified production 'clean' or 'issues_found' verdicts against user code."
                )
                limitations_and_caveats.insert(
                    0,
                    "MOCK_EVIDENCE_ONLY: Live TinyFish credentials required to produce verified production verdicts.",
                )
            elif all_verified_issues:
                verdict = "issues_found"
                summary = (
                    f"Identified {len(all_verified_issues)} verified API contract violation(s) "
                    f"across {len(ast_result.candidates)} analyzed candidate(s)."
                )
                if unresolved_candidates:
                    summary += f" Note: {len(unresolved_candidates)} candidate(s) remain unresolved."
            elif unresolved_candidates:
                verdict = "unable_to_verify"
                summary = (
                    f"Unable to conclusively verify {len(unresolved_candidates)} of "
                    f"{len(ast_result.candidates)} candidate(s) due to missing, ambiguous, or incomplete documentation."
                )
            else:
                verdict = "clean"
                summary = (
                    f"All {len(ast_result.candidates)} in-scope candidate(s) verified clean against official documentation contracts. "
                    "No issue detected within the checks performed. "
                    "This does not certify or imply that the entire program is correct, complete, or bug-free."
                )
                limitations_and_caveats.append(
                    "SCOPE_LIMITATION: A 'No issue detected within the checks performed' result only covers "
                    "supported API calls verified against retrieved documentation contracts. It does not certify "
                    "general program correctness, runtime behavior, or unanalyzed dependencies."
                )

            if llm_resp_status in ("unavailable", "error"):
                limitations_and_caveats.append(
                    f"LLM_REASONING_{llm_resp_status.upper()}: {llm_error_message or 'LLM reasoning provider unavailable.'}"
                )

            # Explicit error disclosures for external provider conditions
            for ev in evidence_items:
                if ev.error_code == "AUTHENTICATION_FAILED":
                    limitations_and_caveats.append(
                        "TINYFISH_AUTH_FAILURE: Documentation retrieval authentication failed (HTTP 401/403). "
                        "Check TINYFISH_API_KEY in your environment or switch to Mock Mode."
                    )
                    break
                elif ev.error_code == "RATE_LIMITED":
                    limitations_and_caveats.append(
                        "TINYFISH_RATE_LIMITED: Documentation retrieval rate limit reached (HTTP 429). "
                        "Please retry with backoff or switch to Mock Mode."
                    )
                    break
                elif ev.error_code == "TIMEOUT":
                    limitations_and_caveats.append(
                        "TINYFISH_TIMEOUT: Documentation retrieval request timed out. "
                        "Upstream provider failed to respond within the allocated deadline. Retry or switch to Mock Mode."
                    )
                    break
                elif ev.error_code == "CIRCUIT_BREAKER_OPEN":
                    limitations_and_caveats.append(
                        "TINYFISH_CIRCUIT_BREAKER: Documentation retrieval circuit breaker is open due to consecutive upstream failures. "
                        "Please retry later or use Mock Mode."
                    )
                    break

            clean_verified_issues: List[VerifiedIssue] = []
            for issue in all_verified_issues:
                if not issue.supporting_evidence_id.startswith("llm_") and issue.verification_status == "verified":
                    clean_verified_issues.append(issue)
                else:
                    logger.error("LLM suggestion leaked into stream verified_issues: %s", issue.issue_id)

            report = AnalysisReport(
                verdict=verdict,
                engine_version="0.1.0",
                filename=request.filename,
                total_lines=ast_result.total_lines,
                evidence_trust=evidence_trust,
                is_mock=is_mock,
                summary=summary,
                checks_performed=checks_performed,
                verified_issues=clean_verified_issues,
                ai_suggestions=ai_suggestions,
                unresolved_candidates=unresolved_candidates,
                candidate_assessments=candidate_assessments,
                evidence_items=evidence_items,
                limitations_and_caveats=limitations_and_caveats,
                syntax_error=None,
                llm_reasoning_status=llm_resp_status,
                llm_reasoning_summary=llm_resp_summary,
            )

            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="evidence_verification_completed",
                message=f"Deterministic adjudication complete. Verdict: {report.verdict}.",
                timestamp=_now_iso(),
                progress_percent=88,
            )

            # Check Disconnect
            if is_disconnected and await is_disconnected():
                logger.info("Client disconnected after evidence verification.")
                return

            # Stage 6: Persistence
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="persistence_started",
                message="Persisting scan audit record to SQLite repository...",
                timestamp=_now_iso(),
                progress_percent=92,
            )

            try:
                scan_id = repo.save_scan(request=request, report=report)
                report.scan_id = scan_id
                report.persistence_status = "saved"
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    scan_id=scan_id,
                    stage="persistence_completed",
                    message=f"Scan audit record persisted successfully with ID {scan_id}.",
                    timestamp=_now_iso(),
                    progress_percent=98,
                )
            except Exception as e:
                logger.warning("Database persistence failed for %s: %s", request.filename, e)
                report.scan_id = None
                report.persistence_status = "failed"
                yield ScanProgressEvent(
                    event_version="1.0.0",
                    stage="persistence_completed",
                    message=f"Database persistence failed: {type(e).__name__}; scan not saved to history.",
                    timestamp=_now_iso(),
                    progress_percent=98,
                )

            # Check Disconnect immediately after persistence
            if is_disconnected and await is_disconnected():
                logger.info(
                    "Client disconnected immediately after persistence; audit record %s remains committed.",
                    report.scan_id,
                )
                return

            # Stage 7: Completed
            yield ScanProgressEvent(
                event_version="1.0.0",
                scan_id=report.scan_id,
                stage="completed",
                message=f"Adjudication complete. Final verdict: {report.verdict}.",
                timestamp=_now_iso(),
                progress_percent=100,
                report=report,
            )

        except asyncio.CancelledError:
            logger.info("Stream adjudication cancelled by client/runtime.")
            raise
        except Exception as e:
            logger.exception("Unexpected error in streaming adjudication: %s", e)
            yield ScanProgressEvent(
                event_version="1.0.0",
                stage="failed",
                message="Internal analysis error occurred during adjudication.",
                error_code="ANALYSIS_FAILURE",
                timestamp=_now_iso(),
            )


stream_adjudicator = StreamAdjudicator()
