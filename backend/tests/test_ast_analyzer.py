"""Unit and integration test suite for static Python AST analysis engine."""

import pytest
from httpx import AsyncClient

from app.services.python_ast_analyzer import analyze_python_source


def test_01_basic_import() -> None:
    """1. Basic import extraction."""
    source = "import stripe\nimport os"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.imports) == 2
    assert result.imports[0].module == "stripe"
    assert result.imports[0].alias is None
    assert result.imports[0].is_from is False
    assert result.imports[1].module == "os"


def test_02_aliased_import() -> None:
    """2. Aliased import extraction."""
    source = "import stripe as s"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.imports) == 1
    assert result.imports[0].module == "stripe"
    assert result.imports[0].alias == "s"


def test_03_from_import() -> None:
    """3. From ... import ... extraction including multiple and aliased symbols."""
    source = "from stripe import Charge, Customer as Cust\nfrom ..internal import helper"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.imports) == 3

    assert result.imports[0].module == "stripe"
    assert result.imports[0].name == "Charge"
    assert result.imports[0].alias is None
    assert result.imports[0].is_from is True
    assert result.imports[0].level == 0

    assert result.imports[1].module == "stripe"
    assert result.imports[1].name == "Customer"
    assert result.imports[1].alias == "Cust"

    assert result.imports[2].module == "internal"
    assert result.imports[2].name == "helper"
    assert result.imports[2].level == 2


def test_04_function_parameters_with_defaults() -> None:
    """4. Function parameters with default values (without executing them)."""
    source = "def create_charge(amount=1000, currency='usd'): pass"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.functions) == 1
    fn = result.functions[0]
    assert fn.name == "create_charge"
    assert len(fn.parameters) == 2
    assert fn.parameters[0].name == "amount"
    assert fn.parameters[0].has_default is True
    assert fn.parameters[0].default_repr == "1000"
    assert fn.parameters[1].name == "currency"
    assert fn.parameters[1].has_default is True
    assert fn.parameters[1].default_repr == "'usd'"


def test_05_keyword_only_parameters() -> None:
    """5. Keyword-only parameters extraction."""
    source = "def execute_order(item_id, *, idempotency_key=None, notify=True): pass"
    result = analyze_python_source(source)
    assert result.status == "success"
    fn = result.functions[0]
    assert len(fn.parameters) == 3
    assert fn.parameters[0].category == "standard"
    assert fn.parameters[1].name == "idempotency_key"
    assert fn.parameters[1].category == "kwonly"
    assert fn.parameters[1].has_default is True
    assert fn.parameters[1].default_repr == "None"
    assert fn.parameters[2].name == "notify"
    assert fn.parameters[2].category == "kwonly"
    assert fn.parameters[2].default_repr == "True"


def test_06_varargs_and_kwargs() -> None:
    """6. Variadic *args and **kwargs extraction."""
    source = "def request_wrapper(*args: str, **kwargs: int): pass"
    result = analyze_python_source(source)
    assert result.status == "success"
    fn = result.functions[0]
    assert len(fn.parameters) == 2
    assert fn.parameters[0].name == "args"
    assert fn.parameters[0].category == "vararg"
    assert fn.parameters[0].type_annotation == "str"
    assert fn.parameters[1].name == "kwargs"
    assert fn.parameters[1].category == "kwarg"
    assert fn.parameters[1].type_annotation == "int"


def test_07_async_function() -> None:
    """7. Async function definition extraction."""
    source = "async def fetch_payment(payment_id: str) -> dict: return {}"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.functions) == 1
    fn = result.functions[0]
    assert fn.name == "fetch_payment"
    assert fn.is_async is True
    assert fn.return_annotation == "dict"


def test_08_class_with_methods() -> None:
    """8. Class with bases and method extraction."""
    source = """
class StripeGateway(BaseGateway, PaymentProcessor):
    def initialize(self):
        pass
    async def process_refund(self, charge_id):
        pass
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.classes) == 1
    cls_info = result.classes[0]
    assert cls_info.name == "StripeGateway"
    assert cls_info.bases == ["BaseGateway", "PaymentProcessor"]
    assert cls_info.methods == ["initialize", "process_refund"]
    assert len(result.functions) == 2
    assert result.functions[0].enclosing_scope == "StripeGateway"
    assert result.functions[1].enclosing_scope == "StripeGateway"
    assert result.functions[1].is_async is True


def test_09_decorators() -> None:
    """9. Decorator expression extraction on functions and classes."""
    source = """
@router.post('/charges')
@rate_limit(rpm=60)
def handle_charge():
    pass
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    fn = result.functions[0]
    assert len(fn.decorators) == 2
    assert fn.decorators[0] == "router.post('/charges')"
    assert fn.decorators[1] == "rate_limit(rpm=60)"


def test_10_direct_function_call() -> None:
    """10. Direct function call extraction."""
    source = "result = process_data(100, 200)"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.call_expr == "process_data"
    assert call.is_attribute_call is False
    assert call.receiver is None
    assert call.method is None
    assert call.positional_args_count == 2


def test_11_attribute_method_call() -> None:
    """11. Attribute / method call extraction."""
    source = "charge = stripe.Charge.create(amount=5000, currency='usd')"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.call_expr == "stripe.Charge.create"
    assert call.is_attribute_call is True
    assert call.receiver == "stripe.Charge"
    assert call.method == "create"
    assert call.keyword_args == ["amount", "currency"]


def test_12_nested_calls() -> None:
    """12. Nested function calls extraction."""
    source = "stripe.Charge.create(amount=int(get_amount()), currency=get_currency('usd'))"
    result = analyze_python_source(source)
    assert result.status == "success"
    # Calls: stripe.Charge.create, int(...), get_amount(), get_currency(...)
    call_exprs = [c.call_expr for c in result.calls]
    assert "stripe.Charge.create" in call_exprs
    assert "int" in call_exprs
    assert "get_amount" in call_exprs
    assert "get_currency" in call_exprs


def test_13_keyword_argument_extraction() -> None:
    """13. Keyword argument count and names extraction."""
    source = "client.request(method='POST', url='/v1/tokens', timeout=30)"
    result = analyze_python_source(source)
    assert result.status == "success"
    call = result.calls[0]
    assert call.keyword_args == ["method", "url", "timeout"]


def test_14_relevant_http_method_or_endpoint_string() -> None:
    """14. Relevant HTTP methods, URLs, API versions, and endpoint strings identified."""
    source = """
method = 'POST'
path = '/v1/charges'
endpoint = 'https://api.stripe.com/v1'
version = '2020-08-27'
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    lit_values = [lit.value for lit in result.relevant_literals]
    assert "POST" in lit_values
    assert "/v1/charges" in lit_values
    assert "https://api.stripe.com/v1" in lit_values
    assert "2020-08-27" in lit_values


def test_15_irrelevant_ordinary_string_excluded() -> None:
    """15. Arbitrary ordinary strings excluded from relevant literals."""
    source = """
msg = 'Customer payment receipt for order 9938'
description = 'This is a description of goods'
user_name = 'Alice Smith'
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    lit_values = [lit.value for lit in result.relevant_literals]
    assert "Customer payment receipt for order 9938" not in lit_values
    assert "This is a description of goods" not in lit_values
    assert "Alice Smith" not in lit_values


def test_16_invalid_syntax_returns_structured_error() -> None:
    """16. Syntax errors produce a structured result instead of raising an unhandled exception."""
    source = "def broken_code(:\n    return 42"
    result = analyze_python_source(source)
    assert result.status == "syntax_error"
    assert result.syntax_error is not None
    assert result.syntax_error.lineno == 1
    assert result.syntax_error.message != ""


def test_17_empty_source() -> None:
    """17. Empty source string handling."""
    source = ""
    result = analyze_python_source(source)
    assert result.status == "success"
    assert result.total_lines == 0
    assert len(result.imports) == 0
    assert len(result.functions) == 0
    assert len(result.classes) == 0
    assert len(result.calls) == 0
    assert len(result.candidates) == 0


def test_18_nested_functions_and_enclosing_context() -> None:
    """18. Hierarchical enclosing scope tracking for nested classes and functions."""
    source = """
class Service:
    def outer_fn(self):
        def inner_helper():
            return 1
        return inner_helper()
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    fn_map = {fn.name: fn for fn in result.functions}
    assert fn_map["outer_fn"].enclosing_scope == "Service"
    assert fn_map["inner_helper"].enclosing_scope == "Service.outer_fn"


def test_19_correct_line_and_column_info() -> None:
    """19. Correct line and column coordinate extraction."""
    source = "x = 1\ny = stripe.Charge.create()\n"
    result = analyze_python_source(source)
    assert result.status == "success"
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.location.lineno == 2
    assert call.location.col_offset >= 0


def test_21_dangerous_calls_are_never_executed() -> None:
    """21. Dangerous-looking calls (exec, eval, system) are parsed statically only and never executed."""
    # If this code were executed, it would raise an exception or mutate system state.
    source = """
eval("raise RuntimeError('EXECUTION_VIOLATION')")
exec("1 / 0")
"""
    result = analyze_python_source(source)
    assert result.status == "success"
    call_exprs = [c.call_expr for c in result.calls]
    assert "eval" in call_exprs
    assert "exec" in call_exprs


@pytest.mark.asyncio
async def test_20_large_source_rejection(client: AsyncClient) -> None:
    """20. Large source payload exceeding limits is rejected by API with HTTP 422."""
    huge_source = "# harmless comment\n" * 6000  # > 100,000 characters
    assert len(huge_source) > 100_000

    response = await client.post(
        "/api/v1/analyze/python",
        json={"source": huge_source, "filename": "huge.py"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_22_api_endpoint_success_and_regression(client: AsyncClient) -> None:
    """22. POST /api/v1/analyze/python returns valid schema and health check remains intact."""
    # 1. Analyze endpoint
    source = """
import stripe

def charge_customer(token: str):
    return stripe.Charge.create(amount=2000, currency="usd", source=token)
"""
    response = await client.post(
        "/api/v1/analyze/python",
        json={"source": source, "filename": "sample.py"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["imports"]) == 1
    assert len(data["calls"]) == 1
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["target_name"] == "create"
    assert data["candidates"][0]["confidence"] == "heuristic"

    # 2. Syntax error handling via HTTP endpoint
    bad_response = await client.post(
        "/api/v1/analyze/python",
        json={"source": "def bad(", "filename": "bad.py"},
    )
    assert bad_response.status_code == 200
    bad_data = bad_response.json()
    assert bad_data["status"] == "syntax_error"
    assert bad_data["syntax_error"] is not None
    assert bad_data["syntax_error"]["lineno"] == 1

    # 3. Health check regression check
    health_response = await client.get("/api/v1/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "healthy"
