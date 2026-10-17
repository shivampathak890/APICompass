"""Conservative evidence-based adjudication engine.

Orchestrates:
1. Static Python AST analysis (zero execution).
2. Official documentation retrieval (TinyFish or deterministic mock fixtures).
3. API contract matching between AST candidates and retrieved evidence.
4. Deterministic quote verification with SHA-256 content hashing.
5. Strict mock evidence quarantine: mock evidence can NEVER produce production
   'clean' or 'issues_found' verdicts against user code.
6. Conservative adjudication precedence:
   - Syntax error -> 'unable_to_verify'
   - Internal analysis failure -> 'unable_to_verify'
   - Unsupported ecosystem -> 'unable_to_verify'
   - Zero recognized API candidates -> 'unable_to_verify' (NO_IN_SCOPE_CANDIDATES)
   - Mock evidence -> 'unable_to_verify' (MOCK_EVIDENCE_ONLY)
   - Verified issue found -> 'issues_found' (unresolved candidates stay unresolved)
   - Any candidate unresolved -> 'unable_to_verify'
   - All in-scope candidates verified clean under live official trust -> 'clean'
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from app.config import settings
from app.schemas.ast_analysis import ApiCandidate, CallInfo
from app.schemas.contract import ContractFindingCandidate
from app.schemas.documentation import DocRetrievalRequest, NormalizedEvidence
from app.schemas.evidence import (
    AnalysisRequest,
    AnalysisReport,
    CandidateAssessment,
    QuoteVerificationResult,
    VerifiedIssue,
)
from app.services.documentation.retrieval_service import retrieval_service
from app.services.documentation.security import validate_destination_url
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import quote_verifier
from app.services.llm.reasoning_service import llm_service, LLMReasoningService
from app.services.python_ast_analyzer import analyze_python_source

logger = logging.getLogger("apicompass.adjudicator")


def is_evidence_relevant(
    candidate: ApiCandidate,
    finding: Optional[ContractFindingCandidate],
    evidence: Optional[NormalizedEvidence],
) -> Tuple[bool, Optional[str]]:
    """Determine whether a documentation evidence record is genuinely relevant to an API candidate.

    Rejects:
    - Missing or empty evidence.
    - Untrusted or failed retrieval status.
    - Evidence from another ecosystem.
    - Disjoint API resource documentation (e.g. customer docs for a charge call).
    """
    if evidence is None:
        return False, "Evidence record is missing (None)."
    if not evidence.content_excerpt or not evidence.content_excerpt.strip():
        return False, "Evidence record contains empty content excerpt."
    if (
        evidence.source_trust in ("untrusted", "rejected")
        or evidence.status in ("unavailable", "rejected", "failed", "rate_limited", "auth_failed", "empty")
    ):
        return False, f"Evidence is untrusted or failed retrieval ({evidence.status})."
    if not getattr(evidence, "is_full_page", True):
        return False, "Search snippets cannot be treated as authoritative proof of contract violations; full documentation page retrieval is required."
    if evidence.ecosystem.lower() != "stripe":
        return False, f"Evidence ecosystem '{evidence.ecosystem}' is irrelevant to Stripe API calls."

    # Identify candidate resource keywords
    candidate_tokens = set()
    if candidate.normalized_target:
        candidate_tokens.update(
            p.lower() for p in candidate.normalized_target.split(".") if p.lower() not in ("stripe", "")
        )
    if candidate.receiver:
        candidate_tokens.update(
            p.lower() for p in candidate.receiver.split(".") if p.lower() not in ("stripe", "client", "")
        )
    if candidate.target_name:
        candidate_tokens.add(candidate.target_name.lower())

    expanded_candidate_tokens = set(candidate_tokens)
    for tok in list(candidate_tokens):
        if tok.endswith("s"):
            expanded_candidate_tokens.add(tok[:-1])
        else:
            expanded_candidate_tokens.add(tok + "s")
        if "_" in tok:
            expanded_candidate_tokens.add(tok.replace("_", ""))
            expanded_candidate_tokens.update(tok.split("_"))

    canonical_lower = evidence.canonical_url.lower()
    title_lower = (evidence.title or "").lower()
    headings_lower = " ".join(h.lower() for h in evidence.headings)

    # Disjoint resource check: reject documentation for completely different resources
    known_disjoint_resources = {
        "charge": ["customer", "invoice", "transfer", "coupon", "subscription", "file", "tax_rate"],
        "customer": ["charge", "refund", "payout", "transfer", "coupon"],
        "refund": ["customer", "coupon", "subscription", "tax_rate"],
        "payment_intent": ["coupon", "tax_rate", "file", "transfer"],
    }

    for res, disjoint in known_disjoint_resources.items():
        if res in expanded_candidate_tokens or res.replace("_", "") in expanded_candidate_tokens:
            for dis in disjoint:
                if (
                    f"/{dis}" in canonical_lower
                    and f"/{res}" not in canonical_lower
                    and res not in title_lower
                    and res not in headings_lower
                ):
                    return False, (
                        f"Evidence from {evidence.canonical_url} relates to '{dis}' resource, "
                        f"which is irrelevant to candidate operation '{candidate.normalized_target or candidate.expression}'."
                    )

    matched_any = any(
        tok in canonical_lower or tok in title_lower or tok in headings_lower
        for tok in expanded_candidate_tokens
        if len(tok) >= 3 and tok not in ("create", "retrieve", "update", "delete", "list", "get", "post")
    )
    if not matched_any and any(len(tok) >= 3 for tok in expanded_candidate_tokens):
        excerpt_lower = evidence.content_excerpt.lower()
        if not any(tok in excerpt_lower for tok in expanded_candidate_tokens if len(tok) >= 3):
            return False, (
                f"Evidence from {evidence.canonical_url} does not contain any reference to candidate "
                f"resource/operation tokens {sorted(list(expanded_candidate_tokens))}."
            )

    return True, None


class EvidenceAdjudicator:
    """Orchestrates deterministic API evidence verification and conservative adjudication."""

    async def adjudicate(
        self,
        request: AnalysisRequest,
        *,
        _internal_evidence: Optional[List[NormalizedEvidence]] = None,
        _llm_service_override: Optional[LLMReasoningService] = None,
    ) -> AnalysisReport:
        """Run full deterministic adjudication on submitted Python source.

        Args:
            request: Public AnalysisRequest payload.
            _internal_evidence: Internal test-only parameter for synthetic live evidence fixtures.
                                Never accepted or exposed through public API endpoints.
            _llm_service_override: Internal test-only parameter for injecting custom LLM reasoning service.
        """
        # Guard: Check supported ecosystem (Finding 3)
        if request.ecosystem.lower() != "stripe":
            return AnalysisReport(
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
            )

        # 1. Parse Python AST safely (Zero-Execution Guarantee)
        try:
            ast_result = analyze_python_source(request.source, request.filename)
        except Exception as e:
            logger.error("Analysis exception during AST parse for %s: %s", request.filename, e, exc_info=True)
            return AnalysisReport(
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
            )

        # Handle Syntax Errors immediately
        if ast_result.status == "syntax_error" and ast_result.syntax_error:
            return AnalysisReport(
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
            )

        checks_performed: List[str] = [
            "Python AST syntax validation",
            "Python AST call graph extraction",
            "API candidate identification",
            "Documentation evidence retrieval",
            "API contract matching",
            "Deterministic quotation verification",
        ]

        # 2. Handle Non-API Code or Zero Candidates (Finding 3):
        # A file with no in-scope candidates MUST NOT automatically certify the entire program as clean.
        if not ast_result.candidates:
            return AnalysisReport(
                verdict="unable_to_verify",
                engine_version="0.1.0",
                filename=request.filename,
                total_lines=ast_result.total_lines,
                evidence_trust="untrusted_or_unavailable",
                is_mock=False,
                summary="No supported in-scope API calls detected in the submitted Python source. Verification was not performed.",
                checks_performed=["Python AST syntax validation", "Python AST call graph extraction", "API candidate identification"],
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
            )

        # 3. Map Candidates to CallInfo
        call_map: Dict[int, CallInfo] = {c.location.lineno: c for c in ast_result.calls}

        # 4. LLM-Assisted Candidate Reasoning (Advisory)
        active_llm = _llm_service_override or llm_service
        existing_ev_ids = [e.evidence_id for e in _internal_evidence] if _internal_evidence else []
        llm_resp, ai_suggestions, suggested_urls = await active_llm.reason(
            source=request.source,
            filename=request.filename,
            ecosystem=request.ecosystem,
            candidates=ast_result.candidates,
            imports=ast_result.imports,
            existing_evidence_ids=existing_ev_ids,
        )
        if llm_resp.status in ("available", "mock"):
            checks_performed.append(f"LLM candidate reasoning ({llm_resp.provider})")

        # 5. Retrieve Relevant Official Documentation
        evidence_items: List[NormalizedEvidence] = []

        if _internal_evidence is not None:
            # Internal test helper injection (cannot be accessed via public HTTP requests)
            evidence_items = _internal_evidence
        else:
            # Production retrieval via configured retrieval service
            use_mock_retrieval = settings.MOCK_MODE or request.force_mock or not settings.TINYFISH_API_KEY
            seen_queries: Set[str] = set()
            seen_ev_ids: Set[str] = set()

            # Dynamic documentation resolution for each identified API candidate
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
                    elif retrieval_res.status in ("unavailable", "rejected", "error"):
                        logger.info(
                            "Doc retrieval for query '%s' resulted in status '%s': %s",
                            norm_query,
                            retrieval_res.status,
                            retrieval_res.message,
                        )
                except Exception as e:
                    logger.warning("Failed to retrieve docs for query '%s': %s", norm_query, e)

            # Incorporate validated documentation URLs suggested by LLM reasoning (if any)
            for sug_url in sorted(suggested_urls):
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
                except Exception as e:
                    logger.warning("Failed to retrieve docs for suggested URL '%s': %s", sug_url, e)

        # 5. Determine Overall Evidence Trust from retrieved evidence (Finding 1 & 2)
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

        # 6. Evaluate Each Candidate Against Retrieved Evidence
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

            # Check quotes for candidate findings to promote to verified issues
            verified_quotes: List[QuoteVerificationResult] = []
            verified_issues: List[VerifiedIssue] = []
            for finding in issues:
                matching_ev = next((e for e in evidence_items if e.evidence_id == finding.supporting_evidence_id), None)
                if not matching_ev:
                    logger.warning("Rejecting finding %s: Missing supporting evidence record.", finding.finding_id)
                    continue

                is_rel, rel_err = is_evidence_relevant(cand, finding, matching_ev)
                if not is_rel:
                    logger.warning("Rejecting finding %s due to irrelevant evidence: %s", finding.finding_id, rel_err)
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
                    cand_expr = getattr(cand, "expression", getattr(cand, "call_expr", ""))
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
                            canonical_url=matching_ev.canonical_url or finding.source_url,
                            source_title=matching_ev.title,
                            retrieval_status=matching_ev.status,
                            retrieved_at=matching_ev.retrieved_at,
                            content_sha256=matching_ev.content_sha256,
                            is_mock=bool(is_mock or q_res.is_mock or matching_ev.is_mock),
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
                            code_fragment=cand_expr,
                            file_path=getattr(cand, "file_path", None),
                            detected_call=cand_expr,
                            detected_argument=finding.parameter_name,
                            expected_contract=f"Official documentation requires: \"{q_res.matched_text or finding.contract_quote}\"",
                            observed_usage=(
                                f"Detected argument '{finding.parameter_name}' ({finding.supplied_value_repr})"
                                if finding.parameter_name and finding.supplied_value_repr
                                else (f"Detected call '{cand_expr}'" if not finding.parameter_name else f"Missing argument '{finding.parameter_name}'")
                            ),
                            suggested_action=(
                                "Replace the legacy parameter with recommended modern alternatives."
                                if "legacy" in finding.violation_type or "deprecated" in finding.violation_type
                                else f"Supply the required parameter '{finding.parameter_name}'."
                                if "missing" in finding.violation_type
                                else f"Remove unsupported parameter '{finding.parameter_name}'."
                                if "unsupported" in finding.violation_type
                                else "Review documented API parameter constraints."
                            ),
                            severity="warning" if ("deprecated" in finding.violation_type or "legacy" in finding.violation_type) else "error",
                            confidence="verified",
                        )
                    )

            # STRICT MOCK QUARANTINE (Finding 1 & Finding 4):
            # If evidence is mock, candidates CANNOT be resolved clean or resolved as an issue!
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
                # Complete contract and zero violations found under live official trust
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
                    file_path=getattr(cand, "file_path", None),
                )
            )

        # 7. Apply Conservative Adjudication Precedence & Strict Mock Quarantine
        limitations_and_caveats: List[str] = [
            "Contract checks are scoped strictly to officially retrieved documentation.",
            "Dynamic runtime behavior, reflection, and monkey-patching are not evaluated.",
        ]

        if is_mock or evidence_trust == "mock_fixture":
            verdict = "unable_to_verify"
            all_verified_issues = []  # Invariant 2 & 5: Mock evidence must NEVER report verified issues
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
            if any(ca.abstention_reason == "DOCUMENTATION_MISSING" for ca in candidate_assessments):
                limitations_and_caveats.insert(
                    0,
                    "DOCUMENTATION_MISSING: Analysis abstained from generating contract violations because official "
                    "documentation for the identified API call could not be retrieved.",
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

        if llm_resp.status in ("unavailable", "error"):
            limitations_and_caveats.append(
                f"LLM_REASONING_{llm_resp.status.upper()}: {llm_resp.error_message or 'LLM reasoning provider unavailable.'}"
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

        # LLM Elevation Defense (Requirement 7):
        # AI suggestions must never be present in verified_issues, and must carry 'unverified_suggestion' status
        clean_verified_issues: List[VerifiedIssue] = []
        for issue in all_verified_issues:
            if not issue.supporting_evidence_id.startswith("llm_") and issue.verification_status == "verified":
                clean_verified_issues.append(issue)
            else:
                logger.error("LLM suggestion leaked into verified_issues: %s", issue.issue_id)

        return AnalysisReport(
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
            llm_reasoning_status=llm_resp.status,
            llm_reasoning_summary=llm_resp.overall_reasoning_summary,
        )


# Singleton instance
adjudicator = EvidenceAdjudicator()
