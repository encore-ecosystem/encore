"""Check retained format templates, warm caches, and body invalidation."""

from pathlib import Path
import subprocess
import sys


fixture = Path(__file__).resolve().parent
repository = fixture.parents[2]
compiler = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else repository / "target/release/encore"


def run(expected: int) -> None:
    result = subprocess.run(
        [str(compiler), "run", "--profile", "dev", "--jobs", "3"],
        cwd=fixture / "app",
        text=True,
        capture_output=True,
    )
    if result.returncode != expected:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(f"expected exit {expected}, got {result.returncode}")


run(0)
print("package codec roundtrip: ok", flush=True)
run(0)
print("warm package cache: ok", flush=True)

model = fixture / "model/src/lib.enq"
original = model.read_text()
assert original.count("count += 1") == 1
try:
    model.write_text(original.replace("count += 1", "count += 2"))
    run(1)  # The unchanged app expects three fields, so the new body must fail it.
    print("template body invalidation: ok", flush=True)
finally:
    model.write_text(original)

run(0)
print("restored package body: ok", flush=True)
