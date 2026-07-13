from dataclasses import replace
from typing import Optional

from ehir.core.instructions.base import Assignable
from ehir.core.type import HeapSmartPointer, Pointer, StackSmartPointer, Type

from encore.compiler.parser import statements as s
from encore.compiler.parser.statements import Block, FunctionSignature
from encore.compiler.types import (
    AnySmartPointer,
    array_size,
    is_array_type,
    is_dyn_trait_type,
    is_mutable_type,
    is_raw_pointer_type,
    is_reference_like_type,
    is_tuple_type,
    make_array_type,
    make_mutable_type,
    make_tuple_type,
    strip_mutability,
    tuple_arity,
    unwrap_for_storage,
)
from encore.utils.diagnostics import CompileDiagnostic

MatchArmLike = s.Statement_MatchArm | s.Expression_MatchArm
MatchLike = s.Statement_Match | s.Expression_Match
MatchBodyLike = Block | s.Statement_Expression
MatchPatternLike = (
    s.Expression_Path
    | s.Expression_BooleanLiteral
    | s.Expression_IntegerLiteral
    | s.Expression_FloatLiteral
    | s.Expression_StringLiteral
    | None
)


def _leaf_type_name(name: str) -> str:
    base = name.split("[", 1)[0]
    return base.rsplit("::", 1)[-1]

OPERATOR_TRAIT_BOUNDS: dict[str, str] = {
    "+": "Add",
    "-": "Sub",
    "*": "Mul",
    "**": "Pow",
    "/": "Div",
    "%": "Rem",
    "<<": "Shl",
    ">>": "Shr",
    "&": "BitAnd",
    "|": "BitOr",
    "^": "BitXor",
    "==": "Eq",
    "!=": "Ne",
    "<": "Lt",
    "<=": "Le",
    ">": "Gt",
    ">=": "Ge",
}


class TypeInferer:
    def __init__(self):
        self._funcs: dict[str, s.Statement_FunctionDefinition | s.FunctionSignature] = {}
        self._structs: dict[str, s.StructureSignature] = {}
        self._enums: dict[str, s.Statement_EnumDefinition] = {}
        self._traits: dict[str, s.Statement_Trait] = {}
        self._impl_traits: dict[str, list[str]] = {}
        self._generic_impl_traits: list[tuple[list[Type], str]] = []
        self._trait_impl_records: list[s.Statement_Impl] = []
        self._type_aliases: dict[str, str] = {}
        self._ambiguous_type_aliases: set[str] = set()
        self._globals: dict[str, Type] = {}
        self._unsafe_depth = 0
        self._current_fn_return_type: Type | None = None
        self._current_self_binding_type: Type | None = None
        self._current_impl_self_type: Type | None = None
        self._active_generic_bounds: dict[str, list[Type]] = {}
        self._active_generic_names: set[str] = set()

    def infer(
        self,
        ast: list[s.Statement],
        imported_declarations: list[object] | None = None,
    ) -> list[s.Statement]:
        imported_declarations = imported_declarations or []
        declaration_entries = [*self._normalize_declaration_entries(imported_declarations)] + [
            (statement, None, None) for statement in ast if isinstance(statement, s.Statement_TopLevel)
        ]
        self._collect_declarations(declaration_entries)

        for statement in ast:
            if isinstance(statement, s.Statement_Global):
                global_env = dict(self._globals)
                inferred = self._infer_expression(statement.expr, global_env, statement.type, mutable_env={})
                if statement.type is None:
                    if inferred is None:
                        raise TypeError(f"Unable to infer type of global '{statement.name}'")
                    statement.type = inferred
                elif inferred is not None and not self._types_compatible(statement.type, inferred):
                    raise TypeError(f"Type mismatch in global '{statement.name}': {statement.type} != {inferred}")
                assert statement.type is not None
                self._globals[statement.name] = statement.type
                continue
            if isinstance(statement, s.Statement_FunctionDefinition):
                self._infer_function(statement)
            elif isinstance(statement, s.Statement_Impl):
                for method in statement.body:
                    impl_generic_names = {generic.name for generic in statement.generics}
                    merged_generics = [*statement.generics]
                    for generic in method.signature.generics:
                        if generic.name in impl_generic_names:
                            continue
                        merged_generics.append(generic)
                        impl_generic_names.add(generic.name)
                    method.signature = replace(method.signature, generics=merged_generics)
                    self._infer_function(method, self_type=statement.struct)

        return ast

    def _diagnostic_for_statement(self, statement: s.Statement, exc: Exception) -> CompileDiagnostic:
        if isinstance(exc, CompileDiagnostic) and exc.line is not None:
            return exc
        return CompileDiagnostic(
            message=str(exc),
            line=getattr(statement, "line", None),
            column=getattr(statement, "column", None),
            span_length=getattr(statement, "span_length", None),
            source_line=getattr(statement, "source_line", None),
            module_id=getattr(statement, "module_id", None),
            cause=exc,
        )

    def _collect_declarations(self, declarations: list[tuple[s.Statement_TopLevel, str | None, str | None]]):
        for statement, local_name, source_name in declarations:
            if isinstance(statement, s.Statement_FunctionDefinition):
                name = local_name or statement.signature.name
                self._funcs[name] = statement
            elif isinstance(statement, s.FunctionSignature):
                name = local_name or statement.name
                self._funcs[name] = statement
            elif isinstance(statement, s.Statement_StructureDefinition):
                name = local_name or statement.signature.name
                canonical_name = self._canonical_declaration_name(statement.signature.name, local_name, source_name)
                self._register_type_aliases(canonical_name, statement.signature.name, local_name, source_name)
                definition = self._normalize_struct_definition(statement.signature)
                self._structs[name] = definition
                self._structs[canonical_name] = definition
            elif isinstance(statement, s.Statement_EnumDefinition):
                name = local_name or statement.name
                canonical_name = self._canonical_declaration_name(statement.name, local_name, source_name)
                self._register_type_aliases(canonical_name, statement.name, local_name, source_name)
                self._enums[name] = statement
                self._enums[canonical_name] = statement
            elif isinstance(statement, s.Statement_Trait):
                name = local_name or statement.name
                self._traits[name] = statement
            elif isinstance(statement, s.Statement_Impl):
                struct_name = self._canonical_type_name(statement.struct.name)
                if statement.trait_name is not None:
                    self._trait_impl_records.append(statement)
                    owner_generic = next(
                        (generic for generic in statement.generics if generic.name == statement.struct.name), None
                    )
                    if owner_generic is not None:
                        bounds = list(owner_generic.bounds) if isinstance(owner_generic, s.GenericParam) else []
                        self._generic_impl_traits.append((bounds, statement.trait_name))
                    else:
                        self._impl_traits.setdefault(struct_name, []).append(statement.trait_name)
                    continue

                for method in statement.body:
                    method_generic_names = {generic.name for generic in statement.generics}
                    merged_generics = [*statement.generics]
                    for generic in method.generics:
                        if generic.name in method_generic_names:
                            continue
                        merged_generics.append(generic)
                        method_generic_names.add(generic.name)

                    normalized_signature = self._normalize_signature(
                        replace(method.signature, generics=merged_generics),
                        self_type=statement.struct,
                    )
                    self._funcs[f"{struct_name}::{method.name}"] = replace(method, signature=normalized_signature)
            elif isinstance(statement, s.Statement_Global):
                name = local_name or statement.name
                if statement.type is not None:
                    self._globals[name] = statement.type

    def _normalize_declaration_entries(
        self, declarations: list[object]
    ) -> list[tuple[s.Statement_TopLevel, str | None, str | None]]:
        normalized: list[tuple[s.Statement_TopLevel, str | None, str | None]] = []
        for declaration in declarations:
            statement = getattr(declaration, "statement", declaration)
            if not isinstance(statement, s.Statement_TopLevel):
                raise TypeError(f"Unsupported imported declaration payload: {declaration!r}")
            local_name = getattr(declaration, "local_name", None)
            source_name = getattr(declaration, "source_name", None)
            normalized.append((statement, local_name, source_name))
        return normalized

    def _canonical_declaration_name(
        self,
        declared_name: str,
        local_name: str | None,
        source_name: str | None,
    ) -> str:
        return source_name or local_name or declared_name

    def _register_type_aliases(
        self,
        canonical_name: str,
        declared_name: str,
        local_name: str | None,
        source_name: str | None,
    ) -> None:
        for alias in (canonical_name, declared_name, local_name, source_name, canonical_name.rsplit("::", 1)[-1]):
            if alias:
                self._register_type_alias(alias, canonical_name)

    def _register_type_alias(self, alias: str, canonical_name: str) -> None:
        if alias in self._ambiguous_type_aliases:
            return
        existing = self._type_aliases.get(alias)
        if existing is None:
            self._type_aliases[alias] = canonical_name
            return
        if existing == canonical_name:
            return
        self._type_aliases.pop(alias, None)
        self._ambiguous_type_aliases.add(alias)

    def _canonical_type_name(self, name: str) -> str:
        exact = self._type_aliases.get(name)
        if exact is not None:
            return exact
        if "::" not in name:
            return name
        leaf = name.rsplit("::", 1)[-1]
        if leaf in self._ambiguous_type_aliases:
            return name
        return self._type_aliases.get(leaf, name)

    def _infer_function(self, statement: s.Statement_FunctionDefinition, self_type: Type | None = None):
        statement.signature = self._normalize_signature(statement.signature, self_type=self_type)
        env = {**self._globals, **{param.name: param.type for param in statement.signature.params}}
        mutability_env = {name: False for name in self._globals}
        mutability_env.update({param.name: is_mutable_type(param.type) for param in statement.signature.params})

        prev_fn_return = self._current_fn_return_type
        prev_self_binding_type = self._current_self_binding_type
        prev_impl_self_type = self._current_impl_self_type
        prev_generic_bounds = self._active_generic_bounds
        prev_generic_names = self._active_generic_names
        if statement.signature.type is None:
            statement.signature.type = self._infer_return_type(statement.body, env, mutability_env)
            if statement.signature.type is None:
                raise TypeError(f"Unable to infer return type for function '{statement.name}'")

        self._current_fn_return_type = statement.signature.type
        self._current_self_binding_type = env.get("self")
        self._current_impl_self_type = self_type
        self._active_generic_bounds = self._collect_generic_bounds(statement.signature.generics)
        self._active_generic_names = {generic.name for generic in statement.signature.generics}
        try:
            self._infer_block(statement.body, env, mutability_env, statement.signature.type)
        finally:
            self._current_fn_return_type = prev_fn_return
            self._current_self_binding_type = prev_self_binding_type
            self._current_impl_self_type = prev_impl_self_type
            self._active_generic_bounds = prev_generic_bounds
            self._active_generic_names = prev_generic_names

    def _infer_block(self, body: Block, env: dict[str, Type], mutability_env: dict[str, bool], fn_ret_type: Type):
        inferable_numeric_lets: dict[str, s.Statement_Let] = {}
        for statement in body.body:
            try:
                if isinstance(statement, s.Statement_Let):
                    inferred = self._infer_expression(statement.expr, env, statement.type, mutability_env)
                    if statement.type is None:
                        if inferred is None:
                            raise TypeError(f"Unable to infer type of variable '{statement.name}'")
                        statement.type = inferred
                        if self._is_unsuffixed_numeric_literal(statement.expr):
                            inferable_numeric_lets[statement.name] = statement
                    elif inferred is not None:
                        if not self._types_compatible(statement.type, inferred) and not self._types_match_ignoring_mut(
                            statement.type, inferred
                        ):
                            raise TypeError(
                                f"Type mismatch in let binding '{statement.name}': {statement.type} != {inferred}"
                            )
                        statement.type = self._concretize_type(statement.type, inferred)
                    self._assert_raw_pointer_usage_allowed(statement.type, context=f"binding '{statement.name}'")
                    env[statement.name] = statement.type
                    mutability_env[statement.name] = statement.is_mut
                elif isinstance(statement, s.Statement_Assignment):
                    self._assert_assignment_target_mutable(statement.target, env, mutability_env)
                    expected = self._infer_lvalue_type(statement.target, env)
                    value_type = self._infer_expression(statement.expr, env, expected, mutability_env)
                    self._assert_raw_pointer_usage_allowed(expected, context="assignment target")
                    if (
                        expected is not None
                        and value_type is not None
                        and not self._types_compatible(expected, value_type)
                        and not self._types_match_ignoring_mut(expected, value_type)
                    ):
                        raise TypeError(f"Type mismatch in assignment: {expected} != {value_type}")
                elif isinstance(statement, s.Statement_Expr):
                    expr_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                    self._assert_raw_pointer_usage_allowed(expr_type, context="expression statement")
                elif isinstance(statement, s.Statement_Ret):
                    ret_type = self._infer_expression(statement.expr, env, fn_ret_type, mutability_env)
                    self._assert_raw_pointer_usage_allowed(ret_type, context="return value")
                    if ret_type is not None and not self._types_compatible(fn_ret_type, ret_type):
                        if isinstance(statement.expr, s.Expression_Path) and len(statement.expr.segments) == 1:
                            local_name = statement.expr.segments[0].name
                            let_stmt = inferable_numeric_lets.get(local_name)
                            if (
                                let_stmt is not None
                                and self._is_numeric_type(fn_ret_type)
                                and self._is_numeric_type(ret_type)
                            ):
                                let_stmt.type = fn_ret_type
                                self._annotate_numeric_literal(let_stmt.expr, fn_ret_type)
                                env[local_name] = fn_ret_type
                                ret_type = fn_ret_type
                    if ret_type is not None and not self._types_compatible(fn_ret_type, ret_type):
                        raise TypeError(f"Return type mismatch: {ret_type} != {fn_ret_type}")
                elif isinstance(statement, s.Statement_While):
                    cond = self._infer_expression(statement.expr, env, Type("bool"), mutability_env)
                    if cond is not None and not self._is_bool_type(cond):
                        raise TypeError(f"While condition must be bool, got {cond}")
                    self._infer_block(statement.body, dict(env), dict(mutability_env), fn_ret_type)
                elif isinstance(statement, s.Statement_DoWhile):
                    self._infer_block(statement.body, dict(env), dict(mutability_env), fn_ret_type)
                    cond = self._infer_expression(statement.expr, env, Type("bool"), mutability_env)
                    if cond is not None and not self._is_bool_type(cond):
                        raise TypeError(f"Do-while condition must be bool, got {cond}")
                elif isinstance(statement, s.Statement_Loop):
                    self._infer_block(statement.body, dict(env), dict(mutability_env), fn_ret_type)
                elif isinstance(statement, s.Statement_For):
                    iter_expr = s.Expression_MethodCall(
                        receiver=statement.iterable, method="iter", generics=[], args=[]
                    )
                    iter_type = self._infer_expression(iter_expr, env, mutable_env=mutability_env)
                    if iter_type is None:
                        raise TypeError("Unable to infer iterator type in for-loop")
                    loop_env = dict(env)
                    loop_mutability_env = dict(mutability_env)
                    loop_env["__for_iter"] = iter_type
                    loop_mutability_env["__for_iter"] = True
                    step_expr = s.Expression_MethodCall(
                        receiver=s.Expression_Path([Type("__for_iter")]),
                        method="next",
                        generics=[],
                        args=[],
                    )
                    step_type = self._infer_expression(step_expr, loop_env, mutable_env=loop_mutability_env)
                    if step_type is None:
                        raise TypeError("Unable to infer iterator step type in for-loop")
                    loop_env["__for_step"] = step_type
                    loop_mutability_env["__for_step"] = False
                    next_iter_type = self._lookup_chained_field_type("__for_step", "0", loop_env)
                    if next_iter_type is not None and not self._types_compatible(iter_type, next_iter_type):
                        raise TypeError(f"For-loop iterator state mismatch: {iter_type} != {next_iter_type}")
                    item_opt_type = self._lookup_chained_field_type("__for_step", "1", loop_env)
                    if item_opt_type is None:
                        raise TypeError("Unable to infer yielded item type in for-loop")
                    item_opt_type = unwrap_for_storage(item_opt_type)
                    if is_reference_like_type(item_opt_type):
                        item_opt_type = item_opt_type.pointee
                    if item_opt_type.name != "Option" or len(item_opt_type.generics) != 1:
                        raise TypeError(f"For-loop `next` must return Option[T], got {item_opt_type}")
                    body_env = dict(loop_env)
                    body_mutability_env = dict(loop_mutability_env)
                    body_env[statement.name] = item_opt_type.generics[0]
                    body_mutability_env[statement.name] = False
                    self._infer_block(statement.body, body_env, body_mutability_env, fn_ret_type)
                elif isinstance(statement, s.Statement_With):
                    resource_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                    if resource_type is None:
                        raise TypeError("Unable to infer resource type in with-statement")
                    base_resource_type = unwrap_for_storage(resource_type)
                    base_resource_type = (
                        base_resource_type.pointee if is_reference_like_type(base_resource_type) else base_resource_type
                    )
                    resource_type_name = self._canonical_type_name(base_resource_type.name)
                    trait_names = list(self._impl_traits.get(resource_type_name, []))
                    resource_leaf = resource_type_name.rsplit("::", 1)[-1]
                    for owner_name, owner_traits in self._impl_traits.items():
                        if owner_name == resource_type_name:
                            continue
                        if owner_name.rsplit("::", 1)[-1] == resource_leaf:
                            for owner_trait in owner_traits:
                                if owner_trait not in trait_names:
                                    trait_names.append(owner_trait)
                    has_context_manager = any(
                        trait_name.rsplit("::", 1)[-1] == "ContextManager" for trait_name in trait_names
                    )
                    if not has_context_manager:
                        raise TypeError(
                            f"with-statement requires `{base_resource_type.name}` to implement ContextManager"
                        )
                    enter_type = self._infer_expression(
                        s.Expression_MethodCall(receiver=statement.expr, method="with_enter", generics=[], args=[]),
                        env,
                        mutable_env=mutability_env,
                    )
                    if enter_type is None:
                        raise TypeError("with-statement requires ContextManager::with_enter(self) -> Self")
                    self._infer_expression(
                        s.Expression_MethodCall(
                            receiver=s.Expression_Path([Type(statement.name)]),
                            method="with_exit",
                            generics=[],
                            args=[],
                        ),
                        {**env, statement.name: enter_type},
                        Type("bool"),
                        {**mutability_env, statement.name: False},
                    )
                    body_env = dict(env)
                    body_mutability_env = dict(mutability_env)
                    body_env[statement.name] = enter_type
                    body_mutability_env[statement.name] = False
                    self._infer_block(statement.body, body_env, body_mutability_env, fn_ret_type)
                elif isinstance(statement, s.Statement_If):
                    for branch in statement.branches:
                        cond = self._infer_expression(branch.expr, env, Type("bool"), mutability_env)
                        if cond is not None and not self._is_bool_type(cond):
                            raise TypeError(f"If condition must be bool, got {cond}")
                        self._infer_block(branch.body, dict(env), dict(mutability_env), fn_ret_type)
                    if statement.else_body is not None:
                        self._infer_block(statement.else_body, dict(env), dict(mutability_env), fn_ret_type)
                elif isinstance(statement, s.Statement_Match):
                    self._infer_match(statement, env, mutability_env, fn_ret_type)
                elif isinstance(statement, s.Statement_Unsafe):
                    self._unsafe_depth += 1
                    try:
                        self._infer_block(statement.body, dict(env), dict(mutability_env), fn_ret_type)
                    finally:
                        self._unsafe_depth -= 1
                elif isinstance(statement, s.Statement_EHIR):
                    self._bind_ehir_outputs(statement, env, mutability_env)
            except Exception as exc:
                raise self._diagnostic_for_statement(statement, exc) from exc

    def _is_numeric_type(self, typ: Type) -> bool:
        return self._is_integer_type(typ) or self._is_float_type(typ)

    def _is_unsuffixed_numeric_literal(self, expr: s.Statement_Expression) -> bool:
        if isinstance(expr, s.Expression_IntegerLiteral):
            return expr.literal_type is None
        if isinstance(expr, s.Expression_FloatLiteral):
            return expr.literal_type is None
        return False

    def _annotate_numeric_literal(self, expr: s.Statement_Expression, inferred_type: Type):
        if isinstance(expr, s.Expression_IntegerLiteral):
            expr.literal_type = inferred_type
        elif isinstance(expr, s.Expression_FloatLiteral):
            expr.literal_type = inferred_type

    def _infer_return_type(
        self,
        body: Block | list[s.Statement_InnerLevel],
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ) -> Optional[Type]:
        statements = body.body if isinstance(body, Block) else body
        types: list[Type] = []
        for statement in statements:
            if isinstance(statement, s.Statement_Let):
                inferred = self._infer_expression(statement.expr, env, statement.type, mutability_env)
                if inferred is not None:
                    if statement.type is None:
                        statement.type = inferred
                    else:
                        if not self._types_compatible(statement.type, inferred) and not self._types_match_ignoring_mut(
                            statement.type, inferred
                        ):
                            raise TypeError(
                                f"Type mismatch in let binding '{statement.name}': {statement.type} != {inferred}"
                            )
                        statement.type = self._concretize_type(statement.type, inferred)
                    self._assert_raw_pointer_usage_allowed(statement.type, context=f"binding '{statement.name}'")
                    env[statement.name] = statement.type
                    mutability_env[statement.name] = statement.is_mut
            if isinstance(statement, s.Statement_Assignment):
                self._assert_assignment_target_mutable(statement.target, env, mutability_env)
                expected = self._infer_lvalue_type(statement.target, env)
                value_type = self._infer_expression(statement.expr, env, expected, mutability_env)
                self._assert_raw_pointer_usage_allowed(expected, context="assignment target")
                if (
                    expected is not None
                    and value_type is not None
                    and not self._types_compatible(expected, value_type)
                    and not self._types_match_ignoring_mut(expected, value_type)
                ):
                    raise TypeError(f"Type mismatch in assignment: {expected} != {value_type}")
            if isinstance(statement, s.Statement_Ret):
                ret_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                if ret_type is not None:
                    self._assert_raw_pointer_usage_allowed(ret_type, context="return value")
                    types.append(ret_type)
            elif isinstance(statement, s.Statement_Expr):
                expr_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                self._assert_raw_pointer_usage_allowed(expr_type, context="expression statement")
            elif isinstance(statement, s.Statement_While):
                nested = self._infer_return_type(statement.body, dict(env), dict(mutability_env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_DoWhile):
                nested = self._infer_return_type(statement.body, dict(env), dict(mutability_env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_Loop):
                nested = self._infer_return_type(statement.body, dict(env), dict(mutability_env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_If):
                for branch in statement.branches:
                    nested = self._infer_return_type(branch.body, dict(env), dict(mutability_env))
                    if nested is not None:
                        types.append(nested)
                if statement.else_body is not None:
                    nested = self._infer_return_type(statement.else_body, dict(env), dict(mutability_env))
                    if nested is not None:
                        types.append(nested)
            elif isinstance(statement, s.Statement_Match):
                scrutinee_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                for arm in statement.arms:
                    arm_env = dict(env)
                    arm_mutability_env = dict(mutability_env)
                    payload_type = self._resolve_match_arm_payload_type(scrutinee_type, arm)
                    if arm.binding is not None and payload_type is not None:
                        arm_env[arm.binding] = payload_type
                        arm_mutability_env[arm.binding] = False
                    nested = self._infer_return_type(arm.body, arm_env, arm_mutability_env)
                    if nested is not None:
                        types.append(nested)
            elif isinstance(statement, s.Statement_Unsafe):
                self._unsafe_depth += 1
                try:
                    nested = self._infer_return_type(statement.body, dict(env), dict(mutability_env))
                finally:
                    self._unsafe_depth -= 1
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_EHIR):
                self._bind_ehir_outputs(statement, env, mutability_env)

        if not types:
            return None
        first = types[0]
        for typ in types[1:]:
            if typ != first:
                raise TypeError(f"Unable to infer a single return type: {first} != {typ}")
        return first

    def _normalize_signature(self, signature: s.FunctionSignature, self_type: Type | None) -> s.FunctionSignature:
        resolved_self_type = self._resolve_self_type(self_type)
        params = [
            replace(param, type=self._resolve_self_in_type(param.type, resolved_self_type))
            for param in signature.params
        ]
        ret_type = None if signature.type is None else self._resolve_self_in_type(signature.type, resolved_self_type)
        return replace(signature, params=params, type=ret_type)

    def _normalize_struct_definition(self, definition: s.StructureSignature) -> s.StructureSignature:
        if isinstance(definition, s.CLikeStructureDefinition):
            return definition
        if isinstance(definition, s.TupleStructureDefinition):
            return definition._to_clike()
        if isinstance(definition, s.UnitStructureDefinition):
            return definition._to_tuple()._to_clike()
        raise NotImplementedError(f"Unsupported structure definition: {type(definition)}")

    def _resolve_self_type(self, self_type: Type | None) -> Type | None:
        if self_type is None:
            return None
        return unwrap_for_storage(self_type)

    def _resolve_self_in_type(self, typ: Type, self_type: Type | None) -> Type:
        if is_mutable_type(typ):
            resolved = self._resolve_self_in_type(unwrap_for_storage(typ), self_type)
            return make_mutable_type(resolved)
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._resolve_self_in_type(typ.pointee, self_type))
        if is_raw_pointer_type(typ):
            return Pointer(self._resolve_self_in_type(typ.pointee, self_type))
        if typ.name == "Self" and not typ.generics and self_type is not None:
            return self_type
        return replace(typ, generics=[self._resolve_self_in_type(g, self_type) for g in typ.generics])

    def _lookup_function_signature(self, fn_name: str) -> s.FunctionSignature | None:
        fn = self._funcs.get(fn_name)
        if fn is None:
            return None

        if isinstance(fn, FunctionSignature):
            return fn
        return fn.signature

    def _resolve_function_call_signature(
        self, expr: s.Expression_Call
    ) -> tuple[str, list[Type], s.FunctionSignature | None]:
        call_name = expr.name
        explicit_generics = list(expr.generics)
        signature = self._lookup_function_signature(call_name)
        if signature is not None:
            return call_name, explicit_generics, signature

        if len(expr.callee.segments) >= 2:
            owner_segments = list(expr.callee.segments[:-1])
            if owner_segments and owner_segments[-1].name == "Self":
                self_hint = self._current_self_binding_type or self._current_impl_self_type
                resolved_self = self._resolve_self_type(self_hint)
                owner_segments[-1] = self._resolve_self_in_type(owner_segments[-1], resolved_self)
            owner = owner_segments[-1]
            normalized_owner = "::".join(segment.name for segment in owner_segments)
            normalized_name = f"{normalized_owner}::{expr.callee.segments[-1].name}"
            signature = self._lookup_function_signature(normalized_name)
            if signature is not None:
                if owner.generics:
                    if explicit_generics:
                        raise TypeError(
                            "Associated function generics must be specified either on the owner type or on the call"
                        )
                    explicit_generics = list(owner.generics)
                return normalized_name, explicit_generics, signature

        return call_name, explicit_generics, None

    def _resolve_trait_qualified_call_signature(
        self,
        expr: s.Expression_Call,
        env: dict[str, Type],
        mutable_env: dict[str, bool],
    ) -> tuple[str, list[Type], s.FunctionSignature | None]:
        if len(expr.callee.segments) < 2 or not expr.args:
            return expr.name, list(expr.generics), None

        trait_name = "::".join(segment.name for segment in expr.callee.segments[:-1])
        method_name = expr.callee.segments[-1].name
        receiver_type = self._infer_expression(expr.args[0], env, mutable_env=mutable_env)
        if receiver_type is None:
            return expr.name, list(expr.generics), None

        signature = self._lookup_trait_method_signature(
            trait_name,
            method_name,
            receiver_type=receiver_type,
        )
        if signature is None:
            return expr.name, list(expr.generics), None

        if not self._type_satisfies_bound(receiver_type, Type(trait_name)):
            raise TypeError(f"Type '{receiver_type}' does not implement trait '{trait_name}'")

        return f"{trait_name}::{method_name}", list(expr.generics), signature

    def _lookup_trait_method_signature(
        self,
        trait_name: str,
        method_name: str,
        *,
        receiver_type: Type | None = None,
        seen: set[str] | None = None,
    ) -> s.FunctionSignature | None:
        trait = self._traits.get(trait_name)
        if trait is None and "::" not in trait_name:
            matches = [name for name in self._traits if name.endswith(f"::{trait_name}")]
            if len(matches) == 1:
                trait_name = matches[0]
                trait = self._traits.get(trait_name)
        if trait is None:
            return None

        seen = seen or set()
        if trait_name in seen:
            return None
        seen.add(trait_name)

        for method in trait.body:
            if method.name == method_name:
                return self._normalize_signature(method, self_type=receiver_type)

        for base in trait.bases:
            signature = self._lookup_trait_method_signature(
                base.name, method_name, receiver_type=receiver_type, seen=seen
            )
            if signature is not None:
                return signature
        return None

    def _resolve_method_signature(self, receiver_type: Type, method_name: str) -> tuple[str, s.FunctionSignature]:
        def base_type_name(name: str) -> str:
            bracket = name.find("[")
            return name if bracket < 0 else name[:bracket]

        def leaf_type_name(name: str) -> str:
            return base_type_name(name).rsplit("::", 1)[-1]

        def impl_trait_names(receiver: Type) -> list[str]:
            type_name = self._canonical_type_name(receiver.name)
            out = list(self._impl_traits.get(type_name, []))
            leaf = leaf_type_name(type_name)
            for owner_name, trait_names in self._impl_traits.items():
                if owner_name == type_name:
                    continue
                if leaf_type_name(owner_name) == leaf:
                    for trait_name in trait_names:
                        if trait_name not in out:
                            out.append(trait_name)
            for bounds, trait_name in self._generic_impl_traits:
                if not self._receiver_satisfies_bounds(receiver, bounds):
                    continue
                if trait_name not in out:
                    out.append(trait_name)
            return out

        receiver_type = unwrap_for_storage(receiver_type)
        base_receiver_type = receiver_type.pointee if is_reference_like_type(receiver_type) else receiver_type
        if is_dyn_trait_type(base_receiver_type):
            trait_type = base_receiver_type.generics[0]
            trait_signature = self._lookup_trait_method_signature(
                trait_type.name,
                method_name,
                receiver_type=base_receiver_type,
            )
            if trait_signature is not None:
                return f"{trait_type.name}::{method_name}", trait_signature

        receiver_type_name = self._canonical_type_name(base_receiver_type.name)
        inherent_name = f"{receiver_type_name}::{method_name}"
        inherent_signature = self._lookup_function_signature(inherent_name)
        if inherent_signature is not None:
            return inherent_name, inherent_signature

        receiver_base = base_type_name(receiver_type_name)
        receiver_leaf = leaf_type_name(receiver_type_name)
        inherent_candidates: list[str] = []
        for candidate_name in self._funcs:
            if not candidate_name.endswith(f"::{method_name}"):
                continue
            parts = candidate_name.rsplit("::", 2)
            if len(parts) < 2:
                continue
            owner_name = base_type_name(parts[-2])
            if owner_name != receiver_base and leaf_type_name(owner_name) != receiver_leaf:
                continue
            inherent_candidates.append(candidate_name)
        if len(inherent_candidates) == 1:
            matched_name = inherent_candidates[0]
            matched_signature = self._lookup_function_signature(matched_name)
            if matched_signature is not None:
                return matched_name, matched_signature

        for trait_name in impl_trait_names(base_receiver_type):
            trait_signature = self._lookup_trait_method_signature(
                trait_name,
                method_name,
                receiver_type=base_receiver_type,
            )
            if trait_signature is not None:
                return f"{trait_name}::{method_name}", trait_signature

        for bound in self._lookup_active_generic_bounds(base_receiver_type):
            trait_signature = self._lookup_trait_method_signature(
                bound.name,
                method_name,
                receiver_type=base_receiver_type,
            )
            if trait_signature is not None:
                return f"{bound.name}::{method_name}", trait_signature

        similar = [name for name in self._funcs if name.endswith(f"::{method_name}")]
        owner_filtered: list[str] = []
        for candidate_name in similar:
            parts = candidate_name.rsplit("::", 2)
            if len(parts) < 2:
                continue
            if leaf_type_name(parts[-2]) == receiver_leaf:
                owner_filtered.append(candidate_name)
        if owner_filtered:
            preferred = [name for name in owner_filtered if "::Iterator::" not in name]
            matched_name = preferred[0] if preferred else owner_filtered[0]
            matched_signature = self._lookup_function_signature(matched_name)
            if matched_signature is not None:
                return matched_name, matched_signature
        raise TypeError(
            f"Method '{method_name}' is not defined for type '{base_receiver_type.name}'. "
            f"inherent_name='{inherent_name}', suffix_matches={len(inherent_candidates)}, method_suffix_matches={len(similar)}"
        )

    def _receiver_satisfies_bounds(self, receiver_type: Type, bounds: list[Type]) -> bool:
        for bound in bounds:
            if not self._type_satisfies_bound(receiver_type, bound):
                return False
        return True

    def _infer_call_signature(
        self,
        *,
        signature: s.FunctionSignature,
        args: list[s.Statement_Expression],
        env: dict[str, Type],
        expected_type: Optional[Type],
        mutable_env: dict[str, bool],
        explicit_generics: list[Type],
        callable_name: str,
    ) -> Optional[Type]:
        if len(args) != len(signature.params):
            raise TypeError(
                f"Argument count mismatch for function '{callable_name}': {len(args)} != {len(signature.params)}"
            )

        generic_mapping: dict[str, Type] = {}
        generic_names = {generic.name for generic in signature.generics}
        if explicit_generics:
            if len(explicit_generics) != len(signature.generics):
                raise TypeError(
                    f"Generic count mismatch for function '{callable_name}': {len(explicit_generics)} != {len(signature.generics)}"
                )
            generic_mapping = {
                generic.name: concrete for generic, concrete in zip(signature.generics, explicit_generics)
            }

        for param, arg in zip(signature.params, args):
            expected_param_type = self._specialize_type(param.type, generic_mapping)
            arg_expected_type = (
                None
                if self._contains_unresolved_generic(param.type, generic_mapping, generic_names)
                else expected_param_type
            )
            arg_type = self._infer_expression(arg, env, arg_expected_type, mutable_env)
            # print(param, arg, expected_param_type, arg_type)
            if arg_type is not None:
                if (
                    expected_param_type is not None
                    and is_mutable_type(expected_param_type)
                    and not is_mutable_type(arg_type)
                ):
                    if (
                        isinstance(arg, s.Expression_Path)
                        and len(arg.segments) == 1
                        and not mutable_env.get(arg.name, False)
                    ):
                        raise TypeError(
                            f"Cannot pass immutable binding '{arg.name}' as mutable argument "
                            f"for '{callable_name}' param '{param.name}'"
                        )
                    arg_type = make_mutable_type(arg_type)
                self._match_generic(param.type, arg_type, generic_mapping)
                expected_param_type = self._specialize_type(param.type, generic_mapping)
                if expected_param_type is not None and not self._types_compatible(expected_param_type, arg_type):
                    raise TypeError(
                        f"Type mismatch in call argument for '{callable_name}' param '{param.name}': "
                        f"{expected_param_type} != {arg_type}"
                    )

        if signature.generics:
            if expected_type is not None and signature.type is not None:
                self._match_generic(signature.type, expected_type, generic_mapping)
            self._infer_missing_generics_from_bounds(signature.generics, generic_mapping)
            missing_generics = [generic.name for generic in signature.generics if generic.name not in generic_mapping]
            if missing_generics:
                raise TypeError(
                    f"Unable to infer generics for function '{callable_name}': {', '.join(missing_generics)}"
                )
            explicit_generics[:] = [generic_mapping[generic.name] for generic in signature.generics]
            self._validate_generic_bounds(signature.generics, generic_mapping, callable_name)

        if signature.type is None:
            return None
        return self._specialize_type(signature.type, generic_mapping)

    def _infer_missing_generics_from_bounds(
        self,
        generics: list[Type],
        generic_mapping: dict[str, Type],
    ) -> None:
        changed = True
        while changed:
            changed = False
            for generic in generics:
                if not isinstance(generic, s.GenericParam):
                    continue
                concrete = generic_mapping.get(generic.name)
                if concrete is None:
                    continue
                for bound in generic.bounds:
                    changed |= self._infer_generics_from_bound_impl(bound, concrete, generic_mapping)

    def _infer_generics_from_bound_impl(
        self,
        bound: Type,
        concrete: Type,
        generic_mapping: dict[str, Type],
    ) -> bool:
        concrete = unwrap_for_storage(concrete)
        if is_reference_like_type(concrete):
            return self._infer_generics_from_bound_impl(bound, concrete.pointee, generic_mapping)
        if is_raw_pointer_type(concrete):
            return self._infer_generics_from_bound_impl(bound, concrete.pointee, generic_mapping)

        changed = False
        for impl in self._trait_impl_records:
            if impl.trait_name is None:
                continue
            if not self._trait_names_match(impl.trait_name, bound.name):
                continue

            impl_mapping: dict[str, Type] = {}
            self._match_generic(impl.struct, concrete, impl_mapping)
            concrete_impl_struct = self._specialize_type(impl.struct, impl_mapping)
            if not self._types_compatible(concrete_impl_struct, concrete):
                continue

            trait_args = [self._specialize_type(arg, impl_mapping) for arg in impl.trait_args]
            actual_bound = Type(bound.name, trait_args)
            before = dict(generic_mapping)
            self._match_generic(bound, actual_bound, generic_mapping)
            changed |= before != generic_mapping
        return changed

    def _trait_names_match(self, lhs: str, rhs: str) -> bool:
        return lhs == rhs or lhs.rsplit("::", 1)[-1] == rhs.rsplit("::", 1)[-1]

    def _call_uses_owner_generics(self, expr: s.Expression_Call) -> bool:
        return len(expr.callee.segments) >= 2 and bool(expr.callee.segments[-2].generics)

    def _infer_lvalue_type(self, expr: s.Statement_Expression, env: dict[str, Type]) -> Optional[Type]:
        if isinstance(expr, s.Expression_Path) and len(expr.segments) == 1:
            return env.get(expr.name)
        if isinstance(expr, s.Expression_StructField):
            return self._lookup_chained_field_type(expr.name, expr.field, env)
        return None

    def _infer_match(
        self,
        statement: s.Statement_Match,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
        fn_ret_type: Type,
    ):
        scrutinee_type = self._infer_match_scrutinee(statement, env, mutability_env)
        for arm in statement.arms:
            arm_env, arm_mutability_env = self._prepare_match_arm_scope(scrutinee_type, arm, env, mutability_env)
            self._infer_match_statement_body(self._get_match_arm_body(arm), arm_env, arm_mutability_env, fn_ret_type)

    def _infer_match_scrutinee(
        self,
        statement: MatchLike,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ) -> Type:
        scrutinee_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
        if scrutinee_type is None:
            raise TypeError("Unable to infer type of match expression")
        self._validate_match_coverage(scrutinee_type, statement.arms)
        return scrutinee_type

    def _prepare_match_arm_scope(
        self,
        scrutinee_type: Type,
        arm: MatchArmLike,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ) -> tuple[dict[str, Type], dict[str, bool]]:
        arm_env = dict(env)
        arm_mutability_env = dict(mutability_env)
        if arm.is_wildcard:
            return arm_env, arm_mutability_env

        if not self._is_match_enum_type(scrutinee_type):
            if arm.binding is not None:
                raise TypeError("Only enum match arms can bind payload")
            return arm_env, arm_mutability_env

        variant_name, payload_type = self._resolve_match_arm_common(scrutinee_type, arm)
        if arm.binding is not None:
            if payload_type is None:
                raise TypeError(f"Variant '{variant_name}' does not carry payload")
            arm_env[arm.binding] = payload_type
            arm_mutability_env[arm.binding] = False
        return arm_env, arm_mutability_env

    def _get_match_arm_body(self, arm: MatchArmLike) -> MatchBodyLike:
        if isinstance(arm, s.Statement_MatchArm):
            return arm.body
        return arm.expr

    def _infer_match_statement_body(
        self,
        body: MatchBodyLike,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
        fn_ret_type: Type,
    ):
        if isinstance(body, Block):
            self._infer_block(body, env, mutability_env, fn_ret_type)
            return
        expr_type = self._infer_expression(body, env, mutable_env=mutability_env)
        self._assert_raw_pointer_usage_allowed(expr_type, context="match arm expression")

    def _infer_match_expression_body(
        self,
        body: MatchBodyLike,
        env: dict[str, Type],
        mutable_env: dict[str, bool],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        if isinstance(body, Block):
            return self._infer_expression_block(body, env, mutable_env, expected_type)
        return self._infer_expression(body, env, expected_type, mutable_env)

    def _infer_match_nested_body(
        self,
        body: MatchBodyLike,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ):
        if isinstance(body, Block):
            self._infer_expression_block_nested(body, env, mutability_env)
            return
        expr_type = self._infer_expression(body, env, mutable_env=mutability_env)
        self._assert_raw_pointer_usage_allowed(expr_type, context="match arm expression")

    def _infer_expression(
        self,
        expr: s.Statement_Expression,
        env: dict[str, Type],
        expected_type: Optional[Type] = None,
        mutable_env: dict[str, bool] | None = None,
    ) -> Optional[Type]:
        mutable_env = mutable_env or {}

        if isinstance(expr, s.Expression_BooleanLiteral):
            return Type("bool")

        if isinstance(expr, s.Expression_Range):
            range_ctor = s.Expression_Call(
                callee=s.Expression_Path([Type("range_inclusive" if expr.inclusive else "range")]),
                generics=[],
                args=[expr.start, expr.end],
            )
            return self._infer_expression(range_ctor, env, expected_type, mutable_env)

        if isinstance(expr, s.Expression_StringLiteral):
            if expected_type is not None and expected_type != Type("str"):
                raise TypeError(f"Type mismatch: {expected_type} != str")
            return Type("str")

        if isinstance(expr, s.Expression_IntegerLiteral):
            if expr.literal_type is not None:
                if not self._is_integer_type(expr.literal_type) and not self._is_float_type(expr.literal_type):
                    raise TypeError(f"Integer literal suffix must be a numeric type, got {expr.literal_type}")
                if expected_type is not None and not self._types_compatible(expected_type, expr.literal_type):
                    raise TypeError(f"Type mismatch: {expected_type} != {expr.literal_type}")
                return expr.literal_type
            if expected_type is not None and self._is_integer_type(expected_type):
                expr.literal_type = expected_type
                return expected_type
            if expected_type is not None and self._is_float_type(expected_type):
                expr.literal_type = expected_type
                return expected_type
            return Type("i32")

        if isinstance(expr, s.Expression_FloatLiteral):
            if expr.literal_type is not None:
                if not self._is_float_type(expr.literal_type):
                    raise TypeError(f"Float literal suffix must be a float type, got {expr.literal_type}")
                if expected_type is not None and not self._types_compatible(expected_type, expr.literal_type):
                    raise TypeError(f"Type mismatch: {expected_type} != {expr.literal_type}")
                return expr.literal_type
            if expected_type is not None and self._is_float_type(expected_type):
                expr.literal_type = expected_type
                return expected_type
            return Type("f64")

        if isinstance(expr, s.Expression_Try):
            inner_type = self._infer_expression(expr.expr, env, mutable_env=mutable_env)
            if inner_type is None:
                raise TypeError("Unable to infer type of expression used with '?'")

            inner_type = unwrap_for_storage(inner_type)
            base_inner = inner_type.pointee if is_reference_like_type(inner_type) else inner_type
            if _leaf_type_name(base_inner.name) != "Result" or len(base_inner.generics) != 2:
                raise TypeError(f"'?' operator expects Result[T, E], got {inner_type}")

            ok_type, err_type = base_inner.generics
            if self._current_fn_return_type is not None:
                current_fn_ret_type = unwrap_for_storage(self._current_fn_return_type)
                fn_ret_base = (
                    current_fn_ret_type.pointee if is_reference_like_type(current_fn_ret_type) else current_fn_ret_type
                )
                if _leaf_type_name(fn_ret_base.name) != "Result" or len(fn_ret_base.generics) != 2:
                    raise TypeError("'?' operator can only be used in functions returning Result")
                fn_err_type = fn_ret_base.generics[1]
                if fn_err_type != err_type:
                    raise TypeError(f"'?' error type mismatch: function expects {fn_err_type}, got {err_type}")

            if expected_type is not None and ok_type != expected_type:
                raise TypeError(f"Type mismatch: {expected_type} != {ok_type}")
            return ok_type

        if isinstance(expr, s.Expression_Cast):
            if is_dyn_trait_type(expr.target):
                source_type = self._infer_expression(expr.expr, env, mutable_env=mutable_env)
                if source_type is None:
                    raise TypeError(f"Unable to infer source type for cast to '{expr.target}'")

                source_type = unwrap_for_storage(source_type)
                source_base = source_type.pointee if is_reference_like_type(source_type) else source_type
                target_trait = expr.target.generics[0]
                if is_dyn_trait_type(source_base):
                    if not self._trait_satisfies_bound(source_base.generics[0].name, target_trait):
                        raise TypeError(f"Cannot cast '{source_base}' to '{expr.target}'")
                elif not self._type_satisfies_bound(source_base, target_trait):
                    raise TypeError(f"Type '{source_base}' does not implement trait '{target_trait}'")
                return expr.target

            cast_call = s.Expression_MethodCall(
                receiver=expr.expr,
                method="cast",
                generics=[],
                args=[],
            )
            self._infer_expression(cast_call, env, expr.target, mutable_env)
            return expr.target

        if isinstance(expr, s.Expression_Parenthesized):
            return self._infer_expression(expr.expr, env, expected_type, mutable_env)

        if isinstance(expr, s.Expression_TupleLiteral):
            expected_items: list[Type | None] = [None] * len(expr.items)
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_tuple_type(expected_base):
                    if tuple_arity(expected_base) != len(expr.items):
                        raise TypeError(
                            f"Tuple arity mismatch: expected {tuple_arity(expected_base)}, got {len(expr.items)}"
                        )
                    expected_items = list(expected_base.generics)
            item_types: list[Type] = []
            for idx, item in enumerate(expr.items):
                inferred = self._infer_expression(item, env, expected_items[idx], mutable_env)
                if inferred is None:
                    raise TypeError("Unable to infer tuple item type")
                item_types.append(inferred)
            tuple_type = make_tuple_type(item_types)
            if expected_type is not None and tuple_type != expected_type:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if not (is_tuple_type(expected_base) and tuple_type == expected_base):
                    raise TypeError(f"Type mismatch: {expected_type} != {tuple_type}")
            return tuple_type

        if isinstance(expr, s.Expression_ArrayRepeat):
            expected_item: Type | None = None
            expected_size: int | None = None
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_array_type(expected_base):
                    expected_item = expected_base.generics[0]
                    expected_size = array_size(expected_base)
            if expected_size is not None and expected_size != expr.size:
                raise TypeError(f"Array size mismatch: expected {expected_size}, got {expr.size}")
            item_type = self._infer_expression(expr.value, env, expected_item, mutable_env)
            if item_type is None:
                raise TypeError("Unable to infer array repeat item type")
            return make_array_type(item_type, expr.size)

        if isinstance(expr, s.Expression_ArrayLiteral):
            expected_item: Type | None = None
            expected_size: int | None = None
            if expected_type is not None:
                expected_base = unwrap_for_storage(expected_type)
                expected_base = expected_base.pointee if is_reference_like_type(expected_base) else expected_base
                if is_array_type(expected_base):
                    expected_item = expected_base.generics[0]
                    expected_size = array_size(expected_base)
            if expected_size is not None and expected_size != len(expr.items):
                raise TypeError(f"Array size mismatch: expected {expected_size}, got {len(expr.items)}")
            if not expr.items:
                if expected_item is None:
                    raise TypeError("Unable to infer type of empty array literal")
                return make_array_type(expected_item, 0)
            inferred_item: Type | None = None
            for item in expr.items:
                item_type = self._infer_expression(item, env, expected_item or inferred_item, mutable_env)
                if item_type is None:
                    raise TypeError("Unable to infer array item type")
                if inferred_item is None:
                    inferred_item = item_type
                elif item_type != inferred_item:
                    raise TypeError(f"Array item type mismatch: {item_type} != {inferred_item}")
            assert inferred_item is not None
            return make_array_type(inferred_item, len(expr.items))

        if isinstance(expr, s.Expression_Block):
            return self._infer_expression_block(expr, env, mutable_env, expected_type)

        if isinstance(expr, s.Expression_Unsafe):
            self._unsafe_depth += 1
            try:
                return self._infer_expression_block(expr.body, env, mutable_env, expected_type)
            finally:
                self._unsafe_depth -= 1

        if isinstance(expr, s.Expression_If):
            return self._infer_if_expression(expr, env, mutable_env, expected_type)

        if isinstance(expr, s.Expression_Match):
            return self._infer_match_expression(expr, env, mutable_env, expected_type)

        if isinstance(expr, s.Expression_Path):
            if len(expr.segments) == 1:
                if expr.name in env:
                    result = env[expr.name]
                    if (
                        expected_type is not None
                        and is_mutable_type(expected_type)
                        and mutable_env.get(expr.name, False)
                        and not is_mutable_type(result)
                    ):
                        result = make_mutable_type(result)
                    self._assert_raw_pointer_usage_allowed(result, context=f"binding '{expr.name}'")
                    return result
                raise CompileDiagnostic(
                    message=f"Unknown variable '{expr.name}'",
                    line=getattr(expr, "line", None),
                    column=getattr(expr, "column", None),
                    source_line=getattr(expr, "source_line", None),
                    module_id=getattr(expr, "module_id", None),
                )
            if len(expr.segments) == 2 and self._canonical_type_name(expr.segments[0].name) in self._enums:
                return self._infer_enum_path(expr, expected_type)
            return None

        if isinstance(expr, s.Expression_StructInitialization):
            self_hint = self._current_self_binding_type or self._current_impl_self_type
            current_self_type = self._resolve_self_type(self_hint)
            struct_type = self._resolve_self_in_type(expr.name, current_self_type)
            field_types = self._lookup_struct_field_types(struct_type)
            for idx, arg in enumerate(expr.args):
                arg_expected = field_types[idx] if idx < len(field_types) else None
                self._infer_expression(arg, env, arg_expected)
            return struct_type

        if isinstance(expr, s.Expression_StructField):
            result = self._lookup_chained_field_type(expr.name, expr.field, env)
            self._assert_raw_pointer_usage_allowed(result, context=f"field '{expr.field}'")
            return result

        if isinstance(expr, s.Expression_FieldAccess):
            receiver_type = self._infer_expression(expr.receiver, env, mutable_env=mutable_env)
            result = self._lookup_field_type(receiver_type, expr.field)
            self._assert_raw_pointer_usage_allowed(result, context=f"field '{expr.field}'")
            return result

        if isinstance(expr, s.Expression_Index):
            base_type = self._infer_expression(expr.base, env, mutable_env=mutable_env)
            if base_type is None:
                raise TypeError("Unable to infer indexed base type")
            index_type = self._infer_expression(expr.index, env, mutable_env=mutable_env)
            if index_type is not None:
                index_base = unwrap_for_storage(index_type)
                index_base = index_base.pointee if is_reference_like_type(index_base) else index_base
                if not (
                    index_base.name == "usize"
                    or index_base.name == "isize"
                    or (index_base.name.startswith("u") and index_base.name[1:].isdigit())
                    or (index_base.name.startswith("i") and index_base.name[1:].isdigit())
                ):
                    raise TypeError(f"Array index must be integer, got {index_type}")
            base_type = unwrap_for_storage(base_type)
            base_type = base_type.pointee if is_reference_like_type(base_type) else base_type
            if not is_array_type(base_type):
                raise TypeError(f"Indexing is supported only for arrays, got {base_type}")
            result = base_type.generics[0]
            self._assert_raw_pointer_usage_allowed(result, context="index expression")
            return result

        if isinstance(expr, s.Expression_MethodCall):
            receiver_type = self._infer_expression(expr.receiver, env, mutable_env=mutable_env)
            if receiver_type is None:
                raise TypeError(f"Unable to infer receiver type for method call '{expr.method}'")

            call_name, signature = self._resolve_method_signature(receiver_type, expr.method)
            inferred = self._infer_call_signature(
                signature=signature,
                args=[expr.receiver, *expr.args],
                env=env,
                expected_type=expected_type,
                mutable_env=mutable_env,
                explicit_generics=expr.generics,
                callable_name=call_name,
            )
            expr.generics = list(expr.generics)
            self._assert_raw_pointer_usage_allowed(inferred, context=f"method call '{call_name}'")
            return inferred

        if isinstance(expr, s.Expression_Call):
            enum_type = self._infer_enum_call(expr, env, expected_type, mutable_env)
            if enum_type is not None:
                return enum_type

            call_name, explicit_generics, signature = self._resolve_function_call_signature(expr)
            if signature is None:
                call_name, explicit_generics, signature = self._resolve_trait_qualified_call_signature(
                    expr,
                    env,
                    mutable_env,
                )
            if signature is None:
                raise CompileDiagnostic(
                    message=f"Unknown symbol '{call_name}'",
                    line=getattr(expr, "line", None),
                    column=getattr(expr, "column", None),
                    span_length=getattr(expr, "span_length", None),
                    source_line=getattr(expr, "source_line", None),
                    module_id=getattr(expr, "module_id", None),
                )
            result = self._infer_call_signature(
                signature=signature,
                args=expr.args,
                env=env,
                expected_type=expected_type,
                mutable_env=mutable_env,
                explicit_generics=explicit_generics,
                callable_name=call_name,
            )
            if not self._call_uses_owner_generics(expr):
                expr.generics = list(explicit_generics)
            self._assert_raw_pointer_usage_allowed(result, context=f"call '{call_name}'")
            return result

        if isinstance(expr, s.Expression_UnaryOperation):
            operand_type = self._infer_expression(expr.expr, env, expected_type, mutable_env)
            if expr.operator in ("!", "not"):
                if operand_type is not None and not self._is_bool_type(operand_type):
                    raise TypeError(f"Logical unary operator '{expr.operator}' expects bool, got {operand_type}")
                if expected_type is not None and not self._is_bool_type(expected_type):
                    raise TypeError(f"Type mismatch: {expected_type} != bool")
                return Type("bool")
            if expr.operator in ("+", "-", "~", "++", "--"):
                return operand_type or expected_type
            return operand_type or expected_type

        if isinstance(expr, s.Expression_BinaryOperation):
            if expr.operator in ("&&", "||"):
                lhs_type = self._infer_expression(expr.lhs, env, mutable_env=mutable_env)
                rhs_type = self._infer_expression(expr.rhs, env, mutable_env=mutable_env)
                if lhs_type is not None and not self._is_bool_type(lhs_type):
                    raise TypeError(f"Logical operator '{expr.operator}' expects bool lhs, got {lhs_type}")
                if rhs_type is not None and not self._is_bool_type(rhs_type):
                    raise TypeError(f"Logical operator '{expr.operator}' expects bool rhs, got {rhs_type}")
                if expected_type is not None and not self._is_bool_type(expected_type):
                    raise TypeError(f"Type mismatch: {expected_type} != bool")
                return Type("bool")

            comparison_ops = {"==", "!=", "<", "<=", ">", ">="}
            lhs_expected_type = None if expr.operator in comparison_ops else expected_type

            lhs_type = self._infer_expression(expr.lhs, env, lhs_expected_type, mutable_env)
            rhs_expected_type = None
            if (
                expr.operator != "**"
                and lhs_type is not None
                and self._is_numeric_type(lhs_type)
                and self._is_unsuffixed_numeric_literal(expr.rhs)
            ):
                rhs_expected_type = lhs_type
            rhs_type = self._infer_expression(expr.rhs, env, rhs_expected_type, mutable_env)
            if (
                expr.operator != "**"
                and rhs_type is not None
                and self._is_numeric_type(rhs_type)
                and self._is_unsuffixed_numeric_literal(expr.lhs)
            ):
                lhs_type = self._infer_expression(expr.lhs, env, rhs_type, mutable_env)
            if lhs_type is None and rhs_type is not None:
                lhs_type = self._infer_expression(expr.lhs, env, lhs_expected_type or rhs_type, mutable_env)
            self._assert_operator_trait_bound(lhs_type, expr.operator)
            if expr.operator in comparison_ops:
                if expected_type is not None and not self._is_bool_type(expected_type):
                    raise TypeError(f"Type mismatch: {expected_type} != bool")
                return Type("bool")
            return lhs_type or expected_type or rhs_type

        return None

    def _infer_enum_call(
        self,
        expr: s.Expression_Call,
        env: dict[str, Type],
        expected_type: Optional[Type] = None,
        mutable_env: dict[str, bool] | None = None,
    ) -> Optional[Type]:
        mutable_env = mutable_env or {}
        if len(expr.callee.segments) != 2:
            return None

        enum_type = expr.callee.segments[0]
        enum_def = self._enums.get(self._canonical_type_name(enum_type.name))
        if enum_def is None:
            return None

        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, enum_type.generics)}
        expected_base = unwrap_for_storage(expected_type) if expected_type is not None else None
        if expected_base is not None and is_reference_like_type(expected_base):
            expected_base = expected_base.pointee
        if expected_base is not None and self._canonical_type_name(expected_base.name) == self._canonical_type_name(enum_def.name):
            for generic, concrete in zip(enum_def.generics, expected_base.generics):
                generic_mapping.setdefault(generic.name, concrete)

        for variant in enum_def.body:
            if variant.name != expr.callee.segments[1].name:
                continue
            if isinstance(variant, s.TupleStructureDefinition) and variant.fields:
                payload_type = self._specialize_type(variant.fields[0], generic_mapping)
                if expr.args:
                    arg_type = self._infer_expression(expr.args[0], env, payload_type, mutable_env)
                    if arg_type is not None:
                        self._match_generic(variant.fields[0], arg_type, generic_mapping)
        if enum_def.generics:
            missing_generics = [generic.name for generic in enum_def.generics if generic.name not in generic_mapping]
            if missing_generics:
                raise TypeError(
                    f"Unable to infer generics for enum constructor '{enum_def.name}::{expr.callee.segments[1].name}': "
                    f"{', '.join(missing_generics)}"
                )
            enum_type.generics = [generic_mapping[generic.name] for generic in enum_def.generics]
        return enum_type

    def _infer_enum_path(self, expr: s.Expression_Path, expected_type: Optional[Type] = None) -> Type:
        enum_type = expr.segments[0]
        enum_def = self._enums[self._canonical_type_name(enum_type.name)]
        variant_name = expr.segments[1].name
        variant = next((candidate for candidate in enum_def.body if candidate.name == variant_name), None)
        if variant is None:
            raise TypeError(f"Unknown enum variant '{variant_name}' for enum '{enum_def.name}'")
        if isinstance(variant, s.TupleStructureDefinition) and variant.fields:
            raise TypeError(f"Enum variant '{enum_def.name}::{variant_name}' requires payload")

        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, enum_type.generics)}
        expected_base = unwrap_for_storage(expected_type) if expected_type is not None else None
        if expected_base is not None and is_reference_like_type(expected_base):
            expected_base = expected_base.pointee
        if expected_base is not None and self._canonical_type_name(expected_base.name) == self._canonical_type_name(enum_def.name):
            for generic, concrete in zip(enum_def.generics, expected_base.generics):
                generic_mapping.setdefault(generic.name, concrete)

        if enum_def.generics:
            missing_generics = [generic.name for generic in enum_def.generics if generic.name not in generic_mapping]
            if missing_generics:
                raise TypeError(
                    f"Unable to infer generics for enum variant '{enum_def.name}::{variant_name}': "
                    f"{', '.join(missing_generics)}"
                )
            enum_type.generics = [generic_mapping[generic.name] for generic in enum_def.generics]
        return enum_type

    def _collect_generic_bounds(self, generics: list[Type]) -> dict[str, list[Type]]:
        bounds: dict[str, list[Type]] = {}
        for generic in generics:
            if isinstance(generic, s.GenericParam) and generic.bounds:
                bounds[generic.name] = list(generic.bounds)
        return bounds

    def _lookup_active_generic_bounds(self, typ: Type | None) -> list[Type]:
        if typ is None:
            return []
        typ = unwrap_for_storage(typ)
        if is_reference_like_type(typ):
            return self._lookup_active_generic_bounds(typ.pointee)
        if is_raw_pointer_type(typ):
            return self._lookup_active_generic_bounds(typ.pointee)
        return list(self._active_generic_bounds.get(typ.name, []))

    def _is_active_generic_type(self, typ: Type | None) -> bool:
        if typ is None:
            return False
        typ = unwrap_for_storage(typ)
        if is_reference_like_type(typ):
            return self._is_active_generic_type(typ.pointee)
        if is_raw_pointer_type(typ):
            return self._is_active_generic_type(typ.pointee)
        return not typ.generics and typ.name in self._active_generic_names

    def _validate_generic_bounds(
        self,
        generics: list[Type],
        generic_mapping: dict[str, Type],
        callable_name: str,
    ) -> None:
        for generic in generics:
            if not isinstance(generic, s.GenericParam):
                continue
            concrete = generic_mapping.get(generic.name)
            if concrete is None:
                continue
            for bound in generic.bounds:
                if not self._type_satisfies_bound(concrete, bound):
                    raise TypeError(
                        f"Type '{concrete}' does not satisfy bound '{bound}' for generic '{generic.name}' "
                        f"in call '{callable_name}'"
                    )

    def _type_satisfies_bound(self, concrete: Type, bound: Type) -> bool:
        concrete = unwrap_for_storage(concrete)
        if is_reference_like_type(concrete):
            return self._type_satisfies_bound(concrete.pointee, bound)
        if is_raw_pointer_type(concrete):
            return self._type_satisfies_bound(concrete.pointee, bound)
        if is_dyn_trait_type(concrete):
            return self._trait_satisfies_bound(concrete.generics[0].name, bound)

        active_bounds = self._lookup_active_generic_bounds(concrete)
        for active_bound in active_bounds:
            if self._trait_satisfies_bound(active_bound.name, bound):
                return True

        for trait_name in self._impl_traits.get(self._canonical_type_name(concrete.name), []):
            if self._trait_satisfies_bound(trait_name, bound):
                return True

        return False

    def _trait_satisfies_bound(self, trait_name: str, required_bound: Type, seen: set[str] | None = None) -> bool:
        required_name = required_bound.name
        if trait_name == required_name or trait_name.split("::")[-1] == required_name.split("::")[-1]:
            return True

        seen = seen or set()
        if trait_name in seen:
            return False
        seen.add(trait_name)

        trait = self._traits.get(trait_name)
        if trait is None:
            return False

        for base in trait.bases:
            if base.name == required_name or base.name.split("::")[-1] == required_name.split("::")[-1]:
                return True
            if self._trait_satisfies_bound(base.name, required_bound, seen):
                return True
        return False

    def _assert_operator_trait_bound(self, lhs_type: Type | None, operator: str) -> None:
        required_trait = OPERATOR_TRAIT_BOUNDS.get(operator)
        if required_trait is None or lhs_type is None:
            return
        if not self._is_active_generic_type(lhs_type):
            return
        if not self._type_satisfies_bound(lhs_type, Type(required_trait)):
            raise TypeError(f"Operator '{operator}' requires bound '{required_trait}' for generic type '{lhs_type}'")
        return None

    def _contains_unresolved_generic(
        self,
        pattern: Type,
        generic_mapping: dict[str, Type],
        generic_names: set[str],
    ) -> bool:
        pattern = unwrap_for_storage(pattern)
        if is_reference_like_type(pattern):
            return self._contains_unresolved_generic(pattern.pointee, generic_mapping, generic_names)
        if is_raw_pointer_type(pattern):
            return self._contains_unresolved_generic(pattern.pointee, generic_mapping, generic_names)
        if not pattern.generics and pattern.name in generic_names and pattern.name not in generic_mapping:
            return True
        return any(
            self._contains_unresolved_generic(generic, generic_mapping, generic_names) for generic in pattern.generics
        )

    def _resolve_match_arm_payload_type(self, scrutinee_type: Optional[Type], arm: MatchArmLike) -> Optional[Type]:
        if scrutinee_type is None:
            return None
        if not self._is_match_enum_type(scrutinee_type):
            return None
        _, payload_type = self._resolve_match_arm_common(scrutinee_type, arm)
        return payload_type

    def _infer_match_expression(
        self,
        expr: MatchLike,
        env: dict[str, Type],
        mutable_env: dict[str, bool],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        scrutinee_type = self._infer_match_scrutinee(expr, env, mutable_env)
        arm_types: list[Type] = []
        for arm in expr.arms:
            arm_env, arm_mutability_env = self._prepare_match_arm_scope(scrutinee_type, arm, env, mutable_env)
            arm_type = self._infer_match_expression_body(
                self._get_match_arm_body(arm),
                arm_env,
                arm_mutability_env,
                expected_type,
            )
            if arm_type is None:
                raise TypeError("Unable to infer type of match arm")
            arm_types.append(arm_type)

        result_type = expected_type or arm_types[0]
        for arm_type in arm_types:
            if arm_type != result_type:
                raise TypeError(f"Match expression arm type mismatch: {arm_type} != {result_type}")
        return result_type

    def _infer_if_expression(
        self,
        expr: s.Expression_If,
        env: dict[str, Type],
        mutable_env: dict[str, bool],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        branch_types: list[Type] = []

        for branch in expr.branches:
            cond = self._infer_expression(branch.expr, env, Type("bool"), mutable_env)
            if cond is not None and not self._is_bool_type(cond):
                raise TypeError(f"If condition must be bool, got {cond}")

            branch_type = self._infer_expression(branch.body, dict(env), expected_type, dict(mutable_env))
            if branch_type is None:
                raise TypeError("Unable to infer if-expression branch type")
            branch_types.append(branch_type)

        else_type = self._infer_expression(expr.else_body, dict(env), expected_type, dict(mutable_env))
        if else_type is None:
            raise TypeError("Unable to infer else branch type")
        branch_types.append(else_type)

        result_type = expected_type or branch_types[0]
        for branch_type in branch_types:
            if branch_type != result_type:
                raise TypeError(f"If expression branch type mismatch: {branch_type} != {result_type}")
        return result_type

    def _infer_expression_block(
        self,
        block: Block | s.Expression_Block,
        env: dict[str, Type],
        mutable_env: dict[str, bool],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        block_env = dict(env)
        block_mutability_env = dict(mutable_env)
        statements, tail_expr = self._split_expression_block(block)
        for statement in statements:
            self._infer_expression_block_statement(statement, block_env, block_mutability_env)

        return self._infer_expression(tail_expr, block_env, expected_type, block_mutability_env)

    def _split_expression_block(
        self,
        block: Block | s.Expression_Block,
    ) -> tuple[list[s.Statement_InnerLevel], s.Statement_Expression]:
        if isinstance(block, s.Expression_Block):
            return list(block.body), block.expr

        if not block.body:
            raise TypeError("Expression block can not be empty")

        *statements, tail = block.body
        if not isinstance(tail, s.Statement_Expr):
            raise TypeError("Expression block must end with an expression statement")
        return statements, tail.expr

    def _infer_expression_block_statement(
        self,
        statement: s.Statement_InnerLevel,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ):
        try:
            if isinstance(statement, s.Statement_Let):
                inferred = self._infer_expression(statement.expr, env, statement.type, mutability_env)
                if statement.type is None:
                    if inferred is None:
                        raise TypeError(f"Unable to infer type of variable '{statement.name}'")
                    statement.type = inferred
                elif inferred is not None:
                    if not self._types_compatible(statement.type, inferred) and not self._types_match_ignoring_mut(
                        statement.type, inferred
                    ):
                        raise TypeError(
                            f"Type mismatch in let binding '{statement.name}': {statement.type} != {inferred}"
                        )
                    statement.type = self._concretize_type(statement.type, inferred)
                self._assert_raw_pointer_usage_allowed(statement.type, context=f"binding '{statement.name}'")
                env[statement.name] = statement.type
                mutability_env[statement.name] = statement.is_mut
                return

            if isinstance(statement, s.Statement_Assignment):
                self._assert_assignment_target_mutable(statement.target, env, mutability_env)
                expected = self._infer_lvalue_type(statement.target, env)
                value_type = self._infer_expression(statement.expr, env, expected, mutability_env)
                self._assert_raw_pointer_usage_allowed(expected, context="assignment target")
                if (
                    expected is not None
                    and value_type is not None
                    and not self._types_compatible(expected, value_type)
                    and not self._types_match_ignoring_mut(expected, value_type)
                ):
                    raise TypeError(f"Type mismatch in assignment: {expected} != {value_type}")
                return

            if isinstance(statement, s.Statement_Expr):
                expr_type = self._infer_expression(statement.expr, env, mutable_env=mutability_env)
                self._assert_raw_pointer_usage_allowed(expr_type, context="expression statement")
                return

            if isinstance(statement, s.Statement_If):
                for branch in statement.branches:
                    cond = self._infer_expression(branch.expr, env, Type("bool"), mutability_env)
                    if cond is not None and not self._is_bool_type(cond):
                        raise TypeError(f"If condition must be bool, got {cond}")
                    self._infer_expression_block_nested(branch.body, dict(env), dict(mutability_env))
                if statement.else_body is not None:
                    self._infer_expression_block_nested(statement.else_body, dict(env), dict(mutability_env))
                return

            if isinstance(statement, s.Statement_Match):
                scrutinee_type = self._infer_match_scrutinee(statement, env, mutability_env)
                for arm in statement.arms:
                    arm_env, arm_mutability_env = self._prepare_match_arm_scope(
                        scrutinee_type, arm, env, mutability_env
                    )
                    self._infer_match_nested_body(self._get_match_arm_body(arm), arm_env, arm_mutability_env)
                return

            if isinstance(statement, s.Statement_While):
                cond = self._infer_expression(statement.expr, env, Type("bool"), mutability_env)
                if cond is not None and not self._is_bool_type(cond):
                    raise TypeError(f"While condition must be bool, got {cond}")
                self._infer_expression_block_nested(statement.body, dict(env), dict(mutability_env))
                return

            if isinstance(statement, s.Statement_DoWhile):
                self._infer_expression_block_nested(statement.body, dict(env), dict(mutability_env))
                cond = self._infer_expression(statement.expr, env, Type("bool"), mutability_env)
                if cond is not None and not self._is_bool_type(cond):
                    raise TypeError(f"Do-while condition must be bool, got {cond}")
                return

            if isinstance(statement, s.Statement_Loop):
                self._infer_expression_block_nested(statement.body, dict(env), dict(mutability_env))
                return

            if isinstance(statement, s.Statement_Unsafe):
                self._unsafe_depth += 1
                try:
                    self._infer_expression_block_nested(statement.body, dict(env), dict(mutability_env))
                finally:
                    self._unsafe_depth -= 1
                return

            if isinstance(statement, s.Statement_EHIR):
                self._bind_ehir_outputs(statement, env, mutability_env)
                return

            if isinstance(statement, (s.Statement_Ret, s.Statement_Break, s.Statement_Continue)):
                raise TypeError(f"{type(statement).__name__} is not allowed inside expression block")

            raise TypeError(f"Unsupported statement in expression block: {type(statement).__name__}")
        except Exception as exc:
            raise self._diagnostic_for_statement(statement, exc) from exc

    def _bind_ehir_outputs(
        self,
        statement: s.Statement_EHIR,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ):
        for instruction in statement.instructions:
            if not isinstance(instruction, Assignable):
                continue
            if instruction.var_out.type is None:
                raise TypeError(f"EHIR output '{instruction.var_out.name}' must have an explicit type")
            env[instruction.var_out.name] = instruction.var_out.type
            mutability_env[instruction.var_out.name] = True

    def _assert_raw_pointer_usage_allowed(self, typ: Type | None, *, context: str):
        if typ is None or self._unsafe_depth > 0:
            return
        typ = unwrap_for_storage(typ)
        if is_raw_pointer_type(typ):
            raise TypeError(f"Raw pointer {context} can only be used inside unsafe block")

    def _infer_expression_block_nested(
        self,
        body: Block | list[s.Statement_InnerLevel],
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ):
        items = body.body if isinstance(body, Block) else body
        for statement in items:
            self._infer_expression_block_statement(statement, env, mutability_env)

    def _resolve_match_arm_common(self, scrutinee_type: Type, arm: MatchArmLike) -> tuple[str, Optional[Type]]:
        enum_def, generic_mapping = self._resolve_enum_definition(scrutinee_type)
        variant_name = self._resolve_match_variant_name(scrutinee_type, arm.pattern)

        for variant in enum_def.body:
            if variant.name != variant_name:
                continue
            if isinstance(variant, s.TupleStructureDefinition) and variant.fields:
                if len(variant.fields) > 1:
                    raise NotImplementedError(
                        f"Match on tuple enum variant with arity > 1 is not supported: {variant.name}"
                    )
                return variant_name, self._specialize_type(variant.fields[0], generic_mapping)
            return variant_name, None

        raise TypeError(f"Unknown variant '{variant_name}' for enum '{enum_def.name}'")

    def _validate_match_coverage(self, scrutinee_type: Type, arms: list[MatchArmLike]):
        if self._is_builtin_match_type(scrutinee_type):
            self._validate_builtin_match_coverage(scrutinee_type, arms)
            return

        enum_def, _ = self._resolve_enum_definition(scrutinee_type)
        if not arms:
            raise TypeError(f"Match on enum '{enum_def.name}' must have at least one arm")

        seen_variants: set[str] = set()
        wildcard_seen = False
        for idx, arm in enumerate(arms):
            if arm.is_wildcard:
                if arm.binding is not None:
                    raise TypeError("Wildcard match arm cannot bind payload")
                if wildcard_seen:
                    raise TypeError("Duplicate wildcard match arm")
                if idx != len(arms) - 1:
                    raise TypeError("Wildcard match arm must be the last arm")
                wildcard_seen = True
                continue

            variant_name, _ = self._resolve_match_arm_common(scrutinee_type, arm)
            if variant_name in seen_variants:
                raise TypeError(f"Duplicate match arm for variant '{variant_name}'")
            seen_variants.add(variant_name)

        if not wildcard_seen:
            missing = [variant.name for variant in enum_def.body if variant.name not in seen_variants]
            if missing:
                raise TypeError(f"Non-exhaustive match for enum '{enum_def.name}', missing: {', '.join(missing)}")

    def _validate_builtin_match_coverage(self, scrutinee_type: Type, arms: list[MatchArmLike]):
        base_type = self._normalize_match_scrutinee_type(scrutinee_type)
        if not arms:
            raise TypeError(f"Match on '{base_type}' must have at least one arm")

        seen_patterns: set[tuple[str, object]] = set()
        wildcard_seen = False
        for idx, arm in enumerate(arms):
            if arm.is_wildcard:
                if arm.binding is not None:
                    raise TypeError("Wildcard match arm cannot bind payload")
                if wildcard_seen:
                    raise TypeError("Duplicate wildcard match arm")
                if idx != len(arms) - 1:
                    raise TypeError("Wildcard match arm must be the last arm")
                wildcard_seen = True
                continue

            if arm.binding is not None:
                raise TypeError("Only enum match arms can bind payload")

            pattern_key = self._resolve_builtin_match_pattern_key(base_type, arm.pattern)
            if pattern_key in seen_patterns:
                raise TypeError(f"Duplicate match arm for pattern '{arm.pattern}'")
            seen_patterns.add(pattern_key)

        if wildcard_seen:
            return

        if base_type.name == "bool":
            missing: list[str] = []
            if ("bool", True) not in seen_patterns:
                missing.append("true")
            if ("bool", False) not in seen_patterns:
                missing.append("false")
            if missing:
                raise TypeError(f"Non-exhaustive match for bool, missing: {', '.join(missing)}")
            return

        raise TypeError(f"Non-exhaustive match for '{base_type}', add wildcard arm")

    def _resolve_enum_definition(self, typ: Type) -> tuple[s.Statement_EnumDefinition, dict[str, Type]]:
        base_type = self._normalize_match_scrutinee_type(typ)
        enum_def = self._enums.get(self._canonical_type_name(base_type.name))
        if enum_def is None:
            raise TypeError(f"Match expression must be an enum, got {typ}")
        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, base_type.generics)}
        return enum_def, generic_mapping

    def _resolve_match_variant_name(self, scrutinee_type: Type, pattern: MatchPatternLike) -> str:
        if pattern is None:
            raise TypeError("Wildcard arm has no explicit variant name")
        if not isinstance(pattern, s.Expression_Path):
            raise TypeError(f"Enum match expects variant path, got {pattern}")
        if len(pattern.segments) == 1:
            return pattern.segments[0].name
        if len(pattern.segments) != 2:
            raise TypeError(f"Unsupported match pattern: {pattern}")

        base_type = self._normalize_match_scrutinee_type(scrutinee_type)
        explicit_enum = pattern.segments[0]
        if self._canonical_type_name(explicit_enum.name) != self._canonical_type_name(base_type.name):
            raise TypeError(f"Pattern enum '{explicit_enum.name}' does not match scrutinee type '{base_type.name}'")

        if explicit_enum.generics and not self._types_compatible(base_type, explicit_enum):
            raise TypeError(f"Pattern enum '{explicit_enum}' does not match scrutinee type '{base_type}'")
        return pattern.segments[1].name

    def _normalize_match_scrutinee_type(self, typ: Type) -> Type:
        typ = unwrap_for_storage(typ)
        return typ.pointee if is_reference_like_type(typ) else typ

    def _is_match_enum_type(self, typ: Type) -> bool:
        return self._canonical_type_name(self._normalize_match_scrutinee_type(typ).name) in self._enums

    def _is_builtin_match_type(self, typ: Type) -> bool:
        base_type = self._normalize_match_scrutinee_type(typ)
        return (
            base_type.name == "str"
            or base_type.name == "bool"
            or self._is_integer_type(base_type)
            or self._is_float_type(base_type)
        )

    def _resolve_builtin_match_pattern_key(
        self,
        scrutinee_type: Type,
        pattern: MatchPatternLike,
    ) -> tuple[str, object]:
        if pattern is None:
            raise TypeError("Wildcard arm has no explicit pattern")

        base_type = self._normalize_match_scrutinee_type(scrutinee_type)
        if base_type.name == "str":
            if not isinstance(pattern, s.Expression_StringLiteral):
                raise TypeError(f"Match on '{base_type}' expects string literal patterns, got {pattern}")
            return ("str", pattern.value)

        if base_type.name == "bool":
            if not isinstance(pattern, s.Expression_BooleanLiteral):
                raise TypeError(f"Match on '{base_type}' expects bool literal patterns, got {pattern}")
            return ("bool", pattern.value)

        if self._is_integer_type(base_type):
            if not isinstance(pattern, s.Expression_IntegerLiteral):
                raise TypeError(f"Match on '{base_type}' expects integer literal patterns, got {pattern}")
            if pattern.literal_type is not None and not self._types_compatible(base_type, pattern.literal_type):
                raise TypeError(f"Match pattern type mismatch: {pattern.literal_type} != {base_type}")
            return (base_type.name, pattern.value)

        if self._is_float_type(base_type):
            if not isinstance(pattern, s.Expression_FloatLiteral):
                raise TypeError(f"Match on '{base_type}' expects float literal patterns, got {pattern}")
            if pattern.literal_type is not None and not self._types_compatible(base_type, pattern.literal_type):
                raise TypeError(f"Match pattern type mismatch: {pattern.literal_type} != {base_type}")
            return (base_type.name, pattern.value)

        raise TypeError(f"Match expression must be an enum or builtin scalar, got {scrutinee_type}")

    def _lookup_struct_field_types(self, typ: Type) -> list[Type]:
        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        if is_tuple_type(base_type):
            return list(base_type.generics)
        if is_array_type(base_type):
            return [base_type.generics[0] for _ in range(array_size(base_type))]
        struct_def = self._structs.get(self._canonical_type_name(base_type.name))
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return []
        generic_mapping = {generic.name: concrete for generic, concrete in zip(struct_def.generics, base_type.generics)}
        return [self._specialize_type(field.type, generic_mapping) for field in struct_def.fields]

    def _lookup_field_type(self, typ: Optional[Type], field: str) -> Optional[Type]:
        if typ is None:
            return None
        typ = unwrap_for_storage(typ)
        base_type = typ.pointee if is_reference_like_type(typ) else typ
        if is_tuple_type(base_type):
            if field.isdigit():
                idx = int(field)
                return base_type.generics[idx] if 0 <= idx < len(base_type.generics) else None
            return None
        if is_array_type(base_type):
            if field.isdigit():
                idx = int(field)
                return base_type.generics[0] if 0 <= idx < array_size(base_type) else None
            return None
        struct_def = self._structs.get(self._canonical_type_name(base_type.name))
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return None
        generic_mapping = {generic.name: concrete for generic, concrete in zip(struct_def.generics, base_type.generics)}
        for field_param in struct_def.fields:
            if field_param.name == field:
                return self._specialize_type(field_param.type, generic_mapping)
        return None

    def _lookup_chained_field_type(self, base_name: str, field: str, env: dict[str, Type]) -> Optional[Type]:
        parts = base_name.split(".")
        if not parts:
            return None

        base_type = env.get(parts[0])
        for segment in parts[1:]:
            base_type = self._lookup_field_type(base_type, segment)
            if base_type is None:
                return None

        return self._lookup_field_type(base_type, field)

    def _specialize_type(self, typ: Type, generic_mapping: dict[str, Type]) -> Type:
        if is_mutable_type(typ):
            return make_mutable_type(self._specialize_type(unwrap_for_storage(typ), generic_mapping))
        if isinstance(typ, AnySmartPointer):
            return AnySmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if is_raw_pointer_type(typ):
            return Pointer(self._specialize_type(typ.pointee, generic_mapping))
        if not typ.generics and typ.name in generic_mapping:
            return generic_mapping[typ.name]
        return replace(typ, generics=[self._specialize_type(g, generic_mapping) for g in typ.generics])

    def _match_generic(self, pattern: Type, concrete: Type, mapping: dict[str, Type]):
        if is_mutable_type(pattern) and not is_mutable_type(concrete):
            return
        pattern = unwrap_for_storage(pattern)
        concrete = unwrap_for_storage(concrete)

        if isinstance(pattern, AnySmartPointer) and is_reference_like_type(concrete):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        if isinstance(pattern, HeapSmartPointer) and isinstance(concrete, HeapSmartPointer):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        if isinstance(pattern, StackSmartPointer) and isinstance(concrete, StackSmartPointer):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        if is_raw_pointer_type(pattern) and is_raw_pointer_type(concrete):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        canonical_pattern_name = self._canonical_type_name(pattern.name)
        if not pattern.generics and canonical_pattern_name not in self._structs and canonical_pattern_name not in self._enums:
            mapping.setdefault(pattern.name, concrete)
            return
        for lhs, rhs in zip(pattern.generics, concrete.generics):
            self._match_generic(lhs, rhs, mapping)

    def _types_match_ignoring_mut(self, lhs: Type, rhs: Type) -> bool:
        return self._types_compatible(strip_mutability(lhs), strip_mutability(rhs))

    def _types_compatible(self, expected: Type, actual: Type) -> bool:
        if is_mutable_type(expected) and not is_mutable_type(actual):
            return False
        expected = unwrap_for_storage(expected)
        actual = unwrap_for_storage(actual)

        if self._is_bool_type(expected) or self._is_bool_type(actual):
            return self._is_bool_type(expected) and self._is_bool_type(actual)

        if isinstance(expected, AnySmartPointer):
            if not is_reference_like_type(actual):
                return False
            return self._types_compatible(expected.pointee, actual.pointee)

        if isinstance(expected, HeapSmartPointer):
            return isinstance(actual, HeapSmartPointer) and self._types_compatible(expected.pointee, actual.pointee)

        if isinstance(expected, StackSmartPointer):
            return isinstance(actual, StackSmartPointer) and self._types_compatible(expected.pointee, actual.pointee)

        if is_raw_pointer_type(expected):
            return is_raw_pointer_type(actual) and self._types_compatible(expected.pointee, actual.pointee)

        if is_reference_like_type(actual):
            return False
        if is_raw_pointer_type(actual):
            return False

        if is_dyn_trait_type(expected) or is_dyn_trait_type(actual):
            if not (is_dyn_trait_type(expected) and is_dyn_trait_type(actual)):
                return False
            return self._trait_satisfies_bound(actual.generics[0].name, expected.generics[0])

        if self._can_widen_primitive(actual, expected):
            return True

        if self._canonical_type_name(expected.name) != self._canonical_type_name(actual.name):
            return False
        if len(expected.generics) != len(actual.generics):
            return False
        return all(self._types_compatible(lhs, rhs) for lhs, rhs in zip(expected.generics, actual.generics))

    def _can_widen_primitive(self, actual: Type, expected: Type) -> bool:
        if self._is_unsigned_integer_type(actual) and self._is_unsigned_integer_type(expected):
            return self._integer_bits(actual) <= self._integer_bits(expected)
        if self._is_signed_integer_type(actual) and self._is_signed_integer_type(expected):
            return self._integer_bits(actual) <= self._integer_bits(expected)
        if self._is_float_type(actual) and self._is_float_type(expected):
            return self._float_bits(actual) <= self._float_bits(expected)
        return False

    def _concretize_type(self, pattern: Type, concrete: Type) -> Type:
        pattern_is_mut = is_mutable_type(pattern)
        concrete_is_mut = is_mutable_type(concrete)
        pattern = unwrap_for_storage(pattern)
        concrete = unwrap_for_storage(concrete)

        if isinstance(pattern, AnySmartPointer):
            if isinstance(concrete, (HeapSmartPointer, StackSmartPointer)):
                return make_mutable_type(concrete) if pattern_is_mut or concrete_is_mut else concrete
            if isinstance(concrete, AnySmartPointer):
                result = AnySmartPointer(self._concretize_type(pattern.pointee, concrete.pointee))
                return make_mutable_type(result) if pattern_is_mut or concrete_is_mut else result
            return make_mutable_type(pattern) if pattern_is_mut else pattern

        if isinstance(pattern, HeapSmartPointer) and isinstance(concrete, HeapSmartPointer):
            result = HeapSmartPointer(self._concretize_type(pattern.pointee, concrete.pointee))
            return make_mutable_type(result) if pattern_is_mut or concrete_is_mut else result

        if isinstance(pattern, StackSmartPointer) and isinstance(concrete, StackSmartPointer):
            result = StackSmartPointer(self._concretize_type(pattern.pointee, concrete.pointee))
            return make_mutable_type(result) if pattern_is_mut or concrete_is_mut else result

        if is_raw_pointer_type(pattern) and is_raw_pointer_type(concrete):
            result = Pointer(self._concretize_type(pattern.pointee, concrete.pointee))
            return make_mutable_type(result) if pattern_is_mut or concrete_is_mut else result

        if len(pattern.generics) != len(concrete.generics) or not pattern.generics:
            return make_mutable_type(pattern) if pattern_is_mut or concrete_is_mut else pattern

        result = replace(
            pattern,
            generics=[self._concretize_type(lhs, rhs) for lhs, rhs in zip(pattern.generics, concrete.generics)],
        )
        return make_mutable_type(result) if pattern_is_mut or concrete_is_mut else result

    def _assert_assignment_target_mutable(
        self,
        target: s.Statement_Expression,
        env: dict[str, Type],
        mutability_env: dict[str, bool],
    ):
        if isinstance(target, s.Expression_Path) and len(target.segments) == 1:
            if mutability_env.get(target.name, False):
                return
            raise TypeError(f"Cannot assign to immutable binding '{target.name}'. Use `let mut {target.name}`.")

        if not isinstance(target, s.Expression_StructField):
            return

        binding_name = target.name.split(".")[0]
        binding_type = env.get(binding_name)
        if binding_type is None and binding_name == "self":
            binding_type = self._current_self_binding_type
        if binding_type is not None and is_mutable_type(binding_type):
            return

        raise TypeError(f"Cannot assign through immutable access '{binding_name}'. Use a `mut` type.")

    @staticmethod
    def _is_integer_type(typ: Type) -> bool:
        typ = unwrap_for_storage(typ)
        return typ.name in ("usize", "isize") or (
            len(typ.name) > 1 and typ.name[0] in ("u", "i") and typ.name[1:].isdigit()
        )

    @staticmethod
    def _is_bool_type(typ: Type) -> bool:
        typ = unwrap_for_storage(typ)
        return typ.name in {"bool", "u1"}

    @staticmethod
    def _is_unsigned_integer_type(typ: Type) -> bool:
        typ = unwrap_for_storage(typ)
        return typ.name == "usize" or (len(typ.name) > 1 and typ.name[0] == "u" and typ.name[1:].isdigit())

    @staticmethod
    def _is_signed_integer_type(typ: Type) -> bool:
        typ = unwrap_for_storage(typ)
        return typ.name == "isize" or (len(typ.name) > 1 and typ.name[0] == "i" and typ.name[1:].isdigit())

    @staticmethod
    def _integer_bits(typ: Type) -> int:
        typ = unwrap_for_storage(typ)
        if typ.name in ("usize", "isize"):
            return 64
        return int(typ.name[1:])

    @staticmethod
    def _is_float_type(typ: Type) -> bool:
        typ = unwrap_for_storage(typ)
        return len(typ.name) > 1 and typ.name[0] == "f" and typ.name[1:].isdigit()

    @staticmethod
    def _float_bits(typ: Type) -> int:
        typ = unwrap_for_storage(typ)
        return int(typ.name[1:])
