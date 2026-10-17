"""Evidence-gated fix proposer and safe in-memory re-verifier."""

import difflib
import logging
import re
import uuid
from typing import Any, List, Optional, Tuple

from app.schemas.ast_analysis import SyntaxErrorInfo
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisReport, AnalysisRequest, CandidateAssessment, VerifiedIssue
from app.schemas.fix_proposal import FixProposalResponse, FixProposalStatusType, ProposeFixRequest, ReverificationStatusType
from app.services.evidence.adjudicator import adjudicator as default_adjudicator
from app.services.fixes.policy import evaluate_fix_eligibility
from app.services.python_ast_analyzer import analyze_python_source

logger = logging.getLogger("apicompass.fixes")


class FixProposer:
    """Orchestrates evidence-gated fix proposals and safe static re-verification."""

    def __init__(self, adjudicator_instance: Any = None):
        self.adjudicator = adjudicator_instance or default_adjudicator

    async def propose_fix(
        self,
        request: ProposeFixRequest,
        _internal_evidence: Optional[List[NormalizedEvidence]] = None,
        _test_edit_generator: Optional[Any] = None,
    ) -> FixProposalResponse:
        """Propose an evidence-gated fix for a target candidate and re-verify in memory.

        Args:
            request: Validated ProposeFixRequest payload.
            _internal_evidence: Test-only synthetic evidence for live-trust test suites.
            _test_edit_generator: Optional callable override for testing invalid/custom edits.

        Returns:
            FixProposalResponse containing diff, evidence receipts, and re-verification state.
        """
        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"

        # 1. Step 1: Preliminary AST Syntax Check on submitted source
        pre_ast = analyze_python_source(request.source, request.filename)
        if pre_ast.status == "syntax_error":
            err: SyntaxErrorInfo = pre_ast.syntax_error  # type: ignore[assignment]
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="syntax_check_failed",
                proposal_type="ineligible",
                summary="Fix proposal cannot be generated for code with syntax errors.",
                reasoning=f"Source code has a syntax error at line {err.lineno}, col {err.col_offset}: {err.message}",
                original_excerpt=None,
                proposed_excerpt=None,
                unified_diff=None,
                proposed_source=None,
                supporting_evidence_ids=[],
                supporting_quotes=[],
                source_urls=[],
                evidence_trust="untrusted_or_unavailable",
                is_mock=False,
                is_ai_generated=False,
                syntax_valid=False,
                reverification_status="syntax_invalid",
                remaining_uncertainties=["Syntax errors prevent AST parsing and semantic contract analysis."],
                warnings=[f"INVALID_SYNTAX: Source code cannot be parsed at line {err.lineno}: {err.message}"],
            )

        # 2. Step 2: Ecosystem Check
        if request.ecosystem.lower() != "stripe":
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="unsupported_candidate",
                proposal_type="ineligible",
                summary=f"Ecosystem '{request.ecosystem}' is not supported for automated fix proposals.",
                reasoning="APICompass fix proposals are currently constrained to the Stripe Python ecosystem.",
                evidence_trust="untrusted_or_unavailable",
                is_mock=False,
                is_ai_generated=False,
                syntax_valid=True,
                reverification_status="not_attempted",
                remaining_uncertainties=[],
                warnings=[f"UNSUPPORTED_ECOSYSTEM: Fix proposals not supported for ecosystem '{request.ecosystem}'."],
            )

        # 3. Step 3: Authoritative Server-Side Adjudication
        # Recomputes analysis independently using server pipeline (zero reliance on client reports)
        report: AnalysisReport = await self.adjudicator.adjudicate(
            AnalysisRequest(
                source=request.source,
                filename=request.filename,
                ecosystem=request.ecosystem,
            ),
            _internal_evidence=_internal_evidence,
        )

        # 4. Step 4: Candidate Authenticity Check
        target_cand: Optional[CandidateAssessment] = next(
            (c for c in report.candidate_assessments if c.candidate_id == request.candidate_id),
            None,
        )
        if target_cand is None:
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="unsupported_candidate",
                proposal_type="ineligible",
                summary=f"Candidate ID '{request.candidate_id}' not found in analyzed source code.",
                reasoning="The candidate ID does not match any static API call candidates extracted from the source.",
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                is_ai_generated=False,
                syntax_valid=True,
                reverification_status="not_attempted",
                remaining_uncertainties=[],
                warnings=[f"UNKNOWN_CANDIDATE_ID: Candidate '{request.candidate_id}' does not exist in the source."],
            )

        # 5. Step 5: Locate Target Issue (if any)
        target_issue: Optional[VerifiedIssue] = None
        if request.issue_id:
            target_issue = next(
                (i for i in report.verified_issues if i.issue_id == request.issue_id and i.candidate_id == request.candidate_id),
                None,
            )
        if target_issue is None:
            target_issue = next(
                (i for i in report.verified_issues if i.candidate_id == request.candidate_id),
                None,
            )

        # 6. Step 6: Evidence Eligibility Policy Evaluation
        status, policy_warnings = evaluate_fix_eligibility(
            candidate=target_cand,
            verified_issue=target_issue,
            evidence_items=report.evidence_items,
            is_mock=report.is_mock,
            evidence_trust=report.evidence_trust,
        )

        # If evidence is fundamentally insufficient or candidate unsupported, abstain immediately
        if status in ("insufficient_evidence", "unsupported_candidate"):
            if target_cand.status == "resolved_clean":
                summary_text = f"Candidate '{target_cand.target_name}' is already compliant with official documentation contracts."
                reasoning_text = "Deterministic contract analysis confirms that this call satisfies all documented requirements. No fix is required."
            elif any("AMBIGUOUS_EVIDENCE" in w for w in policy_warnings):
                summary_text = f"Cannot propose fix: Ambiguous official contract for '{target_cand.target_name}'."
                match_desc = target_cand.evidence_match.match_rationale if target_cand.evidence_match else "multiple conflicting operations"
                reasoning_text = (
                    f"The documentation contract for candidate '{target_cand.target_name}' is ambiguous ({match_desc}). "
                    "When documentation contracts are ambiguous, APICompass strictly refrains from guessing automated migrations "
                    "to avoid corrupting runtime behavior or calling unintended API endpoints. Manual developer review is required."
                )
            elif any("INVENTED_VALUE_PROHIBITED" in w for w in policy_warnings):
                summary_text = f"Cannot propose fix: Required parameter for '{target_cand.target_name}' requires runtime business value."
                reasoning_text = (
                    f"Resolving the contract violation on '{target_cand.target_name}' requires supplying a missing required parameter. "
                    "APICompass policy strictly prohibits inventing financial amounts, customer IDs, API credentials, or other runtime "
                    "values. The parameter must be provided explicitly by the developer according to business requirements."
                )
            else:
                summary_text = f"Cannot propose fix: Missing or incomplete official documentation for '{target_cand.target_name}'."
                reasoning_text = "Authoritative official documentation is missing or incomplete for this operation. APICompass abstains from guessing migrations without verified evidence."

            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status=status,
                proposal_type="ineligible",
                summary=summary_text,
                reasoning=reasoning_text,
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                is_ai_generated=False,
                syntax_valid=True,
                reverification_status="not_attempted",
                remaining_uncertainties=["Official contract documentation for this call is incomplete, missing, or ambiguous."],
                warnings=policy_warnings,
            )

        # 7. Step 7: Deterministic Fix Generation
        if _test_edit_generator is not None:
            original_excerpt, proposed_excerpt, proposed_source, edit_err = _test_edit_generator(
                request.source, target_cand, target_issue
            )
        else:
            original_excerpt, proposed_excerpt, proposed_source, edit_err = self._generate_deterministic_edit(
                source=request.source,
                candidate=target_cand,
                issue=target_issue,
                evidence_items=report.evidence_items,
            )

        if edit_err or proposed_source is None or original_excerpt is None or proposed_excerpt is None:
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="proposal_invalid" if edit_err else "unsupported_candidate",
                proposal_type="ineligible",
                summary=f"No automated migration template available for API candidate '{target_cand.target_name}'.",
                reasoning=edit_err or "APICompass abstains from guessing or inventing migrations without a verified contract mapping.",
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                is_ai_generated=False,
                syntax_valid=True,
                reverification_status="not_attempted",
                remaining_uncertainties=[],
                warnings=policy_warnings + ([edit_err] if edit_err else ["NO_TRANSFORMATION_TEMPLATE: No safe deterministic rule available."]),
            )

        # Check edit boundaries: ensure unmodified regions are 100% identical
        if not self._verify_edit_isolation(request.source, proposed_source, target_cand):
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="proposal_invalid",
                proposal_type="ineligible",
                summary="Proposed edit violated edit isolation boundaries.",
                reasoning="The proposed edit inadvertently altered lines outside the target candidate range.",
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                syntax_valid=False,
                reverification_status="not_attempted",
                warnings=policy_warnings + ["EDIT_ISOLATION_FAILURE: Changes leaked into unrelated source regions."],
            )

        # Check edit size limit: proposed source cannot expand abnormally (> 2000 chars over original)
        if len(proposed_source) > len(request.source) + 2000 or len(proposed_source) > 100_000:
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="proposal_invalid",
                proposal_type="ineligible",
                summary="Proposed edit exceeds configured size limit.",
                reasoning="The proposed edit exceeded allowable modification delta limits.",
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                syntax_valid=False,
                reverification_status="not_attempted",
                warnings=policy_warnings + ["EDIT_SIZE_EXCEEDED: Proposed edit delta exceeds maximum allowable limit."],
            )

        # 8. Step 8: Unified Diff Generation
        orig_split = [l + "\n" for l in request.source.splitlines()]
        prop_split = [l + "\n" for l in proposed_source.splitlines()]
        diff_lines = list(
            difflib.unified_diff(
                orig_split,
                prop_split,
                fromfile=f"a/{request.filename}",
                tofile=f"b/{request.filename}",
            )
        )
        unified_diff = "".join(diff_lines)

        # 9. Step 9: In-Memory Static Re-Verification
        post_ast = analyze_python_source(proposed_source, request.filename)
        if post_ast.status == "syntax_error":
            syntax_err = post_ast.syntax_error  # type: ignore[assignment]
            return FixProposalResponse(
                proposal_id=proposal_id,
                candidate_id=request.candidate_id,
                status="syntax_check_failed",
                proposal_type="ineligible",
                summary="Proposed fix introduced a syntax error.",
                reasoning=f"Proposed replacement produced invalid Python syntax at line {syntax_err.lineno}: {syntax_err.message}",
                original_excerpt=original_excerpt,
                proposed_excerpt=proposed_excerpt,
                unified_diff=unified_diff,
                proposed_source=proposed_source,
                supporting_evidence_ids=[target_issue.supporting_evidence_id] if target_issue else [],
                supporting_quotes=[target_issue.verified_quote] if target_issue else [],
                source_urls=[target_issue.source_url] if target_issue else [],
                evidence_trust=report.evidence_trust,
                is_mock=report.is_mock,
                is_ai_generated=False,
                syntax_valid=False,
                reverification_status="syntax_invalid",
                remaining_uncertainties=["Proposed source text fails Python AST parsing."],
                warnings=policy_warnings + [f"SYNTAX_ERROR: Proposed edit is invalid Python syntax: {syntax_err.message}"],
            )

        # 10. Step 10: Re-adjudication & Reverification Status
        reverification_status: ReverificationStatusType = "not_attempted"
        reverification_warnings = list(policy_warnings)

        if status == "mock_evidence_only":
            reverification_status = "reverification_inconclusive"
            reverification_warnings.append(
                "REVERIFICATION_INCONCLUSIVE: Re-verification in mock mode cannot establish production correctness."
            )
        elif status == "evidence_supported":
            # Re-run adjudication pipeline on in-memory proposed source
            new_report = await self.adjudicator.adjudicate(
                AnalysisRequest(
                    source=proposed_source,
                    filename=request.filename,
                    ecosystem=request.ecosystem,
                ),
                _internal_evidence=_internal_evidence,
            )

            # Check if original violation persists
            original_violation_persists = any(
                i.candidate_id == request.candidate_id
                or (target_issue and i.violation_type == target_issue.violation_type)
                for i in new_report.verified_issues
            )

            # Check if the proposed code actually contains the resolved API candidate
            matching_resolved_cands = [
                c for c in new_report.candidate_assessments
                if c.status == "resolved_clean"
            ]

            if original_violation_persists:
                reverification_status = "concern_persists"
                reverification_warnings.append("CONCERN_PERSISTS: Proposed edit did not eliminate the API contract violation.")
            elif len(new_report.verified_issues) > 0:
                reverification_status = "partially_resolved"
                reverification_warnings.append("PARTIALLY_RESOLVED: Original concern resolved, but other issues remain in the file.")
            elif len(new_report.candidate_assessments) == 0:
                reverification_status = "reverification_inconclusive"
                reverification_warnings.append(
                    "DID_NOT_ADDRESS_FINDING: Proposed edit eliminated or bypassed the API call rather than resolving it against official documentation."
                )
            elif new_report.verdict == "clean" and new_report.evidence_trust == "live_official_source" and matching_resolved_cands:
                reverification_status = "verified_resolved"
            else:
                reverification_status = "reverification_inconclusive"
                reverification_warnings.append(
                    f"REVERIFICATION_INCONCLUSIVE: Analysis verdict is '{new_report.verdict}' (trust: '{new_report.evidence_trust}'). Official resolution could not be verified."
                )

        # Determine proposal_type:
        if (
            status == "evidence_supported"
            and reverification_status == "verified_resolved"
            and not report.is_mock
            and report.evidence_trust == "live_official_source"
        ):
            proposal_type = "verified_correction"
        elif status in ("mock_evidence_only", "evidence_supported"):
            proposal_type = "suggested_patch"
        else:
            proposal_type = "ineligible"

        # Supporting evidence details
        supp_ev_ids: List[str] = []
        supp_quotes: List[str] = []
        source_urls: List[str] = []

        if target_issue:
            supp_ev_ids.append(target_issue.supporting_evidence_id)
            supp_quotes.append(target_issue.verified_quote)
            source_urls.append(target_issue.source_url)
        elif target_cand.evidence_match and target_cand.evidence_match.evidence_id:
            supp_ev_ids.append(target_cand.evidence_match.evidence_id)
            if target_cand.evidence_match.source_url:
                source_urls.append(target_cand.evidence_match.source_url)

        remaining_uncertainties = [
            "Static re-verification confirms AST syntax validity and official documentation contract compliance only.",
            "Runtime properties such as API keys, network transport, webhook idempotency, and banking authorizations cannot be tested statically.",
            "A fix proposal is an evidence-backed suggestion, not a guarantee of runtime correctness.",
        ]

        if target_issue:
            summary_text = (
                f"Evidence-supported migration addressing '{target_issue.claim_checked}'."
                if status == "evidence_supported"
                else f"Illustrative migration addressing '{target_issue.claim_checked}' (Mock Mode)."
            )
            reasoning_text = (
                f"Official Stripe documentation for '{target_cand.target_name}' at {target_issue.source_url} states: "
                f"\"{target_issue.verified_quote}\". "
                f"The finding '{target_issue.claim_checked}' is addressed by migrating from the legacy "
                f"'{target_cand.receiver}.{target_cand.target_name}' to the recommended 'stripe.PaymentIntent.create'. "
                "The deprecated 'source' argument is mapped to 'payment_method' while preserving all other parameters "
                "and source code formatting."
            )
        else:
            summary_text = (
                "Illustrative migration from legacy stripe.Charge to stripe.PaymentIntent (Mock Mode)."
                if status == "mock_evidence_only"
                else "Evidence-supported migration from deprecated stripe.Charge to modern stripe.PaymentIntent."
            )
            reasoning_text = (
                "Official Stripe documentation recommends using the Payment Intents API instead of the Charges API. "
                "The Payment Intents API provides a unified integration flow across payment methods and payment authentication requirements. "
                "Replacing stripe.Charge.create with stripe.PaymentIntent.create and mapping 'source' to 'payment_method' complies with current contracts."
            )

        return FixProposalResponse(
            proposal_id=proposal_id,
            candidate_id=request.candidate_id,
            status=status,
            proposal_type=proposal_type,
            summary=summary_text,
            reasoning=reasoning_text,
            original_excerpt=original_excerpt,
            proposed_excerpt=proposed_excerpt,
            unified_diff=unified_diff,
            proposed_source=proposed_source,
            supporting_evidence_ids=supp_ev_ids,
            supporting_quotes=supp_quotes,
            source_urls=source_urls,
            evidence_trust=report.evidence_trust,
            is_mock=report.is_mock,
            is_ai_generated=False,
            syntax_valid=True,
            reverification_status=reverification_status,
            remaining_uncertainties=remaining_uncertainties,
            warnings=reverification_warnings,
        )

    def _generate_deterministic_edit(
        self,
        source: str,
        candidate: CandidateAssessment,
        issue: Optional[VerifiedIssue],
        evidence_items: List[NormalizedEvidence],
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Perform exact line-bounded deterministic code transformation.

        Returns:
            Tuple of (original_excerpt, proposed_excerpt, proposed_source, error_message)
        """
        lines = source.splitlines(keepends=True)
        start_line = candidate.source_location.lineno
        end_line = candidate.source_location.end_lineno or start_line

        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            return None, None, None, f"Invalid candidate source location range [{start_line}:{end_line}]"

        original_chunk = "".join(lines[start_line - 1 : end_line])

        # Pattern 1: Legacy 'source' parameter or Charge.create call
        call_expr = candidate.call_expr.lower()
        receiver = (candidate.receiver or "").lower()

        is_charge = "charge" in receiver or "charge" in call_expr
        has_source = "source" in original_chunk.lower()

        if is_charge and (has_source or (issue and issue.violation_type == "legacy_deprecated_parameter")):
            # Perform exact transformation on the target excerpt
            modified_chunk = re.sub(r"\bCharge\.create\b", "PaymentIntent.create", original_chunk)
            modified_chunk = re.sub(r"\bsource\s*=", "payment_method=", modified_chunk)

            # Also check if import needs updating
            proposed_lines = list(lines)
            proposed_lines[start_line - 1 : end_line] = [modified_chunk]

            # If source has 'from stripe import Charge', update it cleanly
            for i, line in enumerate(proposed_lines):
                if re.match(r"^\s*from\s+stripe\s+import\s+Charge\b", line):
                    proposed_lines[i] = re.sub(r"\bCharge\b", "PaymentIntent", line)

            proposed_source = "".join(proposed_lines)
            if proposed_source == source:
                return None, None, None, "Transformation produced no net changes to source."

            return original_chunk, modified_chunk, proposed_source, None

        # Pattern 2: Missing required parameters cannot invent runtime values (Requirement 4)
        if issue and issue.violation_type == "missing_required_parameter":
            return (
                None,
                None,
                None,
                "INVENTED_VALUE_PROHIBITED: Cannot invent runtime values (such as amounts, currencies, or identifiers) for missing required parameters.",
            )

        return None, None, None, None

    def _verify_edit_isolation(self, original_source: str, proposed_source: str, candidate: CandidateAssessment) -> bool:
        """Verify that edits only affected the targeted candidate lines."""
        orig_lines = original_source.splitlines(keepends=True)
        prop_lines = proposed_source.splitlines(keepends=True)

        start_idx = candidate.source_location.lineno - 1
        end_idx = candidate.source_location.end_lineno or candidate.source_location.lineno

        # Preceding lines must be strictly identical (allowing import update on line 1-5 if applicable)
        for i in range(min(start_idx, len(orig_lines), len(prop_lines))):
            if orig_lines[i] != prop_lines[i]:
                # Allow only explicit import migration
                if "import" not in orig_lines[i] or "import" not in prop_lines[i]:
                    return False

        # Post lines must be strictly identical from end of block to EOF
        orig_post = orig_lines[end_idx:]
        # Calculate how many lines were inserted/deleted in the target block
        block_delta = len(prop_lines) - len(orig_lines)
        prop_post = prop_lines[end_idx + block_delta :]

        if orig_post != prop_post:
            return False

        return True


# Singleton fix proposer
fix_proposer = FixProposer()
