import time
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from importlib.metadata import version
from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.core.derectives import (
    Derective_enum,
    Derective_extern_fn,
    Derective_impl,
    Derective_struct,
    Derective_trait,
)
from ehir.core.derectives.base import Derective
from ehir.core.derectives.fn import Derective_fn
from ehir.core.enum import Enum
from ehir.core.struct import Struct
from ehir.core.type import Pointer, Reference, Type, mangle_type_name
from ehir.parser import Parser
from ehir.postprocessor import EHIR_ProcessedModule, Postprocessor
from ehir.resolver import EHIR_TypedModule, Resolver
from ehir.simplifier.base import SimplifierPass
from ehir.simplifier.normalizer.norm_fn import Normalized_fn
from ehir.simplifier.passes import (
    AutoDropPass,
    AutoRetainPass,
    DeallocatorPass,
    DowngraderPass,
    DropLoweringPass,
    MatchValidatorPass,
    MonomorphizationPass,
    NormalizerPass,
    ReferenceLoweringPass,
    RetainInsertionPass,
    StripperPass,
)

COMPILER_VERSION = version(__package__ or "ehir")


@dataclass
class TreeNode:
    module: EHIR_Module
    dependencies: set[Path] = field(default_factory=set)


class CompileStageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompileProfileRecord:
    module: str
    stage: str
    seconds: float


@dataclass
class EHIR_ProjectCompiler:
    _parser: Parser = field(default_factory=Parser)
    pass_timings: list[CompileProfileRecord] = field(default_factory=list)

    def compile(self, program: str) -> EHIR_ProcessedModule:
        ast = self._parser.parse(program)
        return self.compile_module(self.resolve_module(EHIR_Module(ast)))

    def resolve_module(self, module: EHIR_Module) -> EHIR_TypedModule:
        return self._time_stage("Resolver", module, lambda: Resolver().run(module))

    def compile_module(self, module: EHIR_TypedModule) -> EHIR_ProcessedModule:
        module = self._time_it(ReferenceLoweringPass(), module)
        module.ast = self._time_stage("LiftImplMethods", module, lambda: self._lift_impl_methods(module.ast))
        module = self._time_it(MonomorphizationPass(), module)
        module = self._time_it(MatchValidatorPass(), module)
        module = self._time_it(AutoDropPass(), module)
        module = self._time_it(AutoRetainPass(), module)
        module = self._time_it(RetainInsertionPass(), module)
        module = self._time_it(MonomorphizationPass(), module)
        module = self._time_it(NormalizerPass(), module)
        module = self._time_it(DeallocatorPass(), module)
        module = self._time_it(DropLoweringPass(), module)
        module = self._time_it(DowngraderPass(), module)
        module = self._time_it(StripperPass(), module)
        module.ast = self._time_stage("PostprocessFilter", module, lambda: self._postprocessable_directives(module.ast))
        module.ast = self._time_stage("DeduplicateDirectives", module, lambda: self._deduplicate_directives(module.ast))
        return self._time_stage("Postprocessor", module, lambda: Postprocessor().run(module))

    def _lift_impl_methods(self, ast: list[Derective]) -> list[Derective]:
        fn_names = {directive.name for directive in ast if isinstance(directive, (Derective_fn, Derective_extern_fn))}
        generated: list[Derective_fn] = []
        for directive in ast:
            if not isinstance(directive, Derective_impl):
                continue
            for method in directive.methods:
                lowered = deepcopy(method)
                merged_generics: list[Type] = []
                known = set()
                for generic in [*directive.generics, *method.generics]:
                    if generic.name in known:
                        continue
                    known.add(generic.name)
                    merged_generics.append(deepcopy(generic))
                lowered.generics = merged_generics
                lowered.name = self._lifted_impl_method_name(directive, method)
                self._replace_self(lowered, directive.for_type)
                if lowered.name in fn_names:
                    continue
                fn_names.add(lowered.name)
                generated.append(lowered)
        return [*ast, *generated]

    def _lifted_impl_method_name(self, impl: Derective_impl, method: Derective_fn) -> str:
        if "::" in method.name:
            return method.name
        if impl.trait_name is None:
            return f"{impl.for_type}::{method.name}"

        method_name = self._trait_impl_method_name(impl, method)
        return f"{impl.trait_name}::{method_name}"

    def _trait_impl_method_name(self, impl: Derective_impl, method: Derective_fn) -> str:
        suffix = mangle_type_name(self._trait_impl_suffix_type(impl))
        if impl.trait_args:
            trait_suffix = "_".join(mangle_type_name(arg) for arg in impl.trait_args)
            if trait_suffix:
                suffix = f"{suffix}__{trait_suffix}" if suffix else trait_suffix
        if not suffix:
            return method.name
        return f"{method.name}__{suffix}"

    def _trait_impl_suffix_type(self, impl: Derective_impl) -> Type:
        if impl.generics:
            return Type(impl.for_type.name, [Type(generic.name) for generic in impl.for_type.generics])
        return impl.for_type

    def _replace_self(self, value, self_type: Type):
        if isinstance(value, Type):
            if isinstance(value, Pointer):
                return Pointer(self._replace_self(value.pointee, self_type))
            if isinstance(value, Reference):
                return Reference(self._replace_self(value.pointee, self_type))
            if value.name == "Self" and not value.generics:
                return deepcopy(self_type)
            return Type(value.name, [self._replace_self(generic, self_type) for generic in value.generics])
        if isinstance(value, Struct):
            if value.name == "Self":
                value.name = self_type.name
                value.generics = deepcopy(self_type.generics)
                value.type = deepcopy(self_type)
        if isinstance(value, Enum):
            if value.name == "Self":
                value.name = self_type.name
                value.generics = deepcopy(self_type.generics)
        if isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = self._replace_self(item, self_type)
            return value
        if not is_dataclass(value):
            return value
        for item in fields(value):
            setattr(value, item.name, self._replace_self(getattr(value, item.name), self_type))
        return value

    def _postprocessable_directives(self, ast: list[Derective]) -> list[Derective]:
        return [
            directive
            for directive in ast
            if isinstance(directive, (Derective_struct, Derective_extern_fn, Normalized_fn))
            and not isinstance(directive, (Derective_enum, Derective_trait, Derective_impl))
        ]

    def _deduplicate_directives(self, ast: list[Derective]) -> list[Derective]:
        seen: set[tuple[type[Derective], str]] = set()
        result: list[Derective] = []
        for directive in ast:
            name = getattr(directive, "name", None)
            if not isinstance(name, str):
                result.append(directive)
                continue
            key = (type(directive), name)
            if key in seen:
                continue
            seen.add(key)
            result.append(directive)
        return result

    def _time_it(self, simp_pass: SimplifierPass, module: EHIR_TypedModule) -> EHIR_TypedModule:
        return self._time_stage(simp_pass.__class__.__name__, module, lambda: simp_pass.run(module))

    def _time_stage(self, stage: str, module: EHIR_Module, runner):
        start_timestamp = time.perf_counter()
        result = runner()
        time_elapsed = time.perf_counter() - start_timestamp
        self.pass_timings.append(
            CompileProfileRecord(
                module=str(module.id) if module.id != Path() else "<memory>",
                stage=stage,
                seconds=time_elapsed,
            )
        )
        return result
