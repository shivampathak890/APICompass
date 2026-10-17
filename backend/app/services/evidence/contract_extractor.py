"""Deterministic documentation contract extractor.

Extracts structured API contract specifications from retrieved technical documentation.
Separates documentation contract parsing from code comparison.
Preserves:
- Explicit required vs. optional parameters.
- Parameter-level and operation-level deprecation.
- Statically checkable parameter constraints (e.g. positive integer, currency format).
- API version and SDK version context.
- Completeness classification ('complete_contract' vs. 'excerpt_only').
"""

import re
from typing import Dict, List, Optional, Tuple

from app.schemas.contract import (
    ExtractedContract,
    ParameterConstraint,
    ParameterContract,
)
from app.schemas.documentation import NormalizedEvidence


class ContractExtractor:
    """Extracts explicit API contracts from normalized technical documentation."""

    @classmethod
    def extract_contract(
        cls,
        evidence: NormalizedEvidence,
        target_operation: Optional[str] = None,
    ) -> ExtractedContract:
        """Extract a structured API contract from a normalized documentation record.

        Args:
            evidence: Normalized evidence item from documentation retrieval.
            target_operation: Optional normalized operation name (e.g. 'stripe.Charge.create').

        Returns:
            ExtractedContract representing the documented API contract.
        """
        # Determine resource and method
        op_name = target_operation or cls._infer_operation_name(evidence)
        resource, target_method = cls._split_resource_and_method(op_name)

        required_params: Dict[str, ParameterContract] = {}
        optional_params: Dict[str, ParameterContract] = {}
        all_params: Dict[str, ParameterContract] = {}

        # 1. Use pre-extracted structured parameters if available from normalized page
        if evidence.parameters:
            for p in evidence.parameters:
                p_name = p.name.strip().lower()
                constraints = cls._extract_constraints_from_text(p.description or "", p_name)
                contract = ParameterContract(
                    name=p_name,
                    param_type=p.param_type,
                    is_required=p.is_required,
                    is_deprecated=p.is_deprecated,
                    description=p.description,
                    constraints=constraints,
                    deprecation_reason=p.description if p.is_deprecated else None,
                )
                all_params[p_name] = contract
                if p.is_required:
                    required_params[p_name] = contract
                else:
                    optional_params[p_name] = contract

        # 2. Extract parameters and constraints from raw markdown or content excerpt
        text_source = evidence.raw_markdown or evidence.content_excerpt or ""
        cls._extract_from_text(
            text=text_source,
            required_params=required_params,
            optional_params=optional_params,
            all_params=all_params,
        )

        # 3. Check for operation-level deprecation
        is_op_deprecated, op_dep_notice = cls._check_operation_deprecation(text_source, resource, target_method)

        # 4. Determine contract completeness
        has_required_clause = bool(
            re.search(r"\brequired\s+parameters?[:\s]", text_source, re.IGNORECASE)
            or re.search(r"\(required\b", text_source, re.IGNORECASE)
            or re.search(r"\*required\*", text_source, re.IGNORECASE)
        )
        has_params_section = bool(
            re.search(r"parameters?[:\s]", text_source, re.IGNORECASE)
            or evidence.parameters
        )

        if has_required_clause or (has_params_section and len(all_params) >= 2):
            completeness = "complete_contract"
            is_closed = True
        elif all_params or has_params_section:
            completeness = "excerpt_only"
            is_closed = False
        else:
            completeness = "excerpt_only"
            is_closed = False

        return ExtractedContract(
            operation_name=op_name,
            resource=resource,
            target_method=target_method,
            required_parameters=required_params,
            optional_parameters=optional_params,
            all_parameters=all_params,
            is_operation_deprecated=is_op_deprecated,
            operation_deprecation_notice=op_dep_notice,
            completeness=completeness,
            is_parameter_list_closed=is_closed,
            doc_version=evidence.doc_version,
            sdk_version=None,
            source_url=evidence.canonical_url,
            evidence_id=evidence.evidence_id,
            raw_excerpt=evidence.content_excerpt,
        )

    @staticmethod
    def _infer_operation_name(evidence: NormalizedEvidence) -> str:
        url = (evidence.canonical_url or "").lower()
        title = (evidence.title or "").lower()
        if "/charges" in url or "charge" in title:
            if "create" in url or "create" in title:
                return "stripe.Charge.create"
            return "stripe.Charge"
        if "/payment_intents" in url or "paymentintent" in title or "payment intent" in title:
            if "create" in url or "create" in title:
                return "stripe.PaymentIntent.create"
            return "stripe.PaymentIntent"
        if "/customers" in url or "customer" in title:
            if "create" in url or "create" in title:
                return "stripe.Customer.create"
            return "stripe.Customer"
        if "/refunds" in url or "refund" in title:
            if "create" in url or "create" in title:
                return "stripe.Refund.create"
            return "stripe.Refund"
        return "stripe.ApiResource"

    @staticmethod
    def _split_resource_and_method(op_name: str) -> Tuple[str, str]:
        parts = op_name.split(".")
        if len(parts) >= 3:
            return ".".join(parts[:-1]), parts[-1]
        if len(parts) == 2:
            return parts[0], parts[1]
        return op_name, "call"

    @classmethod
    def _extract_from_text(
        cls,
        text: str,
        required_params: Dict[str, ParameterContract],
        optional_params: Dict[str, ParameterContract],
        all_params: Dict[str, ParameterContract],
    ) -> None:
        """Parse parameter definitions and deprecation clauses from documentation text."""
        # A. Required parameters inline list: "Required parameters: amount, currency."
        # or "Required parameters: amount (positive integer), currency (three-letter ISO code)."
        req_match = re.search(r"required\s+parameters?[:\s]+([^.]+)", text, re.IGNORECASE)
        if req_match:
            raw_list = req_match.group(1).strip()
            # Split by comma or semicolon
            for item in re.split(r"[,;]\s*", raw_list):
                cleaned_item = item.strip()
                if not cleaned_item or cleaned_item.lower().startswith("use "):
                    continue
                # Extract param name and optional inline description
                p_m = re.match(r"^[`'\"]?([a-zA-Z0-9_]+)[`'\"]?(?:\s*\(([^)]+)\))?", cleaned_item)
                if p_m:
                    p_name = p_m.group(1).lower()
                    desc = p_m.group(2) or ""
                    constraints = cls._extract_constraints_from_text(desc, p_name)
                    contract = ParameterContract(
                        name=p_name,
                        param_type="integer" if "integer" in desc else "string" if "code" in desc or "string" in desc else None,
                        is_required=True,
                        is_deprecated=False,
                        description=desc or "Explicitly documented required parameter",
                        constraints=constraints,
                    )
                    required_params[p_name] = contract
                    all_params[p_name] = contract

        # B. Markdown parameter list items:
        # - `amount` (required, integer): Amount intended to be collected in cents.
        # - `source` (legacy): A payment source to be charged.
        # - `customer` (optional, string): The ID of an existing customer.
        param_item_regex = re.compile(
            r"[-*]\s+[`'\"]?([a-zA-Z0-9_]+)[`'\"]?\s*\(([^)]+)\)[:\s]*(.*)",
            re.MULTILINE,
        )
        for match in param_item_regex.finditer(text):
            p_name = match.group(1).lower()
            modifiers = match.group(2).lower()
            desc = match.group(3).strip()

            is_req = "required" in modifiers
            is_dep = any(w in modifiers for w in ("legacy", "deprecated", "obsolete"))
            is_unsupported = any(w in modifiers for w in ("unsupported", "removed", "invalid"))
            is_opt = "optional" in modifiers

            # Extract constraints from modifiers and description
            constraints = cls._extract_constraints_from_text(f"{modifiers} {desc}", p_name)

            p_type = None
            if "integer" in modifiers or "integer" in desc.lower():
                p_type = "integer"
            elif "string" in modifiers or "string" in desc.lower():
                p_type = "string"
            elif "dictionary" in modifiers or "dict" in modifiers:
                p_type = "dictionary"

            contract = ParameterContract(
                name=p_name,
                param_type=p_type,
                is_required=is_req,
                is_deprecated=is_dep,
                is_unsupported=is_unsupported,
                description=desc or modifiers,
                constraints=constraints,
                deprecation_reason=desc if is_dep else None,
                unsupported_reason=desc if is_unsupported else None,
            )
            all_params[p_name] = contract
            if is_req:
                required_params[p_name] = contract
            elif is_opt or not is_req:
                optional_params[p_name] = contract

        # C. General Parameter list item without parentheses:
        # "Parameters: amount (integer in cents), currency (three-letter ISO currency code)"
        params_match = re.search(r"parameters?[:\s]+([^.]+)", text, re.IGNORECASE)
        if params_match and not req_match:
            raw_list = params_match.group(1).strip()
            for item in re.split(r"[,;]\s*", raw_list):
                cleaned_item = item.strip()
                p_m = re.match(r"^[`'\"]?([a-zA-Z0-9_]+)[`'\"]?(?:\s*\(([^)]+)\))?", cleaned_item)
                if p_m:
                    p_name = p_m.group(1).lower()
                    desc = p_m.group(2) or ""
                    if p_name not in all_params:
                        constraints = cls._extract_constraints_from_text(desc, p_name)
                        contract = ParameterContract(
                            name=p_name,
                            param_type="integer" if "integer" in desc else "string" if "code" in desc or "string" in desc else None,
                            is_required=False,  # If not under "required parameters", do not assume required
                            is_deprecated=False,
                            description=desc,
                            constraints=constraints,
                        )
                        optional_params[p_name] = contract
                        all_params[p_name] = contract

        # D. Detect parameter-level legacy / deprecation sentences:
        # e.g., "The 'source' parameter is considered legacy; PaymentIntents should be used for modern payment methods."
        # e.g., "The 'source' token parameter on stripe.Charge.create is legacy."
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if any(w in s_low for w in ("legacy", "deprecated", "recommend using paymentintents", "recommend using payment intents")):
                # Check for parameter mentions
                p_mention = re.search(r"['\"`]([a-zA-Z0-9_]+)['\"`]\s+parameter", s_clean, re.IGNORECASE) or \
                            re.search(r"parameter\s+['\"`]([a-zA-Z0-9_]+)['\"`]", s_clean, re.IGNORECASE) or \
                            re.search(r"\b(source)\b.*(?:legacy|deprecated)", s_clean, re.IGNORECASE)
                if p_mention:
                    p_name = p_mention.group(1).lower()
                    existing = all_params.get(p_name)
                    if existing:
                        existing.is_deprecated = True
                        existing.deprecation_reason = s_clean
                    else:
                        contract = ParameterContract(
                            name=p_name,
                            is_required=False,
                            is_deprecated=True,
                            description=s_clean,
                            deprecation_reason=s_clean,
                        )
                        all_params[p_name] = contract
                        optional_params[p_name] = contract

            # Check for unsupported parameter sentences:
            # e.g., "Parameter 'custom_field' is unsupported in API version 2024-04-10."
            # e.g., "The 'custom_field' parameter is not supported for this operation."
            if any(w in s_low for w in ("is unsupported", "not supported", "is not allowed", "cannot be used")):
                p_unsupported = re.search(r"['\"`]([a-zA-Z0-9_]+)['\"`]\s+parameter", s_clean, re.IGNORECASE) or \
                                re.search(r"parameter\s+['\"`]([a-zA-Z0-9_]+)['\"`]", s_clean, re.IGNORECASE)
                if p_unsupported:
                    p_name = p_unsupported.group(1).lower()
                    existing = all_params.get(p_name)
                    if existing:
                        existing.is_unsupported = True
                        existing.unsupported_reason = s_clean
                    else:
                        contract = ParameterContract(
                            name=p_name,
                            is_required=False,
                            is_unsupported=True,
                            description=s_clean,
                            unsupported_reason=s_clean,
                        )
                        all_params[p_name] = contract

    @staticmethod
    def _extract_constraints_from_text(text: str, param_name: str) -> List[ParameterConstraint]:
        """Extract statically checkable value constraints from parameter description text."""
        constraints: List[ParameterConstraint] = []
        low = text.lower()

        # 1. Positive integer constraint (e.g. amount: positive integer)
        if "positive integer" in low or ("positive" in low and "integer" in low) or (param_name == "amount" and "cents" in low):
            constraints.append(
                ParameterConstraint(
                    constraint_type="positive_integer",
                    description="Must be a positive integer (> 0)",
                    min_value=1,
                )
            )
        elif "non-negative integer" in low or "non negative integer" in low:
            constraints.append(
                ParameterConstraint(
                    constraint_type="non_negative_integer",
                    description="Must be a non-negative integer (>= 0)",
                    min_value=0,
                )
            )

        # 2. ISO currency code constraint (e.g. three-letter ISO code)
        if "three-letter iso" in low or "iso currency code" in low or (param_name == "currency" and "code" in low):
            constraints.append(
                ParameterConstraint(
                    constraint_type="iso_currency_code",
                    description="Must be a three-letter ISO currency code (e.g. 'usd', 'eur')",
                )
            )

        # 3. Non-empty string constraint
        if "non-empty string" in low or "non empty string" in low:
            constraints.append(
                ParameterConstraint(
                    constraint_type="non_empty_str",
                    description="Must be a non-empty string",
                )
            )

        return constraints

    @staticmethod
    def _check_operation_deprecation(text: str, resource: str, method: str) -> Tuple[bool, Optional[str]]:
        """Check if documentation explicitly marks the entire operation/endpoint as deprecated."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            s_low = s_clean.lower()
            if "endpoint is deprecated" in s_low or "operation is deprecated" in s_low:
                return True, s_clean
            if "charges api is deprecated" in s_low or "charge.create is deprecated" in s_low:
                return True, s_clean
            if ("charges api" in s_low or "charge" in s_low) and "recommend using the payment intents api" in s_low and "legacy" in s_low:
                return True, s_clean
        return False, None


contract_extractor = ContractExtractor()

