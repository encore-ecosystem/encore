#!/usr/bin/env python3
"""Check init's ignore rules without modifying an existing workspace."""
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    compiler = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="encore-init-") as scratch:
        root = Path(scratch)

        def initialize():
            subprocess.run([compiler, "init", "--name", "init_probe"], cwd=root,
                           check=True, capture_output=True, text=True, timeout=30)

        initialize()
        ignore = root / ".gitignore"
        assert ignore.read_text() == "target/\n.encore_cache/\n"
        for name in ("target/output", ".encore_cache/lsp/index"):
            result = subprocess.run(["git", "check-ignore", name], cwd=root,
                                    capture_output=True, text=True)
            assert result.returncode == 0, name
        result = subprocess.run(["git", "check-ignore", "src/main.enq"], cwd=root,
                                capture_output=True, text=True)
        assert result.returncode == 1
        initialize()
        assert ignore.read_text() == "target/\n.encore_cache/\n"
        ignore.write_text("custom/\n")
        initialize()
        assert ignore.read_text() == "custom/\n"
    print("init: generated ignores, Git behavior, repeated init and existing file passed")


if __name__ == "__main__":
    main()
