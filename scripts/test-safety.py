#!/usr/bin/env python3
"""Exercise safety contracts through the installed CLI, not only library queries."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    compiler = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="encore-safety-cli-") as directory:
        source = Path(directory) / "main.enq"
        source.write_text(
            "fn raw() -> u32 { unsafe { ret 42_u32 } }\n"
            "fn transit() -> u32 { ret raw() }\n"
            "#attr(safe)\nfn trusted() -> u32 { ret raw() }\n"
            "trait Handler { fn call(self: Self) -> u32 }\n"
            "fn factory() -> dyn Handler { ret || unsafe { 42_u32 } }\n"
            "fn create() { let f = factory() }\n"
            "fn invoke() -> u32 { let f = factory() ret f.call() }\n"
            "fn main() -> u32 { ret trusted() }\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [compiler, "check", "--safety", "--format", "json", str(source)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        effects = {record["name"]: record for record in records
                   if record.get("kind") == "function-safety"}
        assert set(effects) == {"raw", "transit", "trusted", "main", "call", "factory", "create", "invoke"}, effects
        assert effects["raw"]["unsafe"] and effects["transit"]["unsafe"], effects
        assert not effects["trusted"]["unsafe"] and not effects["main"]["unsafe"], effects
        assert effects["trusted"]["asserted_safe"] and effects["trusted"]["body_unsafe"], effects
        assert not effects["factory"]["unsafe"] and not effects["create"]["unsafe"], effects
        assert effects["invoke"]["unsafe"], effects
        result = subprocess.run(
            [compiler, "check", str(source)], capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0 and "Safety:" not in result.stdout, result
    print("CLI safety contracts, trust boundary and default check: ok")


if __name__ == "__main__":
    main()
