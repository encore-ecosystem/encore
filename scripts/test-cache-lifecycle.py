#!/usr/bin/env python3
"""POSIX probes for interrupted builds, shared-cache writers and incremental GC."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    repository = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="encore-cache-lifecycle-") as directory:
        root = Path(directory)
        project = root / "project"
        (project / "src").mkdir(parents=True)
        (project / "encore.toml").write_text('[project]\nname="lifecycle_probe"\nversion="0.0.0"\ndependencies=[]\n')
        (project / "src/main.enq").write_text(''.join(f'fn helper_{i}() -> u32 {{ ret {i}_u32 }}\n' for i in range(500)) + 'fn main() -> u32 { ret 0_u32 }\n')
        cache = root / "cache"
        env = dict(os.environ, ENCORE_CORE_DIR=str(repository / "packages/core"), ENCORE_BUILD_CACHE=str(cache))
        command = [str(compiler), "build"]
        with (root / "interrupted.log").open("w") as log:
            process = subprocess.Popen(command, cwd=project, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                while not list((project / "target/dev").glob("packages-*")):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("build finished before its managed workspace could be observed")
                    time.sleep(0.01)
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        with (root / "concurrent.log").open("w") as log:
            children = [subprocess.Popen(command, cwd=project, env=env, stdout=log, stderr=log, start_new_session=True) for _ in range(2)]
            try:
                for child in children:
                    if child.wait(timeout=180):
                        raise RuntimeError((root / "concurrent.log").read_text())
            finally:
                for child in children:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
        binary = project / "target/dev/lifecycle_probe"
        subprocess.run([str(binary)], check=True, timeout=10)
        if list((project / "target/dev").glob("packages-*")):
            raise RuntimeError("a finished/interrupted managed workspace was not collected")
        outside = root / "outside"
        outside.mkdir()
        (outside / "keep").write_text("external payload")
        (cache / ("f" * 64)).symlink_to(outside, target_is_directory=True)
        entries = []
        for i in range(500):
            entry = cache / f"{i:064x}"
            entry.mkdir()
            (entry / "unit.complete").write_text("fixture")
            (entry / "payload").write_bytes(b"x" * 1024)
            (entry / ".last-used").write_text("1")
            entries.append(entry)
        locked = entries[0]
        lock_path = Path(str(locked) + ".lock")
        lock_path.touch(mode=0o600)
        with lock_path.open("r+") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            gc_env = dict(env, ENCORE_BUILD_CACHE_MAX_SIZE="0B")
            samples = []
            for _ in range(200):
                (cache / ".maintenance-last").write_text("0")
                started = time.monotonic()
                run = subprocess.run(command, cwd=project, env=gc_env, capture_output=True, text=True, timeout=30)
                samples.append(time.monotonic() - started)
                if run.returncode:
                    raise RuntimeError(run.stdout + run.stderr)
                if not locked.is_dir() or not (outside / "keep").is_file():
                    raise RuntimeError("maintenance removed a locked entry or followed a symlink")
                if not any(entry.exists() for entry in entries[1:]):
                    break
            else:
                state_path = cache / ".maintenance-scan.json"
                state = json.loads(state_path.read_text()) if state_path.is_file() else {}
                state = {key: state.get(key) for key in ("bucket", "offset", "bytes", "schema")}
                raise RuntimeError("incremental maintenance did not converge: " + json.dumps({"remaining": sum(entry.exists() for entry in entries[1:]), "state": state, "stamp": (cache / ".maintenance-last").read_text()}))
            if not ((cache / ".maintenance-scan.json").is_file() or (cache / ".maintenance-last").is_file()):
                raise RuntimeError("maintenance did not record progress")
        pruned = subprocess.run([str(compiler), "cache", "prune", "--all", "--json"], cwd=project, env=env, check=True, capture_output=True, text=True, timeout=30)
        if locked.exists() or not (outside / "keep").is_file():
            raise RuntimeError("explicit prune failed: " + json.dumps({"result": pruned.stdout, "locked_exists": locked.exists(), "outside_exists": (outside / "keep").is_file(), "locked_files": [p.name for p in locked.iterdir()] if locked.is_dir() else []}))
        print(json.dumps({"interrupted_and_concurrent_builds": "passed", "gc_resumes": len(samples),
                          "forced_gc_warm_max_ms": round(max(samples) * 1000),
                          "locks_and_external_symlink": "preserved"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
