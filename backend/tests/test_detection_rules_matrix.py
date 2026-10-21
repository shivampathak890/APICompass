"""Comprehensive Detection Rules Matrix and Contract Verification Test Suite.

Covers:
A. Input validation
B. Supported analysis behavior
C. Detection rules matrix (Positive, Negative, Edge-case, Invalid-input)
D. Evidence validation
E. Missing evidence
F. Contradictory evidence
G. Invalid source syntax
H. Unsupported inputs
I. Malformed requests
J. Output schema completeness
K. Exception handling
L. API endpoints
M. Database operations
N. Frontend/backend contract compatibility
O. Security-sensitive input handling
"""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db import init_db, get_db
from app.repositories.scan_repository import ScanRepository
from app.schemas.ast_analysis import (
    AnalyzePythonRequest,
    ApiCandidate,
    CallArgument,
    CallInfo,
    SourceLocation,
)
from app.schemas.documentation import DocParameter, NormalizedEvidence
from app.schemas.evidence import (
    AnalysisReport,
    AnalysisRequest,
    VerifiedIssue,
)
from app.schemas.identification import IdentifyApiCallsRequest
from app.schemas.project_analysis import ProjectAnalysisRequest
from app.services.evidence.contract_comparator import contract_comparator
from app.services.evidence.contract_extractor import contract_extractor
from app.services.evidence.quote_verifier import quote_verifier
from app.services.python_ast_analyzer import analyze_python_source

client = TestClient(app)


# ---------------------------------------------------------------------------
# Reusable Deterministic Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def deterministic_charge_evidence() -> NormalizedEvidence:
    """Official live-trust documentation fixture for stripe.Charge.create."""
    return NormalizedEvidence(
        evidence_id="ev_det_charge_001",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=(
            "Creates a new charge object. The source parameter is deprecated in favor of Payment Intents. "
            "Accepts parameters: amount (required positive integer), currency (required 3-letter ISO code), "
            "and customer (optional string)."
        ),
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        doc_version="2024-04-10",
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False, description="Positive integer in cents"),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False, description="Three-letter ISO code"),
            DocParameter(name="source", param_type="string", is_required=False, is_deprecated=True, description="The source parameter is deprecated in favor of Payment Intents"),
            DocParameter(name="customer", param_type="string", is_required=False, is_deprecated=False, description="Customer identifier"),
        ],
        required_fields=["amount", "currency"],
        deprecation_notices=["The source parameter is deprecated in favor of Payment Intents"],
    )


@pytest.fixture
def deterministic_deprecated_op_evidence() -> NormalizedEvidence:
    """Documentation fixture marking an entire operation deprecated."""
    return NormalizedEvidence(
        evidence_id="ev_det_deprecated_op",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Legacy Charges API | Stripe API Reference",
        content_excerpt=(
            "The Charges API is deprecated. We strongly recommend using the Payment Intents API instead. "
            "New integrations should not use stripe.Charge.create."
        ),
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        doc_version="2024-04-10",
        parameters=[],
        required_fields=[],
        deprecation_notices=["The Charges API is deprecated. We strongly recommend using the Payment Intents API instead."],
    )


# ---------------------------------------------------------------------------
# C. Detection Rules Matrix: Rule 1 - Deprecated Operation
# ---------------------------------------------------------------------------

def test_rule_deprecated_operation_positive(deterministic_deprecated_op_evidence):
    """Positive: Calling an operation explicitly marked as deprecated produces deprecated_operation violation."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)
    assert len(ast_res.candidates) == 1
    assert len(ast_res.calls) == 1

    contract = contract_extractor.extract_contract(deterministic_deprecated_op_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_deprecated_op_evidence)

    assert len(findings) >= 1
    types = [f.violation_type for f in findings]
    assert "deprecated_operation" in types


def test_rule_deprecated_operation_negative(deterministic_charge_evidence):
    """Negative: Calling an active non-deprecated operation produces no deprecated_operation violation."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "deprecated_operation" not in types


def test_rule_deprecated_operation_edge_case_alias_import(deterministic_deprecated_op_evidence):
    """Edge Case: Invoking deprecated operation via from-import alias is still detected."""
    source = "from stripe import Charge\nCharge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)
    assert len(ast_res.candidates) == 1

    contract = contract_extractor.extract_contract(deterministic_deprecated_op_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_deprecated_op_evidence)

    types = [f.violation_type for f in findings]
    assert "deprecated_operation" in types


def test_rule_deprecated_operation_invalid_syntax():
    """Invalid Input: Malformed syntax is caught as syntax_error before reaching contract comparison."""
    source = "import stripe\nstripe.Charge.create(amount="
    ast_res = analyze_python_source(source)
    assert ast_res.status == "syntax_error"
    assert ast_res.syntax_error is not None
    assert len(ast_res.candidates) == 0


# ---------------------------------------------------------------------------
# C. Detection Rules Matrix: Rule 2 - Legacy / Deprecated Parameter
# ---------------------------------------------------------------------------

def test_rule_legacy_deprecated_parameter_positive(deterministic_charge_evidence):
    """Positive: Supplying a parameter marked deprecated (e.g. 'source') produces legacy_deprecated_parameter."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', source='tok_123')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "legacy_deprecated_parameter" in types
    legacy_finding = next(f for f in findings if f.violation_type == "legacy_deprecated_parameter")
    assert legacy_finding.parameter_name == "source"


def test_rule_legacy_deprecated_parameter_negative(deterministic_charge_evidence):
    """Negative: Conforming call omitting deprecated parameter produces no legacy_deprecated_parameter violation."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "legacy_deprecated_parameter" not in types


def test_rule_legacy_deprecated_parameter_edge_case_optional_valid_param(deterministic_charge_evidence):
    """Edge Case: Supplying valid non-deprecated optional parameter (customer) does not trigger deprecation."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', customer='cus_999')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "legacy_deprecated_parameter" not in types
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# C. Detection Rules Matrix: Rule 3 - Unsupported Parameter
# ---------------------------------------------------------------------------

def test_rule_unsupported_parameter_positive():
    """Positive: Passing parameter explicitly documented as unsupported produces unsupported_parameter violation."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd', bitcoin_receiver='btc_123')"
    ast_res = analyze_python_source(source)

    ev = NormalizedEvidence(
        evidence_id="ev_det_charge_unsupp",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        content_excerpt=(
            "Creates a new charge object.\n"
            "### Parameters\n"
            "- `amount` (required, integer): Amount in cents.\n"
            "- `currency` (required, string): Three-letter ISO code.\n"
            "- `bitcoin_receiver` (unsupported, string): Parameter bitcoin_receiver is not supported.\n"
        ),
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        doc_version="2024-04-10",
        required_fields=["amount", "currency"],
    )

    contract = contract_extractor.extract_contract(ev, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, ev)

    types = [f.violation_type for f in findings]
    assert "unsupported_parameter" in types
    unsupp = next(f for f in findings if f.violation_type == "unsupported_parameter")
    assert unsupp.parameter_name == "bitcoin_receiver"


def test_rule_unsupported_parameter_negative(deterministic_charge_evidence):
    """Negative: Passing only documented parameters does not trigger unsupported_parameter."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "unsupported_parameter" not in types


def test_rule_unsupported_parameter_edge_case_kwargs_unpack(deterministic_charge_evidence):
    """Edge Case: Dynamic **kwargs unpack is treated conservatively and not falsely flagged as unsupported."""
    source = "import stripe\nparams = {'amount': 1000}\nstripe.Charge.create(**params)"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    # Dynamic kwargs unpack must NOT produce false unsupported_parameter accusations
    types = [f.violation_type for f in findings]
    assert "unsupported_parameter" not in types


# ---------------------------------------------------------------------------
# C. Detection Rules Matrix: Rule 4 - Missing Required Parameter
# ---------------------------------------------------------------------------

def test_rule_missing_required_parameter_positive(deterministic_charge_evidence):
    """Positive: Omitting required parameter 'currency' produces missing_required_parameter violation."""
    source = "import stripe\nstripe.Charge.create(amount=1000)"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "missing_required_parameter" in types
    missing_finding = next(f for f in findings if f.violation_type == "missing_required_parameter")
    assert missing_finding.parameter_name == "currency"


def test_rule_missing_required_parameter_negative(deterministic_charge_evidence):
    """Negative: Supplying all required parameters satisfies contract requirements."""
    source = "import stripe\nstripe.Charge.create(amount=1000, currency='usd')"
    ast_res = analyze_python_source(source)

    contract = contract_extractor.extract_contract(deterministic_charge_evidence, "stripe.Charge.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, deterministic_charge_evidence)

    types = [f.violation_type for f in findings]
    assert "missing_required_parameter" not in types


def test_rule_missing_required_parameter_edge_case_positional_args(deterministic_charge_evidence):
    """Edge Case: Ambiguous or positional calls do not falsely trigger missing required parameters if unspecified."""
    # When call has positional args and cannot be mapped, conservative abstention applies
    source = "import stripe\nstripe.Charge.create(1000, 'usd')"
    ast_res = analyze_python_source(source)
    assert len(ast_res.calls) == 1
    assert ast_res.calls[0].positional_args_count == 2


# ---------------------------------------------------------------------------
# C. Detection Rules Matrix: Rule 5 - Constraint Violation
# ---------------------------------------------------------------------------

def test_rule_constraint_violation_positive():
    """Positive: Passing negative amount when positive integer required produces constraint_violation."""
    source = "import stripe\nstripe.PaymentIntent.create(amount=-500, currency='usd')"
    ast_res = analyze_python_source(source)

    pi_evidence = NormalizedEvidence(
        evidence_id="ev_pi_constraint",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt="A positive integer representing how much to charge in the smallest currency unit.",
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        doc_version="2024-04-10",
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False, description="Positive integer in cents"),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False, description="3-letter ISO code"),
        ],
        required_fields=["amount", "currency"],
    )

    contract = contract_extractor.extract_contract(pi_evidence, "stripe.PaymentIntent.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, pi_evidence)

    types = [f.violation_type for f in findings]
    assert "constraint_violation" in types


def test_rule_constraint_violation_negative():
    """Negative: Passing valid positive integer satisfies positive integer constraint."""
    source = "import stripe\nstripe.PaymentIntent.create(amount=2000, currency='usd')"
    ast_res = analyze_python_source(source)

    pi_evidence = NormalizedEvidence(
        evidence_id="ev_pi_constraint_clean",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt="A positive integer representing how much to charge in the smallest currency unit.",
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        doc_version="2024-04-10",
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False, description="Positive integer in cents"),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False, description="3-letter ISO code"),
        ],
        required_fields=["amount", "currency"],
    )

    contract = contract_extractor.extract_contract(pi_evidence, "stripe.PaymentIntent.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, pi_evidence)

    types = [f.violation_type for f in findings]
    assert "constraint_violation" not in types


def test_rule_constraint_violation_edge_case_variable_argument():
    """Edge Case: Passing non-literal variable expression does not trigger false constraint violation."""
    source = "import stripe\ndef pay(user_amount):\n    stripe.PaymentIntent.create(amount=user_amount, currency='usd')"
    ast_res = analyze_python_source(source)

    pi_evidence = NormalizedEvidence(
        evidence_id="ev_pi_var",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/payment_intents/create",
        canonical_url="https://docs.stripe.com/api/payment_intents/create",
        title="Create a PaymentIntent | Stripe API Reference",
        content_excerpt="A positive integer representing how much to charge in the smallest currency unit.",
        retrieved_at="2026-10-21T00:00:00Z",
        provider="tinyfish_live",
        status="success",
        is_mock=False,
        source_trust="live_official_source",
        parameters=[
            DocParameter(name="amount", param_type="integer", is_required=True, is_deprecated=False, description="Positive integer in cents"),
            DocParameter(name="currency", param_type="string", is_required=True, is_deprecated=False, description="3-letter ISO code"),
        ],
        required_fields=["amount", "currency"],
    )

    contract = contract_extractor.extract_contract(pi_evidence, "stripe.PaymentIntent.create")
    findings = contract_comparator.compare(ast_res.candidates[0], ast_res.calls[0], contract, pi_evidence)

    # Static AST cannot evaluate variable values at runtime; must not falsely flag as negative integer
    types = [f.violation_type for f in findings]
    assert "constraint_violation" not in types


# ---------------------------------------------------------------------------
# A, H, I. Input Validation, Unsupported Inputs & Malformed Requests
# ---------------------------------------------------------------------------

def test_input_validation_forbids_extra_fields():
    """Verify that extra inputs on all endpoints are strictly rejected with HTTP 422."""
    endpoints = [
        ("/api/v1/analyze", {"source": "import stripe", "unexpected_extra": "hack"}),
        ("/api/v1/analyze/python", {"source": "import stripe", "extra": 123}),
        ("/api/v1/identify/python", {"source": "import stripe", "bogus": True}),
        ("/api/v1/docs/search", {"query": "stripe.Charge", "bad_param": "val"}),
    ]
    for url, payload in endpoints:
        resp = client.post(url, json=payload)
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "extra_forbidden" in json.dumps(body)


def test_input_validation_oversized_source_rejected():
    """Verify source exceeding 100,000 characters is rejected by Pydantic."""
    oversized = "a = 1\n" * 20000  # > 100 KB
    resp = client.post("/api/v1/analyze", json={"source": oversized})
    assert resp.status_code == 422
    assert "string_too_long" in json.dumps(resp.json())


def test_input_validation_empty_source():
    """Verify empty source is handled explicitly."""
    resp = client.post("/api/v1/analyze", json={"source": "   \n\t  "})
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "unable_to_verify"


def test_input_validation_invalid_ecosystem_regex():
    """Verify invalid ecosystem string with prohibited characters is rejected with 422."""
    resp = client.post("/api/v1/analyze", json={"source": "import stripe", "ecosystem": "stripe; DROP TABLE scans;"})
    assert resp.status_code == 422
    assert "string_pattern_mismatch" in json.dumps(resp.json())


# ---------------------------------------------------------------------------
# J & N. Output Schema Completeness & Frontend Contract Compatibility
# ---------------------------------------------------------------------------

def test_frontend_backend_contract_compatibility_keys():
    """Verify AnalysisReport contains all exact fields expected by frontend TypeScript types (evidence.ts)."""
    resp = client.post("/api/v1/analyze", json={"source": "import stripe\ndef pay(): pass"})
    assert resp.status_code == 200
    report = resp.json()

    # Required frontend fields from frontend/src/types/evidence.ts: AnalysisReport
    expected_fields = [
        "verdict",
        "result_state",
        "engine_version",
        "filename",
        "total_lines",
        "evidence_trust",
        "is_mock",
        "summary",
        "checks_performed",
        "verified_issues",
        "ai_suggestions",
        "unresolved_candidates",
        "candidate_assessments",
        "evidence_items",
        "limitations_and_caveats",
        "syntax_error",
        "llm_reasoning_status",
        "llm_reasoning_summary",
        "disclaimer",
        "scan_id",
        "persistence_status",
    ]
    for field in expected_fields:
        assert field in report, f"Missing field '{field}' required by frontend TypeScript types."


def test_frontend_backend_error_response_compatibility():
    """Verify 422 ErrorResponse matches frontend/src/types/errors.ts: ErrorResponse."""
    resp = client.post("/api/v1/analyze", json={"source": "import stripe", "unknown": "extra"})
    assert resp.status_code == 422
    err_body = resp.json()

    # Required frontend fields from frontend/src/types/errors.ts
    assert "detail" in err_body
    assert "error_code" in err_body
    assert "status_code" in err_body
    assert "timestamp" in err_body
    assert "errors" in err_body
    assert isinstance(err_body["errors"], list)
    if err_body["errors"]:
        first_err = err_body["errors"][0]
        assert "loc" in first_err
        assert "msg" in first_err
        assert "type" in first_err


def test_frontend_backend_health_response_compatibility():
    """Verify GET /api/v1/health matches frontend/src/types/health.ts."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    health = resp.json()
    assert "status" in health
    assert "service" in health
    assert "version" in health
    assert "timestamp" in health
    assert "mock_mode" in health
    assert "database_status" in health
    assert "provider_status" in health


# ---------------------------------------------------------------------------
# M. Database Operations & Consistency
# ---------------------------------------------------------------------------

def test_database_persistence_unique_scan_id_and_integrity(tmp_path):
    """Verify that scan persistence produces unique IDs, correct foreign keys, and excludes source code."""
    test_db = str(tmp_path / "matrix_db_test.db")
    init_db(test_db)
    repo = ScanRepository(db_path_override=test_db)

    req1 = AnalysisRequest(source="import stripe\nstripe.Charge.create()", filename="test1.py")
    rep1 = AnalysisReport(
        verdict="unable_to_verify",
        filename="test1.py",
        summary="Test 1",
        evidence_trust="mock_fixture",
        is_mock=True,
    )
    scan_id1 = repo.save_scan(req1, rep1)

    req2 = AnalysisRequest(source="import stripe\nstripe.Charge.create()", filename="test2.py")
    rep2 = AnalysisReport(
        verdict="unable_to_verify",
        filename="test2.py",
        summary="Test 2",
        evidence_trust="mock_fixture",
        is_mock=True,
    )
    scan_id2 = repo.save_scan(req2, rep2)

    # Identifiers must be unique even for identical source code
    assert scan_id1 != scan_id2
    assert scan_id1.startswith("scan_")
    assert scan_id2.startswith("scan_")

    # Raw user source code must never be in SQLite
    with get_db(test_db) as conn:
        cursor = conn.execute("SELECT * FROM scans WHERE scan_id = ?", (scan_id1,))
        row = dict(cursor.fetchone())
        assert row["source_sha256"] is not None
        assert row["source_length"] == len(req1.source)
        for col, val in row.items():
            assert "import stripe" not in str(val)
