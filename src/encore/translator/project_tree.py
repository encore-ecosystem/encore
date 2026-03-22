from dataclasses import dataclass
from pathlib import Path

import ehir
from ehir import EHIR_Backend, OptProfile

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

    def compile(self, entrypoint: Path):
        self._build(entrypoint)

    def _build(self, file: Path):
        with file.open("r") as f:
            program = f.read()

        translator = Translator()
        program_ehir = translator.run(program)
        print(program_ehir.get_raw_program())

        # project_name = self.manifest.get_project_name()
        # ehir_compiler = ehir.Compiler()
        # ehir_module = ehir_compiler.compile(program_ehir.get_raw_program(), name=project_name)
        # print(ehir_module)
