import hashlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from importlib.metadata import version
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
    Derective_typealias,
)
from ehir.core.derectives.base import Derective
from ehir.core.primitives import Str_t
from ehir.core.primitives.base import PrimitiveType
from ehir.core.type import Pointer, Reference, Type, is_box_type
from ehir.core.variable import Parameter
from ehir.format import ThemePalette, printfmt
from ehir.frontend import EHIR_Frontend
from ehir.postprocessor import Postprocessor
from ehir.refrain import CompiledRefrain, Refrain
from ehir.simplifier import (
    AutoDropPass,
    AutoRetainPass,
    Deallocator,
    Downgrader,
    DropLoweringPass,
    MonomorphizationPass,
    Normalizer,
    ReferenceLoweringPass,
    RetainInsertionPass,
    Resolver,
)
from ehir.simplifier.stripper import UnneededSymbolsStripper

COMPILER_VERSION = version(__package__ or "ehir")


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
        for relative_dir in refrain.merge_module_dirs:
            self._merge_refrain_modules(refrain, entrypoint_id, node, Path(relative_dir))
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
            ast=self._merge_builtin_directives(self._builtin_directives(), deepcopy(node.module.ast)),
        )

        module.ast = self._lift_impl_methods(module.ast)
        module.ast = Resolver().run(module.ast)
        self._emit_ehir_stage(refrain.name, "post_resolve", module.ast)
        module.ast = ReferenceLoweringPass().run(module.ast)
        module.ast = MonomorphizationPass().run(module.ast)
        self._emit_ehir_stage(refrain.name, "post_monomorphize", module.ast)
        module.ast = AutoDropPass().run(module.ast)
        module.ast = AutoRetainPass().run(module.ast)
        module.ast = RetainInsertionPass().run(module.ast)
        # TODO: re-enable after migrating core/std to explicit safety attrs.
        # module.ast = SafetyValidator().run(module.ast)
        module.ast = Normalizer().run(module.ast)
        module.ast = Deallocator().run(module.ast)
        module.ast = DropLoweringPass().run(module.ast)
        self._emit_ehir_stage(refrain.name, "pre_downgrade", module.ast)
        module.ast = Downgrader().run(module.ast)
        self._emit_ehir_stage(refrain.name, "post_downgrade", module.ast)
        if refrain.type == Refrain.TargetType.EXECUTABLE:
            module.ast = UnneededSymbolsStripper().run(module.ast, keep_public_api=False)
        module.ast = [
            directive
            for directive in module.ast
            if not isinstance(directive, (Derective_trait, Derective_impl, Derective_import))
        ]
        concrete_type_names = {
            directive.name for directive in module.ast if isinstance(directive, (Derective_struct, Derective_enum))
        }
        known_type_names = set(concrete_type_names)
        known_type_names |= {
            directive.name for directive in module.ast if isinstance(directive, Derective_typealias)
        }
        known_type_names |= {
            type_name.rsplit("::", 1)[-1] for type_name in concrete_type_names if "::" in type_name
        }
        module.ast = [
            directive for directive in module.ast if self._is_backend_emittable(directive, known_type_names)
        ]
        module.ast = [directive for directive in module.ast if not isinstance(directive, Derective_typealias)]
        self._emit_ehir_stage(refrain.name, "pre_postprocess", module.ast)
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

    def _merge_builtin_directives(
        self,
        builtins: list[Derective],
        user_directives: list[Derective],
    ) -> list[Derective]:
        existing: set[tuple[type, str]] = set()
        for directive in user_directives:
            existing.add(self._directive_identity(directive))

        merged: list[Derective] = []
        for directive in builtins:
            key = self._directive_identity(directive)
            if key in existing:
                continue
            merged.append(directive)
        merged.extend(user_directives)
        return merged

    def _directive_identity(self, directive: Derective) -> tuple[type, str]:
        if isinstance(directive, Derective_impl):
            trait_name = directive.trait_name or ""
            return (type(directive), f"{trait_name}::{directive.for_type}")
        return (type(directive), getattr(directive, "name", ""))

    def _lift_impl_methods(self, ast: list[Derective]) -> list[Derective]:
        lifted_method_names = {
            directive.name for directive in ast if isinstance(directive, (Derective_fn, Derective_extern_fn))
        }
        lifted_methods: list[Derective_fn] = []
        for directive in ast:
            if not isinstance(directive, Derective_impl):
                continue
            for method in directive.methods:
                if not isinstance(method, Derective_fn):
                    continue
                lifted = deepcopy(method)
                if "::" not in lifted.name:
                    owner = directive.trait_name if directive.trait_name else directive.for_type.name
                    if owner:
                        method_name = lifted.name
                        if method_name != "op":
                            suffix = self._mangle_type_name(directive.for_type)
                            if suffix:
                                method_name = f"{method_name}__{suffix}"
                        lifted.name = f"{owner}::{method_name}"
                if lifted.name in lifted_method_names:
                    continue
                lifted_method_names.add(lifted.name)
                lifted_methods.append(lifted)
        if lifted_methods:
            return [*ast, *lifted_methods]
        return ast

    def _mangle_type_name(self, typ: Type) -> str:
        if self._is_placeholder_type_name(typ.name):
            return ""
        if typ.generics:
            mangled_generics = [self._mangle_type_name(generic) for generic in typ.generics]
            if any(not part for part in mangled_generics):
                return ""
            inner = "_".join(mangled_generics)
            return f"{typ.name}_{inner}"
        return typ.name.replace("::", "_")

    def _is_placeholder_type_name(self, name: str) -> bool:
        if name == "T":
            return True
        return len(name) > 1 and name.startswith("T") and name[1:].isdigit()

    def _emit_ehir_stage(self, refrain_name: str, stage: str, ast: list[Derective]) -> None:
        ehir_dir = self.backend.profile_path / "ehir"
        ehir_dir.mkdir(parents=True, exist_ok=True)
        out_path = ehir_dir / f"{refrain_name}.{stage}.ehir"
        text = "\n\n".join(str(directive) for directive in ast) + "\n"
        out_path.write_text(text)

    def _merge_refrain_modules(
        self,
        refrain: Refrain,
        entrypoint_id: Path,
        target_node: TreeNode,
        relative_dir: Path,
    ) -> None:
        src_root = refrain.path / refrain.entry_root
        extension = self.frontend.get_file_extension()
        merge_root = src_root / relative_dir
        if not merge_root.exists():
            return
        module_paths = sorted(merge_root.rglob(f"*{extension}"))
        if not module_paths:
            return

        symbol_keys: set[tuple[type, str]] = set()
        impl_keys: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
        for directive in target_node.module.ast:
            if isinstance(
                directive,
                (
                    Derective_fn,
                    Derective_extern_fn,
                    Derective_struct,
                    Derective_enum,
                    Derective_trait,
                    Derective_typealias,
                ),
            ):
                symbol_keys.add((type(directive), directive.name))
            elif isinstance(directive, Derective_impl):
                impl_keys.add(
                    (
                        directive.trait_name or "",
                        str(directive.for_type),
                        tuple(str(arg) for arg in directive.trait_args),
                        tuple(method.name for method in directive.methods),
                    )
                )

        for module_path in module_paths:
            if module_path.resolve() == entrypoint_id.resolve():
                continue
            module_node = self._compile_node_by_id(module_path)
            target_node.dependencies.add(module_path)
            for directive in module_node.module.ast:
                if isinstance(directive, Derective_import):
                    continue
                if isinstance(
                    directive,
                    (
                        Derective_fn,
                        Derective_extern_fn,
                        Derective_struct,
                        Derective_enum,
                        Derective_trait,
                        Derective_typealias,
                    ),
                ):
                    key = (type(directive), directive.name)
                    if key in symbol_keys:
                        continue
                    symbol_keys.add(key)
                elif isinstance(directive, Derective_impl):
                    key = (
                        directive.trait_name or "",
                        str(directive.for_type),
                        tuple(str(arg) for arg in directive.trait_args),
                        tuple(method.name for method in directive.methods),
                    )
                    if key in impl_keys:
                        continue
                    impl_keys.add(key)
                target_node.module.ast.append(directive)

    def _is_backend_emittable(self, directive, known_type_names: set[str]) -> bool:
        if isinstance(directive, Derective_fn):
            return all(
                self._is_concrete_type(param.type, known_type_names) for param in directive.params
            ) and self._is_concrete_type(directive.ret_type, known_type_names)
        if getattr(directive, "generics", []):
            if isinstance(directive, (Derective_struct, Derective_enum)):
                return True
            return False
        if isinstance(directive, Derective_struct):
            return True
        if isinstance(directive, Derective_enum):
            return True
        if isinstance(directive, Derective_typealias):
            return False
        return True

    def _is_concrete_type(self, typ: Type, known_type_names: set[str]) -> bool:
        if isinstance(typ, (Pointer, Reference)):
            return self._is_concrete_type(typ.pointee, known_type_names)
        if isinstance(typ, PrimitiveType):
            return True
        if typ.generics and not all(self._is_concrete_type(generic, known_type_names) for generic in typ.generics):
            return False
        builtin_scalar_names = {"void", "str", "char"}
        return (
            is_box_type(typ)
            or
            typ.name in known_type_names
            or typ.name in builtin_scalar_names
            or not typ.name.isidentifier()
            or typ.name.startswith(("u", "i", "f"))
        )

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
            if isinstance(
                directive,
                (
                    Derective_fn,
                    Derective_extern_fn,
                    Derective_struct,
                    Derective_enum,
                    Derective_trait,
                    Derective_typealias,
                ),
            ):
                key = (type(directive), directive.name)
                if key in resolved_symbols:
                    return
                resolved_symbols.add(key)
            elif isinstance(directive, Derective_impl):
                key = (
                    directive.trait_name or "",
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

        def append_module_tree(root_module_id: Path):
            pending = [root_module_id]
            observed: set[Path] = set()
            while pending:
                current_module_id = pending.pop()
                if current_module_id in observed:
                    continue
                observed.add(current_module_id)

                node.dependencies.add(current_module_id)
                current_node = self._compile_node_by_id(current_module_id)
                append_module_contents(current_node.module.ast)

                for child_id in self.frontend.list_child_module_ids(current_module_id):
                    pending.append(child_id)

        def matches_import_symbol(directive_name: str, import_symbol: str) -> bool:
            return directive_name == import_symbol or directive_name.endswith(f"::{import_symbol}")

        def module_name_from_id(module_id: Path) -> str:
            if module_id.stem == "mod":
                return module_id.parent.name
            return module_id.stem

        for directive in module.ast:
            if not isinstance(directive, Derective_import):
                append_directive(directive)
                continue

            parent_id = self._resolve_parent_id(id, directive)
            if Path(parent_id).resolve() == Path(id).resolve():
                # Ignore self-imports (can appear in transitional bootstrap/prelude lowering).
                continue

            if not parent_id.exists():
                raise RuntimeError(f"Unable to find import path: {parent_id}")

            node.dependencies.add(parent_id)

            parent_node = self._compile_node_by_id(parent_id)
            parent_ast = parent_node.module.ast

            if directive.symbol == "*":
                append_module_tree(parent_id)

            else:
                for d in parent_ast:
                    if isinstance(d, (Derective_fn, Derective_extern_fn)):
                        append_directive(d)
                for d in parent_ast:
                    if isinstance(d, Derective_import):
                        continue

                    if isinstance(
                        d,
                        (
                            Derective_fn,
                            Derective_extern_fn,
                            Derective_struct,
                            Derective_enum,
                            Derective_trait,
                            Derective_typealias,
                        ),
                    ) and matches_import_symbol(d.name, directive.symbol):
                        if isinstance(
                            d,
                            (Derective_fn, Derective_extern_fn, Derective_trait, Derective_struct, Derective_typealias),
                        ):
                            append_module_contents(parent_ast)
                        else:
                            append_directive(d)
                        break
                else:
                    if module_name_from_id(parent_id) == directive.symbol:
                        append_module_tree(parent_id)
                        continue
                    raise RuntimeError(f"Unable to import: {directive}")

        # Optionally include direct child modules exposed by the active frontend.
        for child_id in self.frontend.list_child_module_ids(id):
            append_module_tree(child_id)

        node.module.ast = resolved_ast
        return node

    def _core_dir(self) -> Path:
        repo_core = Path(__file__).resolve().parents[2] / "core"
        if repo_core.exists():
            return repo_core
        return Path(__file__).resolve().parent / "core"

    def _core_module_ids(self) -> list[Path]:
        core_dir = self._core_dir()
        if not core_dir.exists():
            return []
        return sorted(path.resolve() for path in core_dir.glob("*.ehir"))

    def _is_core_module_id(self, module_id: Path) -> bool:
        core_dir = self._core_dir().resolve()
        try:
            Path(module_id).resolve().relative_to(core_dir)
            return True
        except ValueError:
            return False

    def _resolve_parent_id(self, module_id: Path, directive: Derective_import) -> Path:
        resolve_with_frontend = getattr(self.frontend, "get_parent_id_of", None)
        if callable(resolve_with_frontend):
            return resolve_with_frontend(module_id, directive)

        parent_refrain_name = directive.prefix[0]
        if parent_refrain_name == "core":
            core_root = self._core_dir()
            rest = directive.prefix[1:]
            candidates = []
            if directive.symbol != "*":
                candidates.append(
                    (core_root / Path(*rest, directive.symbol)).with_suffix(self.frontend.get_file_extension())
                )
            candidates.append((core_root / Path(*rest)).with_suffix(self.frontend.get_file_extension()))
            if rest:
                candidates.append(core_root / Path(*rest) / f"mod{self.frontend.get_file_extension()}")
            candidates.append(core_root / f"mod{self.frontend.get_file_extension()}")
            for candidate in candidates:
                if candidate.exists():
                    return candidate

        if parent_refrain_name in self.refrains:
            refrain_root = self.refrains[parent_refrain_name].path / "src"
            if len(directive.prefix) == 1:
                return refrain_root / f"lib{self.frontend.get_file_extension()}"

            parent_id = (refrain_root / Path(*directive.prefix[1:])).with_suffix(self.frontend.get_file_extension())
            if not parent_id.exists():
                parent_id = parent_id.parent / parent_id.stem / f"mod{self.frontend.get_file_extension()}"
            return parent_id

        parent_id = (module_id.parent / Path(*directive.prefix)).with_suffix(self.frontend.get_file_extension())
        if not parent_id.exists():
            parent_id = parent_id.parent / parent_id.stem / f"mod{self.frontend.get_file_extension()}"
        return parent_id

    def _builtin_directives(self) -> list[Derective]:
        builtins: list[Derective] = []
        builtins.extend(self._builtin_box_directives())

        unit_t = Type("void")
        str_t = Str_t()
        params = [Parameter("text", str_t)]
        builtins.extend(
            [
                Derective_extern_fn(name="print", params=deepcopy(params), ret_type=unit_t, attrs=("safe",)),
                Derective_extern_fn(name="eprint", params=deepcopy(params), ret_type=unit_t, attrs=("safe",)),
            ]
        )
        return builtins

    def _builtin_box_directives(self) -> list[Derective]:
        core_root = self._core_dir()
        owner_id = core_root / "owner.ehir"
        box_id = core_root / "smart_box.ehir"
        runtime_id = core_root / "runtime.ehir"

        from ehir.frontend.builtin import EHIR_DirectFrontend

        core_frontend = self.frontend if self.frontend.get_file_extension() == ".ehir" else EHIR_DirectFrontend()

        directives: list[Derective] = []
        seen_symbols: set[tuple[type, str]] = set()
        for module_id in (owner_id, box_id, runtime_id):
            if not module_id.exists():
                continue
            module = core_frontend.get_module_by_id(module_id)
            for directive in module.ast:
                if isinstance(directive, Derective_import):
                    continue
                symbol_name = getattr(directive, "name", "")
                key = (type(directive), symbol_name)
                if key in seen_symbols:
                    continue
                seen_symbols.add(key)
                directives.append(deepcopy(directive))
        return directives
