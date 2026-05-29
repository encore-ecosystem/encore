import subprocess
import sys
from pathlib import Path

from ehir.refrain import NativeLibrary
from ehir_llvm_backend.runtime import runtime_c_path


class Linker:
    def run(
        self,
        obj_file_path: Path,
        output_file_path: Path,
        *,
        native_libraries: list[NativeLibrary] | None = None,
    ) -> Path:
        runtime_obj_path = output_file_path.with_name(f"{output_file_path.name}.runtime.o")
        self._compile_runtime(runtime_obj_path)

        cmd = [
            "clang",
            obj_file_path,
            runtime_obj_path,
            "-o",
            output_file_path,
            *self._platform_link_args(),
            *self._native_link_args(native_libraries or []),
        ]
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

    def _platform_link_args(self) -> list[str]:
        if sys.platform.startswith("win32"):
            return []
        if sys.platform == "darwin":
            return ["-lc", "-lm", "-lpthread"]
        return ["-lc", "-lm", "-lpthread", "-ldl"]

    def _native_link_args(self, native_libraries: list[NativeLibrary]) -> list[str]:
        args: list[str] = []
        for native in native_libraries:
            for search_path in native.search_paths:
                args.append(f"-L{search_path}")

            if native.kind == "link_args":
                pass
            elif native.kind == "framework":
                framework_name = native.link_name or native.name
                args.extend(["-framework", framework_name])
            elif native.path:
                args.append(native.path)
            else:
                link_name = native.link_name or native.name
                args.append(f"-l{link_name}")

            args.extend(native.link_args)
            for framework in native.frameworks:
                args.extend(["-framework", framework])
        return args
