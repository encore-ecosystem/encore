import subprocess
import sys
from pathlib import Path


class Linker:
    def run(
        self,
        obj_file_path: Path,
        output_file_path: Path,
    ) -> Path:
        cmd = [
            "clang",
            obj_file_path,
            "-o",
            output_file_path,
            *self._platform_link_args(),
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
