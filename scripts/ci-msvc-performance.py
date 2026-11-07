"""Remote-only comparison using the already converged baseline/candidate binaries."""

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time


root = Path.cwd()
output = root / "target/performance"
output.mkdir(parents=True, exist_ok=True)
results = []
case = "tests/reflection_metadata_imports.enq"
for label in ("baseline", "candidate"):
    source = root / "baseline" if label == "baseline" else root
    context = output / label
    compiler = context / "bin/encore.exe"
    provenance = json.loads((context / "provenance.json").read_text())
    digest = hashlib.sha256(compiler.read_bytes()).hexdigest()
    assert digest == provenance["compiler_sha256"]
    assert provenance["converged"] and digest == provenance["stage2_sha256"]
    environment = os.environ.copy()
    environment["ENCORE_CORE_DIR"] = str(source / "packages/core")
    environment["ENCORE_REGISTRY_CACHE"] = str(source / "target/performance-registry")
    environment["ENCORE_CODEGEN_PROFILE"] = "1"
    log_path = output / f"{label}.log"
    report = output / f"{label}-report.json"
    command = [str(compiler), "test", "--filter", case, "--jobs", "1", "--report", str(report)]
    print(f"{label}: starting {case}; compiler={digest}", flush=True)
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(child.pid)], check=False)
            code = 124
    result = {"label": label, "seconds": round(time.perf_counter() - started, 3), "exit_code": code,
              "compiler_sha256": digest, "provenance_commit": provenance["commit"]}
    if report.exists():
        result["summary"] = json.loads(report.read_text())["summary"]
    results.append(result)
    print(json.dumps(result), flush=True)
    (output / "comparison.json").write_text(json.dumps({"platform": platform.platform(),
        "cpu_count": os.cpu_count(), "results": results}, indent=2))
    if code:
        print(log_path.read_text(encoding="utf-8", errors="replace")[-16000:], flush=True)
        raise SystemExit(code)
ratio = results[1]["seconds"] / results[0]["seconds"]
print(f"Candidate/baseline elapsed-time ratio on this runner: {ratio:.3f}", flush=True)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as stream:
        stream.write(f"Same test, same runner, one worker: baseline {results[0]['seconds']}s; "
                     f"candidate {results[1]['seconds']}s; ratio {ratio:.3f}.\n")
