from dataclasses import dataclass, field
from pathlib import Path

from ehir import EHIR_Backend, OptProfile
from ehir.core.derectives import Derective_cimp, Derective_imp

from encore import PROJECT_ROOT
from encore.translator.builder import EHIR_Module
from encore.translator.translator import Translator
from encore.utils.manifest import ProjectManifest


@dataclass
class Codefile:
    path: Path
    deps: list["Codefile"]
    module: EHIR_Module


@dataclass
class ProjectTree:
    manifest: ProjectManifest
    profile: OptProfile
    backend: EHIR_Backend
    root: Path
    tree: dict[Path, Codefile] = field(default_factory=dict)

    def compile(self, entrypoint: Path):
        entryblock = self._build(entrypoint)
        print(entryblock)

    def _build(self, filepath: Path) -> Codefile:
        if filepath in self.tree:
            return self.tree[filepath]

        with filepath.open("r") as f:
            program = f.read()

        print(f"Building {filepath}")
        translator = Translator()
        ehir_module = translator.run(program)
        codefile = Codefile(filepath, [], ehir_module)
        self.tree[filepath] = codefile

        for derective in ehir_module.ast:
            if isinstance(derective, (Derective_imp, Derective_cimp)):
                match derective.prefix[0]:
                    case "repo":
                        dep_filepath = self.root / "src" / Path(*derective.prefix[1:])
                    case "std":
                        dep_filepath = PROJECT_ROOT / "std" / "src" / Path(*derective.prefix[1:])
                    case _:
                        raise ImportError("Only repo and std imports available")

                if not dep_filepath.with_suffix(".enq").exists():
                    dep_filepath /= "mod"
                dep_filepath = dep_filepath.with_suffix(".enq")

                codefile.deps.append(self._build(dep_filepath))

        return codefile
