"""Project-level static analysis and evidence adjudication engine.

Orchestrates:
1. Zero-execution AST analysis across all submitted project files.
2. Independent parsing with syntax-error resilience (errors in one file do not crash others).
3. Conservative cross-file relationship graph resolution.
4. Project-wide API candidate collection and deduplication.
5. Evidence Court adjudication against official documentation contracts.
6. Strict mock evidence quarantine: mock evidence never produces production 'clean' or 'issues_found'.
7. Deterministic project-level verdict determination adhering to conservative precedence rules.
"""

import hashlib
import logging
from typing import Dict, List, Optional, Set, Tuple

from app.config import settings
from app.repositories import ScanRepository
from app.schemas.ast_analysis import (
    AnalyzePythonResponse,
    ApiCandidate,
    CallInfo,
)
from app.schemas.documentation import DocRetrievalRequest, NormalizedEvidence
from app.schemas.evidence import (
    AISuggestion,
    CandidateAssessment,
    EvidenceTrustType,
    QuoteVerificationResult,
    VerdictType,
    VerifiedIssue,
)
from app.schemas.project_analysis import (
    ProjectAnalysisReport,
    ProjectAnalysisRequest,
    ProjectFileAnalysisResult,
    ProjectRelationship,
)
from app.services.documentation.retrieval_service import retrieval_service
from app.services.documentation.security import validate_destination_url
from app.services.evidence.adjudicator import is_evidence_relevant
from app.services.evidence.contract_matcher import contract_matcher
from app.services.evidence.quote_verifier import quote_verifier
from app.services.llm.reasoning_service import llm_service, LLMReasoningService
from app.services.project.graph_resolver import ProjectGraphResolver
from app.services.python_ast_analyzer import analyze_python_source

logger = logging.getLogger("apicompass.project.adjudicator")


class ProjectAdjudicator:
    """Orchestrates multi-file Python project static analysis and Evidence Court verification."""

    async def adjudicate_project(
        self,
        request: ProjectAnalysisRequest,
        repo: Optional[ScanRepository] = None,
        *,
        _internal_evidence: Optional[List[NormalizedEvidence]] = None,
        _llm_service_override: Optional[LLMReasoningService] = None,
    ) -> ProjectAnalysisReport:
        """Run complete static analysis, graph resolution, and Evidence Court on a multi-file project."""
        logger.info(
            "Starting multi-file project analysis for '%s' (%d files, ecosystem: %s)",
            request.project_name,
            len(request.files),
            request.ecosystem,
        )

        checks_performed: List[str] = [
            "Project path safety and normalization check",
            "Zero-execution multi-file AST parsing",
            "Cross-file dependency and relationship graph resolution",
            "Project API candidate extraction and deduplication",
        ]

        # Guard: Check supported ecosystem
        if request.ecosystem.lower() != "stripe":
            return self._build_unsupported_ecosystem_report(request)

        # 1. Parse each Python file independently (syntax errors do not halt parsing of other files)
        file_results: List[ProjectFileAnalysisResult] = []
        ast_results_map: Dict[str, AnalyzePythonResponse] = {}
        files_data_map: Dict[str, str] = {}
        syntax_errors_count = 0
        total_combined_lines = 0

        for file_item in request.files:
            files_data_map[file_item.path] = file_item.content
            try:
                ast_res = analyze_python_source(file_item.content, filename=file_item.path)
            except Exception as e:
                logger.error("Internal AST failure in file %s: %s", file_item.path, e, exc_info=True)
                ast_res = AnalyzePythonResponse(
                    status="syntax_error",
                    engine_version="0.1.0",
                    filename=file_item.path,
                    total_lines=len(file_item.content.splitlines()),
                    syntax_error=None,
                    imports=[],
                    functions=[],
                    classes=[],
                    calls=[],
                    candidates=[],
                    relevant_literals=[],
                )

            ast_results_map[file_item.path] = ast_res
            total_combined_lines += ast_res.total_lines

            is_syntax_err = ast_res.status == "syntax_error"
            if is_syntax_err:
                syntax_errors_count += 1

            file_results.append(
                ProjectFileAnalysisResult(
                    path=file_item.path,
                    parse_status="syntax_error" if is_syntax_err else "success",
                    total_lines=ast_res.total_lines,
                    syntax_error=ast_res.syntax_error,
                    imports=ast_res.imports,
                    functions=ast_res.functions,
                    classes=ast_res.classes,
                    calls=ast_res.calls,
                    candidates=ast_res.candidates,
                    relevant_literals=ast_res.relevant_literals,
                    defined_symbols=[],  # will be populated by graph resolver
                )
            )

        # 2. Build cross-file relationship graph
        resolver = ProjectGraphResolver(files_data_map, ast_results_map)
        relationships, circular_warnings = resolver.resolve_all_relationships()

        # Update defined_symbols in file_results
        for fres in file_results:
            fres.defined_symbols = resolver.defined_symbols.get(fres.path, [])

        resolved_imports = sum(1 for r in relationships if r.status == "resolved")
        unresolved_imports = sum(1 for r in relationships if r.status == "unresolved")
        ambiguous_imports = sum(1 for r in relationships if r.status == "ambiguous")
        external_imports = sum(1 for r in relationships if r.status == "external")

        # 3. Collect and deduplicate API candidates across all project files
        all_candidates: List[Tuple[str, ApiCandidate]] = []
        call_maps_by_file: Dict[str, Dict[int, CallInfo]] = {}

        candidate_global_idx = 1
        for fres in file_results:
            call_maps_by_file[fres.path] = {c.location.lineno: c for c in fres.calls}
            for cand in fres.candidates:
                # Ensure globally unique candidate ID across files while preserving file association
                unique_cand_id = f"cand_p{candidate_global_idx:03d}"
                candidate_global_idx += 1
                unique_cand = cand.model_copy(update={"candidate_id": unique_cand_id})
                all_candidates.append((fres.path, unique_cand))

        total_candidates_count = len(all_candidates)

        # 4. Evidence Retrieval and Evidence Court Evaluation
        evidence_items: List[NormalizedEvidence] = []
        all_verified_issues: List[VerifiedIssue] = []
        candidate_assessments: List[CandidateAssessment] = []
        unresolved_candidates: List[str] = []
        ai_suggestions: List[AISuggestion] = []
        limitations: List[str] = [
            "Project analysis is strictly static and zero-execution; dynamic behavior and reflection are not evaluated.",
            "Import resolution reflects syntax-level module hierarchies and does not execute package __init__ files.",
        ]

        if circular_warnings:
            limitations.extend(circular_warnings)

        if syntax_errors_count > 0:
            syntax_files = [f.path for f in file_results if f.parse_status == "syntax_error"]
            limitations.append(
                f"SYNTAX_ERRORS_IN_PROJECT: {syntax_errors_count} file(s) contain syntax errors ({', '.join(syntax_files)}). Complete whole-project verification is impossible."
            )

        if unresolved_imports > 0 or ambiguous_imports > 0:
            limitations.append(
                f"UNRESOLVED_RELATIONSHIPS: {unresolved_imports} unresolved and {ambiguous_imports} ambiguous cross-file import(s) detected. Incomplete cross-file relationships prevent certifying the project as clean."
            )

        # If zero candidates across the entire project
        if total_candidates_count == 0:
            return self._build_zero_candidates_report(
                request=request,
                file_results=file_results,
                relationships=relationships,
                total_lines=total_combined_lines,
                syntax_errors_count=syntax_errors_count,
                resolved_imports=resolved_imports,
                unresolved_imports=unresolved_imports,
                ambiguous_imports=ambiguous_imports,
                external_imports=external_imports,
                limitations=limitations,
                repo=repo,
            )

        # 5. Retrieve Official Documentation
        checks_performed.extend([
            "Documentation evidence retrieval",
            "API contract matching",
            "Deterministic quotation verification",
        ])

        if _internal_evidence is not None:
            evidence_items = _internal_evidence
        else:
            use_mock = settings.MOCK_MODE or request.force_mock or not settings.TINYFISH_API_KEY
            seen_queries: Set[str] = set()
            seen_ev_ids: Set[str] = set()

            for _, cand in all_candidates:
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
                    res = await retrieval_service.retrieve(
                        DocRetrievalRequest(
                            query=norm_query,
                            ecosystem=request.ecosystem,
                            force_mock=use_mock,
                            max_results=3,
                        )
                    )
                    if res.status in ("live", "success", "mock") and res.evidence:
                        for ev in res.evidence:
                            if ev.evidence_id not in seen_ev_ids:
                                is_valid, _, _ = validate_destination_url(ev.canonical_url)
                                if is_valid:
                                    seen_ev_ids.add(ev.evidence_id)
                                    evidence_items.append(ev)
                except Exception as e:
                    logger.warning("Doc retrieval failed for query '%s': %s", norm_query, e)

        # 6. Trust & Mock Classification
        if not evidence_items:
            evidence_trust: EvidenceTrustType = "untrusted_or_unavailable"
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

        # 7. Evaluate Candidates
        seen_issues_fingerprints: Set[Tuple[str, int, str, str]] = set()

        for file_path, cand in all_candidates:
            call_map = call_maps_by_file.get(file_path, {})
            call_info = call_map.get(cand.location.lineno)
            match_record, issues = contract_matcher.match_candidate_to_evidence(
                candidate=cand,
                call_info=call_info,
                evidence_items=evidence_items,
            )

            # Quote verification and issue promotion
            verified_quotes: List[QuoteVerificationResult] = []
            verified_issues: List[VerifiedIssue] = []
            for finding in issues:
                matching_ev = next((e for e in evidence_items if e.evidence_id == finding.supporting_evidence_id), None)
                if not matching_ev:
                    continue

                is_rel, rel_err = is_evidence_relevant(cand, finding, matching_ev)
                if not is_rel:
                    logger.warning("Project adjudicator rejecting finding %s: %s", finding.finding_id, rel_err)
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
                            file_path=file_path,
                        )
                    )

            # Strict Mock Quarantine: Mock evidence NEVER resolves candidates or issues
            if is_mock or (match_record and "MOCK FIXTURE" in match_record.match_rationale):
                cand_status = "unresolved"
                unresolved_candidates.append(cand.candidate_id)
                abstention_reason = "MOCK_EVIDENCE_ONLY"
                explanation = (
                    f"Candidate in '{file_path}' evaluated against offline mock fixtures. "
                    "In strict adherence to Evidence Court rules, mock evidence cannot produce verified verdicts."
                )
                verified_issues = []
            elif verified_issues:
                cand_status = "resolved_issue"
                for issue in verified_issues:
                    # Deduplicate findings across multiple import paths (Finding Suppression)
                    fingerprint = (
                        file_path,
                        issue.source_location.lineno,
                        issue.violation_type,
                        issue.claim_checked,
                    )
                    if fingerprint not in seen_issues_fingerprints:
                        seen_issues_fingerprints.add(fingerprint)
                        all_verified_issues.append(issue)

                explanation = f"Detected {len(verified_issues)} verified API contract violation(s) in '{file_path}'."
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
                    else f"No official documentation retrieved for '{cand.target_name}' in '{file_path}'."
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
                    file_path=file_path,
                )
            )

        # 8. Conservative Verdict Precedence
        if is_mock or evidence_trust == "mock_fixture":
            verdict: VerdictType = "unable_to_verify"
            all_verified_issues = []  # Strict Invariant: Zero verified issues under mock evidence
            summary = (
                f"Multi-file project analysis executed in MOCK MODE across {len(request.files)} file(s). "
                "In strict adherence to evidence integrity rules, mock evidence cannot produce verified verdicts."
            )
            limitations.insert(
                0,
                "MOCK_EVIDENCE_ONLY: Live TinyFish documentation retrieval credentials required to produce verified production verdicts.",
            )
        elif all_verified_issues:
            verdict = "issues_found"
            summary = (
                f"Identified {len(all_verified_issues)} verified API contract violation(s) "
                f"across {total_candidates_count} candidate(s) in {len(request.files)} file(s)."
            )
            if syntax_errors_count > 0:
                summary += f" Caveat: {syntax_errors_count} file(s) contained syntax errors."
            elif unresolved_candidates:
                summary += f" Note: {len(unresolved_candidates)} candidate(s) remain unresolved."
        elif syntax_errors_count > 0:
            verdict = "unable_to_verify"
            summary = (
                f"Unable to conclusively verify project: {syntax_errors_count} of {len(request.files)} "
                "file(s) contained Python syntax errors. Analysis could not fully parse project structure."
            )
        elif unresolved_candidates:
            verdict = "unable_to_verify"
            summary = (
                f"Unable to conclusively verify {len(unresolved_candidates)} of {total_candidates_count} "
                "candidate(s) due to missing, ambiguous, or incomplete official documentation."
            )
        elif unresolved_imports > 0 or ambiguous_imports > 0:
            verdict = "unable_to_verify"
            summary = (
                f"Unable to conclusively verify project: {unresolved_imports} unresolved import(s) and "
                f"{ambiguous_imports} ambiguous import(s) detected. Incomplete cross-file relationships cannot be certified clean."
            )
            limitations.append(
                "UNRESOLVED_RELATIONSHIPS: Incomplete or ambiguous cross-file relationships prevent certifying the project as clean."
            )
        else:
            verdict = "clean"
            summary = (
                f"All {total_candidates_count} candidate(s) across {len(request.files)} project file(s) "
                "verified clean against official documentation contracts. No issue detected within the checks performed. "
                "This does not certify or imply that the entire program is correct, complete, or bug-free."
            )
            limitations.append(
                "SCOPE_LIMITATION: A 'No issue detected within the checks performed' result only covers "
                "supported API calls verified against retrieved documentation contracts. It does not certify "
                "general program correctness, runtime behavior, or unanalyzed dependencies."
            )

        report = ProjectAnalysisReport(
            project_name=request.project_name,
            verdict=verdict,
            engine_version="0.1.0",
            total_files=len(request.files),
            total_lines=total_combined_lines,
            parsed_files_count=len(request.files) - syntax_errors_count,
            syntax_errors_count=syntax_errors_count,
            total_candidates=total_candidates_count,
            resolved_imports_count=resolved_imports,
            unresolved_imports_count=unresolved_imports,
            ambiguous_imports_count=ambiguous_imports,
            external_imports_count=external_imports,
            evidence_trust=evidence_trust,
            is_mock=is_mock,
            summary=summary,
            checks_performed=checks_performed,
            relationships=relationships,
            files=file_results,
            verified_issues=all_verified_issues,
            ai_suggestions=ai_suggestions,
            unresolved_candidates=unresolved_candidates,
            candidate_assessments=candidate_assessments,
            evidence_items=evidence_items,
            limitations_and_caveats=limitations,
            scan_id=None,
            persistence_status="disabled",
        )

        # 9. Optional SQLite Audit Persistence
        if repo is not None:
            try:
                scan_id = repo.save_project_scan(request, report)
                report.scan_id = scan_id
                report.persistence_status = "saved"
            except Exception as e:
                logger.error("Failed to persist project scan audit record: %s", e, exc_info=True)
                report.persistence_status = "failed"

        return report

    def _build_unsupported_ecosystem_report(self, request: ProjectAnalysisRequest) -> ProjectAnalysisReport:
        """Return conservative unable_to_verify report when ecosystem is unsupported."""
        return ProjectAnalysisReport(
            project_name=request.project_name,
            verdict="unable_to_verify",
            engine_version="0.1.0",
            total_files=len(request.files),
            total_lines=0,
            parsed_files_count=0,
            syntax_errors_count=0,
            total_candidates=0,
            resolved_imports_count=0,
            unresolved_imports_count=0,
            ambiguous_imports_count=0,
            external_imports_count=0,
            evidence_trust="untrusted_or_unavailable",
            is_mock=False,
            summary=f"Ecosystem '{request.ecosystem}' is not supported. APICompass currently verifies the 'stripe' ecosystem.",
            checks_performed=["API ecosystem compatibility check"],
            relationships=[],
            files=[],
            verified_issues=[],
            ai_suggestions=[],
            unresolved_candidates=[],
            candidate_assessments=[],
            evidence_items=[],
            limitations_and_caveats=[
                f"UNSUPPORTED_ECOSYSTEM: '{request.ecosystem}' is not supported. Supported ecosystem: stripe."
            ],
            scan_id=None,
            persistence_status="disabled",
        )

    def _build_zero_candidates_report(
        self,
        request: ProjectAnalysisRequest,
        file_results: List[ProjectFileAnalysisResult],
        relationships: List[ProjectRelationship],
        total_lines: int,
        syntax_errors_count: int,
        resolved_imports: int,
        unresolved_imports: int,
        ambiguous_imports: int,
        external_imports: int,
        limitations: List[str],
        repo: Optional[ScanRepository] = None,
    ) -> ProjectAnalysisReport:
        """Return conservative unable_to_verify report when no in-scope candidates exist across the project."""
        limitations.append(
            "NO_IN_SCOPE_CANDIDATES: Static AST analysis identified no supported Stripe API calls to verify across the project."
        )
        report = ProjectAnalysisReport(
            project_name=request.project_name,
            verdict="unable_to_verify",
            engine_version="0.1.0",
            total_files=len(request.files),
            total_lines=total_lines,
            parsed_files_count=len(request.files) - syntax_errors_count,
            syntax_errors_count=syntax_errors_count,
            total_candidates=0,
            resolved_imports_count=resolved_imports,
            unresolved_imports_count=unresolved_imports,
            ambiguous_imports_count=ambiguous_imports,
            external_imports_count=external_imports,
            evidence_trust="untrusted_or_unavailable",
            is_mock=False,
            summary=f"No supported in-scope API calls detected across {len(request.files)} project file(s). Verification was not performed.",
            checks_performed=[
                "Project path safety and normalization check",
                "Zero-execution multi-file AST parsing",
                "Cross-file dependency and relationship graph resolution",
                "API candidate identification",
            ],
            relationships=relationships,
            files=file_results,
            verified_issues=[],
            ai_suggestions=[],
            unresolved_candidates=[],
            candidate_assessments=[],
            evidence_items=[],
            limitations_and_caveats=limitations,
            scan_id=None,
            persistence_status="disabled",
        )

        if repo is not None:
            try:
                scan_id = repo.save_project_scan(request, report)
                report.scan_id = scan_id
                report.persistence_status = "saved"
            except Exception as e:
                logger.error("Failed to persist zero-candidates project scan: %s", e)
                report.persistence_status = "failed"

        return report


# Singleton project adjudicator instance
project_adjudicator = ProjectAdjudicator()
