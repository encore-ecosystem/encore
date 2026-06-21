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
    Derective_typealias,
)
from ehir.core.derectives.base import Derective
from ehir.parser import Parser
from ehir.postprocessor import EHIR_ProcessedModule, Postprocessor
from ehir.simplifier.normalizer.norm_fn import Normalized_fn
from ehir.simplifier.passes import (
    AutoDropPass,
    AutoRetainPass,
    DeallocatorPass,
    DowngraderPass,
    DropLoweringPass,
    InstanceCallLoweringPass,
    MatchValidatorPass,
    MonomorphizationPass,
    NormalizerPass,
    ReferenceLoweringPass,
    ResolverPass,
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
    refrain: str
    stage: str
    seconds: float
    detail: str = ""


@dataclass
class EHIR_ProjectCompiler:
    _parser: Parser = field(default_factory=Parser)

    def compile(self, program: str) -> EHIR_ProcessedModule:
        ast = self._parser.parse(program)
        return self.compile_module(EHIR_Module(ast))

    def compile_module(self, module: EHIR_Module) -> EHIR_ProcessedModule:
        module = InstanceCallLoweringPass().run(module)
        module = ResolverPass().run(module)
        module = ReferenceLoweringPass().run(module)
        module = MonomorphizationPass().run(module)
        module = ResolverPass().run(module)
        module = MonomorphizationPass().run(module)
        module = ResolverPass().run(module)
        module = MatchValidatorPass().run(module)
        module = AutoDropPass().run(module)
        module = AutoRetainPass().run(module)
        module = RetainInsertionPass().run(module)
        module = NormalizerPass().run(module)
        module = DeallocatorPass().run(module)
        module = DropLoweringPass().run(module)
        module = DowngraderPass().run(module)
        module = StripperPass().run(module)
        module.ast = self._postprocessable_directives(module.ast)
        module.ast = self._deduplicate_directives(module.ast)
        return Postprocessor().run(module)

    def _postprocessable_directives(self, ast: list[Derective]) -> list[Derective]:
        return [
            directive
            for directive in ast
            if isinstance(directive, (Derective_struct, Derective_extern_fn, Normalized_fn))
            and not isinstance(directive, (Derective_enum, Derective_trait, Derective_impl, Derective_typealias))
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
