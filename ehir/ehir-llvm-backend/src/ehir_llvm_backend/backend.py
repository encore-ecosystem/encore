from dataclasses import dataclass
from pathlib import Path

from ehir.postprocessor import EHIR_ProcessedModule

from ehir_llvm_backend.archiver import Archiver
from ehir_llvm_backend.assembler import Assembler
from ehir_llvm_backend.codegen import Codegen
from ehir_llvm_backend.linker import Linker
from ehir_llvm_backend.optimizer import OptimizationProfile, Optimizer


@dataclass
class EHIR_LLVM_Backend:
    def __post_init__(self):
        self._codegen = Codegen()
        self._optimizer = Optimizer()
        self._archiver = Archiver()
        self._assembler = Assembler()
        self._linker = Linker()

    def compile(
        self,
        module: EHIR_ProcessedModule,
        *,
        opt_profile: OptimizationProfile,
        output_path: Path | None = None,
        native_objects: list[Path] | None = None,
        native_link_args: list[str] | None = None,
    ) -> Path:
        llvm_mod = self._codegen.run(module)
        llvm_optimized_mod = self._optimizer.run(llvm_mod, opt_profile=opt_profile)

        paths = self._artifact_paths(module, opt_profile, output_path)
        paths.object.parent.mkdir(parents=True, exist_ok=True)
        paths.output.parent.mkdir(parents=True, exist_ok=True)

        object_path = self._assembler.run(
            llvm_optimized_mod,
            paths.object,
            opt_level=self._assembler_opt_level(opt_profile),
        )
        if self._has_entrypoint(module):
            return self._linker.run(
                object_path,
                paths.output,
                native_objects=native_objects,
                native_link_args=native_link_args,
            )
        return self._archiver.run(object_path, paths.output)

    def _artifact_paths(self, module: EHIR_ProcessedModule, profile: OptimizationProfile, output_path: Path | None) -> "_ArtifactPaths":
        project_root = self._project_root(module)
        name = self._module_name(module, project_root)
        object_path = project_root / "target" / profile / "object" / f"{name}.o"

        if output_path is not None:
            return _ArtifactPaths(object=object_path, output=output_path)

        if self._has_entrypoint(module):
            return _ArtifactPaths(object=object_path, output=project_root / "target" / profile / name)
        return _ArtifactPaths(object=object_path, output=project_root / "target" / profile / f"lib{name}.a")

    def artifact_output_path(
        self,
        module: EHIR_ProcessedModule,
        *,
        opt_profile: OptimizationProfile,
        output_path: Path | None = None,
    ) -> Path:
        return self._artifact_paths(module, opt_profile, output_path).output

    def _project_root(self, module: EHIR_ProcessedModule) -> Path:
        if module.id != Path():
            source_path = module.id
            if source_path.name in {"main.enq", "lib.enq"} and source_path.parent.name == "src":
                return source_path.parent.parent
            return source_path.parent
        return Path.cwd()

    def _module_name(self, module: EHIR_ProcessedModule, project_root: Path) -> str:
        if project_root.name:
            return project_root.name
        if module.id != Path() and module.id.stem:
            return module.id.stem
        return "main"

    def _has_entrypoint(self, module: EHIR_ProcessedModule) -> bool:
        return any(func.name == "main" for func in module.funcs)

    def _assembler_opt_level(self, opt_profile: OptimizationProfile) -> int:
        if opt_profile == OptimizationProfile.debug:
            return 0
        if opt_profile == OptimizationProfile.release:
            return 1
        return 2


@dataclass(frozen=True)
class _ArtifactPaths:
    object: Path
    output: Path
