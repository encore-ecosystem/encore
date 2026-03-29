from dataclasses import dataclass, field
from pathlib import Path

from ehir import EHIR_Frontend
from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_import

from encore import PROJECT_ROOT
from encore.frontend.translator import Translator


@dataclass
class EHIR_EncoreFrontend(EHIR_Frontend):
    src_dir: Path
    _cache: dict[Path, EHIR_Module] = field(default_factory=dict)

    def get_module_by_id(self, id: Path) -> EHIR_Module:
        if m := self._cache.get(id, None):
            return m

        with id.open("r") as f:
            module = Translator().run(f.read())

        self._cache[module.id] = module
        return module

    def get_parent_id_of(self, id: Path, derective: Derective_import) -> Path:
        match derective.prefix[0]:
            case "refrain":
                dep_filepath = self._get_project_root_of(id) / "src" / Path(*derective.prefix[1:])
            case "repo":
                dep_filepath = self.src_dir / Path(*derective.prefix[1:])
            case "std":
                dep_filepath = PROJECT_ROOT / "std" / "src" / Path(*derective.prefix[1:])
            case _:
                dep_filepath = id.parent / Path(*derective.prefix)

        dep_filepath = self._resolve_module_path(dep_filepath)

        if not dep_filepath.exists():
            raise RuntimeError(f"Unable to import: {derective} in {id}")
        return dep_filepath

    def _get_project_root_of(self, id: Path) -> Path:
        for parent in [id.parent, *id.parents]:
            if (parent / "encore.toml").exists():
                return parent
        raise RuntimeError(f"Unable to find encore.toml for module: {id}")

    def _resolve_module_path(self, path: Path) -> Path:
        if path.with_suffix(".enq").exists():
            return path.with_suffix(".enq")
        return (path / "mod").with_suffix(".enq")

    def get_file_extension(self) -> str:
        return ".enq"
