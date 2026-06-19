import subprocess
from pathlib import Path


class Archiver:
    def run(self, object_file_path: Path, output_file_path: Path) -> Path:
        for command in (
            ["llvm-ar", "rcs", output_file_path, object_file_path],
            ["ar", "rcs", output_file_path, object_file_path],
        ):
            try:
                result = subprocess.run(command, capture_output=True, text=True)
            except FileNotFoundError:
                continue

            if result.returncode == 0:
                return output_file_path

            raise RuntimeError(f"Archive error: {result.stderr}")

        raise RuntimeError("Unable to locate llvm-ar or ar")
