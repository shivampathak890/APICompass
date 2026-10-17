"""Automated test suite for Stripe API call identification layer.

Tests:
1. Recognized direct operations (stripe.Charge.create, stripe.PaymentIntent.create, etc.)
2. Aliased imports (import stripe as s, from stripe import Charge as C)
3. StripeClient instance methods (client.charges.create, client.payment_intents.create)
4. Unsupported operations (stripe.Charge.teleport, stripe.UnknownResource.create)
5. Misleading method names on non-Stripe objects (db.create, user_service.retrieve, cache.delete)
6. Substring name collision avoidance (super_charge.create, charge_battery.create)
7. Uncertain client objects (untyped function parameter, factory function return)
8. Ambiguity preservation preventing contract violations in ContractMatcher
9. Positional and keyword argument mapping in IdentifiedApiCall
10. HTTP endpoint POST /api/v1/identify/python
"""

import pytest
from httpx import AsyncClient

from app.schemas.ast_analysis import ApiCandidate, SourceLocation
from app.schemas.documentation import NormalizedEvidence
from app.services.evidence.contract_matcher import contract_matcher
from app.services.identification.call_identifier import api_call_identifier
from app.services.python_ast_analyzer import analyze_python_source


# ---------------------------------------------------------------------------
# 1. Recognized Operations
# ---------------------------------------------------------------------------

def test_recognized_direct_stripe_operations() -> None:
    """Verifies direct stripe.<Resource>.<method> calls are mapped to structured IdentifiedApiCall."""
    source = """
import stripe

charge = stripe.Charge.create(amount=2000, currency="usd")
pi = stripe.PaymentIntent.create(amount=5000, currency="eur")
cust = stripe.Customer.retrieve("cus_12345")
ref = stripe.Refund.create(charge="ch_999")
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.confirmed_count == 4
    assert resp.ambiguous_count == 0
    assert resp.unsupported_count == 0

    calls_by_symbol = {c.symbol: c for c in resp.identified_calls}
    assert "stripe.Charge.create" in calls_by_symbol
    assert "stripe.PaymentIntent.create" in calls_by_symbol
    assert "stripe.Customer.retrieve" in calls_by_symbol
    assert "stripe.Refund.create" in calls_by_symbol

    # Inspect Charge.create call details
    charge_call = calls_by_symbol["stripe.Charge.create"]
    assert charge_call.sdk_or_library == "stripe"
    assert charge_call.api_resource == "Charge"
    assert charge_call.operation == "create"
    assert charge_call.confidence == "confirmed"
    assert charge_call.is_ambiguous is False
    assert charge_call.unresolved_ambiguity is None
    assert charge_call.canonical_doc_url == "https://docs.stripe.com/api/charges/create"
    assert charge_call.doc_query == "charge.create"

    # Verify structured keyword arguments
    assert "amount" in charge_call.keyword_arguments
    assert charge_call.keyword_arguments["amount"].is_literal is True
    assert charge_call.keyword_arguments["amount"].literal_value == 2000
    assert "currency" in charge_call.keyword_arguments
    assert charge_call.keyword_arguments["currency"].literal_value == "usd"


def test_recognized_stripe_client_instance_methods() -> None:
    """Verifies modern StripeClient instance dispatch (v5+ SDK)."""
    source = """
import stripe

client = stripe.StripeClient("sk_test_123")
charge = client.charges.create(amount=1500, currency="usd")
pi = client.payment_intents.create(amount=3000, currency="usd")
raw = client.request("POST", "/v1/charges")
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.confirmed_count >= 3

    calls_by_symbol = {c.symbol: c for c in resp.identified_calls}
    assert "stripe.Charge.create" in calls_by_symbol
    assert "stripe.PaymentIntent.create" in calls_by_symbol
    assert "stripe.StripeClient.request" in calls_by_symbol

    charge_call = calls_by_symbol["stripe.Charge.create"]
    assert charge_call.sdk_or_library == "stripe"
    assert charge_call.api_resource == "Charge"
    assert charge_call.operation == "create"
    assert charge_call.matching_strategy == "client_instance"
    assert charge_call.is_ambiguous is False


# ---------------------------------------------------------------------------
# 2. Aliased Imports & Symbol Aliases
# ---------------------------------------------------------------------------

def test_aliased_imports_and_from_imports() -> None:
    """Verifies import aliasing (import ... as, from ... import ... as)."""
    source = """
import stripe as s
from stripe import Charge as C, PaymentIntent as PI
from stripe.Customer import retrieve as get_cust

c = C.create(amount=1000, currency="usd")
pi = PI.create(amount=2000, currency="usd")
cust = get_cust("cus_abc")
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.confirmed_count == 3
    assert resp.ambiguous_count == 0

    symbols = [c.symbol for c in resp.identified_calls]
    assert "stripe.Charge.create" in symbols
    assert "stripe.PaymentIntent.create" in symbols
    assert "stripe.Customer.retrieve" in symbols

    for c in resp.identified_calls:
        assert c.sdk_or_library == "stripe"
        assert c.confidence == "confirmed"
        assert c.is_ambiguous is False


# ---------------------------------------------------------------------------
# 3. Unsupported Operations
# ---------------------------------------------------------------------------

def test_unsupported_stripe_operations() -> None:
    """Identifies unsupported or unrecognized operations on confirmed Stripe resources."""
    source = """
import stripe

# teleport is not an official Stripe Charge operation
stripe.Charge.teleport(destination="mars")

# UnknownResource does not exist on Stripe
stripe.UnknownResource.create(foo="bar")
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.unsupported_count == 2

    teleport_call = [c for c in resp.identified_calls if c.operation == "teleport"][0]
    assert teleport_call.sdk_or_library == "stripe"
    assert teleport_call.api_resource == "Charge"
    assert teleport_call.operation == "teleport"
    assert teleport_call.confidence == "unsupported"
    assert teleport_call.is_ambiguous is False
    assert "not a recognized method" in teleport_call.unresolved_ambiguity

    unknown_res = [c for c in resp.identified_calls if c.api_resource == "UnknownResource"][0]
    assert unknown_res.confidence == "unsupported"
    assert "not a recognized Stripe API resource" in unknown_res.unresolved_ambiguity


# ---------------------------------------------------------------------------
# 4. Misleading Method Names on Non-Stripe Objects
# ---------------------------------------------------------------------------

def test_misleading_method_names_on_non_stripe_objects() -> None:
    """Requirement: Do not assume every attribute named create, retrieve, update, delete is Stripe."""
    source = """
# None of these have Stripe imports or bindings
db.create(table="users", data={"name": "Alice"})
user_service.retrieve(user_id=42)
cache.delete(key="session_token")
inventory.update(sku="XYZ", count=10)
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.confirmed_count == 0
    assert resp.ambiguous_count == 4

    for call in resp.identified_calls:
        assert call.sdk_or_library == "unknown"
        assert call.api_resource is None
        assert call.operation is None
        assert call.confidence == "ambiguous"
        assert call.is_ambiguous is True
        assert "no verifiable Stripe SDK import" in call.unresolved_ambiguity


def test_substring_name_collision_avoidance() -> None:
    """Ensures names containing 'charge' as a substring are NOT mistakenly identified as Stripe Charge."""
    source = """
# 'super_charge' contains 'charge' as substring, but is NOT Stripe
super_charge.create(level=9000)
charge_battery.start()
turbo_charge.execute()
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert resp.confirmed_count == 0

    # Only super_charge.create matches generic verb create, but is marked ambiguous
    ambig_calls = [c for c in resp.identified_calls if c.is_ambiguous]
    assert len(ambig_calls) >= 1
    super_call = [c for c in ambig_calls if "super_charge" in c.symbol][0]
    assert super_call.sdk_or_library == "unknown"
    assert super_call.api_resource is None
    assert super_call.is_ambiguous is True


# ---------------------------------------------------------------------------
# 5. Uncertain Client Objects
# ---------------------------------------------------------------------------

def test_uncertain_client_function_parameter() -> None:
    """Untyped function parameter 'client' calling .charges.create preserves ambiguity."""
    source = """
def process_order(client, order_id):
    # client is an untyped parameter; cannot statically confirm it is StripeClient
    return client.charges.create(amount=1000, currency="usd")
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert len(resp.identified_calls) == 1
    call = resp.identified_calls[0]

    assert call.confidence == "uncertain_receiver"
    assert call.is_ambiguous is True
    assert call.api_resource == "Charge"
    assert call.operation == "create"
    assert "untyped parameter" in call.unresolved_ambiguity


def test_uncertain_client_factory_function() -> None:
    """Client assigned from an untracked factory function preserves ambiguity."""
    source = """
import stripe

client = get_stripe_client()  # untracked factory
client.charges.create(amount=5000)
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    create_call = [c for c in resp.identified_calls if "charges" in c.symbol][0]

    assert create_call.confidence == "uncertain_receiver"
    assert create_call.is_ambiguous is True
    assert "unverified factory return" in create_call.unresolved_ambiguity


def test_client_reassignment_to_primitive_becomes_ambiguous() -> None:
    """Reassigning a client to a primitive resets client binding and marks subsequent calls ambiguous."""
    source = """
import stripe

client = stripe.StripeClient("sk_test")
client = "reassigned"
client.charges.create(amount=1000)
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    create_call = [c for c in resp.identified_calls if "charges" in c.symbol][0]
    assert create_call.is_ambiguous is True


# ---------------------------------------------------------------------------
# 6. Ambiguity Preservation in ContractMatcher
# ---------------------------------------------------------------------------

def test_ambiguous_call_produces_zero_contract_violations() -> None:
    """Requirement: When operation cannot be identified confidently, avoid generating contract violations."""
    # Create an ambiguous candidate (e.g. db.create or super_charge.create)
    ambiguous_cand = ApiCandidate(
        candidate_id="cand_ambig_001",
        expression="db.create(source='tok_visa')",  # Has 'source' keyword, but on 'db'
        receiver="db",
        target_name="create",
        normalized_target=None,
        is_ambiguous=True,
        kind="method_call",
        confidence="heuristic",
        rationale="Ambiguous candidate: Method 'create' on receiver 'db' has no verifiable Stripe SDK binding.",
        enclosing_scope=None,
        location=SourceLocation(lineno=1, col_offset=0, end_lineno=1, end_col_offset=30),
    )

    # Synthetic official documentation for stripe.Charge.create
    ev = NormalizedEvidence(
        evidence_id="ev_stripe_charge",
        ecosystem="stripe",
        package="stripe",
        source_url="https://docs.stripe.com/api/charges/create",
        canonical_url="https://docs.stripe.com/api/charges/create",
        title="Create a charge | Stripe API Reference",
        provider="tinyfish_live",
        source_trust="official",
        status="success",
        doc_version="2024-06-20",
        content_excerpt="The source parameter is legacy and deprecated. Use PaymentIntents instead.",
        retrieved_at="2024-06-20T00:00:00Z",
        is_mock=False,
    )

    match_record, issues = contract_matcher.match_candidate_to_evidence(
        candidate=ambiguous_cand,
        call_info=None,
        evidence_items=[ev],
    )

    # Invariant: Ambiguity is preserved, strictly NO verified issues generated!
    assert match_record is not None
    assert match_record.is_ambiguous is True
    assert issues == []


# ---------------------------------------------------------------------------
# 7. Positional & Keyword Argument Representation
# ---------------------------------------------------------------------------

def test_positional_and_keyword_arguments_structured_representation() -> None:
    """Verifies positional arguments and keyword arguments are preserved in IdentifiedApiCall."""
    source = """
import stripe

stripe.Charge.retrieve("ch_test_999", expand=["customer", "invoice"])
"""
    resp = api_call_identifier.identify_from_source(source)
    assert resp.status == "success"
    assert len(resp.identified_calls) == 1
    call = resp.identified_calls[0]

    # Positional argument
    assert len(call.positional_arguments) == 1
    pos = call.positional_arguments[0]
    assert pos.position == 0
    assert pos.is_literal is True
    assert pos.literal_value == "ch_test_999"
    assert pos.value_type == "literal_str"

    # Keyword argument
    assert "expand" in call.keyword_arguments
    kw = call.keyword_arguments["expand"]
    assert kw.name == "expand"
    assert kw.is_literal is True
    assert kw.literal_value == ["customer", "invoice"]
    assert kw.value_type == "literal_list"


# ---------------------------------------------------------------------------
# 8. HTTP Endpoint Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identify_python_api_endpoint(client: AsyncClient) -> None:
    """Verifies POST /api/v1/identify/python returns structured identification schema."""
    source = """
import stripe

def create_payment(token):
    return stripe.PaymentIntent.create(amount=3000, currency="usd")
"""
    response = await client.post(
        "/api/v1/identify/python",
        json={"source": source, "filename": "pay.py", "ecosystem": "stripe"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["confirmed_count"] == 1
    assert data["ambiguous_count"] == 0
    assert len(data["identified_calls"]) == 1

    ident = data["identified_calls"][0]
    assert ident["sdk_or_library"] == "stripe"
    assert ident["api_resource"] == "PaymentIntent"
    assert ident["operation"] == "create"
    assert ident["confidence"] == "confirmed"
    assert ident["is_ambiguous"] is False
    assert ident["canonical_doc_url"] == "https://docs.stripe.com/api/payment_intents/create"
