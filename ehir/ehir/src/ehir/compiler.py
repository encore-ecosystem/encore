from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.parser import Parser
from ehir.postprocessor import ProcessedModule
from ehir.simplifier.passes import (
    ResolverPass,
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

    def compile(self, program: str) -> ProcessedModule:
        ast = self._parser.parse(program)
        mod = EHIR_Module(ast)
        return self.compile_module(mod)

    def compile_module(self, module: EHIR_Module) -> ProcessedModule:
        a = ResolverPass().run(module)
        print(a)

    # def emit_all(
    #     self,
    #     backend: EHIR_Backend | None = None,
    #     compiled_refrains: list[CompiledRefrain] | None = None,
    # ) -> list[tuple[str, Path]]:
    #     active_backend = backend or self.backend
    #     prepared = self.prepare_all() if compiled_refrains is None else compiled_refrains

    #     result = []
    #     previous_callback = active_backend.profile_callback
    #     previous_artifact_cache = active_backend.use_artifact_cache
    #     active_backend.profile_callback = self._record_backend_profile if self.profile_timings else None
    #     active_backend.use_artifact_cache = self.use_cache
    #     try:
    #         for compiled_refrain in prepared:
    #             if self.profile_timings:
    #                 output_path = self._run_timed_action(
    #                     "backend.emit",
    #                     compiled_refrain.name,
    #                     lambda compiled=compiled_refrain: active_backend.compile_refrain(compiled),
    #                 )
    #             else:
    #                 output_path = self._time_stage(
    #                     "backend.emit",
    #                     compiled_refrain.name,
    #                     lambda compiled=compiled_refrain: active_backend.compile_refrain(compiled),
    #                 )
    #             result.append((compiled_refrain.name, output_path))
    #     finally:
    #         active_backend.profile_callback = previous_callback
    #         active_backend.use_artifact_cache = previous_artifact_cache
    #     return result

    # def compile_all(self) -> list[tuple[str, Path]]:
    #     return self.emit_all()

    # def prepare_refrain(self, refrain: Refrain) -> CompiledRefrain:
    #     if compiled_refrain := self.compiled_refrains.get(refrain.name):
    #         return compiled_refrain

    #     if self.on_refrain is not None:
    #         self.on_refrain(refrain)

    #     entrypoint_id = self._get_entrypoint_id(refrain)
    #     node = self._compile_node_by_id(entrypoint_id)
    #     source_files = self._collect_source_files(entrypoint_id)
    #     semantic_hash = self._build_semantic_hash(refrain, source_files)

    #     if self.use_cache and (compiled_refrain := self._cache.load(refrain.name, semantic_hash)):
    #         if self.on_refrain is None:
    #             printfmt(f"[{refrain.name}] Cache hit.\n", style=ThemePalette.ACCENT_TEXT)
    #         self.compiled_refrains[refrain.name] = compiled_refrain
    #         return compiled_refrain

    #     if self.on_refrain is None:
    #         printfmt(f"[{refrain.name}] Compiling...\n", style=ThemePalette.ACCENT_TEXT)

    #     module = EHIR_Module(
    #         id=node.module.id,
    #         ast=self._merge_builtin_directives(self._builtin_directives(), deepcopy(node.module.ast)),
    #     )

    #     module.ast = self._run_stage("lift_impl_methods", refrain, lambda: self._lift_impl_methods(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_lift", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage(
    #         "instance_call_lowering_pre_resolve", refrain, lambda: InstanceCallLoweringPass().run(module.ast)
    #     )
    #     module.ast = self._run_stage(
    #         "deduplicate_after_instance_call_lowering_pre_resolve",
    #         refrain,
    #         lambda: self._deduplicate_directives(module.ast),
    #     )
    #     module.ast = self._run_stage("resolve_1", refrain, lambda: Resolver().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_resolve_1", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     self._emit_ehir_stage(refrain.name, "post_resolve", module.ast)
    #     module.ast = self._run_stage("reference_lowering", refrain, lambda: ReferenceLoweringPass().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_reference_lowering", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage("monomorphization", refrain, lambda: MonomorphizationPass().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_monomorphization", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage("resolve_2", refrain, lambda: Resolver().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_resolve_2", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage("late_monomorphization", refrain, lambda: MonomorphizationPass().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_late_monomorphization", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage("resolve_3", refrain, lambda: Resolver().run(module.ast))
    #     module.ast = self._run_stage(
    #         "deduplicate_after_resolve_3", refrain, lambda: self._deduplicate_directives(module.ast)
    #     )
    #     module.ast = self._run_stage("match_validator", refrain, lambda: MatchValidatorPass().run(module.ast))
    #     self._emit_ehir_stage(refrain.name, "post_monomorphize", module.ast)
    #     module.ast = self._run_stage(
    #         "autodrop", refrain, lambda: AutoDropPass(trace_cfree=self.trace_cfree).run(module.ast)
    #     )
    #     module.ast = self._run_stage("autoretain", refrain, lambda: AutoRetainPass().run(module.ast))
    #     module.ast = self._run_stage("retain_insertion", refrain, lambda: RetainInsertionPass().run(module.ast))
    #     # TODO: re-enable after migrating core/std to explicit safety attrs.
    #     # module.ast = SafetyValidator().run(module.ast)
    #     module.ast = self._run_stage("normalizer", refrain, lambda: Normalizer().run(module.ast))
    #     module.ast = self._run_stage("deallocator", refrain, lambda: Deallocator().run(module.ast))
    #     module.ast = self._run_stage("drop_lowering", refrain, lambda: DropLoweringPass().run(module.ast))
    #     self._emit_ehir_stage(refrain.name, "pre_downgrade", module.ast)
    #     module.ast = self._run_stage("downgrader", refrain, lambda: Downgrader().run(module.ast))
    #     self._emit_ehir_stage(refrain.name, "post_downgrade", module.ast)
    #     if refrain.type == Refrain.TargetType.EXECUTABLE:
    #         module.ast = self._run_stage(
    #             "stripper", refrain, lambda: UnneededSymbolsStripper().run(module.ast, keep_public_api=False)
    #         )
    #     module.ast = [
    #         directive for directive in module.ast if not isinstance(directive, (Derective_trait, Derective_impl))
    #     ]
    #     concrete_type_names = {
    #         directive.name for directive in module.ast if isinstance(directive, (Derective_struct, Derective_enum))
    #     }
    #     known_type_names = set(concrete_type_names)
    #     known_type_names |= {directive.name for directive in module.ast if isinstance(directive, Derective_typealias)}
    #     known_type_names |= {type_name.rsplit("::", 1)[-1] for type_name in concrete_type_names if "::" in type_name}
    #     module.ast = [directive for directive in module.ast if self._is_backend_emittable(directive, known_type_names)]
    #     module.ast = [directive for directive in module.ast if not isinstance(directive, Derective_typealias)]
    #     module.ast = self._deduplicate_directives(module.ast)
    #     self._emit_ehir_stage(refrain.name, "pre_postprocess", module.ast)
    #     processed_mod = self._run_stage("postprocessor", refrain, lambda: Postprocessor().run(module))

    #     compiled_refrain = CompiledRefrain(
    #         name=refrain.name,
    #         path=refrain.path,
    #         type=refrain.type,
    #         module=processed_mod,
    #         semantic_hash=semantic_hash,
    #         compiler_version=self._compiler_version,
    #         dependencies=sorted(node.dependencies),
    #         source_files=source_files,
    #         native_libraries=self._collect_native_libraries_for(refrain),
    #     )
    #     self._cache.store(compiled_refrain)
    #     self.compiled_refrains[refrain.name] = compiled_refrain
    #     return compiled_refrain

    # def _run_stage(self, stage: str, refrain: Refrain, action):
    #     return self._time_stage(stage, refrain.name, action, detail=refrain.path.as_posix())

    # def _time_stage(self, stage: str, refrain_name: str, action, detail: str = ""):
    #     if not self.profile_timings:
    #         return self._run_timed_action(stage, refrain_name, action, detail)

    #     start = time.perf_counter()
    #     try:
    #         return self._run_timed_action(stage, refrain_name, action, detail)
    #     finally:
    #         self.profile_records.append(
    #             CompileProfileRecord(
    #                 refrain=refrain_name,
    #                 stage=stage,
    #                 seconds=time.perf_counter() - start,
    #                 detail=detail,
    #             )
    #         )

    # def _record_backend_profile(self, stage: str, refrain_name: str, seconds: float, detail: str = "") -> None:
    #     self.profile_records.append(
    #         CompileProfileRecord(
    #             refrain=refrain_name,
    #             stage=stage,
    #             seconds=seconds,
    #             detail=detail,
    #         )
    #     )

    # @staticmethod
    # def _run_timed_action(stage: str, refrain_name: str, action, detail: str = ""):
    #     try:
    #         return action()
    #     except Exception as exc:
    #         location = f" ({detail})" if detail else ""
    #         raise CompileStageError(
    #             f"Compile stage '{stage}' failed for refrain '{refrain_name}'{location}: {exc}"
    #         ) from exc

    # def _merge_builtin_directives(
    #     self,
    #     builtins: list[Derective],
    #     user_directives: list[Derective],
    # ) -> list[Derective]:
    #     existing: set[tuple[type, str]] = set()
    #     for directive in user_directives:
    #         existing.add(self._directive_identity(directive))

    #     merged: list[Derective] = []
    #     for directive in builtins:
    #         key = self._directive_identity(directive)
    #         if key in existing:
    #             continue
    #         merged.append(directive)
    #     merged.extend(user_directives)
    #     return merged

    # def _directive_identity(self, directive: Derective) -> tuple[type, str]:
    #     if isinstance(directive, Derective_impl):
    #         trait_name = directive.trait_name or ""
    #         trait_args_suffix = ""
    #         if directive.trait_args:
    #             trait_args_suffix = "[" + ",".join(self._mangle_type_name(arg) for arg in directive.trait_args) + "]"
    #         return (type(directive), f"{trait_name}{trait_args_suffix}::{directive.for_type}")
    #     return (type(directive), getattr(directive, "name", ""))

    # def _deduplicate_directives(self, directives: list[Derective]) -> list[Derective]:
    #     result: list[Derective] = []
    #     seen: dict[tuple[type, str], str] = {}
    #     for directive in directives:
    #         key = self._directive_identity(directive)
    #         text = str(directive)
    #         existing = seen.get(key)
    #         if existing is not None:
    #             if existing != text:
    #                 raise RuntimeError(f"Conflicting generated directive for '{key[1]}'")
    #             continue
    #         seen[key] = text
    #         result.append(directive)
    #     return result

    # def _lift_impl_methods(self, ast: list[Derective]) -> list[Derective]:
    #     lifted_method_names = {
    #         directive.name for directive in ast if isinstance(directive, (Derective_fn, Derective_extern_fn))
    #     }
    #     lifted_methods: list[Derective_fn] = []
    #     for directive in ast:
    #         if not isinstance(directive, Derective_impl):
    #             continue
    #         self._replace_self(directive.methods, directive.for_type)
    #         for method in directive.methods:
    #             if not isinstance(method, Derective_fn):
    #                 continue
    #             lifted = deepcopy(method)
    #             lifted.generics = self._merge_generics(directive.generics, lifted.generics)
    #             lifted = self._replace_self(lifted, directive.for_type)
    #             if "::" not in lifted.name:
    #                 owner = directive.trait_name if directive.trait_name else str(directive.for_type)
    #                 if owner:
    #                     method_name = lifted.name
    #                     if directive.trait_name is not None:
    #                         suffix = self._mangle_type_template_name(directive.for_type)
    #                         if directive.trait_args:
    #                             trait_suffix = "_".join(
    #                                 self._mangle_type_template_name(arg) for arg in directive.trait_args
    #                             )
    #                             if trait_suffix:
    #                                 suffix = f"{suffix}__{trait_suffix}" if suffix else trait_suffix
    #                         if suffix:
    #                             method_name = f"{method_name}__{suffix}"
    #                     lifted.name = f"{owner}::{method_name}"
    #             if lifted.name in lifted_method_names:
    #                 continue
    #             lifted_method_names.add(lifted.name)
    #             lifted_methods.append(lifted)
    #     if lifted_methods:
    #         return [*ast, *lifted_methods]
    #     return ast

    # def _replace_self(self, value, self_type: Type):
    #     if isinstance(value, Type):
    #         if isinstance(value, Pointer):
    #             return Pointer(self._replace_self(value.pointee, self_type))
    #         if isinstance(value, Reference):
    #             return Reference(self._replace_self(value.pointee, self_type))
    #         if value.name == "Self" and not value.generics:
    #             return deepcopy(self_type)
    #         return Type(value.name, [self._replace_self(generic, self_type) for generic in value.generics])
    #     if isinstance(value, list):
    #         for i, item in enumerate(value):
    #             value[i] = self._replace_self(item, self_type)
    #         return value
    #     if not is_dataclass(value):
    #         return value
    #     for f in fields(value):
    #         setattr(value, f.name, self._replace_self(getattr(value, f.name), self_type))
    #     return value

    # def _merge_generics(self, *generic_groups: list[Type]) -> list[Type]:
    #     merged: list[Type] = []
    #     seen: set[str] = set()
    #     for group in generic_groups:
    #         for generic in group:
    #             if generic.name in seen:
    #                 continue
    #             seen.add(generic.name)
    #             merged.append(deepcopy(generic))
    #     return merged

    # def _mangle_type_template_name(self, typ: Type) -> str:
    #     name = typ.name.replace("::", "_")
    #     if not typ.generics:
    #         return name
    #     inner = "_".join(self._mangle_type_template_name(generic) for generic in typ.generics)
    #     return f"{name}_{inner}"

    # def _mangle_type_name(self, typ: Type) -> str:
    #     if self._is_placeholder_type_name(typ.name):
    #         return ""
    #     if typ.generics:
    #         mangled_generics = [self._mangle_type_name(generic) for generic in typ.generics]
    #         if any(not part for part in mangled_generics):
    #             return ""
    #         inner = "_".join(mangled_generics)
    #         return f"{typ.name}_{inner}"
    #     return typ.name.replace("::", "_")

    # def _is_placeholder_type_name(self, name: str) -> bool:
    #     if name in {"Self", "T"}:
    #         return True
    #     if len(name) == 1 and name.isupper():
    #         return True
    #     return len(name) > 1 and name.startswith("T") and name[1:].isdigit()

    # def _emit_ehir_stage(self, refrain_name: str, stage: str, ast: list[Derective]) -> None:
    #     ehir_dir = self.backend.profile_path / "ehir"
    #     ehir_dir.mkdir(parents=True, exist_ok=True)
    #     out_path = ehir_dir / f"{refrain_name}.{stage}.ehir"
    #     text = "\n\n".join(str(directive) for directive in ast) + "\n"
    #     out_path.write_text(text)

    # def _merge_refrain_modules(
    #     self,
    #     refrain: Refrain,
    #     entrypoint_id: Path,
    #     target_node: TreeNode,
    #     relative_dir: Path,
    # ) -> None:
    #     src_root = refrain.path / refrain.entry_root
    #     extension = self.frontend.get_file_extension()
    #     merge_root = src_root / relative_dir
    #     if not merge_root.exists():
    #         return
    #     module_paths = sorted(merge_root.rglob(f"*{extension}"))
    #     if not module_paths:
    #         return

    #     symbol_keys: set[tuple[type, str]] = set()
    #     impl_keys: set[str] = set()
    #     for directive in target_node.module.ast:
    #         if isinstance(
    #             directive,
    #             (
    #                 Derective_fn,
    #                 Derective_extern_fn,
    #                 Derective_struct,
    #                 Derective_enum,
    #                 Derective_trait,
    #                 Derective_typealias,
    #             ),
    #         ):
    #             symbol_keys.add((type(directive), directive.name))
    #         elif isinstance(directive, Derective_impl):
    #             impl_keys.add(str(directive))

    #     for module_path in module_paths:
    #         if module_path.resolve() == entrypoint_id.resolve():
    #             continue
    #         module_node = self._compile_node_by_id(module_path)
    #         target_node.dependencies.add(module_path)
    #         for directive in module_node.module.ast:
    #             if isinstance(
    #                 directive,
    #                 (
    #                     Derective_fn,
    #                     Derective_extern_fn,
    #                     Derective_struct,
    #                     Derective_enum,
    #                     Derective_trait,
    #                     Derective_typealias,
    #                 ),
    #             ):
    #                 key = (type(directive), directive.name)
    #                 if key in symbol_keys:
    #                     continue
    #                 symbol_keys.add(key)
    #             elif isinstance(directive, Derective_impl):
    #                 key = str(directive)
    #                 if key in impl_keys:
    #                     continue
    #                 impl_keys.add(key)
    #             target_node.module.ast.append(directive)

    # def _is_backend_emittable(self, directive, known_type_names: set[str]) -> bool:
    #     if isinstance(directive, Derective_fn):
    #         return all(
    #             self._is_concrete_type(param.type, known_type_names) for param in directive.params
    #         ) and self._is_concrete_type(directive.ret_type, known_type_names)
    #     if getattr(directive, "generics", []):
    #         if isinstance(directive, (Derective_struct, Derective_enum)):
    #             return True
    #         return False
    #     if isinstance(directive, Derective_struct):
    #         return True
    #     if isinstance(directive, Derective_enum):
    #         return True
    #     if isinstance(directive, Derective_typealias):
    #         return False
    #     return True

    # def _is_concrete_type(self, typ: Type, known_type_names: set[str]) -> bool:
    #     if isinstance(typ, (Pointer, Reference)):
    #         return self._is_concrete_type(typ.pointee, known_type_names)
    #     if isinstance(typ, PrimitiveType):
    #         return True
    #     if typ.name == "dyn":
    #         return len(typ.generics) == 1
    #     if typ.generics and not all(self._is_concrete_type(generic, known_type_names) for generic in typ.generics):
    #         return False
    #     builtin_scalar_names = {"void", "str", "char"}
    #     return (
    #         is_box_type(typ)
    #         or typ.name in known_type_names
    #         or typ.name in builtin_scalar_names
    #         or not typ.name.isidentifier()
    #         or typ.name.startswith(("u", "i", "f"))
    #     )

    # def _get_entrypoint_id(self, refrain: Refrain) -> Path:
    #     return refrain.path / refrain.entry_root / f"{refrain.entrypoint_stem}{self.frontend.get_file_extension()}"

    # def _collect_source_files(self, entrypoint_id: Path) -> list[Path]:
    #     observed: set[Path] = set()

    #     def visit(module_id: Path):
    #         if module_id in observed:
    #             return

    #         observed.add(module_id)
    #         node = self.tree[module_id]
    #         for dependency in sorted(node.dependencies):
    #             visit(dependency)

    #     visit(entrypoint_id)
    #     return sorted(observed)

    # def _build_semantic_hash(self, refrain: Refrain, source_files: list[Path]) -> str:
    #     digest = hashlib.sha256()
    #     digest.update(self._compiler_version.encode())
    #     digest.update(refrain.name.encode())
    #     digest.update(refrain.type.value.encode())
    #     digest.update(b"trace_cfree=")
    #     digest.update(b"1" if self.trace_cfree else b"0")
    #     digest.update(b"cfg.flags=")
    #     digest.update(",".join(sorted(self.cfg_environment.flags)).encode())
    #     digest.update(b"cfg.values=")
    #     digest.update(",".join(f"{k}={v}" for k, v in sorted(self.cfg_environment.values.items())).encode())
    #     digest.update(b"native=")
    #     for native in self._collect_native_libraries_for(refrain):
    #         digest.update(repr(native).encode())

    #     for source_file in source_files:
    #         resolved_file = source_file.resolve()
    #         digest.update(resolved_file.as_posix().encode())
    #         digest.update(resolved_file.read_bytes())

    #     return digest.hexdigest()

    # def _collect_native_libraries_for(self, refrain: Refrain) -> list[NativeLibrary]:
    #     candidates = self.refrains.values() if refrain.type == Refrain.TargetType.EXECUTABLE else [refrain]
    #     result: list[NativeLibrary] = []
    #     seen: set[NativeLibrary] = set()
    #     for candidate in candidates:
    #         for native in candidate.native_libraries:
    #             if native in seen:
    #                 continue
    #             seen.add(native)
    #             result.append(native)
    #     return result

    # def _compile_node_by_id(self, id: Path) -> TreeNode:
    #     if node := self.tree.get(id):
    #         return node

    #     original_module = self._time_stage(
    #         "frontend.load_module",
    #         self._profile_refrain_name_for_module(id),
    #         lambda: self.frontend.get_module_by_id(id=id),
    #         detail=id.as_posix(),
    #     )

    #     module = EHIR_Module(
    #         id=original_module.id,
    #         ast=list(original_module.ast),
    #     )

    #     node = TreeNode(module)
    #     self.tree[id] = node

    #     resolved_ast = []
    #     resolved_symbols: set[tuple[type, str]] = set()
    #     resolved_impls: set[str] = set()

    #     def append_directive(directive):
    #         if isinstance(
    #             directive,
    #             (
    #                 Derective_fn,
    #                 Derective_extern_fn,
    #                 Derective_struct,
    #                 Derective_enum,
    #                 Derective_trait,
    #                 Derective_typealias,
    #             ),
    #         ):
    #             key = (type(directive), directive.name)
    #             if key in resolved_symbols:
    #                 return
    #             resolved_symbols.add(key)
    #         elif isinstance(directive, Derective_impl):
    #             key = str(directive)
    #             if key in resolved_impls:
    #                 return
    #             resolved_impls.add(key)
    #         resolved_ast.append(directive)

    #     for directive in module.ast:
    #         append_directive(directive)

    #     node.module.ast = resolved_ast
    #     return node

    # def _profile_refrain_name_for_module(self, module_id: Path) -> str:
    #     resolved = module_id.resolve()
    #     for refrain in self.refrains.values():
    #         try:
    #             resolved.relative_to(refrain.path.resolve())
    #             return refrain.name
    #         except ValueError:
    #             continue
    #     return "<unknown>"

    # def _core_dir(self) -> Path:
    #     repo_core = Path(__file__).resolve().parents[2] / "core"
    #     if repo_core.exists():
    #         return repo_core
    #     return Path(__file__).resolve().parent / "core"

    # def _core_module_ids(self) -> list[Path]:
    #     core_dir = self._core_dir()
    #     if not core_dir.exists():
    #         return []
    #     return sorted(path.resolve() for path in core_dir.glob("*.ehir"))

    # def _is_core_module_id(self, module_id: Path) -> bool:
    #     core_dir = self._core_dir().resolve()
    #     try:
    #         Path(module_id).resolve().relative_to(core_dir)
    #         return True
    #     except ValueError:
    #         return False

    # def _builtin_directives(self) -> list[Derective]:
    #     builtins: list[Derective] = []
    #     builtins.extend(self._builtin_box_directives())

    #     unit_t = Type("void")
    #     str_t = Str_t()
    #     params = [Parameter("text", str_t)]
    #     builtins.extend(
    #         [
    #             Derective_extern_fn(name="print", params=deepcopy(params), ret_type=unit_t, attrs=("safe",)),
    #             Derective_extern_fn(name="eprint", params=deepcopy(params), ret_type=unit_t, attrs=("safe",)),
    #         ]
    #     )
    #     return builtins

    # def _builtin_box_directives(self) -> list[Derective]:
    #     core_root = self._core_dir()
    #     owner_id = core_root / "owner.ehir"
    #     box_id = core_root / "smart_box.ehir"

    #     from ehir.frontend.builtin import EHIR_DirectFrontend

    #     core_frontend = (
    #         self.frontend
    #         if self.frontend.get_file_extension() == ".ehir"
    #         else EHIR_DirectFrontend(cfg_environment=self.cfg_environment)
    #     )

    #     directives: list[Derective] = []
    #     seen_symbols: set[tuple[type, str]] = set()
    #     for module_id in (owner_id, box_id):
    #         if not module_id.exists():
    #             continue
    #         module = core_frontend.get_module_by_id(module_id)
    #         for directive in module.ast:
    #             symbol_name = getattr(directive, "name", "")
    #             key = (type(directive), symbol_name)
    #             if key in seen_symbols:
    #                 continue
    #             seen_symbols.add(key)
    #             directives.append(deepcopy(directive))
    #     return directives
