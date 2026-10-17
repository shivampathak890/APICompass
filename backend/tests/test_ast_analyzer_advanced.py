"""Comprehensive test suite for advanced static Python AST analysis.

Covers:
- Direct API calls
- Nested calls
- Assignment expressions (walrus operator :=)
- Imports and aliases (import as, from import, from import as)
- Client-instance methods (StripeClient tracking and resource dispatch)
- Chained attributes
- Multiline calls and exact source line/column preservation
- Positional, keyword, and unpacked arguments (*args, **kwargs)
- Variables passed as arguments (guaranteeing runtime value is not fabricated)
- Syntax errors (structured error reporting without server crash)
- Ambiguous calls vs confirmed API calls
- AST complexity and source size safety limits
- Zero-execution safety verification
"""

import pytest
from app.services.python_ast_analyzer import (
    MAX_SOURCE_CHARS,
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    analyze_python_source,
    check_ast_complexity,
)


def test_direct_stripe_api_calls() -> None:
    """Confirms direct stripe.<Resource>.<method> calls are accurately recognized."""
    source = """
import stripe

charge = stripe.Charge.create(amount=2000, currency="usd")
pi = stripe.PaymentIntent.create(amount=5000, currency="eur")
cust = stripe.Customer.retrieve("cus_12345")
ref = stripe.Refund.create(charge="ch_99999")
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.candidates) == 4

    targets = [c.normalized_target for c in result.candidates]
    assert "stripe.Charge.create" in targets
    assert "stripe.PaymentIntent.create" in targets
    assert "stripe.Customer.retrieve" in targets
    assert "stripe.Refund.create" in targets

    for c in result.candidates:
        assert c.is_ambiguous is False
        assert c.confidence == "heuristic"


def test_import_aliases_and_from_imports() -> None:
    """Verifies import aliasing (import ... as, from ... import, from ... import as)."""
    source = """
import stripe as s
from stripe import Charge as C, PaymentIntent
from stripe.Customer import retrieve as get_customer

c1 = s.Charge.create(amount=1000, currency="usd")
c2 = C.create(amount=2000, currency="usd")
pi = PaymentIntent.create(amount=3000, currency="usd")
cust = get_customer("cus_abc")
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.candidates) == 4

    targets = [c.normalized_target for c in result.candidates]
    assert "stripe.Charge.create" in targets
    assert "stripe.PaymentIntent.create" in targets
    assert "stripe.Customer.retrieve" in targets

    for c in result.candidates:
        assert c.is_ambiguous is False


def test_client_instance_methods_and_resource_mapping() -> None:
    """Verifies StripeClient instance tracking and resource mapping (v5+ SDK)."""
    source = """
import stripe

client = stripe.StripeClient("sk_test_secret123")
charge = client.charges.create(amount=1500, currency="usd")
pi = client.payment_intents.create(amount=3500, currency="usd")
portal = client.billing_portal.sessions.create(customer="cus_123")
raw = client.request("POST", "/v1/charges")
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.candidates) >= 4

    targets = [c.normalized_target for c in result.candidates if c.normalized_target]
    assert "stripe.Charge.create" in targets
    assert "stripe.PaymentIntent.create" in targets
    assert "stripe.billing_portal.Session.create" in targets
    assert "stripe.StripeClient.request" in targets

    for c in result.candidates:
        if c.normalized_target:
            assert c.is_ambiguous is False


def test_client_instance_via_from_import() -> None:
    """Verifies StripeClient when imported via from stripe import StripeClient."""
    source = """
from stripe import StripeClient

client = StripeClient("sk_test_key")
cust = client.customers.create(email="user@example.com")
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.candidates) >= 1
    cust_cand = [c for c in result.candidates if c.target_name == "create"][0]
    assert cust_cand.normalized_target == "stripe.Customer.create"
    assert cust_cand.is_ambiguous is False


def test_assignment_expressions_walrus_operator() -> None:
    """Verifies assignment expressions (:=) for both client binding and API calls."""
    source = """
import stripe

if (client := stripe.StripeClient("sk_test_walrus")):
    if (charge := client.charges.create(amount=4000, currency="usd")):
        print(charge.id)
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    charge_cands = [c for c in result.candidates if c.target_name == "create"]
    assert len(charge_cands) == 1
    assert charge_cands[0].normalized_target == "stripe.Charge.create"
    assert charge_cands[0].is_ambiguous is False


def test_nested_api_calls() -> None:
    """Verifies nested API calls extract both outer and inner candidates cleanly."""
    source = """
import stripe

charge = stripe.Charge.create(
    amount=2500,
    currency="usd",
    customer=stripe.Customer.create(email="nested@example.com").id
)
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.candidates) == 2

    targets = {c.normalized_target for c in result.candidates}
    assert "stripe.Charge.create" in targets
    assert "stripe.Customer.create" in targets


def test_multiline_calls_and_exact_coordinate_preservation() -> None:
    """Verifies multiline call coordinates and argument locations are precisely preserved."""
    source = """
import stripe

charge = stripe.Charge.create(
    amount=9900,
    currency="usd",
    description="Multiline test charge",
)
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.calls) == 1
    call = result.calls[0]

    # Multiline call location should span lines 4 to 8
    assert call.location.lineno == 4
    assert call.location.end_lineno == 8

    # Check arguments
    assert len(call.arguments) == 3
    amt_arg = call.arguments[0]
    assert amt_arg.name == "amount"
    assert amt_arg.is_literal is True
    assert amt_arg.literal_value == 9900
    assert amt_arg.value_type == "literal_int"
    assert amt_arg.location.lineno == 5

    curr_arg = call.arguments[1]
    assert curr_arg.name == "currency"
    assert curr_arg.is_literal is True
    assert curr_arg.literal_value == "usd"
    assert curr_arg.value_type == "literal_str"
    assert curr_arg.location.lineno == 6

    desc_arg = call.arguments[2]
    assert desc_arg.name == "description"
    assert desc_arg.is_literal is True
    assert desc_arg.literal_value == "Multiline test charge"
    assert desc_arg.location.lineno == 7


def test_variables_passed_as_arguments_never_fabricated() -> None:
    """Requirement 4: Static analysis must not pretend a variable's runtime value is known."""
    source = """
import stripe

amount_var = calculate_total()
customer_id = get_current_user_id()

charge = stripe.Charge.create(
    amount=amount_var,
    currency="usd",
    customer=customer_id,
)
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    call = [c for c in result.calls if c.call_expr == "stripe.Charge.create"][0]

    args_by_name = {arg.name: arg for arg in call.arguments}

    # Variable 'amount_var'
    amt = args_by_name["amount"]
    assert amt.is_literal is False
    assert amt.literal_value is None
    assert amt.value_type == "identifier"
    assert amt.value_repr == "amount_var"

    # Literal 'usd'
    curr = args_by_name["currency"]
    assert curr.is_literal is True
    assert curr.literal_value == "usd"
    assert curr.value_type == "literal_str"

    # Variable 'customer_id'
    cust = args_by_name["customer"]
    assert cust.is_literal is False
    assert cust.literal_value is None
    assert cust.value_type == "identifier"
    assert cust.value_repr == "customer_id"


def test_positional_and_unpacked_arguments() -> None:
    """Verifies positional arguments, *args, and **kwargs unpacking."""
    source = """
import stripe

charge = stripe.Charge.retrieve("ch_pos_123", expand=["customer"])
stripe.PaymentIntent.create(*extra_args, **kw_params)
"""
    result = analyze_python_source(source)
    assert result.status == "success"

    # Call 1: retrieve
    call_1 = result.calls[0]
    assert call_1.positional_args_count == 1
    assert len(call_1.arguments) == 2
    pos_arg = call_1.arguments[0]
    assert pos_arg.position == 0
    assert pos_arg.name is None
    assert pos_arg.is_literal is True
    assert pos_arg.literal_value == "ch_pos_123"

    kw_arg = call_1.arguments[1]
    assert kw_arg.name == "expand"
    assert kw_arg.is_literal is True
    assert kw_arg.literal_value == ["customer"]
    assert kw_arg.value_type == "literal_list"

    # Call 2: create with *args and **kwargs
    call_2 = result.calls[1]
    assert len(call_2.arguments) == 2
    starred = call_2.arguments[0]
    assert starred.value_type == "starred"
    assert starred.is_literal is False
    assert starred.literal_value is None

    kw_unpack = call_2.arguments[1]
    assert kw_unpack.value_type == "kwargs_unpack"
    assert kw_unpack.is_literal is False
    assert kw_unpack.literal_value is None


def test_ambiguous_vs_confident_patterns() -> None:
    """Requirement 3 & 7: Distinguishes confirmed Stripe calls from generic/unverified receivers."""
    source = """
import stripe

# Confident Stripe call
stripe.Charge.create(amount=1000)

# Ambiguous generic calls (receiver has no verifiable Stripe SDK binding)
generic_service.create(name="product")
user_repo.delete(id=42)

# Non-API calls should not be candidates at all
len([1, 2, 3])
print("hello world")
"""
    result = analyze_python_source(source)
    assert result.status == "success"

    # Candidates: stripe.Charge.create + generic_service.create + user_repo.delete
    assert len(result.candidates) == 3

    stripe_cand = [c for c in result.candidates if c.receiver == "stripe.Charge"][0]
    assert stripe_cand.is_ambiguous is False
    assert stripe_cand.normalized_target == "stripe.Charge.create"

    ambig_cands = [c for c in result.candidates if c.is_ambiguous]
    assert len(ambig_cands) == 2
    for ac in ambig_cands:
        assert ac.is_ambiguous is True
        assert ac.normalized_target is None
        assert "no verifiable Stripe SDK binding" in ac.rationale

    # len and print are not candidates
    cand_targets = [c.target_name for c in result.candidates]
    assert "len" not in cand_targets
    assert "print" not in cand_targets


def test_variable_reassignment_clears_client_binding() -> None:
    """Verifies that reassigning a client variable invalidates subsequent StripeClient dispatch."""
    source = """
import stripe

client = stripe.StripeClient("sk_test")
client = "reassigned_to_string"
client.charges.create(amount=1000)
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    # When client is reassigned to string, client.charges.create is ambiguous, not stripe.Charge.create
    create_cand = [c for c in result.candidates if c.target_name == "create"][0]
    assert create_cand.is_ambiguous is True
    assert create_cand.normalized_target is None


def test_syntax_errors_handled_gracefully() -> None:
    """Verifies syntax errors return structured diagnostics without exceptions."""
    bad_source = "def broken(:\n    return"
    result = analyze_python_source(bad_source, filename="bad_code.py")
    assert result.status == "syntax_error"
    assert result.syntax_error is not None
    assert result.syntax_error.lineno == 1
    assert result.syntax_error.message != ""
    assert result.candidates == []
    assert result.calls == []


def test_ast_complexity_depth_limit() -> None:
    """Verifies defense against AST depth bomb (recursion/stack overflow attack)."""
    # Create deeply nested function call expression beyond MAX_AST_DEPTH (100)
    deep_source = "f(" * 150 + "1" + ")" * 150
    result = analyze_python_source(deep_source, filename="bomb.py")
    assert result.status == "complexity_limit_exceeded"
    assert result.syntax_error is not None
    assert "nesting depth" in result.syntax_error.message


def test_ast_complexity_node_count_limit() -> None:
    """Verifies defense against massive AST node count attack."""
    # Generate tree with more than MAX_AST_NODES (10,000)
    statements = ["x = 1\n"] * 12_000
    huge_source = "".join(statements)
    # len is ~ 72,000 chars, so under MAX_SOURCE_CHARS (100k), but > 10,000 nodes!
    assert len(huge_source) < MAX_SOURCE_CHARS
    result = analyze_python_source(huge_source, filename="massive_nodes.py")
    assert result.status == "complexity_limit_exceeded"
    assert result.syntax_error is not None
    assert "node count" in result.syntax_error.message


def test_source_size_limit() -> None:
    """Verifies defense against source code exceeding MAX_SOURCE_CHARS."""
    oversized = "a = 1\n" * 20_000  # 120,000 chars > 100,000 limit
    assert len(oversized) > MAX_SOURCE_CHARS
    result = analyze_python_source(oversized, filename="oversized.py")
    assert result.status == "source_too_large"
    assert result.syntax_error is not None
    assert "exceeds maximum limit" in result.syntax_error.message


def test_zero_code_execution_guarantee() -> None:
    """Requirement 5: Confirms dangerous OS / system commands are NEVER executed."""
    malicious_source = """
import os
import sys

# If executed, this would write a file or mutate state
os.system("touch /tmp/should_never_exist_apicompass.txt")
sys.exit(99)
"""
    result = analyze_python_source(malicious_source)
    assert result.status == "success"
    # File must not have been created
    import os
    assert not os.path.exists("/tmp/should_never_exist_apicompass.txt")
