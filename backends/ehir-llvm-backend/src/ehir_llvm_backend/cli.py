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

AVAILABLE_ROOT_TYPES = {
    "executable": Refrain.TargetType.EXECUTABLE,
    "static_lib": Refrain.TargetType.STATIC_LIB,
    "object": Refrain.TargetType.OBJECT,
}


def main():
    parser = argparse.ArgumentParser(
        prog="ehir-llvm-backend",
    )
    parser.add_argument("--profile", default="debug", choices=AVAILABLE_PROFILES.keys(), help="Optimization profile")
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Output target directory (defaults to <cwd>/target)",
    )
    parser.add_argument(
        "--root-type",
        default="executable",
        choices=AVAILABLE_ROOT_TYPES.keys(),
        help="Artifact type for root refrain",
    )
    args = parser.parse_args()
    opt_profile = AVAILABLE_PROFILES[args.profile]

    cwd = Path().resolve()
    target_dir = Path(args.target_dir).resolve() if args.target_dir is not None else cwd / "target"
    root_type = AVAILABLE_ROOT_TYPES[args.root_type]

    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(),
        backend=EHIR_LLVM_Backend(target_dir=target_dir, opt_profile=opt_profile),
    )
    for refrain in (cwd / "refrains").iterdir():
        if not refrain.is_dir():
            continue
        compiler.add_refrain_to_build(Refrain(name=refrain.name, path=refrain, type=Refrain.TargetType.STATIC_LIB))

    compiler.add_refrain_to_build(Refrain(name=cwd.name, path=cwd, type=root_type))
    compiler.compile_all()


if __name__ == "__main__":
    main()
