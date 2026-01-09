import shutil
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Callable

import ehir
from ehir.backend import OptProfile
from ehir_llvm_backend import EHIR_LLVM_Backend

from encore.translator.translator import Translator
from encore.utils.manifest import ProjectManifest


def add_build_parser(subparsers) -> tuple[str, Callable]:
    section = "build"
    build_parser = subparsers.add_parser(section, help="Build a project")
    build_parser.add_argument("--release", action="store_true", help="Enable release optimizations")
    return (section, handle_build)


def handle_build(args: Namespace):
    cwd = Path().resolve()

    manifest_path = cwd / ProjectManifest.default_filename()
    if not manifest_path.exists():
        print("Project is not initialized")
        exit(-1)

    with manifest_path.open("r") as f:
        manifest = ProjectManifest(**tomllib.loads(f.read()))

    input_file_path = cwd / "src" / "main.enq"
    if not input_file_path.exists():
        print("Unable to find `main.enq`")
        exit(-1)

    with input_file_path.open("r") as f:
        program = f.read()

    translator = Translator()
    program_ehir = translator.run(program)
    # print(program_ehir.get_raw_program())

    project_name = manifest.get_project_name()
    ehir_compiler = ehir.Compiler()
    ehir_module = ehir_compiler.compile(program_ehir.get_raw_program(), name=project_name)

    profile = OptProfile.debug
    profile_path = cwd / "target" / profile.value
    profile_path.mkdir(parents=True, exist_ok=True)

    ehir_dir = profile_path / "ehir"
    llvm_dir = profile_path / "llvm"
    obj_dir = profile_path / "object"

    folders = [ehir_dir, llvm_dir, obj_dir]
    for folder in folders:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(exist_ok=True, parents=True)

    with (ehir_dir / "main.ehir").open("w") as f:
        f.write(str(ehir_module))

    backend = EHIR_LLVM_Backend(output_llvm_ir_path=llvm_dir)
    backend.compile(
        ehir_module,
        output_object_path=obj_dir / "main.o",
        output_file_path=profile_path / project_name,
        opt_level=profile,
    )
