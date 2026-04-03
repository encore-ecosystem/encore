import argparse
from pathlib import Path

from ehir.compiler import EHIR_ProjectCompiler, Refrain
from ehir.frontend.builtin import EHIR_DirectFrontend

from ehir_llvm_backend import EHIR_LLVM_Backend

AVAILABLE_PROFILES = {
    "debug": EHIR_LLVM_Backend.OptProfile.debug,
    "release": EHIR_LLVM_Backend.OptProfile.release,
    "extreme": EHIR_LLVM_Backend.OptProfile.extreme,
}


def main():
    parser = argparse.ArgumentParser(
        prog="ehir-llvm-backend",
    )
    parser.add_argument("--profile", default="debug", choices=AVAILABLE_PROFILES.keys(), help="Optimization profile")
    args = parser.parse_args()
    opt_profile = AVAILABLE_PROFILES[args.profile]

    cwd = Path().resolve()

    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(),
        backend=EHIR_LLVM_Backend(target_dir=cwd / "target", opt_profile=opt_profile),
    )
    for refrain in (cwd / "refrains").iterdir():
        compiler.add_refrain_to_build(Refrain(name=refrain.name, path=refrain, type=Refrain.TargetType.STATIC_LIB))

    compiler.add_refrain_to_build(Refrain(name=cwd.name, path=cwd, type=Refrain.TargetType.EXECUTABLE))
    compiler.compile_all()


if __name__ == "__main__":
    main()
