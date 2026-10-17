"""Deterministic API contract matcher.

Coordinates:
1. Matching static AST candidates against retrieved official documentation evidence.
2. Extracting structured API contracts via ContractExtractor.
3. Deterministically comparing code invocations against extracted contracts via ContractComparator.
4. Returning structured candidate findings before quote verification and final adjudication.

Enforces strict integrity and safety rules:
- Mock evidence can NEVER produce a production contract violation.
- Does not infer errors from omitted parameters in incomplete excerpts.
- Preserves operation ambiguity and abstains.
- Evaluates contract compliance deterministically.
- Validates provenance and rejects unapproved or untrusted evidence sources.
- Detects stale or version-inapplicable documentation.
- Ranks evidence by method specificity and parameter completeness.
- Attaches the relevant contract evidence to each candidate finding.
"""

from typing import List, Optional, Tuple

from app.schemas.ast_analysis import ApiCandidate, CallInfo
from app.schemas.contract import (
    ContractFindingCandidate,
    ExtractedContract,
)
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import EvidenceMatch
from app.services.documentation.security import validate_destination_url
from app.services.evidence.contract_comparator import contract_comparator
from app.services.evidence.contract_extractor import contract_extractor
from app.services.evidence.quote_verifier import quote_verifier


class ContractMatcher:
    """Matches static AST candidates against retrieved official documentation evidence."""

    @classmethod
    def match_candidate_to_evidence(
        cls,
        candidate: ApiCandidate,
        call_info: Optional[CallInfo],
        evidence_items: List[NormalizedEvidence],
    ) -> Tuple[Optional[EvidenceMatch], List[ContractFindingCandidate]]:
        """Match an AST candidate against evidence items and identify candidate contract mismatches.

        Args:
            candidate: Static API candidate from AST analysis.
            call_info: Associated detailed call information (e.g. keyword arguments).
            evidence_items: List of normalized evidence records retrieved for the scan.

        Returns:
            Tuple of (EvidenceMatch, List[ContractFindingCandidate])
        """
        target_name = candidate.target_name.lower()
        receiver = (candidate.receiver or "").lower()
        call_expr = candidate.expression.lower()

        # Guard: If candidate has unresolved ambiguity, preserve ambiguity and avoid generating contract violations
        if candidate.is_ambiguous:
            return (
                EvidenceMatch(
                    candidate_id=candidate.candidate_id,
                    matched_operation=candidate.normalized_target,
                    evidence_id=None,
                    source_url=None,
                    completeness="excerpt_only",
                    is_ambiguous=True,
                    match_rationale=f"Ambiguous candidate: {candidate.rationale}",
                ),
                [],
            )

        # SDK Client Instantiation: StripeClient constructor initializes SDK instance locally
        if candidate.normalized_target in ("stripe.StripeClient", "StripeClient") or candidate.target_name == "StripeClient":
            first_ev = evidence_items[0] if evidence_items else None
            return (
                EvidenceMatch(
                    candidate_id=candidate.candidate_id,
                    matched_operation="stripe.StripeClient",
                    evidence_id=first_ev.evidence_id if first_ev else "ev_sdk_init",
                    source_url=first_ev.source_url if first_ev else "https://docs.stripe.com/api",
                    completeness="complete_contract",
                    is_ambiguous=False,
                    match_rationale="Client constructor initialization compliant with Stripe Python SDK.",
                ),
                [],
            )

        # 1. Filter evidence matching candidate's receiver and target method
        candidate_matches: List[Tuple[NormalizedEvidence, str]] = []
        norm_target_low = (candidate.normalized_target or "").lower()

        for ev in evidence_items:
            # Provenance Check: Reject unapproved, untrusted, or failed retrieval evidence
            is_valid, _, _ = validate_destination_url(ev.canonical_url)
            if (
                not is_valid
                or ev.source_trust in ("untrusted", "rejected")
                or ev.status in ("unavailable", "rejected", "failed", "rate_limited", "auth_failed", "empty")
            ):
                continue

            # Staleness / Version Applicability Check
            version = (ev.doc_version or "").lower()
            if (
                version in ("stale", "inapplicable", "unsupported", "deprecated")
                or version.startswith("201")
                or ev.error_code == "STALE_VERSION"
            ):
                continue

            canonical_lower = ev.canonical_url.lower()
            title_lower = (ev.title or "").lower()

            # Resource matching using normalized target or receiver context
            if "charge" in norm_target_low or "charge" in receiver or "charge" in call_expr:
                if "/charges" in canonical_lower or "charge" in title_lower:
                    candidate_matches.append((ev, "stripe.Charge"))

            if "paymentintent" in norm_target_low or "paymentintent" in receiver or "paymentintent" in call_expr or "payment_intent" in call_expr:
                if "/payment_intents" in canonical_lower or "paymentintent" in title_lower:
                    candidate_matches.append((ev, "stripe.PaymentIntent"))

            if "customer" in norm_target_low or "customer" in receiver or "customer" in call_expr:
                if "/customers" in canonical_lower or "customer" in title_lower:
                    candidate_matches.append((ev, "stripe.Customer"))

            if "refund" in norm_target_low or "refund" in receiver or "refund" in call_expr:
                if "/refunds" in canonical_lower or "refund" in title_lower:
                    candidate_matches.append((ev, "stripe.Refund"))

            # Dynamic matching for other Stripe SDK resources
            if not any(e == ev for e, _ in candidate_matches):
                rec_parts = [p.lower() for p in (receiver or "").split(".") if p.lower() not in ("stripe", "")]
                for part in rec_parts:
                    if len(part) >= 3 and (part in canonical_lower or part in title_lower):
                        candidate_matches.append((ev, receiver or candidate.expression))
                        break

        # 2. Check for Ambiguity: If multiple completely different operations match equally
        if len(candidate_matches) > 1:
            matched_ops = set(op for _, op in candidate_matches)
            if len(matched_ops) > 1:
                return (
                    EvidenceMatch(
                        candidate_id=candidate.candidate_id,
                        matched_operation=None,
                        evidence_id=None,
                        source_url=None,
                        canonical_url=None,
                        source_title=None,
                        retrieval_status=None,
                        retrieved_at=None,
                        is_mock=False,
                        completeness="excerpt_only",
                        is_ambiguous=True,
                        match_rationale=f"Ambiguous operation match across multiple targets: {sorted(list(matched_ops))}",
                    ),
                    [],
                )

        # 3. No documentation matched (Missing Documentation / Undocumented Method)
        if not candidate_matches:
            return (
                EvidenceMatch(
                    candidate_id=candidate.candidate_id,
                    matched_operation=None,
                    evidence_id=None,
                    source_url=None,
                    canonical_url=None,
                    source_title=None,
                    retrieval_status=None,
                    retrieved_at=None,
                    is_mock=False,
                    completeness="missing",
                    is_ambiguous=False,
                    match_rationale=f"No official documentation evidence found for candidate '{candidate.target_name}'.",
                ),
                [],
            )

        # 4. Rank matching evidence by source trust, full page, method specificity, parameter completeness, and version
        def rank_evidence(item: Tuple[NormalizedEvidence, str]) -> Tuple[int, int, int, int, int]:
            e, _ = item
            url_low = e.canonical_url.lower()
            excerpt = e.content_excerpt
            is_official = 0 if e.source_trust == "official" else 1
            is_full_page = 0 if getattr(e, "is_full_page", True) else 1
            is_method_specific = 0 if (f"/{target_name}" in url_low or target_name in (e.title or "").lower()) else 1
            has_params = 0 if ("required parameters" in excerpt.lower() or "parameters:" in excerpt.lower()) else 1
            version_match = 0 if (e.doc_version and not e.doc_version.startswith("201")) else 1
            return (is_official, is_full_page, is_method_specific, has_params, version_match)

        candidate_matches.sort(key=rank_evidence)
        best_ev, matched_op = candidate_matches[0]

        # Check for Conflicting Documentation across matching evidence items
        if len(candidate_matches) > 1:
            extracted_contracts = [
                contract_extractor.extract_contract(ev, f"{op}.{candidate.target_name}")
                for ev, op in candidate_matches
            ]
            all_deprecations = set()
            all_required = set()
            for c in extracted_contracts:
                dep_params = {name for name, p in c.all_parameters.items() if p.is_deprecated}
                req_params = set(c.required_parameters.keys())
                if (dep_params & all_required) or (req_params & all_deprecations):
                    return (
                        EvidenceMatch(
                            candidate_id=candidate.candidate_id,
                            matched_operation=matched_op,
                            evidence_id=best_ev.evidence_id,
                            source_url=best_ev.canonical_url,
                            canonical_url=best_ev.canonical_url,
                            source_title=best_ev.title,
                            retrieval_status=best_ev.status,
                            retrieved_at=best_ev.retrieved_at,
                            is_mock=bool(best_ev.is_mock or best_ev.provider == "tinyfish_mock"),
                            completeness="excerpt_only",
                            is_ambiguous=True,
                            match_rationale=f"Conflicting documentation detected across retrieved sources for '{matched_op}'.",
                        ),
                        [],
                    )
                all_deprecations.update(dep_params)
                all_required.update(req_params)

        # 5. Extract structured contract using the dedicated ContractExtractor (Requirement 1 & 2)
        full_op = f"{matched_op}.{candidate.target_name}" if candidate.target_name and not matched_op.endswith(f".{candidate.target_name}") else matched_op
        contract: ExtractedContract = contract_extractor.extract_contract(best_ev, full_op)

        # Determine overall completeness across matches
        has_complete_params = contract.completeness == "complete_contract" or any(
            "required parameters" in e.content_excerpt.lower()
            or "parameters:" in e.content_excerpt.lower()
            for e, _ in candidate_matches
        )
        completeness = "complete_contract" if has_complete_params else "excerpt_only"
        contract.completeness = completeness

        match_record = EvidenceMatch(
            candidate_id=candidate.candidate_id,
            matched_operation=matched_op,
            evidence_id=best_ev.evidence_id,
            source_url=best_ev.canonical_url,
            canonical_url=best_ev.canonical_url,
            source_title=best_ev.title,
            retrieval_status=best_ev.status,
            retrieved_at=best_ev.retrieved_at,
            is_mock=bool(best_ev.is_mock or best_ev.provider == "tinyfish_mock"),
            completeness=completeness,
            is_ambiguous=False,
            match_rationale=f"Matched official documentation for '{matched_op}' at {best_ev.canonical_url}.",
        )

        # 6. STRICT MOCK QUARANTINE:
        # Mock evidence CANNOT produce production contract violations.
        is_mock_match = any(e.is_mock or e.provider == "tinyfish_mock" for e, _ in candidate_matches)
        if is_mock_match:
            match_record.match_rationale += " [MOCK FIXTURE: Cannot establish verified contract violations]"
            return match_record, []

        # 7. Compare call against extracted contract using ContractComparator (Requirement 1, 4, 5, 6, 7, 8)
        candidate_findings = contract_comparator.compare(
            candidate=candidate,
            call_info=call_info,
            contract=contract,
            evidence=best_ev,
        )

        # Ensure quote verification pass on candidate findings where applicable
        for finding in candidate_findings:
            q_res = quote_verifier.verify_quote(finding.contract_quote, best_ev)
            if q_res.is_verified:
                finding.match_method = q_res.match_method
                finding.contract_quote = q_res.matched_text or finding.contract_quote

        return match_record, candidate_findings


contract_matcher = ContractMatcher()
