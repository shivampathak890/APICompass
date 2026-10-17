"""Rule-based and registry-driven API call identification engine for Stripe Python code.

Maps statically extracted AST call expressions and context (imports, aliases,
client bindings, function parameters) into structured IdentifiedApiCall objects.

Guarantees:
1. Never executes user code or imports submitted modules.
2. Does not assume generic method names ('create', 'retrieve', 'update', 'delete')
   refer to Stripe without verifiable SDK bindings.
3. Distinguishes confirmed operations from ambiguous or uncertain receivers.
4. Preserves ambiguity so downstream contract adjudicators never generate false
   verified contract violations.
"""

import ast
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from app.schemas.ast_analysis import (
    AnalyzePythonResponse,
    CallArgument,
    CallInfo,
    FunctionInfo,
    ImportInfo,
    SourceLocation,
)
from app.schemas.identification import (
    IdentifiedApiCall,
    IdentifyApiCallsRequest,
    IdentifyApiCallsResponse,
)
from app.services.documentation.registry import (
    STRIPE_REGISTRY_MAPPINGS,
    get_approved_source,
    normalize_api_symbol,
    pascal_to_snake,
    resolve_from_registry,
)
from app.services.python_ast_analyzer import analyze_python_source

logger = logging.getLogger("apicompass.identification")

# Canonical Stripe resource normalization table (singular and plural to PascalCase)
KNOWN_STRIPE_RESOURCES: Dict[str, str] = {
    "charge": "Charge",
    "charges": "Charge",
    "paymentintent": "PaymentIntent",
    "payment_intent": "PaymentIntent",
    "paymentintents": "PaymentIntent",
    "payment_intents": "PaymentIntent",
    "customer": "Customer",
    "customers": "Customer",
    "refund": "Refund",
    "refunds": "Refund",
    "payout": "Payout",
    "payouts": "Payout",
    "subscription": "Subscription",
    "subscriptions": "Subscription",
    "invoice": "Invoice",
    "invoices": "Invoice",
    "setupintent": "SetupIntent",
    "setup_intent": "SetupIntent",
    "setupintents": "SetupIntent",
    "setup_intents": "SetupIntent",
    "paymentmethod": "PaymentMethod",
    "payment_method": "PaymentMethod",
    "paymentmethods": "PaymentMethod",
    "payment_methods": "PaymentMethod",
    "token": "Token",
    "tokens": "Token",
    "price": "Price",
    "prices": "Price",
    "product": "Product",
    "products": "Product",
    "balance": "Balance",
    "balances": "Balance",
    "checkout.session": "Checkout.Session",
    "checkout.sessions": "Checkout.Session",
    "billing_portal.session": "BillingPortal.Session",
    "billing_portal.sessions": "BillingPortal.Session",
}

# Standard Stripe resource operation verbs
STANDARD_STRIPE_OPERATIONS: Set[str] = {
    "create", "retrieve", "update", "delete", "list", "cancel", "capture", "confirm", "search"
}

# Common generic method verbs that often appear on unrelated objects (e.g. db.create(), user.delete())
GENERIC_METHOD_VERBS: Set[str] = {
    "create", "retrieve", "update", "delete", "list", "get", "post", 
    "put", "patch", "cancel", "save", "query", "fetch", "execute", "capture", "confirm"
}


class ContextVisitor(ast.NodeVisitor):
    """Extracts semantic context: module aliases, symbol imports, client bindings, and parameters."""

    def __init__(self) -> None:
        self.imported_modules: Dict[str, str] = {}
        self.imported_symbols: Dict[str, str] = {}
        self.confirmed_clients: Dict[str, str] = {}
        self.uncertain_clients: Set[str] = set()
        self.function_params: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name
            self.imported_modules[local] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            canonical = f"{mod}.{alias.name}" if mod else alias.name
            self.imported_symbols[local] = canonical
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            type_text = ast.unparse(arg.annotation) if arg.annotation else None
            if type_text and any(term in type_text.lower() for term in ("stripeclient", "stripe.stripeclient")):
                self.confirmed_clients[arg.arg] = "stripe.StripeClient"
            else:
                self.function_params.add(arg.arg)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            type_text = ast.unparse(arg.annotation) if arg.annotation else None
            if type_text and any(term in type_text.lower() for term in ("stripeclient", "stripe.stripeclient")):
                self.confirmed_clients[arg.arg] = "stripe.StripeClient"
            else:
                self.function_params.add(arg.arg)
        self.generic_visit(node)

    def _handle_binding(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        var_name = target.id
        if isinstance(value, ast.Call):
            call_func = ast.unparse(value.func)
            resolved = self.resolve_symbol(call_func)
            if (
                resolved in ("stripe.StripeClient", "StripeClient")
                or resolved.endswith(".StripeClient")
                or call_func.endswith("StripeClient")
            ):
                self.confirmed_clients[var_name] = "stripe.StripeClient"
                self.uncertain_clients.discard(var_name)
            else:
                # Factory or untracked function return (e.g. client = get_client())
                if var_name.lower() in ("client", "stripe_client", "stripe", "s_client"):
                    self.uncertain_clients.add(var_name)
                    self.confirmed_clients.pop(var_name, None)
        elif isinstance(value, ast.Name):
            if value.id in self.confirmed_clients:
                self.confirmed_clients[var_name] = self.confirmed_clients[value.id]
                self.uncertain_clients.discard(var_name)
            elif value.id in self.uncertain_clients:
                self.uncertain_clients.add(var_name)
        elif isinstance(value, ast.Constant):
            # Reassigned to constant string/int: invalidates previous client binding
            self.confirmed_clients.pop(var_name, None)
            self.uncertain_clients.discard(var_name)
        else:
            if var_name in self.confirmed_clients:
                self.confirmed_clients.pop(var_name, None)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._handle_binding(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.target and node.value:
            self._handle_binding(node.target, node.value)
        elif node.target and not node.value and isinstance(node.target, ast.Name) and node.annotation:
            ann_text = ast.unparse(node.annotation)
            if "stripeclient" in ann_text.lower():
                self.confirmed_clients[node.target.id] = "stripe.StripeClient"
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if node.target and node.value:
            self._handle_binding(node.target, node.value)
        self.generic_visit(node)

    def resolve_symbol(self, expr: str) -> str:
        if expr in self.imported_symbols:
            return self.imported_symbols[expr]
        parts = expr.split(".")
        if parts[0] in self.imported_modules:
            mod = self.imported_modules[parts[0]]
            return ".".join([mod] + parts[1:])
        if parts[0] in self.imported_symbols:
            sym = self.imported_symbols[parts[0]]
            return ".".join([sym] + parts[1:])
        return expr


class ApiCallIdentifier:
    """Identifies and classifies API calls against documentation registry and SDK rules."""

    def identify_calls(
        self,
        ast_result: AnalyzePythonResponse,
        source: str = "",
        ecosystem: str = "stripe",
    ) -> List[IdentifiedApiCall]:
        """Map AST calls and contextual bindings to structured IdentifiedApiCall objects."""
        if ast_result.status != "success":
            return []

        # Build context from AST tree or imports
        ctx = ContextVisitor()
        if source:
            try:
                tree = ast.parse(source)
                ctx.visit(tree)
            except Exception as e:
                logger.debug("Failed secondary context parse: %s. Using import metadata.", e)
                self._populate_context_from_metadata(ctx, ast_result)
        else:
            self._populate_context_from_metadata(ctx, ast_result)

        identified_calls: List[IdentifiedApiCall] = []
        call_counter = 0

        for call in ast_result.calls:
            call_id = f"call_{call_counter + 1:03d}"
            identified = self._classify_call(call, ctx, call_id, ecosystem)
            if identified:
                call_counter += 1
                identified_calls.append(identified)

        return identified_calls

    def _populate_context_from_metadata(
        self,
        ctx: ContextVisitor,
        ast_result: AnalyzePythonResponse,
    ) -> None:
        """Fallback to populate context from already analyzed ImportInfo objects."""
        for imp in ast_result.imports:
            if imp.is_from:
                local = imp.alias or imp.name or ""
                canonical = f"{imp.module}.{imp.name}" if imp.name else imp.module
                ctx.imported_symbols[local] = canonical
            else:
                local = imp.alias or imp.module
                ctx.imported_modules[local] = imp.module

    def _classify_call(
        self,
        call: CallInfo,
        ctx: ContextVisitor,
        call_id: str,
        ecosystem: str,
    ) -> Optional[IdentifiedApiCall]:
        """Classify a single AST call using explicit rules and documentation registry."""
        pos_args: List[CallArgument] = []
        kw_args: Dict[str, CallArgument] = {}
        for arg in call.arguments:
            if arg.name:
                kw_args[arg.name] = arg
            elif arg.position is not None:
                pos_args.append(arg)
            elif arg.value_type == "kwargs_unpack":
                kw_args["**kwargs"] = arg
            elif arg.value_type == "starred":
                pos_args.append(arg)

        receiver = call.receiver
        method = call.method
        call_expr = call.call_expr

        # -----------------------------------------------------------------------
        # Branch 1: Attribute call on an explicit receiver
        # -----------------------------------------------------------------------
        if receiver and method:
            receiver_parts = receiver.split(".")
            root_var = receiver_parts[0]

            # 1A. Direct Stripe Module Call: stripe.<Resource>.<method> or alias s.<Resource>.<method>
            if root_var == "stripe" or ctx.imported_modules.get(root_var) == "stripe":
                sub_res_raw = ".".join(receiver_parts[1:])
                norm_res = KNOWN_STRIPE_RESOURCES.get(sub_res_raw.lower())

                if norm_res:
                    return self._build_stripe_call(
                        call_id=call_id,
                        call=call,
                        pos_args=pos_args,
                        kw_args=kw_args,
                        api_resource=norm_res,
                        operation=method,
                        matching_strategy="sdk_direct",
                    )
                elif sub_res_raw == "":
                    # Direct module method, e.g. stripe.raw_request(...)
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="stripe",
                        api_resource="stripe",
                        operation=method,
                        symbol=f"stripe.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="confirmed",
                        is_ambiguous=False,
                        unresolved_ambiguity=None,
                        doc_query=None,
                        canonical_doc_url=None,
                        matching_strategy="sdk_module_function",
                    )
                else:
                    # Unrecognized Stripe resource
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="stripe",
                        api_resource=sub_res_raw,
                        operation=method,
                        symbol=f"stripe.{sub_res_raw}.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="unsupported",
                        is_ambiguous=False,
                        unresolved_ambiguity=f"Resource '{sub_res_raw}' is not a recognized Stripe API resource in documentation registry.",
                        doc_query=None,
                        canonical_doc_url=None,
                        matching_strategy="unsupported_operation",
                    )

            # 1B. Imported Symbol Reference: e.g. from stripe import Charge as C; C.create(...)
            elif root_var in ctx.imported_symbols:
                target_sym = ctx.imported_symbols[root_var]
                if target_sym.startswith("stripe."):
                    sym_parts = target_sym.split(".")
                    res_candidate = sym_parts[1] if len(sym_parts) > 1 else ""
                    norm_res = KNOWN_STRIPE_RESOURCES.get(res_candidate.lower())
                    if norm_res:
                        return self._build_stripe_call(
                            call_id=call_id,
                            call=call,
                            pos_args=pos_args,
                            kw_args=kw_args,
                            api_resource=norm_res,
                            operation=method,
                            matching_strategy="sdk_alias",
                        )

            # 1C. Confirmed StripeClient Instance Call: client = stripe.StripeClient(...); client.charges.create(...)
            elif root_var in ctx.confirmed_clients and ctx.confirmed_clients[root_var] == "stripe.StripeClient":
                sub_res_raw = ".".join(receiver_parts[1:])
                norm_res = KNOWN_STRIPE_RESOURCES.get(sub_res_raw.lower())
                if norm_res:
                    return self._build_stripe_call(
                        call_id=call_id,
                        call=call,
                        pos_args=pos_args,
                        kw_args=kw_args,
                        api_resource=norm_res,
                        operation=method,
                        matching_strategy="client_instance",
                    )
                elif sub_res_raw == "":
                    # Direct client method: client.request("POST", ...)
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="stripe",
                        api_resource="StripeClient",
                        operation=method,
                        symbol=f"stripe.StripeClient.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="confirmed",
                        is_ambiguous=False,
                        unresolved_ambiguity=None,
                        doc_query=None,
                        canonical_doc_url=None,
                        matching_strategy="client_instance",
                    )
                else:
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="stripe",
                        api_resource=sub_res_raw,
                        operation=method,
                        symbol=f"stripe.{sub_res_raw}.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="unsupported",
                        is_ambiguous=False,
                        unresolved_ambiguity=f"Sub-resource '{sub_res_raw}' is not a recognized resource on StripeClient.",
                        doc_query=None,
                        canonical_doc_url=None,
                        matching_strategy="unsupported_operation",
                    )

            # 1D. Uncertain Client Object Call (untyped parameter or untracked factory)
            elif (
                root_var in ctx.uncertain_clients
                or (root_var in ctx.function_params and root_var.lower() in ("client", "stripe_client", "stripe", "s_client"))
            ):
                sub_res_raw = ".".join(receiver_parts[1:])
                norm_res = KNOWN_STRIPE_RESOURCES.get(sub_res_raw.lower())
                if norm_res:
                    # Looks like Stripe, but client receiver is untracked/untyped
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="stripe",
                        api_resource=norm_res,
                        operation=method,
                        symbol=f"uncertain_client.{sub_res_raw}.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="uncertain_receiver",
                        is_ambiguous=True,
                        unresolved_ambiguity=(
                            f"Receiver variable '{root_var}' is an untyped parameter or unverified factory return "
                            f"without confirmed StripeClient instantiation. Sub-resource '{sub_res_raw}' resembles Stripe, "
                            f"but client binding cannot be statically verified."
                        ),
                        doc_query=f"{pascal_to_snake(norm_res)}.{method}",
                        canonical_doc_url=None,
                        matching_strategy="uncertain_receiver",
                    )
                else:
                    return IdentifiedApiCall(
                        call_id=call_id,
                        sdk_or_library="unknown",
                        api_resource=None,
                        operation=None,
                        symbol=f"{receiver}.{method}",
                        raw_expression=call.call_expr,
                        positional_arguments=pos_args,
                        keyword_arguments=kw_args,
                        location=call.location,
                        confidence="ambiguous",
                        is_ambiguous=True,
                        unresolved_ambiguity=f"Receiver '{root_var}' has no verified Stripe SDK import or client binding.",
                        doc_query=None,
                        canonical_doc_url=None,
                        matching_strategy="unverified_receiver",
                    )

            # 1E. Third-Party Libraries (e.g. requests.post, httpx.get)
            elif any(root_var.lower() == lib for lib in ("requests", "httpx", "boto3")):
                return IdentifiedApiCall(
                    call_id=call_id,
                    sdk_or_library=root_var.lower(),
                    api_resource=None,
                    operation=method,
                    symbol=f"{receiver}.{method}",
                    raw_expression=call.call_expr,
                    positional_arguments=pos_args,
                    keyword_arguments=kw_args,
                    location=call.location,
                    confidence="unsupported",
                    is_ambiguous=False,
                    unresolved_ambiguity=f"Library '{root_var}' is outside the supported Stripe API ecosystem.",
                    doc_query=None,
                    canonical_doc_url=None,
                    matching_strategy="rule_based",
                )

            # 1F. Misleading Method Names on Non-Stripe Objects (db.create(), user_service.retrieve(), cache.delete())
            elif method in GENERIC_METHOD_VERBS:
                return IdentifiedApiCall(
                    call_id=call_id,
                    sdk_or_library="unknown",
                    api_resource=None,
                    operation=None,
                    symbol=f"{receiver}.{method}",
                    raw_expression=call.call_expr,
                    positional_arguments=pos_args,
                    keyword_arguments=kw_args,
                    location=call.location,
                    confidence="ambiguous",
                    is_ambiguous=True,
                    unresolved_ambiguity=(
                        f"Receiver '{receiver}' has no verifiable Stripe SDK import, alias, or client binding. "
                        f"Method '{method}' cannot be attributed to Stripe."
                    ),
                    doc_query=None,
                    canonical_doc_url=None,
                    matching_strategy="non_stripe_receiver",
                )

        # -----------------------------------------------------------------------
        # Branch 2: Direct function call (no receiver, e.g. create_charge(...))
        # -----------------------------------------------------------------------
        else:
            if call_expr in ctx.imported_symbols:
                target_sym = ctx.imported_symbols[call_expr]
                if target_sym.startswith("stripe."):
                    sym_parts = target_sym.split(".")
                    if len(sym_parts) >= 3:
                        res_part = sym_parts[1]
                        op_part = sym_parts[2]
                        norm_res = KNOWN_STRIPE_RESOURCES.get(res_part.lower())
                        if norm_res:
                            return self._build_stripe_call(
                                call_id=call_id,
                                call=call,
                                pos_args=pos_args,
                                kw_args=kw_args,
                                api_resource=norm_res,
                                operation=op_part,
                                matching_strategy="sdk_alias",
                            )

            elif call_expr.endswith("StripeClient") or call_expr == "StripeClient":
                return IdentifiedApiCall(
                    call_id=call_id,
                    sdk_or_library="stripe",
                    api_resource="StripeClient",
                    operation="__init__",
                    symbol="stripe.StripeClient",
                    raw_expression=call.call_expr,
                    positional_arguments=pos_args,
                    keyword_arguments=kw_args,
                    location=call.location,
                    confidence="confirmed",
                    is_ambiguous=False,
                    unresolved_ambiguity=None,
                    doc_query=None,
                    canonical_doc_url=None,
                    matching_strategy="client_constructor",
                )

        # Not an API call (e.g. print(), len(), math.sqrt(), local helper)
        return None

    def _build_stripe_call(
        self,
        call_id: str,
        call: CallInfo,
        pos_args: List[CallArgument],
        kw_args: Dict[str, CallArgument],
        api_resource: str,
        operation: str,
        matching_strategy: str,
    ) -> IdentifiedApiCall:
        """Construct an IdentifiedApiCall for a confirmed Stripe operation and check registry."""
        symbol = f"stripe.{api_resource}.{operation}"
        doc_query = f"{pascal_to_snake(api_resource)}.{operation}"

        # Check documentation registry
        registry_res = resolve_from_registry(doc_query, ecosystem="stripe")
        canonical_url = registry_res.canonical_url if registry_res.is_valid else None

        strategy = matching_strategy
        if matching_strategy == "sdk_direct" and registry_res.is_valid and registry_res.strategy == "registry_exact":
            strategy = "registry_exact"

        if registry_res.is_valid:
            return IdentifiedApiCall(
                call_id=call_id,
                sdk_or_library="stripe",
                api_resource=api_resource,
                operation=operation,
                symbol=symbol,
                raw_expression=call.call_expr,
                positional_arguments=pos_args,
                keyword_arguments=kw_args,
                location=call.location,
                confidence="confirmed",
                is_ambiguous=False,
                unresolved_ambiguity=None,
                doc_query=doc_query,
                canonical_doc_url=canonical_url,
                matching_strategy=strategy,
            )
        elif operation in STANDARD_STRIPE_OPERATIONS:
            return IdentifiedApiCall(
                call_id=call_id,
                sdk_or_library="stripe",
                api_resource=api_resource,
                operation=operation,
                symbol=symbol,
                raw_expression=call.call_expr,
                positional_arguments=pos_args,
                keyword_arguments=kw_args,
                location=call.location,
                confidence="confirmed",
                is_ambiguous=False,
                unresolved_ambiguity=None,
                doc_query=doc_query,
                canonical_doc_url=None,
                matching_strategy=matching_strategy,
            )
        else:
            # Operation is not a recognized Stripe operation on this resource
            return IdentifiedApiCall(
                call_id=call_id,
                sdk_or_library="stripe",
                api_resource=api_resource,
                operation=operation,
                symbol=symbol,
                raw_expression=call.call_expr,
                positional_arguments=pos_args,
                keyword_arguments=kw_args,
                location=call.location,
                confidence="unsupported",
                is_ambiguous=False,
                unresolved_ambiguity=f"Operation '{operation}' is not a recognized method of Stripe resource '{api_resource}' in official documentation registry.",
                doc_query=doc_query,
                canonical_doc_url=None,
                matching_strategy="unsupported_operation",
            )

    def identify_from_source(
        self,
        source: str,
        filename: str = "<unknown>",
        ecosystem: str = "stripe",
    ) -> IdentifyApiCallsResponse:
        """Run safe static AST analysis and call identification directly on source text."""
        ast_result = analyze_python_source(source=source, filename=filename)
        if ast_result.status != "success":
            return IdentifyApiCallsResponse(
                status=ast_result.status,
                filename=filename,
                total_calls_detected=0,
                identified_calls=[],
                confirmed_count=0,
                ambiguous_count=0,
                unsupported_count=0,
                syntax_error=ast_result.syntax_error,
            )

        identified_calls = self.identify_calls(ast_result, source=source, ecosystem=ecosystem)
        confirmed_count = sum(1 for c in identified_calls if c.confidence == "confirmed" and not c.is_ambiguous)
        ambiguous_count = sum(1 for c in identified_calls if c.is_ambiguous)
        unsupported_count = sum(1 for c in identified_calls if c.confidence == "unsupported")

        return IdentifyApiCallsResponse(
            status="success",
            filename=filename,
            total_calls_detected=len(ast_result.calls),
            identified_calls=identified_calls,
            confirmed_count=confirmed_count,
            ambiguous_count=ambiguous_count,
            unsupported_count=unsupported_count,
            syntax_error=None,
        )


api_call_identifier = ApiCallIdentifier()
