"""Tests for APICompass's improved contract matcher and documentation extractor.

Verifies:
1. Documentation extraction separated from contract comparison.
2. Explicit required vs. optional parameters.
3. Preservation of SDK and API version context.
4. No inference of missing required fields from incomplete excerpts.
5. No invalidation of parameters merely because absent from incomplete excerpts.
6. Distinction of statically known literal values from unknown runtime values.
7. Structured candidate findings returned before final verification.
8. Attachment of relevant contract evidence to each candidate.
"""

import pytest

from app.schemas.ast_analysis import ApiCandidate, CallArgument, CallInfo, SourceLocation
from app.schemas.contract import (
    ContractFindingCandidate,
    ExtractedContract,
    ParameterContract,
)
from app.schemas.documentation import NormalizedEvidence
from app.services.evidence.contract_comparator import contract_comparator
from app.services.evidence.contract_extractor import contract_extractor
from app.services.evidence.contract_matcher import contract_matcher


@pytest.fixture
def complete_charges_evidence() -> NormalizedEvidence:
    """Fixture providing complete documented contract for stripe.Charge.create."""
    excerpt = (
        "# Create a charge\n"
        "To charge a credit card, create a Charge object.\n"
        "### Parameters\n"
        "- `amount` (required, integer): Amount in cents. Must be a positive integer.\n"
        "- `currency` (required, string): Three-letter ISO currency code.\n"
        "- `source` (legacy): The 'source' parameter is considered legacy; PaymentIntents should be used.\n"
        "- `customer` (optional, string): The ID of an existing customer.\n"
        "Required parameters: amount (positive integer), currency (three-letter ISO code).\n"
    )
    return NormalizedEvidence(
        evidence_id="ev_charges_complete",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


@pytest.fixture
def incomplete_charges_excerpt_evidence() -> NormalizedEvidence:
    """Fixture providing an incomplete narrative excerpt without complete parameter contract."""
    excerpt = (
        "The Charge object represents a single payment attempt in Stripe. "
        "Charges can be created directly or via PaymentIntents."
    )
    return NormalizedEvidence(
        evidence_id="ev_charges_incomplete",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges",
        canonical_url="https://docs.stripe.com/api/charges",
        title="Charges Overview | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


@pytest.fixture
def deprecated_operation_evidence() -> NormalizedEvidence:
    """Fixture providing documentation explicitly marking an operation as deprecated."""
    excerpt = (
        "# Charges API\n"
        "The Charges API is deprecated; use Payment Intents instead for dynamic authentication. "
        "Required parameters: amount, currency."
    )
    return NormalizedEvidence(
        evidence_id="ev_charges_deprecated",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=excerpt,
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )


# -----------------------------------------------------------------------------
# 1. Documentation Extraction Unit Tests (Requirement 1 & 2)
# -----------------------------------------------------------------------------
def test_contract_extractor_separates_documentation_and_represents_parameters(complete_charges_evidence: NormalizedEvidence):
    contract = contract_extractor.extract_contract(complete_charges_evidence, "stripe.Charge.create")

    assert isinstance(contract, ExtractedContract)
    assert contract.operation_name == "stripe.Charge.create"
    assert contract.completeness == "complete_contract"
    assert contract.doc_version == "2024-04-10"

    # Explicit required parameters
    assert "amount" in contract.required_parameters
    assert "currency" in contract.required_parameters
    assert contract.required_parameters["amount"].is_required is True
    assert contract.required_parameters["currency"].is_required is True

    # Explicit optional parameters
    assert "customer" in contract.optional_parameters
    assert contract.optional_parameters["customer"].is_required is False

    # Deprecated parameter
    assert "source" in contract.all_parameters
    assert contract.all_parameters["source"].is_deprecated is True


def test_contract_extractor_recognizes_incomplete_excerpt(incomplete_charges_excerpt_evidence: NormalizedEvidence):
    contract = contract_extractor.extract_contract(incomplete_charges_excerpt_evidence, "stripe.Charge.create")

    assert contract.completeness == "excerpt_only"
    assert contract.is_parameter_list_closed is False
    assert len(contract.required_parameters) == 0


# -----------------------------------------------------------------------------
# 2. Required Fields Positive and Negative Tests (Requirement 4)
# -----------------------------------------------------------------------------
def test_missing_required_parameter_detected_positive(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_missing_amount",
        expression="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=10, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["currency"],
        location=SourceLocation(lineno=10, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])

    assert match_rec is not None
    assert match_rec.completeness == "complete_contract"
    assert len(findings) == 1
    finding = findings[0]
    assert finding.violation_type == "missing_required_parameter"
    assert finding.parameter_name == "amount"
    assert "amount" in finding.explanation.lower()
    # Attached relevant evidence (Requirement 8)
    assert finding.evidence is not None
    assert finding.evidence.evidence_id == complete_charges_evidence.evidence_id
    assert finding.supporting_evidence_id == complete_charges_evidence.evidence_id


def test_missing_parameter_not_flagged_when_optional_negative(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_optional_omitted",
        expression="stripe.Charge.create(amount=1000, currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=10, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=1000, currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency"],
        location=SourceLocation(lineno=10, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])
    # customer is optional and omitted; no missing required parameter violation
    missing_findings = [f for f in findings if f.violation_type == "missing_required_parameter"]
    assert len(missing_findings) == 0


def test_missing_parameter_not_inferred_from_incomplete_excerpt_negative(incomplete_charges_excerpt_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_incomplete_doc",
        expression="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=10, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["currency"],
        location=SourceLocation(lineno=10, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [incomplete_charges_excerpt_evidence])
    assert match_rec.completeness == "excerpt_only"
    # Never infer missing fields from incomplete documentation excerpts!
    assert len(findings) == 0


# -----------------------------------------------------------------------------
# 3. Valid and Unsupported Parameters (Requirement 5)
# -----------------------------------------------------------------------------
def test_valid_parameters_produce_zero_findings_positive(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_valid",
        expression="stripe.Charge.create(amount=5000, currency='usd', customer='cus_123')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=10, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=5000, currency='usd', customer='cus_123')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency", "customer"],
        location=SourceLocation(lineno=10, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])
    assert len(findings) == 0


def test_unsupported_parameter_detected_when_explicitly_documented(complete_charges_evidence: NormalizedEvidence):
    # Create evidence that explicitly documents a parameter as unsupported
    evidence_with_unsupported = NormalizedEvidence(
        evidence_id="ev_unsupported_field",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=(
            "Create a charge.\n"
            "Required parameters: amount, currency.\n"
            "Parameter 'legacy_token' is not supported for this operation.\n"
        ),
        retrieved_at="2026-10-18T00:00:00Z",
        provider="tinyfish_live",
        status="live",
        is_mock=False,
        source_trust="official",
        doc_version="2024-04-10",
    )

    cand = ApiCandidate(
        candidate_id="cand_unsupported",
        expression="stripe.Charge.create(amount=100, currency='usd', legacy_token='tok_1')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=100, currency='usd', legacy_token='tok_1')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency", "legacy_token"],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [evidence_with_unsupported])
    unsupported = [f for f in findings if f.violation_type == "unsupported_parameter"]
    assert len(unsupported) == 1
    assert unsupported[0].parameter_name == "legacy_token"
    assert "legacy_token" in unsupported[0].explanation


def test_parameter_not_invalidated_by_incomplete_excerpt_negative(incomplete_charges_excerpt_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_extra_arg",
        expression="stripe.Charge.create(amount=100, unmentioned_field='test')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=100, unmentioned_field='test')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "unmentioned_field"],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [incomplete_charges_excerpt_evidence])
    # Must NOT call 'unmentioned_field' invalid merely because it was absent from an incomplete excerpt!
    unsupported = [f for f in findings if f.violation_type == "unsupported_parameter"]
    assert len(unsupported) == 0


# -----------------------------------------------------------------------------
# 4. Deprecated Operations and Parameters (Requirement 3 & 4)
# -----------------------------------------------------------------------------
def test_deprecated_operation_detected_positive(deprecated_operation_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_dep_op",
        expression="stripe.Charge.create(amount=100, currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=100, currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency"],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [deprecated_operation_evidence])
    dep_findings = [f for f in findings if f.violation_type == "deprecated_operation"]
    assert len(dep_findings) == 1
    assert "deprecated" in dep_findings[0].explanation.lower()
    assert dep_findings[0].contract_version == "2024-04-10"


def test_legacy_deprecated_parameter_detected_positive(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_legacy_source",
        expression="stripe.Charge.create(amount=2000, currency='usd', source='tok_visa')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=2000, currency='usd', source='tok_visa')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency", "source"],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])
    dep_findings = [f for f in findings if f.violation_type == "legacy_deprecated_parameter"]
    assert len(dep_findings) == 1
    assert dep_findings[0].parameter_name == "source"
    assert "legacy" in dep_findings[0].explanation.lower()


# -----------------------------------------------------------------------------
# 5. Statically Known Values vs. Unknown Runtime Values (Requirement 6)
# -----------------------------------------------------------------------------
def test_static_value_constraint_violation_positive(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_negative_amount",
        expression="stripe.Charge.create(amount=-500, currency='usd')",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=-500, currency='usd')",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency"],
        arguments=[
            CallArgument(
                name="amount",
                position=None,
                value_repr="-500",
                value_type="literal_int",
                is_literal=True,
                literal_value=-500,
                location=SourceLocation(lineno=1, col_offset=28),
            ),
            CallArgument(
                name="currency",
                position=None,
                value_repr="'usd'",
                value_type="literal_str",
                is_literal=True,
                literal_value="usd",
                location=SourceLocation(lineno=1, col_offset=42),
            ),
        ],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])
    constraint_findings = [f for f in findings if f.violation_type == "constraint_violation"]
    assert len(constraint_findings) == 1
    finding = constraint_findings[0]
    assert finding.parameter_name == "amount"
    assert finding.is_statically_determined is True
    assert "-500" in finding.supplied_value_repr


def test_dynamic_runtime_value_does_not_trigger_constraint_violation_negative(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_dynamic_amount",
        expression="stripe.Charge.create(amount=calculate_total(), currency=user_currency)",
        receiver="stripe.Charge",
        target_name="create",
        normalized_target="stripe.Charge.create",
        kind="method_call",
        confidence="heuristic",
        rationale="API call",
        location=SourceLocation(lineno=1, col_offset=0),
    )
    call_info = CallInfo(
        call_expr="stripe.Charge.create(amount=calculate_total(), currency=user_currency)",
        receiver="stripe.Charge",
        method="create",
        is_attribute_call=True,
        positional_args_count=0,
        keyword_args=["amount", "currency"],
        arguments=[
            CallArgument(
                name="amount",
                position=None,
                value_repr="calculate_total()",
                value_type="call",
                is_literal=False,
                literal_value=None,
                location=SourceLocation(lineno=1, col_offset=28),
            ),
            CallArgument(
                name="currency",
                position=None,
                value_repr="user_currency",
                value_type="identifier",
                is_literal=False,
                literal_value=None,
                location=SourceLocation(lineno=1, col_offset=56),
            ),
        ],
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, call_info, [complete_charges_evidence])
    # Unknown dynamic values MUST NOT trigger static constraint violations!
    constraint_findings = [f for f in findings if f.violation_type == "constraint_violation"]
    assert len(constraint_findings) == 0


# -----------------------------------------------------------------------------
# 6. Ambiguous Candidates (Requirement 6 & 7)
# -----------------------------------------------------------------------------
def test_ambiguous_candidate_abstains_without_violations(complete_charges_evidence: NormalizedEvidence):
    cand = ApiCandidate(
        candidate_id="cand_ambiguous",
        expression="client.charges.create()",
        receiver="client.charges",
        target_name="create",
        normalized_target=None,
        is_ambiguous=True,
        kind="method_call",
        confidence="heuristic",
        rationale="Client is an untyped function parameter",
        location=SourceLocation(lineno=1, col_offset=0),
    )

    match_rec, findings = contract_matcher.match_candidate_to_evidence(cand, None, [complete_charges_evidence])
    assert match_rec.is_ambiguous is True
    assert len(findings) == 0

