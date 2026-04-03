import subprocess
from pathlib import Path

from ehir_llvm_backend.runtime import runtime_c_path


class Linker:
    def run(self, obj_file_path: Path, output_file_path: Path) -> Path:
        runtime_obj_path = output_file_path.with_name(f"{output_file_path.name}.runtime.o")
        self._compile_runtime(runtime_obj_path)

        cmd = ["clang", obj_file_path, runtime_obj_path, "-o", output_file_path, "-lc", "-lm", "-lpthread", "-ldl"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Link error: {result.stderr}")

        return output_file_path

    def _compile_runtime(self, runtime_obj_path: Path):
        runtime_obj_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["clang", "-std=c11", "-c", str(runtime_c_path()), "-o", str(runtime_obj_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Runtime compile error: {result.stderr}")
