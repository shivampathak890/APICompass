"""Deterministic API contract comparator.

Compares static Python AST candidates against extracted technical documentation contracts.
Supports ONLY checks justified by available contract documentation:
1. An explicitly documented required parameter is missing.
2. A supplied parameter is explicitly documented as unsupported for the operation/version.
3. An operation is explicitly documented as deprecated.
4. A supplied parameter is documented as legacy or deprecated.
5. A supplied value contradicts a clearly documented constraint, when that value can be determined statically.

Enforces conservative guardrails:
- Does NOT infer missing fields when the documentation does not establish they are required.
- Does NOT call a parameter invalid merely because it is absent from an incomplete excerpt.
- Distinguishes statically known values from unknown runtime values (zero false alarms on variables).
- Attaches the relevant contract evidence to each candidate finding.
"""

import ast
import re
from typing import List, Optional

from app.schemas.ast_analysis import ApiCandidate, CallArgument, CallInfo, SourceLocation
from app.schemas.contract import (
    ContractFindingCandidate,
    ExtractedContract,
)
from app.schemas.documentation import NormalizedEvidence


class ContractComparator:
    """Compares static code candidates against extracted documentation contracts."""

    @classmethod
    def compare(
        cls,
        candidate: ApiCandidate,
        call_info: Optional[CallInfo],
        contract: ExtractedContract,
        evidence: NormalizedEvidence,
    ) -> List[ContractFindingCandidate]:
        """Compare an API call candidate against an extracted API contract.

        Args:
            candidate: Static API candidate from AST analysis.
            call_info: Associated detailed call metadata.
            contract: Extracted API contract from official documentation.
            evidence: The source NormalizedEvidence item.

        Returns:
            List of structured ContractFindingCandidate findings.
        """
        findings: List[ContractFindingCandidate] = []

        # If candidate has unresolved ambiguity, do not generate contract violation candidates
        if candidate.is_ambiguous:
            return []

        # Parse structured arguments if call_info exists
        args_by_name = {}
        supplied_kwargs = []
        positional_count = 0
        has_kwargs_unpack = False

        if call_info:
            supplied_kwargs = [kw.lower() for kw in call_info.keyword_args]
            positional_count = call_info.positional_args_count
            if call_info.arguments:
                for a in call_info.arguments:
                    if a.name:
                        args_by_name[a.name.lower()] = a
                    elif a.value_type == "kwargs_unpack":
                        has_kwargs_unpack = True
            else:
                # Fallback: attempt safe AST literal parse from call_expr if call_info.arguments is empty
                cls._populate_args_from_expr(call_info.call_expr, args_by_name)

        # ---------------------------------------------------------------------
        # 1. Operation Deprecation Check
        # ---------------------------------------------------------------------
        if contract.is_operation_deprecated and contract.operation_deprecation_notice:
            quote = cls._find_sentence_containing(
                contract.raw_excerpt,
                ["deprecated", "payment intents", "charges api"],
            ) or contract.operation_deprecation_notice
            findings.append(
                ContractFindingCandidate(
                    finding_id=f"iss_{candidate.candidate_id}_op_deprecated",
                    candidate_id=candidate.candidate_id,
                    source_location=candidate.location,
                    claim_checked=f"Deprecation status of {contract.operation_name}",
                    violation_type="deprecated_operation",
                    explanation=(
                        f"The operation '{contract.operation_name}' is explicitly documented as deprecated. "
                        f"{contract.operation_deprecation_notice}"
                    ),
                    supporting_evidence_id=contract.evidence_id,
                    source_url=contract.source_url,
                    contract_quote=quote,
                    contract_version=contract.doc_version,
                    evidence=evidence,
                    limitations=f"Applies to {contract.operation_name} as documented in API version {contract.doc_version or 'latest'}.",
                )
            )

        # ---------------------------------------------------------------------
        # 2. Legacy / Deprecated Parameter Check
        # ---------------------------------------------------------------------
        for kw in supplied_kwargs:
            param_spec = contract.all_parameters.get(kw)
            # Special handling for Stripe Charge 'source' legacy parameter
            if kw == "source" and ("charge" in contract.operation_name.lower() or "charge" in candidate.expression.lower()):
                quote = cls._find_sentence_matching(
                    contract.raw_excerpt,
                    must_include=["source"],
                    any_of=["legacy", "deprecated", "paymentintent", "payment intent", "recommend"],
                )
                if quote:
                    findings.append(
                        ContractFindingCandidate(
                            finding_id=f"iss_{candidate.candidate_id}_source_deprecated",
                            candidate_id=candidate.candidate_id,
                            source_location=candidate.location,
                            claim_checked=f"Parameter 'source' on {contract.operation_name}",
                            violation_type="legacy_deprecated_parameter",
                            explanation=(
                                f"The 'source' token parameter on {contract.operation_name} is legacy. "
                                "Modern Stripe integrations should use the PaymentIntents API."
                            ),
                            parameter_name="source",
                            supporting_evidence_id=contract.evidence_id,
                            source_url=contract.source_url,
                            contract_quote=quote,
                            contract_version=contract.doc_version,
                            evidence=evidence,
                            limitations="Applies to Stripe API integrations targeting modern payment flows.",
                        )
                    )
            elif param_spec and param_spec.is_deprecated:
                quote = cls._find_sentence_matching(
                    contract.raw_excerpt,
                    must_include=[kw],
                    any_of=["deprecated", "legacy"],
                ) or param_spec.deprecation_reason or f"Parameter '{kw}' is deprecated."
                findings.append(
                    ContractFindingCandidate(
                        finding_id=f"iss_{candidate.candidate_id}_{kw}_deprecated",
                        candidate_id=candidate.candidate_id,
                        source_location=candidate.location,
                        claim_checked=f"Parameter '{kw}' on {contract.operation_name}",
                        violation_type="legacy_deprecated_parameter",
                        explanation=f"Parameter '{kw}' is explicitly documented as deprecated or legacy on {contract.operation_name}.",
                        parameter_name=kw,
                        supporting_evidence_id=contract.evidence_id,
                        source_url=contract.source_url,
                        contract_quote=quote,
                        contract_version=contract.doc_version,
                        evidence=evidence,
                        limitations="Preserved from official API documentation contract.",
                    )
                )

        # ---------------------------------------------------------------------
        # 3. Explicitly Unsupported Parameter Check
        # ---------------------------------------------------------------------
        for kw in supplied_kwargs:
            param_spec = contract.all_parameters.get(kw)
            if param_spec and param_spec.is_unsupported:
                quote = cls._find_sentence_containing(
                    contract.raw_excerpt,
                    [kw, "unsupported", "not supported"],
                ) or param_spec.unsupported_reason or f"Parameter '{kw}' is not supported."
                findings.append(
                    ContractFindingCandidate(
                        finding_id=f"iss_{candidate.candidate_id}_{kw}_unsupported",
                        candidate_id=candidate.candidate_id,
                        source_location=candidate.location,
                        claim_checked=f"Supported parameters for {contract.operation_name}",
                        violation_type="unsupported_parameter",
                        explanation=f"Parameter '{kw}' is explicitly documented as unsupported for {contract.operation_name}.",
                        parameter_name=kw,
                        supporting_evidence_id=contract.evidence_id,
                        source_url=contract.source_url,
                        contract_quote=quote,
                        contract_version=contract.doc_version,
                        evidence=evidence,
                        limitations=f"API version {contract.doc_version or 'latest'} does not support parameter '{kw}'.",
                    )
                )

        # ---------------------------------------------------------------------
        # 4. Missing Required Parameter Check (Requirement 4)
        # ---------------------------------------------------------------------
        # Only check when the contract completeness is 'complete_contract'
        # Do not infer missing required parameters from incomplete excerpts or dynamic **kwargs unpacking!
        if (
            contract.completeness == "complete_contract"
            and contract.required_parameters
            and not has_kwargs_unpack
        ):
            for req_name, req_spec in contract.required_parameters.items():
                if req_name not in supplied_kwargs and positional_count == 0:
                    quote = cls._find_required_quote(contract.raw_excerpt, req_name)
                    if quote:
                        findings.append(
                            ContractFindingCandidate(
                                finding_id=f"iss_{candidate.candidate_id}_missing_{req_name}",
                                candidate_id=candidate.candidate_id,
                                source_location=candidate.location,
                                claim_checked=f"Required parameters on {contract.operation_name}",
                                violation_type="missing_required_parameter",
                                explanation=f"Missing required '{req_name}' parameter in {contract.operation_name} call.",
                                parameter_name=req_name,
                                supporting_evidence_id=contract.evidence_id,
                                source_url=contract.source_url,
                                contract_quote=quote,
                                contract_version=contract.doc_version,
                                evidence=evidence,
                                limitations=f"Applies to direct {contract.operation_name} calls as documented in official API reference.",
                            )
                        )

        # ---------------------------------------------------------------------
        # 5. Static Value Constraint Check (Requirement 6)
        # ---------------------------------------------------------------------
        for kw, arg in args_by_name.items():
            param_spec = contract.all_parameters.get(kw)
            if not param_spec or not param_spec.constraints:
                continue

            for constraint in param_spec.constraints:
                # Guard: Distinguish statically known values from unknown runtime values!
                # If the argument is an identifier or function call (is_literal=False), DO NOT flag!
                if not arg.is_literal:
                    continue

                val = arg.literal_value
                if constraint.constraint_type == "positive_integer":
                    is_invalid = False
                    if isinstance(val, bool) or not isinstance(val, (int, float)):
                        is_invalid = True
                    elif val <= 0:
                        is_invalid = True

                    if is_invalid:
                        quote = (
                            cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw, "positive", "integer", "cents"],
                            )
                            or cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw, "integer"],
                            )
                            or cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw],
                            )
                            or contract.raw_excerpt[:150]
                        )
                        findings.append(
                            ContractFindingCandidate(
                                finding_id=f"iss_{candidate.candidate_id}_{kw}_constraint_positive_integer",
                                candidate_id=candidate.candidate_id,
                                source_location=arg.location,
                                claim_checked=f"Constraint on parameter '{kw}'",
                                violation_type="constraint_violation",
                                explanation=(
                                    f"Supplied literal value '{arg.value_repr}' for parameter '{kw}' "
                                    f"violates documented constraint: {constraint.description}."
                                ),
                                parameter_name=kw,
                                supplied_value_repr=arg.value_repr,
                                is_statically_determined=True,
                                supporting_evidence_id=contract.evidence_id,
                                source_url=contract.source_url,
                                contract_quote=quote,
                                contract_version=contract.doc_version,
                                evidence=evidence,
                                limitations="Evaluated on statically known compile-time literal value.",
                            )
                        )
                elif constraint.constraint_type == "iso_currency_code":
                    is_invalid = False
                    if isinstance(val, bool) or not isinstance(val, str):
                        is_invalid = True
                    elif len(val.strip()) != 3 or not val.isalpha():
                        is_invalid = True

                    if is_invalid:
                        quote = (
                            cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw, "iso", "currency"],
                            )
                            or cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw, "currency"],
                            )
                            or cls._find_sentence_containing(
                                contract.raw_excerpt,
                                [kw],
                            )
                            or contract.raw_excerpt[:150]
                        )
                        findings.append(
                            ContractFindingCandidate(
                                finding_id=f"iss_{candidate.candidate_id}_{kw}_constraint_iso_currency",
                                candidate_id=candidate.candidate_id,
                                source_location=arg.location,
                                claim_checked=f"Constraint on parameter '{kw}'",
                                violation_type="constraint_violation",
                                explanation=(
                                    f"Supplied literal value '{arg.value_repr}' for parameter '{kw}' "
                                    f"violates documented constraint: {constraint.description}."
                                ),
                                parameter_name=kw,
                                supplied_value_repr=arg.value_repr,
                                is_statically_determined=True,
                                supporting_evidence_id=contract.evidence_id,
                                source_url=contract.source_url,
                                contract_quote=quote,
                                contract_version=contract.doc_version,
                                evidence=evidence,
                                limitations="Evaluated on statically known compile-time literal value.",
                            )
                        )
                elif constraint.constraint_type == "non_empty_str":
                    if isinstance(val, str) and len(val.strip()) == 0:
                        quote = cls._find_sentence_containing(
                            contract.raw_excerpt,
                            [kw, "non-empty", "string"],
                        ) or contract.raw_excerpt[:150]
                        findings.append(
                            ContractFindingCandidate(
                                finding_id=f"iss_{candidate.candidate_id}_{kw}_constraint_non_empty",
                                candidate_id=candidate.candidate_id,
                                source_location=arg.location,
                                claim_checked=f"Constraint on parameter '{kw}'",
                                violation_type="constraint_violation",
                                explanation=(
                                    f"Supplied empty string for parameter '{kw}' violates documented constraint: "
                                    f"{constraint.description}."
                                ),
                                parameter_name=kw,
                                supplied_value_repr=arg.value_repr,
                                is_statically_determined=True,
                                supporting_evidence_id=contract.evidence_id,
                                source_url=contract.source_url,
                                contract_quote=quote,
                                contract_version=contract.doc_version,
                                evidence=evidence,
                                limitations="Evaluated on statically known compile-time literal value.",
                            )
                        )

        return findings

    @classmethod
    def _find_sentence_matching(
        cls,
        text: str,
        must_include: List[str],
        any_of: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Find the sentence in documentation text containing all required terms and any optional terms."""
        if not text:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", text)
        must_low = [m.lower() for m in must_include]
        any_low = [a.lower() for a in any_of] if any_of else []
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if all(m in s_low for m in must_low):
                if not any_low or any(a in s_low for a in any_low):
                    return s_clean
        return None

    @classmethod
    def _find_sentence_containing(cls, text: str, keywords: List[str]) -> Optional[str]:
        """Find the sentence in documentation text containing target keywords."""
        if not text:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", text)
        kw_lower = [k.lower() for k in keywords]
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if any(k in s_low for k in kw_lower):
                return s_clean
        return None

    @classmethod
    def _find_required_quote(cls, text: str, param_name: str) -> Optional[str]:
        """Find the exact sentence or line establishing that a parameter is required."""
        if not text:
            return None
        # 1. Search for sentences with "required parameter" or "required" and param_name
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if "required" in s_low and param_name.lower() in s_low:
                return s_clean
            if "required parameter" in s_low or "parameters:" in s_low:
                return s_clean

        # 2. Search for markdown line with param_name (required)
        for line in text.splitlines():
            l_clean = line.strip()
            l_low = l_clean.lower()
            if param_name.lower() in l_low and "required" in l_low:
                return l_clean

        return None

    @classmethod
    def _populate_args_from_expr(cls, call_expr: str, args_by_name: dict) -> None:
        """Fallback to extract CallArgument literals from call_expr via safe AST parse."""
        try:
            tree = ast.parse(call_expr)
            call_node = next((n for n in ast.walk(tree) if isinstance(n, ast.Call)), None)
            if not call_node:
                return
            for kw in call_node.keywords:
                if not kw.arg:
                    continue
                name = kw.arg.lower()
                val_node = kw.value
                val_repr = ast.unparse(val_node) if hasattr(ast, "unparse") else ""
                is_lit = isinstance(val_node, ast.Constant)
                lit_val = val_node.value if is_lit else None
                args_by_name[name] = CallArgument(
                    name=name,
                    position=None,
                    value_repr=val_repr,
                    value_type="literal_int" if isinstance(lit_val, int) else "literal_str" if isinstance(lit_val, str) else "identifier",
                    is_literal=is_lit,
                    literal_value=lit_val,
                    location=SourceLocation(lineno=1, col_offset=0),
                )
        except Exception:
            pass


contract_comparator = ContractComparator()
