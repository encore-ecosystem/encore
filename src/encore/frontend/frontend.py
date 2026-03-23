from dataclasses import dataclass, field
from pathlib import Path

from ehir import EHIR_Frontend
from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_import

from encore import PROJECT_ROOT
from encore.frontend.translator import Translator


@dataclass
class EHIR_EncoreFrontend(EHIR_Frontend):
    """
    ID - Absolute path to file with .enq suffix
    """

    src_dir: Path
    _cache: dict[str, EHIR_Module] = field(default_factory=dict)

    def get_module_by_id(self, id: str) -> EHIR_Module:
        if m := self._cache.get(id, None):
            return m

        with Path(id).open("r") as f:
            module = Translator().run(f.read())

        self._cache[module.id] = module
        return module

    def get_parent_id_of(self, id: str, derective: Derective_import) -> str:
        match derective.prefix[0]:
            case "repo":
                dep_filepath = self.src_dir / Path(*derective.prefix[1:])
            case "std":
                dep_filepath = PROJECT_ROOT / "std" / "src" / Path(*derective.prefix[1:])
            case _:
                raise ImportError("Only repo and std imports available")

        if not dep_filepath.with_suffix(".enq").exists():
            dep_filepath /= "mod"
        dep_filepath = dep_filepath.with_suffix(".enq")

        if not dep_filepath.exists():
            raise RuntimeError(f"Unable to import: {derective} in {id}")
        return dep_filepath.__str__()
