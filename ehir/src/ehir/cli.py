from pathlib import Path

from ehir.backend.builtin import EHIR_DirectBackend
from ehir.compiler import EHIR_ProjectCompiler, Refrain
from ehir.frontend.builtin import EHIR_DirectFrontend


def main():
    cwd = Path().resolve()
    target_path = cwd / "target"
    refrains_path = cwd / "refrains"

    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(),
        backend=EHIR_DirectBackend(target_dir=target_path),
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
