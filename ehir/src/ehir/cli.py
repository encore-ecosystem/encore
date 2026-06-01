import argparse
from pathlib import Path

from ehir.cfg import default_cfg_environment
from ehir.backend.builtin import EHIR_DirectBackend
from ehir.compiler import EHIR_ProjectCompiler, Refrain
from ehir.frontend.builtin import EHIR_DirectFrontend


def main():
    parser = argparse.ArgumentParser(prog="ehir")
    parser.add_argument(
        "--trace-cfree",
        action="store_true",
        help="Print debug messages right before cfree deallocations.",
    )
    parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )
    args = parser.parse_args()

    cwd = Path().resolve()
    target_path = cwd / "target"
    refrains_path = cwd / "refrains"

    cfg_environment = default_cfg_environment(extra=args.cfg)
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(cfg_environment=cfg_environment),
        backend=EHIR_DirectBackend(target_dir=target_path),
        trace_cfree=args.trace_cfree,
        cfg_environment=cfg_environment,
    )

    if refrains_path.exists():
        for refrain in refrains_path.iterdir():
            if not refrain.is_dir():
                continue
            compiler.add_refrain_to_build(
                Refrain(
                    name=refrain.name,
                    path=refrain,
                    type=Refrain.TargetType.STATIC_LIB,
                )
            )

    compiler.add_refrain_to_build(Refrain(name=cwd.name, path=cwd, type=Refrain.TargetType.EXECUTABLE))
    compiler.compile_all()


if __name__ == "__main__":
    main()
