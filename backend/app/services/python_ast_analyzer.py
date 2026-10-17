"""Safe static Python AST extraction engine.

This module inspects Python source code text using Python's standard `ast` module.
It NEVER executes, evaluates, or imports submitted code.
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.ast_analysis import (
    AnalyzePythonResponse,
    ApiCandidate,
    CallArgument,
    CallInfo,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParameterInfo,
    RelevantLiteral,
    SourceLocation,
    SyntaxErrorInfo,
)

# Safety limits for source size and AST complexity
MAX_SOURCE_CHARS: int = 100_000
MAX_AST_NODES: int = 10_000
MAX_AST_DEPTH: int = 100

# Regex patterns for relevant string literals
HTTP_METHODS: Set[str] = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
API_VERSION_PATTERN = re.compile(r"^(?:20\d\d-[01]\d-[0-3]\d|v\d+(?:\.\d+)*)$", re.IGNORECASE)
ENDPOINT_PATH_PATTERN = re.compile(r"^/(?:api|v[0-9]+)/[a-zA-Z0-9_\-/{}]*$", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://[a-zA-Z0-9_\-.]+(?:/[a-zA-Z0-9_\-./?%&=]*)?$", re.IGNORECASE)

# Specific external libraries vs generic ambiguous receiver names
KNOWN_API_LIBRARIES: Set[str] = {"stripe", "requests", "httpx", "boto3"}
GENERIC_API_RECEIVERS: Set[str] = {
    "client", "api", "session", "sdk", "service", "endpoint", "conn", "http"
}
KNOWN_API_RECEIVERS: Set[str] = KNOWN_API_LIBRARIES | GENERIC_API_RECEIVERS
KNOWN_API_METHODS: Set[str] = {
    "create", "retrieve", "update", "delete", "list", "get", "post", 
    "put", "patch", "request", "send", "query", "fetch", "execute", "cancel",
    "capture", "confirm"
}

# Mapping from StripeClient instance attribute to canonical Stripe resource
STRIPE_CLIENT_RESOURCE_MAP: Dict[str, str] = {
    "charges": "stripe.Charge",
    "payment_intents": "stripe.PaymentIntent",
    "customers": "stripe.Customer",
    "refunds": "stripe.Refund",
    "payouts": "stripe.Payout",
    "balance": "stripe.Balance",
    "invoices": "stripe.Invoice",
    "subscriptions": "stripe.Subscription",
    "setup_intents": "stripe.SetupIntent",
    "payment_methods": "stripe.PaymentMethod",
    "tokens": "stripe.Token",
    "checkout.sessions": "stripe.checkout.Session",
    "billing_portal.sessions": "stripe.billing_portal.Session",
}


def check_ast_complexity(tree: ast.AST, max_nodes: int = MAX_AST_NODES, max_depth: int = MAX_AST_DEPTH) -> Optional[str]:
    """Iteratively verify AST node count and depth to prevent DoS from maliciously nested or massive AST structures.

    Returns an error message if limits are exceeded, or None if AST is within limits.
    """
    node_count = 0
    stack: List[Tuple[ast.AST, int]] = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > max_nodes:
            return f"Source AST node count ({node_count}) exceeds safety limit of {max_nodes} nodes."
        if depth > max_depth:
            return f"Source AST nesting depth ({depth}) exceeds safety limit of {max_depth} levels."
        for child in ast.iter_child_nodes(node):
            stack.append((child, depth + 1))
    return None


class ASTAnalysisVisitor(ast.NodeVisitor):
    """AST visitor extracting structural symbols, calls, and heuristic candidates."""

    def __init__(self, filename: str = "<unknown>") -> None:
        self.filename = filename
        self.imports: List[ImportInfo] = []
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.calls: List[CallInfo] = []
        self.candidates: List[ApiCandidate] = []
        self.relevant_literals: List[RelevantLiteral] = []
        self.candidate_counter = 0

        # Scope tracking stack: ["ClassName", "method_name"]
        self._scope_stack: List[str] = []

        # Alias tracking: local_alias -> canonical_target (e.g. "s" -> "stripe", "Charge" -> "stripe.Charge")
        self.aliases: Dict[str, str] = {}

        # Client variable tracking: var_name -> client_type (e.g. "client" -> "stripe.StripeClient")
        self.client_bindings: Dict[str, str] = {}

    @property
    def current_scope(self) -> Optional[str]:
        """Return the current hierarchical scope identifier."""
        return ".".join(self._scope_stack) if self._scope_stack else None

    def _get_location(self, node: ast.AST) -> SourceLocation:
        """Extract source location coordinates safely from an AST node."""
        lineno = getattr(node, "lineno", 1)
        col_offset = getattr(node, "col_offset", 0)
        end_lineno = getattr(node, "end_lineno", lineno)
        end_col_offset = getattr(node, "end_col_offset", col_offset)
        return SourceLocation(
            lineno=lineno,
            col_offset=col_offset,
            end_lineno=end_lineno,
            end_col_offset=end_col_offset,
        )

    def resolve_symbol(self, expr: str) -> str:
        """Resolve an expression string against tracked import aliases.

        Examples:
            's' -> 'stripe'
            's.Charge' -> 'stripe.Charge'
            'C' -> 'stripe.Charge'
            'C.create' -> 'stripe.Charge.create'
            'Charge' -> 'stripe.Charge'
        """
        if not expr:
            return expr
        if expr in self.aliases:
            return self.aliases[expr]
        parts = expr.split(".")
        if parts[0] in self.aliases:
            resolved_root = self.aliases[parts[0]]
            return ".".join([resolved_root] + parts[1:])
        return expr

    def visit_Import(self, node: ast.Import) -> None:
        """Extract standard 'import x' statements and record aliases."""
        loc = self._get_location(node)
        for alias in node.names:
            self.imports.append(
                ImportInfo(
                    module=alias.name,
                    alias=alias.asname,
                    is_from=False,
                    level=0,
                    location=loc,
                )
            )
            if alias.asname:
                self.aliases[alias.asname] = alias.name
            else:
                self.aliases[alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Extract 'from x import y' statements including relative imports and record aliases."""
        loc = self._get_location(node)
        module_name = node.module or ""
        for alias in node.names:
            self.imports.append(
                ImportInfo(
                    module=module_name,
                    name=alias.name,
                    alias=alias.asname,
                    is_from=True,
                    level=node.level or 0,
                    location=loc,
                )
            )
            local_name = alias.asname or alias.name
            if module_name:
                canonical = f"{module_name}.{alias.name}"
            else:
                canonical = alias.name
            self.aliases[local_name] = canonical
        self.generic_visit(node)

    def _resolve_expression_type(self, value: ast.AST) -> Optional[str]:
        """Statically inspect an AST expression to determine if it references or instantiates StripeClient."""
        if isinstance(value, ast.Call):
            func_expr = ast.unparse(value.func)
            resolved_func = self.resolve_symbol(func_expr)
            if (
                resolved_func in ("stripe.StripeClient", "StripeClient")
                or resolved_func.endswith(".StripeClient")
                or func_expr.endswith("StripeClient")
            ):
                return "stripe.StripeClient"
            if resolved_func == "stripe" or func_expr == "stripe":
                return "stripe"
        elif isinstance(value, ast.Name):
            if value.id in self.client_bindings:
                return self.client_bindings[value.id]
            if value.id in self.aliases:
                return self.aliases[value.id]
        elif isinstance(value, ast.Attribute):
            unparsed = ast.unparse(value)
            resolved = self.resolve_symbol(unparsed)
            if resolved in ("stripe.StripeClient", "StripeClient") or resolved.endswith(".StripeClient"):
                return "stripe.StripeClient"
        return None

    def _track_variable_binding(self, targets: List[ast.AST], value: ast.AST) -> None:
        """Record or clear variable bindings to StripeClient or API instances."""
        resolved_type = self._resolve_expression_type(value)
        for target in targets:
            if isinstance(target, ast.Name):
                if resolved_type:
                    self.client_bindings[target.id] = resolved_type
                elif target.id in self.client_bindings:
                    del self.client_bindings[target.id]

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track variable assignments and client bindings."""
        self._track_variable_binding(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Track annotated variable assignments and client bindings."""
        if node.target and node.value:
            self._track_variable_binding([node.target], node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        """Track assignment expressions (walrus operator `:=`)."""
        if node.target and node.value:
            self._track_variable_binding([node.target], node.value)
        self.generic_visit(node)

    def _extract_parameters(self, args_node: ast.arguments) -> List[ParameterInfo]:
        """Extract all parameter categories and unparsed defaults safely."""
        params: List[ParameterInfo] = []

        # 1. Positional-only parameters (Python 3.8+)
        posonly_count = len(args_node.posonlyargs)
        total_pos_args = posonly_count + len(args_node.args)
        defaults_count = len(args_node.defaults)
        first_default_idx = total_pos_args - defaults_count

        for idx, arg in enumerate(args_node.posonlyargs):
            has_default = idx >= first_default_idx
            default_repr = None
            if has_default:
                default_node = args_node.defaults[idx - first_default_idx]
                default_repr = ast.unparse(default_node)
            type_ann = ast.unparse(arg.annotation) if arg.annotation else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    category="posonly",
                    has_default=has_default,
                    default_repr=default_repr,
                    type_annotation=type_ann,
                )
            )

        # 2. Standard positional / keyword parameters
        for idx, arg in enumerate(args_node.args):
            global_idx = posonly_count + idx
            has_default = global_idx >= first_default_idx
            default_repr = None
            if has_default:
                default_node = args_node.defaults[global_idx - first_default_idx]
                default_repr = ast.unparse(default_node)
            type_ann = ast.unparse(arg.annotation) if arg.annotation else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    category="standard",
                    has_default=has_default,
                    default_repr=default_repr,
                    type_annotation=type_ann,
                )
            )

        # 3. Variadic positional parameter (*args)
        if args_node.vararg:
            type_ann = ast.unparse(args_node.vararg.annotation) if args_node.vararg.annotation else None
            params.append(
                ParameterInfo(
                    name=args_node.vararg.arg,
                    category="vararg",
                    has_default=False,
                    default_repr=None,
                    type_annotation=type_ann,
                )
            )

        # 4. Keyword-only parameters
        for idx, arg in enumerate(args_node.kwonlyargs):
            default_node = args_node.kw_defaults[idx] if idx < len(args_node.kw_defaults) else None
            has_default = default_node is not None
            default_repr = ast.unparse(default_node) if default_node else None
            type_ann = ast.unparse(arg.annotation) if arg.annotation else None
            params.append(
                ParameterInfo(
                    name=arg.arg,
                    category="kwonly",
                    has_default=has_default,
                    default_repr=default_repr,
                    type_annotation=type_ann,
                )
            )

        # 5. Keyword-variadic parameter (**kwargs)
        if args_node.kwarg:
            type_ann = ast.unparse(args_node.kwarg.annotation) if args_node.kwarg.annotation else None
            params.append(
                ParameterInfo(
                    name=args_node.kwarg.arg,
                    category="kwarg",
                    has_default=False,
                    default_repr=None,
                    type_annotation=type_ann,
                )
            )

        return params

    def _handle_function(self, node: ast.AST, is_async: bool) -> None:
        """Handle FunctionDef or AsyncFunctionDef."""
        name = getattr(node, "name", "<anonymous>")
        loc = self._get_location(node)
        params = self._extract_parameters(getattr(node, "args"))
        decorators = [ast.unparse(d) for d in getattr(node, "decorator_list", [])]
        returns_node = getattr(node, "returns", None)
        return_ann = ast.unparse(returns_node) if returns_node else None

        self.functions.append(
            FunctionInfo(
                name=name,
                is_async=is_async,
                parameters=params,
                decorators=decorators,
                return_annotation=return_ann,
                enclosing_scope=self.current_scope,
                location=loc,
            )
        )

        # Enter function scope and visit children
        self._scope_stack.append(name)
        for child in getattr(node, "body", []):
            self.visit(child)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node, is_async=True)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Extract class definition, bases, decorators, and methods."""
        loc = self._get_location(node)
        bases = [ast.unparse(b) for b in node.bases]
        decorators = [ast.unparse(d) for d in node.decorator_list]

        # Method names directly in body
        methods = [
            item.name for item in node.body 
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        self.classes.append(
            ClassInfo(
                name=node.name,
                bases=bases,
                decorators=decorators,
                methods=methods,
                enclosing_scope=self.current_scope,
                location=loc,
            )
        )

        # Enter class scope and visit children
        self._scope_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._scope_stack.pop()

    def _extract_argument(
        self,
        value_node: ast.AST,
        name: Optional[str] = None,
        position: Optional[int] = None,
    ) -> CallArgument:
        """Extract a structured call argument preserving literal values, identifiers, and locations."""
        loc = self._get_location(value_node)
        value_repr = ast.unparse(value_node)

        # 1. Constants
        if isinstance(value_node, ast.Constant):
            val = value_node.value
            if isinstance(val, bool):
                val_type = "literal_bool"
            elif isinstance(val, int):
                val_type = "literal_int"
            elif isinstance(val, float):
                val_type = "literal_float"
            elif isinstance(val, str):
                val_type = "literal_str"
            elif val is None:
                val_type = "literal_none"
            else:
                val_type = f"literal_{type(val).__name__}"
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type=val_type,
                is_literal=True,
                literal_value=val,
                location=loc,
            )

        # 2. Unary operations on constants (e.g. -500, +10)
        if (
            isinstance(value_node, ast.UnaryOp)
            and isinstance(value_node.op, (ast.USub, ast.UAdd))
            and isinstance(value_node.operand, ast.Constant)
        ):
            val = value_node.operand.value
            if isinstance(val, (int, float)):
                num_val = -val if isinstance(value_node.op, ast.USub) else val
                val_type = "literal_int" if isinstance(num_val, int) else "literal_float"
                return CallArgument(
                    name=name,
                    position=position,
                    value_repr=value_repr,
                    value_type=val_type,
                    is_literal=True,
                    literal_value=num_val,
                    location=loc,
                )

        # 3. Literal lists
        if isinstance(value_node, ast.List):
            if all(isinstance(elt, ast.Constant) for elt in value_node.elts):
                return CallArgument(
                    name=name,
                    position=position,
                    value_repr=value_repr,
                    value_type="literal_list",
                    is_literal=True,
                    literal_value=[elt.value for elt in value_node.elts],  # type: ignore[attr-defined]
                    location=loc,
                )
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="expression",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 4. Literal dicts
        if isinstance(value_node, ast.Dict):
            if all(
                isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                for k, v in zip(value_node.keys, value_node.values)
                if k is not None
            ):
                dict_val = {
                    k.value: v.value
                    for k, v in zip(value_node.keys, value_node.values)
                    if k is not None
                }  # type: ignore[attr-defined]
                return CallArgument(
                    name=name,
                    position=position,
                    value_repr=value_repr,
                    value_type="literal_dict",
                    is_literal=True,
                    literal_value=dict_val,
                    location=loc,
                )
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="expression",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 5. Identifiers / Variables
        # REQUIREMENT 4: Avoid pretending that a variable's runtime value is known when static analysis cannot determine it.
        if isinstance(value_node, ast.Name):
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="identifier",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 6. Calls (nested)
        if isinstance(value_node, ast.Call):
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="call",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 7. Attribute access
        if isinstance(value_node, ast.Attribute):
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="attribute",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 8. Starred arguments (*args)
        if isinstance(value_node, ast.Starred):
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="starred",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 9. Binary operations
        if isinstance(value_node, ast.BinOp):
            return CallArgument(
                name=name,
                position=position,
                value_repr=value_repr,
                value_type="binary_op",
                is_literal=False,
                literal_value=None,
                location=loc,
            )

        # 10. Default / complex expression
        return CallArgument(
            name=name,
            position=position,
            value_repr=value_repr,
            value_type="expression",
            is_literal=False,
            literal_value=None,
            location=loc,
        )

    def visit_Call(self, node: ast.Call) -> None:
        """Extract call expression, structured arguments, and evaluate API candidate."""
        loc = self._get_location(node)
        call_expr = ast.unparse(node.func)
        is_attr = isinstance(node.func, ast.Attribute)
        receiver: Optional[str] = None
        method_name: Optional[str] = None

        if is_attr:
            method_name = node.func.attr
            receiver = ast.unparse(node.func.value)

        pos_count = len(node.args)
        kw_names = [kw.arg for kw in node.keywords if kw.arg is not None]

        # Extract structured arguments
        arguments: List[CallArgument] = []
        for idx, arg_node in enumerate(node.args):
            arguments.append(self._extract_argument(arg_node, name=None, position=idx))

        for kw in node.keywords:
            if kw.arg is not None:
                arguments.append(self._extract_argument(kw.value, name=kw.arg, position=None))
            else:
                kw_loc = self._get_location(kw.value)
                arguments.append(
                    CallArgument(
                        name=None,
                        position=None,
                        value_repr=f"**{ast.unparse(kw.value)}",
                        value_type="kwargs_unpack",
                        is_literal=False,
                        literal_value=None,
                        location=kw_loc,
                    )
                )

        self.calls.append(
            CallInfo(
                call_expr=call_expr,
                receiver=receiver,
                method=method_name,
                is_attribute_call=is_attr,
                positional_args_count=pos_count,
                keyword_args=kw_names,
                arguments=arguments,
                enclosing_scope=self.current_scope,
                location=loc,
            )
        )

        # Check for Heuristic API Candidate
        self._evaluate_candidate(
            node=node,
            call_expr=call_expr,
            receiver=receiver,
            method_name=method_name,
            is_attr=is_attr,
            loc=loc,
        )

        # Continue visiting arguments (handles nested calls)
        self.generic_visit(node)

    def _evaluate_candidate(
        self,
        node: ast.Call,
        call_expr: str,
        receiver: Optional[str],
        method_name: Optional[str],
        is_attr: bool,
        loc: SourceLocation,
    ) -> None:
        """Evaluate if a call matches heuristic patterns of an API interaction.

        Distinguishes confidently recognized patterns from ambiguous ones.
        """
        rationale: Optional[str] = None
        normalized_target: Optional[str] = None
        is_ambiguous = False
        kind = "method_call" if is_attr else "direct_call"
        target_name = method_name or call_expr

        # Case 1: Method call on a receiver
        if receiver:
            receiver_parts = receiver.split(".")
            root_var = receiver_parts[0]

            # 1a. Receiver root is tracked as StripeClient instance
            if root_var in self.client_bindings and self.client_bindings[root_var] == "stripe.StripeClient":
                sub_path = ".".join(receiver_parts[1:])
                if sub_path in STRIPE_CLIENT_RESOURCE_MAP:
                    mapped = STRIPE_CLIENT_RESOURCE_MAP[sub_path]
                    normalized_target = f"{mapped}.{method_name}" if method_name else mapped
                    rationale = f"Method '{method_name}' on StripeClient resource '{receiver}' (mapped to {normalized_target})."
                    is_ambiguous = False
                elif sub_path:
                    normalized_target = f"stripe.{sub_path}.{method_name}" if method_name else f"stripe.{sub_path}"
                    rationale = f"Method '{method_name}' on StripeClient resource '{receiver}'."
                    is_ambiguous = False
                else:
                    normalized_target = f"stripe.StripeClient.{method_name}" if method_name else "stripe.StripeClient"
                    rationale = f"Direct method '{method_name}' on StripeClient instance '{receiver}'."
                    is_ambiguous = False

            # 1b. Receiver resolves to a Stripe symbol via import or alias
            else:
                resolved_receiver = self.resolve_symbol(receiver)
                if resolved_receiver.startswith("stripe.") or resolved_receiver == "stripe":
                    normalized_target = f"{resolved_receiver}.{method_name}" if method_name else resolved_receiver
                    is_ambiguous = False
                    if receiver != resolved_receiver:
                        rationale = f"Call to Stripe SDK resource '{normalized_target}' via alias/import '{receiver}'."
                    else:
                        rationale = f"Call to Stripe SDK resource '{normalized_target}'."

                # 1c. Receiver matches known third-party API libraries (e.g. requests, httpx, boto3)
                elif any(part.lower() in KNOWN_API_LIBRARIES for part in resolved_receiver.split(".")):
                    normalized_target = f"{resolved_receiver}.{method_name}" if method_name else resolved_receiver
                    if method_name and method_name.lower() in KNOWN_API_METHODS:
                        rationale = f"Method '{method_name}' on receiver '{receiver}' matches standard API client call pattern."
                    else:
                        rationale = f"Call on API-associated receiver '{receiver}'."
                    is_ambiguous = False

                # 1d. Action method on generic, unverified receiver (Ambiguous Pattern)
                elif any(part.lower() in GENERIC_API_RECEIVERS for part in resolved_receiver.split(".")) or (method_name and method_name.lower() in KNOWN_API_METHODS):
                    is_ambiguous = True
                    normalized_target = None
                    rationale = (
                        f"Ambiguous candidate: Method '{method_name}' on receiver '{receiver}' "
                        f"has no verifiable Stripe SDK binding."
                    )

        # Case 2: Direct call (no receiver)
        else:
            resolved_call = self.resolve_symbol(call_expr)
            if resolved_call.startswith("stripe."):
                normalized_target = resolved_call
                target_name = method_name or resolved_call.split(".")[-1]
                is_ambiguous = False
                rationale = f"Direct call to Stripe API operation '{resolved_call}' via imported symbol '{call_expr}'."
            elif call_expr.endswith("Client") or call_expr in {"Session", "OAuth2"}:
                normalized_target = resolved_call if resolved_call.startswith("stripe.") else None
                is_ambiguous = not resolved_call.startswith("stripe.")
                rationale = f"Direct constructor call '{call_expr}' matches API client initialization pattern."

        if rationale:
            self.candidate_counter += 1
            cand_id = f"cand_{self.candidate_counter:03d}"
            self.candidates.append(
                ApiCandidate(
                    candidate_id=cand_id,
                    expression=ast.unparse(node),
                    receiver=receiver,
                    target_name=target_name,
                    normalized_target=normalized_target,
                    is_ambiguous=is_ambiguous,
                    kind=kind,
                    confidence="heuristic",
                    rationale=rationale,
                    enclosing_scope=self.current_scope,
                    location=loc,
                )
            )

    def visit_Constant(self, node: ast.Constant) -> None:
        """Extract relevant string literals (HTTP methods, endpoints, URLs, API versions)."""
        if isinstance(node.value, str):
            val = node.value.strip()
            loc = self._get_location(node)

            # 1. HTTP Methods (uppercase or lowercase standard methods, short length)
            if val.upper() in HTTP_METHODS and len(val) <= 7:
                if " " not in val:
                    self.relevant_literals.append(
                        RelevantLiteral(
                            value=val,
                            kind="http_method",
                            reason=f"Matches standard HTTP method '{val.upper()}'",
                            location=loc,
                        )
                    )

            # 2. Full URLs
            elif val.startswith(("https://", "http://")) and URL_PATTERN.match(val):
                self.relevant_literals.append(
                    RelevantLiteral(
                        value=val,
                        kind="api_url",
                        reason="Matches external HTTP/HTTPS URL pattern",
                        location=loc,
                    )
                )

            # 3. API Endpoint Paths (e.g. /v1/charges, /api/payments)
            elif val.startswith(("/v1/", "/v2/", "/v3/", "/api/")) or (val.startswith("/") and len(val) > 2 and "/" in val[1:]):
                if " " not in val and len(val) < 120:
                    self.relevant_literals.append(
                        RelevantLiteral(
                            value=val,
                            kind="endpoint_path",
                            reason="Matches standard REST API endpoint path pattern",
                            location=loc,
                        )
                    )

            # 4. API Version strings (e.g. 2020-08-27 or v1)
            elif API_VERSION_PATTERN.match(val):
                self.relevant_literals.append(
                    RelevantLiteral(
                        value=val,
                        kind="api_version",
                        reason=f"Matches API release date or version tag format '{val}'",
                        location=loc,
                    )
                )

        self.generic_visit(node)


def analyze_python_source(source: str, filename: str = "<unknown>") -> AnalyzePythonResponse:
    """Analyze Python source text statically using Python AST.

    Guarantees:
    - Never executes submitted code.
    - Strictly static parsing and iterative inspection.
    - Enforces source size and AST complexity limits.
    - Captures syntax errors without raising server exceptions.
    - Extracts imports, aliases, functions, classes, calls, structured arguments, heuristic candidates, and relevant literals.

    Args:
        source: Python source code text.
        filename: Optional source file identifier.

    Returns:
        AnalyzePythonResponse containing structured analysis findings or syntax error details.
    """
    total_lines = len(source.splitlines()) if source else 0

    # 1. Enforce source size limit
    if len(source) > MAX_SOURCE_CHARS:
        error_info = SyntaxErrorInfo(
            message=f"Source code size ({len(source)} characters) exceeds maximum limit of {MAX_SOURCE_CHARS} characters.",
            lineno=1,
            col_offset=0,
            text=None,
        )
        return AnalyzePythonResponse(
            status="source_too_large",
            engine_version="0.1.0",
            filename=filename,
            total_lines=total_lines,
            syntax_error=error_info,
            imports=[],
            functions=[],
            classes=[],
            calls=[],
            candidates=[],
            relevant_literals=[],
        )

    # 2. Parse AST safely
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        error_info = SyntaxErrorInfo(
            message=e.msg or "Python syntax error",
            lineno=e.lineno,
            col_offset=e.offset,
            text=e.text.strip() if e.text else None,
        )
        return AnalyzePythonResponse(
            status="syntax_error",
            engine_version="0.1.0",
            filename=filename,
            total_lines=total_lines,
            syntax_error=error_info,
            imports=[],
            functions=[],
            classes=[],
            calls=[],
            candidates=[],
            relevant_literals=[],
        )

    # 3. Enforce AST complexity limits (node count & recursion depth)
    complexity_err = check_ast_complexity(tree, max_nodes=MAX_AST_NODES, max_depth=MAX_AST_DEPTH)
    if complexity_err:
        error_info = SyntaxErrorInfo(
            message=complexity_err,
            lineno=1,
            col_offset=0,
            text=None,
        )
        return AnalyzePythonResponse(
            status="complexity_limit_exceeded",
            engine_version="0.1.0",
            filename=filename,
            total_lines=total_lines,
            syntax_error=error_info,
            imports=[],
            functions=[],
            classes=[],
            calls=[],
            candidates=[],
            relevant_literals=[],
        )

    # 4. Traverse AST
    visitor = ASTAnalysisVisitor(filename=filename)
    visitor.visit(tree)

    return AnalyzePythonResponse(
        status="success",
        engine_version="0.1.0",
        filename=filename,
        total_lines=total_lines,
        imports=visitor.imports,
        functions=visitor.functions,
        classes=visitor.classes,
        calls=visitor.calls,
        candidates=visitor.candidates,
        relevant_literals=visitor.relevant_literals,
        syntax_error=None,
    )
