"""Evidence eligibility policy for APICompass fix proposals.

Defines the non-negotiable server-side policy determining whether sufficient,
authentic, and complete official documentation evidence exists to justify an
evidence-supported fix proposal.
"""

from typing import List, Optional, Tuple
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import CandidateAssessment, VerifiedIssue
from app.schemas.fix_proposal import FixProposalStatusType


def evaluate_fix_eligibility(
    candidate: Optional[CandidateAssessment],
    verified_issue: Optional[VerifiedIssue],
    evidence_items: List[NormalizedEvidence],
    is_mock: bool,
    evidence_trust: str,
) -> Tuple[FixProposalStatusType, List[str]]:
    """Evaluate whether evidence meets the strict eligibility criteria for a fix.

    Returns:
        Tuple of (FixProposalStatusType, List[str] of policy warnings/reasons)
    """
    warnings: List[str] = []

    # 1. Candidate must belong to source
    if candidate is None:
        warnings.append("UNKNOWN_CANDIDATE: Target candidate does not belong to the analyzed source.")
        return "unsupported_candidate", warnings

    # 2. Strict Mock Quarantine: Mock evidence CANNOT produce an evidence-supported fix
    if is_mock or evidence_trust == "mock_fixture":
        warnings.append(
            "MOCK_EVIDENCE_ONLY: Offline mock fixtures cannot produce an evidence-supported production fix. "
            "Showing illustrative migration example only."
        )
        return "mock_evidence_only", warnings

    # 3. Candidate already verified clean
    if candidate.status == "resolved_clean" and verified_issue is None:
        warnings.append("NO_FIX_NEEDED: Candidate is already verified clean against official documentation contracts.")
        return "unsupported_candidate", warnings

    # 4. Check documentation match
    match = candidate.evidence_match
    if match is None or match.completeness == "missing":
        warnings.append("INSUFFICIENT_EVIDENCE: Missing official documentation for candidate.")
        return "insufficient_evidence", warnings

    # 5. Check ambiguity
    if (
        match.is_ambiguous
        or candidate.abstention_reason in ("AMBIGUOUS_OPERATION_MATCH", "CONFLICTING_DOCUMENTATION")
    ):
        match_desc = match.match_rationale if match else (candidate.abstention_reason or "Ambiguous API operation")
        warnings.append(f"AMBIGUOUS_EVIDENCE: Multiple conflicting API operations or documentation matched candidate: {match_desc}")
        return "insufficient_evidence", warnings

    # 6. Must have supporting evidence in report
    matched_ev = next((e for e in evidence_items if e.evidence_id == match.evidence_id), None)
    if matched_ev is None:
        warnings.append("INSUFFICIENT_EVIDENCE: Supporting evidence record not found in analysis report.")
        return "insufficient_evidence", warnings

    # 7. Evidence must be from approved, live official source
    if matched_ev.source_trust != "official" or matched_ev.is_mock or matched_ev.provider == "tinyfish_mock":
        warnings.append("UNTRUSTED_EVIDENCE: Documentation source is not verified official live documentation.")
        return "insufficient_evidence", warnings

    # 8. Must have verified issue with verified quotation
    if verified_issue is None:
        # If no verified issue exists under live trust, check if contract is incomplete
        if match.completeness != "complete_contract":
            warnings.append("INCOMPLETE_CONTRACT: Retrieved documentation excerpt is incomplete.")
            return "insufficient_evidence", warnings
        warnings.append("NO_VERIFIED_ISSUE: No verified contract violation was established for this candidate.")
        return "insufficient_evidence", warnings

    if not verified_issue.verified_quote or verified_issue.match_method not in ("exact", "whitespace_normalized"):
        warnings.append("UNVERIFIED_QUOTE: Supporting quotation failed deterministic verification.")
        return "insufficient_evidence", warnings

    # 9. Prohibition on inventing runtime values (Requirement 4)
    if verified_issue.violation_type == "missing_required_parameter":
        warnings.append(
            f"INVENTED_VALUE_PROHIBITED: Cannot safely generate automated fix for '{verified_issue.claim_checked}' "
            "because resolving a missing required parameter requires business-logic runtime values that cannot be invented."
        )
        return "insufficient_evidence", warnings

    # 10. All criteria satisfied for live evidence-supported proposal
    return "evidence_supported", warnings
