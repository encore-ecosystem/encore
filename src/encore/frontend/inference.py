from dataclasses import replace
from typing import Optional

from ehir.core.type import HeapSmartPointer, StackSmartPointer, Type

from encore.frontend.parser import statements as s
from encore.frontend.parser.statements import Block

MatchArmLike = s.Statement_MatchArm | s.Expression_MatchArm


class TypeInferer:
    def __init__(self):
        self._funcs: dict[str, s.Statement_FunctionDefinition] = {}
        self._structs: dict[str, s.Statement_StructureDefinition] = {}
        self._enums: dict[str, s.Statement_EnumDefinition] = {}
        self._traits: dict[str, s.Statement_Trait] = {}
        self._unsafe_depth = 0
        self._current_fn_return_type: Type | None = None

    def infer(
        self,
        ast: list[s.Statement],
        imported_declarations: list[s.Statement_TopLevel] | None = None,
    ) -> list[s.Statement]:
        imported_declarations = imported_declarations or []
        self._collect_declarations(imported_declarations)
        self._collect_declarations(ast)

        for statement in ast:
            if isinstance(statement, s.Statement_FunctionDefinition):
                self._infer_function(statement)
            elif isinstance(statement, s.Statement_Impl):
                for method in statement.body:
                    self._infer_function(method)

        return ast

    def _collect_declarations(self, statements: list[s.Statement]):
        for statement in statements:
            if isinstance(statement, s.Statement_FunctionDefinition):
                self._funcs[statement.signature.name] = statement
            elif isinstance(statement, s.Statement_StructureDefinition):
                self._structs[statement.signature.name] = statement
            elif isinstance(statement, s.Statement_EnumDefinition):
                self._enums[statement.name] = statement
            elif isinstance(statement, s.Statement_Trait):
                self._traits[statement.name] = statement
            elif isinstance(statement, s.Statement_Impl) and statement.trait_name is None:
                struct_name = statement.struct.name
                for method in statement.body:
                    method_generic_names = {generic.name for generic in statement.generics}
                    merged_generics = [*statement.generics]
                    for generic in method.generics:
                        if generic.name in method_generic_names:
                            continue
                        merged_generics.append(generic)
                        method_generic_names.add(generic.name)
                    self._funcs[f"{struct_name}::{method.name}"] = replace(method, generics=merged_generics)

    def _infer_function(self, statement: s.Statement_FunctionDefinition):
        env = {param.name: param.type for param in statement.signature.params}

        prev_fn_return = self._current_fn_return_type
        if statement.signature.type is None:
            statement.signature.type = self._infer_return_type(statement.body, env)
            if statement.type is None:
                raise TypeError(f"Unable to infer return type for function '{statement.name}'")

        self._current_fn_return_type = statement.signature.type
        try:
            self._infer_block(statement.body, env, statement.signature.type)
        finally:
            self._current_fn_return_type = prev_fn_return

    def _infer_block(self, body: Block, env: dict[str, Type], fn_ret_type: Type):
        for statement in body.body:
            if isinstance(statement, s.Statement_Let):
                inferred = self._infer_expression(statement.expr, env, statement.type)
                if statement.type is None:
                    if inferred is None:
                        raise TypeError(f"Unable to infer type of variable '{statement.name}'")
                    statement.type = inferred
                elif inferred is not None and statement.type != inferred:
                    raise TypeError(f"Type mismatch in let binding '{statement.name}': {statement.type} != {inferred}")
                env[statement.name] = statement.type
            elif isinstance(statement, s.Statement_Assignment):
                expected = self._infer_lvalue_type(statement.target, env)
                value_type = self._infer_expression(statement.expr, env, expected)
                if expected is not None and value_type is not None and expected != value_type:
                    raise TypeError(f"Type mismatch in assignment: {expected} != {value_type}")
            elif isinstance(statement, s.Statement_Expr):
                self._infer_expression(statement.expr, env)
            elif isinstance(statement, s.Statement_Ret):
                ret_type = self._infer_expression(statement.expr, env, fn_ret_type)
                if ret_type is not None and ret_type != fn_ret_type:
                    raise TypeError(f"Return type mismatch: {ret_type} != {fn_ret_type}")
            elif isinstance(statement, s.Statement_While):
                cond = self._infer_expression(statement.expr, env, Type("bool"))
                if cond is not None and cond != Type("bool"):
                    raise TypeError(f"While condition must be bool, got {cond}")
                self._infer_block(statement.body, dict(env), fn_ret_type)
            elif isinstance(statement, s.Statement_DoWhile):
                self._infer_block(statement.body, dict(env), fn_ret_type)
                cond = self._infer_expression(statement.expr, env, Type("bool"))
                if cond is not None and cond != Type("bool"):
                    raise TypeError(f"Do-while condition must be bool, got {cond}")
            elif isinstance(statement, s.Statement_Loop):
                self._infer_block(statement.body, dict(env), fn_ret_type)
            elif isinstance(statement, s.Statement_If):
                for branch in statement.branches:
                    cond = self._infer_expression(branch.expr, env, Type("bool"))
                    if cond is not None and cond != Type("bool"):
                        raise TypeError(f"If condition must be bool, got {cond}")
                    self._infer_block(branch.body, dict(env), fn_ret_type)
                if statement.else_body is not None:
                    self._infer_block(statement.else_body, dict(env), fn_ret_type)
            elif isinstance(statement, s.Statement_Match):
                self._infer_match(statement, env, fn_ret_type)
            elif isinstance(statement, s.Statement_Unsafe):
                self._unsafe_depth += 1
                try:
                    self._infer_block(statement.body, dict(env), fn_ret_type)
                finally:
                    self._unsafe_depth -= 1

    def _infer_return_type(self, body: list[s.Statement_InnerLevel], env: dict[str, Type]) -> Optional[Type]:
        types: list[Type] = []
        for statement in body:
            if isinstance(statement, s.Statement_Let):
                inferred = self._infer_expression(statement.expr, env, statement.type)
                if inferred is not None:
                    if statement.type is None:
                        statement.type = inferred
                    env[statement.name] = statement.type
            if isinstance(statement, s.Statement_Ret):
                ret_type = self._infer_expression(statement.expr, env)
                if ret_type is not None:
                    types.append(ret_type)
            elif isinstance(statement, s.Statement_Expr):
                self._infer_expression(statement.expr, env)
            elif isinstance(statement, s.Statement_While):
                nested = self._infer_return_type(statement.body, dict(env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_DoWhile):
                nested = self._infer_return_type(statement.body, dict(env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_Loop):
                nested = self._infer_return_type(statement.body, dict(env))
                if nested is not None:
                    types.append(nested)
            elif isinstance(statement, s.Statement_If):
                for branch in statement.branches:
                    nested = self._infer_return_type(branch.body, dict(env))
                    if nested is not None:
                        types.append(nested)
                if statement.else_body is not None:
                    nested = self._infer_return_type(statement.else_body, dict(env))
                    if nested is not None:
                        types.append(nested)
            elif isinstance(statement, s.Statement_Match):
                scrutinee_type = self._infer_expression(statement.expr, env)
                for arm in statement.arms:
                    arm_env = dict(env)
                    payload_type = self._resolve_match_arm_payload_type(scrutinee_type, arm)
                    if arm.binding is not None and payload_type is not None:
                        arm_env[arm.binding] = payload_type
                    nested = self._infer_return_type(arm.body, arm_env)
                    if nested is not None:
                        types.append(nested)
            elif isinstance(statement, s.Statement_Unsafe):
                self._unsafe_depth += 1
                try:
                    nested = self._infer_return_type(statement.body, dict(env))
                finally:
                    self._unsafe_depth -= 1
                if nested is not None:
                    types.append(nested)

        if not types:
            return None
        first = types[0]
        for typ in types[1:]:
            if typ != first:
                raise TypeError(f"Unable to infer a single return type: {first} != {typ}")
        return first

    def _infer_lvalue_type(self, expr: s.Statement_Expression, env: dict[str, Type]) -> Optional[Type]:
        if isinstance(expr, s.Expression_Path) and len(expr.segments) == 1:
            return env.get(expr.name)
        if isinstance(expr, s.Expression_StructField):
            return self._lookup_chained_field_type(expr.name, expr.field, env)
        return None

    def _infer_match(self, statement: s.Statement_Match, env: dict[str, Type], fn_ret_type: Type):
        scrutinee_type = self._infer_expression(statement.expr, env)
        if scrutinee_type is None:
            raise TypeError("Unable to infer type of match expression")
        self._validate_match_coverage(scrutinee_type, statement.arms)

        for arm in statement.arms:
            if arm.is_wildcard:
                self._infer_block(arm.body, dict(env), fn_ret_type)
                continue

            variant_name, payload_type = self._resolve_match_arm(scrutinee_type, arm)

            arm_env = dict(env)
            if arm.binding is not None:
                if payload_type is None:
                    raise TypeError(f"Variant '{variant_name}' does not carry payload")
                arm_env[arm.binding] = payload_type
            elif payload_type is not None:
                # Payload-less matching is allowed; no binding is introduced.
                pass
            self._infer_block(arm.body, arm_env, fn_ret_type)

    def _infer_expression(
        self,
        expr: s.Statement_Expression,
        env: dict[str, Type],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        if isinstance(expr, s.Expression_BooleanLiteral):
            return Type("bool")

        if isinstance(expr, s.Expression_StringLiteral):
            if expected_type is not None and expected_type != Type("str"):
                raise TypeError(f"Type mismatch: {expected_type} != str")
            return Type("str")

        if isinstance(expr, s.Expression_IntegerLiteral):
            if expr.literal_type is not None:
                if not self._is_integer_type(expr.literal_type):
                    raise TypeError(f"Integer literal suffix must be an integer type, got {expr.literal_type}")
                if expected_type is not None and expected_type != expr.literal_type:
                    raise TypeError(f"Type mismatch: {expected_type} != {expr.literal_type}")
                return expr.literal_type
            if expected_type is not None and self._is_integer_type(expected_type):
                expr.literal_type = expected_type
                return expected_type
            return Type("i32")

        if isinstance(expr, s.Expression_FloatLiteral):
            if expr.literal_type is not None:
                if not self._is_float_type(expr.literal_type):
                    raise TypeError(f"Float literal suffix must be a float type, got {expr.literal_type}")
                if expected_type is not None and expected_type != expr.literal_type:
                    raise TypeError(f"Type mismatch: {expected_type} != {expr.literal_type}")
                return expr.literal_type
            if expected_type is not None and self._is_float_type(expected_type):
                expr.literal_type = expected_type
                return expected_type
            return Type("f64")

        if isinstance(expr, s.Expression_Try):
            inner_type = self._infer_expression(expr.expr, env)
            if inner_type is None:
                raise TypeError("Unable to infer type of expression used with '?'")

            base_inner = (
                inner_type.pointee if isinstance(inner_type, (HeapSmartPointer, StackSmartPointer)) else inner_type
            )
            if base_inner.name != "Result" or len(base_inner.generics) != 2:
                raise TypeError(f"'?' operator expects Result[T, E], got {inner_type}")

            ok_type, err_type = base_inner.generics
            if self._current_fn_return_type is not None:
                fn_ret_base = (
                    self._current_fn_return_type.pointee
                    if isinstance(self._current_fn_return_type, (HeapSmartPointer, StackSmartPointer))
                    else self._current_fn_return_type
                )
                if fn_ret_base.name != "Result" or len(fn_ret_base.generics) != 2:
                    raise TypeError("'?' operator can only be used in functions returning Result")
                fn_err_type = fn_ret_base.generics[1]
                if fn_err_type != err_type:
                    raise TypeError(f"'?' error type mismatch: function expects {fn_err_type}, got {err_type}")

            if expected_type is not None and ok_type != expected_type:
                raise TypeError(f"Type mismatch: {expected_type} != {ok_type}")
            return ok_type

        if isinstance(expr, s.Expression_Parenthesized):
            return self._infer_expression(expr.expr, env, expected_type)

        if isinstance(expr, s.Expression_Block):
            return self._infer_expression_block(expr, env, expected_type)

        if isinstance(expr, s.Expression_Unsafe):
            self._unsafe_depth += 1
            try:
                return self._infer_expression_block(expr.body, env, expected_type)
            finally:
                self._unsafe_depth -= 1

        if isinstance(expr, s.Expression_If):
            return self._infer_if_expression(expr, env, expected_type)

        if isinstance(expr, s.Expression_Match):
            return self._infer_match_expression(expr, env, expected_type)

        if isinstance(expr, s.Expression_Path):
            if len(expr.segments) == 1:
                return env.get(expr.name, expr.segments[0])
            if len(expr.segments) == 2 and expr.segments[0].name in self._enums:
                return expr.segments[0]
            return None

        if isinstance(expr, s.Expression_StructInitialization):
            field_types = self._lookup_struct_field_types(expr.name)
            for idx, arg in enumerate(expr.args):
                arg_expected = field_types[idx] if idx < len(field_types) else None
                self._infer_expression(arg, env, arg_expected)
            return expr.name

        if isinstance(expr, s.Expression_StructField):
            return self._lookup_chained_field_type(expr.name, expr.field, env)

        if isinstance(expr, s.Expression_MethodCall):
            receiver_type = self._infer_expression(expr.receiver, env)
            if receiver_type is None:
                raise TypeError(f"Unable to infer receiver type for method call '{expr.method}'")

            base_receiver_type = (
                receiver_type.pointee
                if isinstance(receiver_type, (HeapSmartPointer, StackSmartPointer))
                else receiver_type
            )
            fn_name = f"{base_receiver_type.name}::{expr.method}"
            if fn_name not in self._funcs:
                raise TypeError(f"Method '{expr.method}' is not defined for type '{base_receiver_type.name}'")

            desugared = s.Expression_Call(
                callee=s.Expression_Path([Type(fn_name)]),
                generics=list(expr.generics),
                args=[expr.receiver, *expr.args],
            )
            inferred = self._infer_expression(desugared, env, expected_type)
            expr.generics = desugared.generics
            return inferred

        if isinstance(expr, s.Expression_Call):
            enum_type = self._infer_enum_call(expr, env)
            if enum_type is not None:
                return enum_type

            fn = self._funcs.get(expr.name)
            if fn is None:
                return None
            if isinstance(fn, s.FunctionSignature) and self._unsafe_depth <= 0:
                raise TypeError(f"Extern function '{fn.name}' can only be called inside unsafe block")

            generic_mapping: dict[str, Type] = {}
            if expr.generics:
                if len(expr.generics) != len(fn.signature.generics):
                    raise TypeError(
                        f"Generic count mismatch for function '{fn.signature.name}': {len(expr.generics)} != {len(fn.signature.generics)}"
                    )
                generic_mapping = {
                    generic.name: concrete for generic, concrete in zip(fn.signature.generics, expr.generics)
                }

            for param, arg in zip(fn.signature.params, expr.args):
                expected_param_type = self._specialize_type(param.type, generic_mapping)
                arg_type = self._infer_expression(arg, env, expected_param_type)
                if arg_type is not None:
                    self._match_generic(param.type, arg_type, generic_mapping)

            if fn.signature.generics:
                missing_generics = [
                    generic.name for generic in fn.signature.generics if generic.name not in generic_mapping
                ]
                if missing_generics:
                    raise TypeError(
                        f"Unable to infer generics for function '{fn.signature.name}': {', '.join(missing_generics)}"
                    )
                expr.generics = [generic_mapping[generic.name] for generic in fn.signature.generics]
            if fn.signature.type is None:
                return None
            return self._specialize_type(fn.signature.type, generic_mapping)

        if isinstance(expr, s.Expression_BinaryOperation):
            if expr.operator in ("&&", "||"):
                lhs_type = self._infer_expression(expr.lhs, env)
                rhs_type = self._infer_expression(expr.rhs, env)
                if lhs_type is not None and lhs_type != Type("bool"):
                    raise TypeError(f"Logical operator '{expr.operator}' expects bool lhs, got {lhs_type}")
                if rhs_type is not None and rhs_type != Type("bool"):
                    raise TypeError(f"Logical operator '{expr.operator}' expects bool rhs, got {rhs_type}")
                if expected_type is not None and expected_type != Type("bool"):
                    raise TypeError(f"Type mismatch: {expected_type} != bool")
                return Type("bool")

            lhs_type = self._infer_expression(expr.lhs, env, expected_type)
            rhs_type = self._infer_expression(expr.rhs, env, lhs_type or expected_type)
            if lhs_type is None and rhs_type is not None:
                lhs_type = self._infer_expression(expr.lhs, env, rhs_type)
            if expr.operator in ("==", "!=", "<", "<=", ">", ">="):
                return Type("bool")
            return lhs_type or rhs_type or expected_type

        return None

    def _infer_enum_call(self, expr: s.Expression_Call, env: dict[str, Type]) -> Optional[Type]:
        if len(expr.callee.segments) != 2:
            return None

        enum_type = expr.callee.segments[0]
        enum_def = self._enums.get(enum_type.name)
        if enum_def is None:
            return None

        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, enum_type.generics)}
        for variant in enum_def.body:
            if variant.name != expr.callee.segments[1].name:
                continue
            if isinstance(variant, s.TupleStructureDefinition) and variant.fields:
                payload_type = self._specialize_type(variant.fields[0], generic_mapping)
                if expr.args:
                    self._infer_expression(expr.args[0], env, payload_type)
            return enum_type
        return None

    def _resolve_match_arm_payload_type(
        self, scrutinee_type: Optional[Type], arm: s.Statement_MatchArm
    ) -> Optional[Type]:
        if scrutinee_type is None:
            return None
        _, payload_type = self._resolve_match_arm(scrutinee_type, arm)
        return payload_type

    def _infer_match_expression(
        self,
        expr: s.Expression_Match,
        env: dict[str, Type],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        scrutinee_type = self._infer_expression(expr.expr, env)
        if scrutinee_type is None:
            raise TypeError("Unable to infer type of match expression")
        self._validate_match_coverage(scrutinee_type, expr.arms)
        arm_types: list[Type] = []
        for arm in expr.arms:
            if arm.is_wildcard:
                arm_type = self._infer_expression(arm.expr, dict(env), expected_type)
                if arm_type is None:
                    raise TypeError("Unable to infer wildcard match arm type")
                arm_types.append(arm_type)
                continue

            variant_name, payload_type = self._resolve_match_arm(scrutinee_type, arm)

            arm_env = dict(env)
            if arm.binding is not None:
                if payload_type is None:
                    raise TypeError(f"Variant '{variant_name}' does not carry payload")
                arm_env[arm.binding] = payload_type

            arm_type = self._infer_expression(arm.expr, arm_env, expected_type)
            if arm_type is None:
                raise TypeError(f"Unable to infer type of match arm '{variant_name}'")
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
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        branch_types: list[Type] = []

        for branch in expr.branches:
            cond = self._infer_expression(branch.expr, env, Type("bool"))
            if cond is not None and cond != Type("bool"):
                raise TypeError(f"If condition must be bool, got {cond}")

            branch_type = self._infer_expression(branch.body, dict(env), expected_type)
            if branch_type is None:
                raise TypeError("Unable to infer if-expression branch type")
            branch_types.append(branch_type)

        else_type = self._infer_expression(expr.else_body, dict(env), expected_type)
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
        block: Block,
        env: dict[str, Type],
        expected_type: Optional[Type] = None,
    ) -> Optional[Type]:
        block_env = dict(env)
        for statement in block.body[:-1]:
            self._infer_expression_block_statement(statement, block_env)

        return self._infer_expression(block.body[-1], block_env, expected_type)

    def _infer_expression_block_statement(self, statement: s.Statement_InnerLevel, env: dict[str, Type]):
        if isinstance(statement, s.Statement_Let):
            inferred = self._infer_expression(statement.expr, env, statement.type)
            if statement.type is None:
                if inferred is None:
                    raise TypeError(f"Unable to infer type of variable '{statement.name}'")
                statement.type = inferred
            elif inferred is not None and statement.type != inferred:
                raise TypeError(f"Type mismatch in let binding '{statement.name}': {statement.type} != {inferred}")
            env[statement.name] = statement.type
            return

        if isinstance(statement, s.Statement_Assignment):
            expected = self._infer_lvalue_type(statement.target, env)
            value_type = self._infer_expression(statement.expr, env, expected)
            if expected is not None and value_type is not None and expected != value_type:
                raise TypeError(f"Type mismatch in assignment: {expected} != {value_type}")
            return

        if isinstance(statement, s.Statement_Expr):
            self._infer_expression(statement.expr, env)
            return

        if isinstance(statement, s.Statement_If):
            for branch in statement.branches:
                cond = self._infer_expression(branch.expr, env, Type("bool"))
                if cond is not None and cond != Type("bool"):
                    raise TypeError(f"If condition must be bool, got {cond}")
                self._infer_expression_block_nested(branch.body, dict(env))
            if statement.else_body is not None:
                self._infer_expression_block_nested(statement.else_body, dict(env))
            return

        if isinstance(statement, s.Statement_Match):
            scrutinee_type = self._infer_expression(statement.expr, env)
            if scrutinee_type is None:
                raise TypeError("Unable to infer type of match expression")
            self._validate_match_coverage(scrutinee_type, statement.arms)
            for arm in statement.arms:
                arm_env = dict(env)
                if not arm.is_wildcard:
                    variant_name, payload_type = self._resolve_match_arm(scrutinee_type, arm)
                    if arm.binding is not None:
                        if payload_type is None:
                            raise TypeError(f"Variant '{variant_name}' does not carry payload")
                        arm_env[arm.binding] = payload_type
                self._infer_expression_block_nested(arm.body, arm_env)
            return

        if isinstance(statement, s.Statement_While):
            cond = self._infer_expression(statement.expr, env, Type("bool"))
            if cond is not None and cond != Type("bool"):
                raise TypeError(f"While condition must be bool, got {cond}")
            self._infer_expression_block_nested(statement.body, dict(env))
            return

        if isinstance(statement, s.Statement_DoWhile):
            self._infer_expression_block_nested(statement.body, dict(env))
            cond = self._infer_expression(statement.expr, env, Type("bool"))
            if cond is not None and cond != Type("bool"):
                raise TypeError(f"Do-while condition must be bool, got {cond}")
            return

        if isinstance(statement, s.Statement_Loop):
            self._infer_expression_block_nested(statement.body, dict(env))
            return

        if isinstance(statement, s.Statement_Unsafe):
            self._unsafe_depth += 1
            try:
                self._infer_expression_block_nested(statement.body, dict(env))
            finally:
                self._unsafe_depth -= 1
            return

        if isinstance(statement, (s.Statement_Ret, s.Statement_Break, s.Statement_Continue)):
            raise TypeError(f"{type(statement).__name__} is not allowed inside expression block")

        raise TypeError(f"Unsupported statement in expression block: {type(statement).__name__}")

    def _infer_expression_block_nested(self, body: list[s.Statement_InnerLevel], env: dict[str, Type]):
        for statement in body:
            self._infer_expression_block_statement(statement, env)

    def _resolve_match_arm(self, scrutinee_type: Type, arm: s.Statement_MatchArm) -> tuple[str, Optional[Type]]:
        if arm.is_wildcard:
            raise TypeError("Wildcard arm has no variant")
        return self._resolve_match_arm_common(scrutinee_type, arm)

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

    def _resolve_enum_definition(self, typ: Type) -> tuple[s.Statement_EnumDefinition, dict[str, Type]]:
        base_type = typ.pointee if isinstance(typ, (HeapSmartPointer, StackSmartPointer)) else typ
        enum_def = self._enums.get(base_type.name)
        if enum_def is None:
            raise TypeError(f"Match expression must be an enum, got {typ}")
        generic_mapping = {generic.name: concrete for generic, concrete in zip(enum_def.generics, base_type.generics)}
        return enum_def, generic_mapping

    def _resolve_match_variant_name(self, scrutinee_type: Type, pattern: s.Expression_Path | None) -> str:
        if pattern is None:
            raise TypeError("Wildcard arm has no explicit variant name")
        if len(pattern.segments) == 1:
            return pattern.segments[0].name
        if len(pattern.segments) != 2:
            raise TypeError(f"Unsupported match pattern: {pattern}")

        base_type = (
            scrutinee_type.pointee
            if isinstance(scrutinee_type, (HeapSmartPointer, StackSmartPointer))
            else scrutinee_type
        )
        explicit_enum = pattern.segments[0]
        if explicit_enum.name != base_type.name:
            raise TypeError(f"Pattern enum '{explicit_enum.name}' does not match scrutinee type '{base_type.name}'")
        if explicit_enum.generics and explicit_enum != base_type:
            raise TypeError(f"Pattern enum '{explicit_enum}' does not match scrutinee type '{base_type}'")
        return pattern.segments[1].name

    def _lookup_struct_field_types(self, typ: Type) -> list[Type]:
        base_type = typ.pointee if isinstance(typ, (HeapSmartPointer, StackSmartPointer)) else typ
        struct_def = self._structs.get(base_type.name)
        if not isinstance(struct_def, s.CLikeStructureDefinition):
            return []
        generic_mapping = {generic.name: concrete for generic, concrete in zip(struct_def.generics, base_type.generics)}
        return [self._specialize_type(field.type, generic_mapping) for field in struct_def.fields]

    def _lookup_field_type(self, typ: Optional[Type], field: str) -> Optional[Type]:
        if typ is None:
            return None
        base_type = typ.pointee if isinstance(typ, (HeapSmartPointer, StackSmartPointer)) else typ
        struct_def = self._structs.get(base_type.name)
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
        if isinstance(typ, HeapSmartPointer):
            return HeapSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if isinstance(typ, StackSmartPointer):
            return StackSmartPointer(self._specialize_type(typ.pointee, generic_mapping))
        if not typ.generics and typ.name in generic_mapping:
            return generic_mapping[typ.name]
        return replace(typ, generics=[self._specialize_type(g, generic_mapping) for g in typ.generics])

    def _match_generic(self, pattern: Type, concrete: Type, mapping: dict[str, Type]):
        if isinstance(pattern, HeapSmartPointer) and isinstance(concrete, HeapSmartPointer):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        if isinstance(pattern, StackSmartPointer) and isinstance(concrete, StackSmartPointer):
            self._match_generic(pattern.pointee, concrete.pointee, mapping)
            return
        if not pattern.generics and pattern.name not in self._structs and pattern.name not in self._enums:
            mapping.setdefault(pattern.name, concrete)
            return
        for lhs, rhs in zip(pattern.generics, concrete.generics):
            self._match_generic(lhs, rhs, mapping)

    @staticmethod
    def _is_integer_type(typ: Type) -> bool:
        return typ.name in ("usize", "isize") or (
            len(typ.name) > 1 and typ.name[0] in ("u", "i") and typ.name[1:].isdigit()
        )

    @staticmethod
    def _is_float_type(typ: Type) -> bool:
        return len(typ.name) > 1 and typ.name[0] == "f" and typ.name[1:].isdigit()
