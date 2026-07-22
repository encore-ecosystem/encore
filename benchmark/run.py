#!/usr/bin/env python3
"""Build and benchmark equivalent Encore and Rust programs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
ENCORE_ROOT = ROOT / "encore"
RUST_MANIFEST = ROOT / "rust" / "Cargo.toml"
RUST_TARGET = ROOT / "target" / "rust"
BENCHMARKS = (
    "arithmetic",
    "recursive",
    "vector",
    "mandelbrot",
    "spectral_norm",
    "binary_trees",
    "nbody",
)


def command_text(command: list[str]) -> str:
    return " ".join(command)


def run_checked(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print(f"command failed: {command_text(command)}", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise SystemExit(result.returncode)
    return result


def timed_command(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> tuple[float, str]:
    started = time.perf_counter_ns()
    result = run_checked(command, cwd=cwd, env=env)
    elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
    return elapsed, result.stdout.strip()


def build_encore(name: str, compiler: Path) -> tuple[float, Path]:
    project = ENCORE_ROOT / name
    target = project / "target"
    shutil.rmtree(target, ignore_errors=True)
    elapsed, _ = timed_command(
        [str(compiler), "build", "--profile", "extreme"], cwd=project
    )
    binary = target / "extreme" / name
    if not binary.is_file():
        raise SystemExit(f"Encore build did not produce {binary}")
    return elapsed, binary


def build_rust(name: str) -> tuple[float, Path]:
    target = RUST_TARGET / name
    shutil.rmtree(target, ignore_errors=True)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    elapsed, _ = timed_command(
        ["cargo", "build", "--quiet", "--release", "--bin", name],
        cwd=ROOT / "rust",
        env=env,
    )
    binary = target / "release" / name
    if not binary.is_file():
        raise SystemExit(f"Rust build did not produce {binary}")
    return elapsed, binary


def existing_binaries(name: str) -> tuple[Path, Path]:
    encore = ENCORE_ROOT / name / "target" / "extreme" / name
    rust = RUST_TARGET / name / "release" / name
    for binary in (encore, rust):
        if not binary.is_file():
            raise SystemExit(f"missing {binary}; run without --skip-build first")
    return encore, rust


def measure(binary: Path, runs: int) -> tuple[list[float], str]:
    samples: list[float] = []
    expected = ""
    for _ in range(runs):
        elapsed, output = timed_command([str(binary)], cwd=binary.parent)
        if expected and output != expected:
            raise SystemExit(f"unstable output from {binary}: {output!r} != {expected!r}")
        expected = output
        samples.append(elapsed)
    return samples, expected


def milliseconds(seconds: float) -> str:
    return f"{seconds * 1000.0:.3f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench",
        action="append",
        choices=BENCHMARKS,
        dest="benchmarks",
        help="benchmark to run; may be repeated (default: all)",
    )
    parser.add_argument("--runs", type=int, default=7, help="runtime samples (default: 7)")
    parser.add_argument(
        "--skip-build", action="store_true", help="reuse previously built binaries"
    )
    parser.add_argument(
        "--encore-bin",
        type=Path,
        default=REPOSITORY / "target" / "extreme" / "encore",
        help="path to the Encore compiler",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    return args


def main() -> int:
    args = parse_args()
    names = args.benchmarks or list(BENCHMARKS)
    compiler = args.encore_bin.expanduser().resolve()

    if not args.skip_build and not compiler.is_file():
        raise SystemExit(f"Encore compiler not found: {compiler}")
    if not args.skip_build and shutil.which("cargo") is None:
        raise SystemExit("cargo was not found in PATH")

    print(f"Benchmarks: {', '.join(names)}")
    print(f"Runtime samples: {args.runs}\n")
    print(
        f"{'benchmark':<12} {'build Encore':>14} {'build Rust':>12} "
        f"{'run Encore':>13} {'run Rust':>11} {'E/R':>8}"
    )
    print("-" * 77)

    for name in names:
        if args.skip_build:
            encore_binary, rust_binary = existing_binaries(name)
            encore_build = rust_build = None
        else:
            encore_build, encore_binary = build_encore(name, compiler)
            rust_build, rust_binary = build_rust(name)

        encore_samples, encore_output = measure(encore_binary, args.runs)
        rust_samples, rust_output = measure(rust_binary, args.runs)
        if encore_output != rust_output:
            raise SystemExit(
                f"checksum mismatch for {name}: "
                f"Encore={encore_output!r}, Rust={rust_output!r}"
            )

        encore_median = statistics.median(encore_samples)
        rust_median = statistics.median(rust_samples)
        ratio = encore_median / rust_median if rust_median else float("inf")
        encore_build_text = "reused" if encore_build is None else milliseconds(encore_build)
        rust_build_text = "reused" if rust_build is None else milliseconds(rust_build)
        print(
            f"{name:<12} {encore_build_text:>14} {rust_build_text:>12} "
            f"{milliseconds(encore_median):>13} {milliseconds(rust_median):>11} "
            f"{ratio:>7.2f}x"
        )
        print(f"  checksum: {encore_output}")

    print("\nTimes are milliseconds; runtime columns are medians.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
