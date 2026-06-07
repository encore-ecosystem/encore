from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from ehir.postprocessor import ProcessedModule


@dataclass(frozen=True)
class NativeLibrary:
    name: str
    kind: str = "system"
    link_name: str | None = None
    path: str | None = None
    search_paths: tuple[str, ...] = field(default_factory=tuple)
    frameworks: tuple[str, ...] = field(default_factory=tuple)
    link_args: tuple[str, ...] = field(default_factory=tuple)
    cfg: str | None = None


@dataclass
class Refrain:
    class TargetType(StrEnum):
        EXECUTABLE = auto()
        STATIC_LIB = auto()
        OBJECT = auto()

    name: str
    path: Path
    type: TargetType = TargetType.EXECUTABLE
    entrypoint: str | None = None
    entry_root: str = "src"
    merge_module_dirs: tuple[str, ...] = field(default_factory=tuple)
    native_libraries: list[NativeLibrary] = field(default_factory=list)

    @property
    def entrypoint_stem(self) -> str:
        if self.entrypoint is not None:
            return self.entrypoint
        if self.type == self.TargetType.EXECUTABLE:
            return "main"
        return "lib"


@dataclass
class CompiledRefrain:
    name: str
    path: Path
    type: Refrain.TargetType
    module: ProcessedModule
    semantic_hash: str
    compiler_version: str
    dependencies: list[Path] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)
    native_libraries: list[NativeLibrary] = field(default_factory=list)
