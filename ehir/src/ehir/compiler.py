import hashlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from ehir.backend import EHIR_Backend
from ehir.builder import EHIR_Module
from ehir.cache import CompiledRefrainCache
from ehir.core.derectives import (
    Derective_enum,
    Derective_extern_fn,
    Derective_fn,
    Derective_impl,
    Derective_import,
    Derective_struct,
    Derective_trait,
)
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, SmartPointer, Type
from ehir.format import ThemePalette, printfmt
from ehir.frontend import EHIR_Frontend
from ehir.postprocessor import Postprocessor
from ehir.refrain import CompiledRefrain, Refrain
from ehir.simplifier import Deallocator, Downgrader, Normalizer, Resolver
from ehir.simplifier.cfree import Cfree_Simplifier_Pass
from ehir.version import COMPILER_VERSION


@dataclass
class TreeNode:
    module: EHIR_Module
    dependencies: set[Path] = field(default_factory=set)


@dataclass
class EHIR_ProjectCompiler:
    frontend: EHIR_Frontend
    backend: EHIR_Backend
    cache_dir: Path | None = None
    use_cache: bool = True
    on_refrain: Callable[[Refrain], None] | None = None
    refrains: dict[str, Refrain] = field(default_factory=dict)
    tree: dict[Path, TreeNode] = field(default_factory=dict)
    compiled_refrains: dict[str, CompiledRefrain] = field(default_factory=dict)
    _cache: CompiledRefrainCache = field(init=False)
    _compiler_version: str = field(init=False, default=COMPILER_VERSION)

    def __post_init__(self):
        if self.cache_dir is None:
            # Keep EHIR cache alongside backend artifacts:
            # target/<profile>/{llvm,object,ehir}
            self.cache_dir = self.backend.profile_path / "ehir" / "cache"

        self._cache = CompiledRefrainCache(self.cache_dir)

    def add_refrain_to_build(self, refrain: Refrain):
        if refrain.name in self.refrains:
            return
        self.refrains[refrain.name] = refrain

    def prepare_all(self) -> list[CompiledRefrain]:
        return [self.prepare_refrain(refrain) for refrain in self.refrains.values()]

    def emit_all(
        self,
        backend: EHIR_Backend | None = None,
        compiled_refrains: list[CompiledRefrain] | None = None,
    ) -> list[tuple[str, Path]]:
        active_backend = backend or self.backend
        prepared = self.prepare_all() if compiled_refrains is None else compiled_refrains

        result = []
        for compiled_refrain in prepared:
            output_path = active_backend.compile_refrain(compiled_refrain)
            result.append((compiled_refrain.name, output_path))
        return result

    def compile_all(self) -> list[tuple[str, Path]]:
        return self.emit_all()

    def prepare_refrain(self, refrain: Refrain) -> CompiledRefrain:
        if compiled_refrain := self.compiled_refrains.get(refrain.name):
            return compiled_refrain

        if self.on_refrain is not None:
            self.on_refrain(refrain)

        entrypoint_id = self._get_entrypoint_id(refrain)
        node = self._compile_node_by_id(entrypoint_id)
        source_files = self._collect_source_files(entrypoint_id)
        semantic_hash = self._build_semantic_hash(refrain, source_files)

        if self.use_cache and (compiled_refrain := self._cache.load(refrain.name, semantic_hash)):
            if self.on_refrain is None:
                printfmt(f"[{refrain.name}] Cache hit.\n", style=ThemePalette.ACCENT_TEXT)
            self.compiled_refrains[refrain.name] = compiled_refrain
            return compiled_refrain

        if self.on_refrain is None:
            printfmt(f"[{refrain.name}] Compiling...\n", style=ThemePalette.ACCENT_TEXT)

        module = EHIR_Module(
            id=node.module.id,
            ast=deepcopy(node.module.ast),
        )

        module.ast = Resolver().run(module.ast)
        concrete_type_names = {
            directive.name for directive in module.ast if isinstance(directive, (Derective_struct, Derective_enum))
        }
        module.ast = [
            directive for directive in module.ast if self._is_backend_emittable(directive, concrete_type_names)
        ]
        module.ast = Normalizer().run(module.ast)
        module.ast = Deallocator().run(module.ast)
        module.ast = Cfree_Simplifier_Pass().run(module.ast)
        module.ast = Downgrader().run(module.ast)
        processed_mod = Postprocessor().run(module)

        compiled_refrain = CompiledRefrain(
            name=refrain.name,
            path=refrain.path,
            type=refrain.type,
            module=processed_mod,
            semantic_hash=semantic_hash,
            compiler_version=self._compiler_version,
            dependencies=sorted(node.dependencies),
            source_files=source_files,
        )
        self._cache.store(compiled_refrain)
        self.compiled_refrains[refrain.name] = compiled_refrain
        return compiled_refrain

    def _is_backend_emittable(self, directive, concrete_type_names: set[str]) -> bool:
        if getattr(directive, "generics", []):
            return False

        if isinstance(directive, Derective_fn):
            return all(
                self._is_concrete_type(param.type, concrete_type_names) for param in directive.params
            ) and self._is_concrete_type(directive.ret_type, concrete_type_names)
        if isinstance(directive, Derective_struct):
            return all(self._is_concrete_type(param.type, concrete_type_names) for param in directive.params)
        if isinstance(directive, Derective_enum):
            return all(
                variant.type is None or self._is_concrete_type(variant.type, concrete_type_names)
                for variant in directive.variants
            )
        return True

    def _is_concrete_type(self, typ: Type, concrete_type_names: set[str]) -> bool:
        if isinstance(typ, SmartPointer):
            return self._is_concrete_type(typ.pointee, concrete_type_names)
        if isinstance(typ, Pointer):
            return self._is_concrete_type(typ.pointee, concrete_type_names)
        if isinstance(typ, PrimitiveType):
            return True
        if typ.generics and not all(self._is_concrete_type(generic, concrete_type_names) for generic in typ.generics):
            return False
        return typ.name in concrete_type_names or not typ.name.isidentifier() or typ.name.startswith(("u", "i", "f"))

    def _get_entrypoint_id(self, refrain: Refrain) -> Path:
        return refrain.path / refrain.entry_root / f"{refrain.entrypoint_stem}{self.frontend.get_file_extension()}"

    def _collect_source_files(self, entrypoint_id: Path) -> list[Path]:
        observed: set[Path] = set()

        def visit(module_id: Path):
            if module_id in observed:
                return

            observed.add(module_id)
            node = self.tree[module_id]
            for dependency in sorted(node.dependencies):
                visit(dependency)

        visit(entrypoint_id)
        return sorted(observed)

    def _build_semantic_hash(self, refrain: Refrain, source_files: list[Path]) -> str:
        digest = hashlib.sha256()
        digest.update(self._compiler_version.encode())
        digest.update(refrain.name.encode())
        digest.update(refrain.type.value.encode())

        for source_file in source_files:
            resolved_file = source_file.resolve()
            digest.update(resolved_file.as_posix().encode())
            digest.update(resolved_file.read_bytes())

        return digest.hexdigest()

    def _compile_node_by_id(self, id: Path) -> TreeNode:
        if node := self.tree.get(id):
            return node

        original_module = self.frontend.get_module_by_id(id=id)

        module = EHIR_Module(
            id=original_module.id,
            ast=list(original_module.ast),
        )

        node = TreeNode(module)
        self.tree[id] = node

        resolved_ast = []
        resolved_symbols: set[tuple[type, str]] = set()
        resolved_impls: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()

        def append_directive(directive):
            if isinstance(directive, (Derective_fn, Derective_extern_fn, Derective_struct, Derective_enum, Derective_trait)):
                key = (type(directive), directive.name)
                if key in resolved_symbols:
                    return
                resolved_symbols.add(key)
            elif isinstance(directive, Derective_impl):
                key = (
                    directive.trait_name,
                    str(directive.for_type),
                    tuple(str(arg) for arg in directive.trait_args),
                    tuple(method.name for method in directive.methods),
                )
                if key in resolved_impls:
                    return
                resolved_impls.add(key)
            resolved_ast.append(directive)

        def append_module_contents(parent_ast):
            for d in parent_ast:
                if isinstance(d, Derective_import):
                    continue
                append_directive(d)

        def matches_import_symbol(directive_name: str, import_symbol: str) -> bool:
            return directive_name == import_symbol or directive_name.endswith(f"::{import_symbol}")

        for directive in module.ast:
            if not isinstance(directive, Derective_import):
                append_directive(directive)
                continue

            parent_id = self._resolve_parent_id(id, directive)

            if not parent_id.exists():
                raise RuntimeError(f"Unable to find import path: {parent_id}")

            node.dependencies.add(parent_id)

            parent_node = self._compile_node_by_id(parent_id)
            parent_ast = parent_node.module.ast

            if directive.symbol == "*":
                append_module_contents(parent_ast)

            else:
                for d in parent_ast:
                    if isinstance(d, (Derective_fn, Derective_extern_fn)):
                        append_directive(d)
                for d in parent_ast:
                    if isinstance(d, Derective_import):
                        continue

                    if (
                        isinstance(d, (Derective_fn, Derective_extern_fn, Derective_struct, Derective_enum, Derective_trait))
                        and matches_import_symbol(d.name, directive.symbol)
                    ):
                        if isinstance(d, (Derective_fn, Derective_extern_fn, Derective_trait, Derective_struct)):
                            append_module_contents(parent_ast)
                        else:
                            append_directive(d)
                        break
                else:
                    raise RuntimeError(f"Unable to import: {directive}")

        node.module.ast = resolved_ast
        return node

    def _resolve_parent_id(self, module_id: Path, directive: Derective_import) -> Path:
        resolve_with_frontend = getattr(self.frontend, "get_parent_id_of", None)
        if callable(resolve_with_frontend):
            return resolve_with_frontend(module_id, directive)

        parent_refrain_name = directive.prefix[0]
        if parent_refrain_name in self.refrains:
            return self.refrains[parent_refrain_name].path / "src" / f"lib{self.frontend.get_file_extension()}"

        parent_id = (module_id.parent / Path(*directive.prefix)).with_suffix(self.frontend.get_file_extension())
        if not parent_id.exists():
            parent_id = parent_id.parent / parent_id.stem / f"mod{self.frontend.get_file_extension()}"
        return parent_id
