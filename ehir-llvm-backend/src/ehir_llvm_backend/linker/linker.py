import subprocess
import sys
from pathlib import Path

from ehir.refrain import NativeLibrary


class Linker:
    def run(
        self,
        obj_file_path: Path,
        output_file_path: Path,
        *,
        native_libraries: list[NativeLibrary] | None = None,
    ) -> Path:
        cmd = [
            "clang",
            obj_file_path,
            "-o",
            output_file_path,
            *self._platform_link_args(),
            *self._native_link_args(native_libraries or []),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Link error: {result.stderr}")

        return output_file_path

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
