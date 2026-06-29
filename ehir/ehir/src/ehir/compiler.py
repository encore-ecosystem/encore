import time
from dataclasses import dataclass, field
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
        module = self._time_it(MonomorphizationPass(), module)
        module = self._time_it(MatchValidatorPass(), module)
        module = self._time_it(AutoDropPass(), module)
        module = self._time_it(AutoRetainPass(), module)
        module = self._time_it(RetainInsertionPass(), module)
        module = self._time_it(NormalizerPass(), module)
        module = self._time_it(DeallocatorPass(), module)
        module = self._time_it(DropLoweringPass(), module)
        module = self._time_it(DowngraderPass(), module)
        module = self._time_it(StripperPass(), module)
        module.ast = self._time_stage("PostprocessFilter", module, lambda: self._postprocessable_directives(module.ast))
        module.ast = self._time_stage("DeduplicateDirectives", module, lambda: self._deduplicate_directives(module.ast))
        return self._time_stage("Postprocessor", module, lambda: Postprocessor().run(module))

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
