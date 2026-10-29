#!/usr/bin/env python3
"""Measure sequential, paired build/test runs across a worker-count matrix.

Each cold sample uses a frozen source snapshot, empty output, and private
compiled/registry caches. The following warm sample reuses only that sample's
caches. Downloads and snapshot preparation are outside the measured interval.
No profiler is enabled and no user cache is modified.
"""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


CASES = ("owned_shadowing_lifetime", "lexer_lifetime", "parser_lifetime", "translator_lifetime")
PROJECT_CASES = ("app-std", "eight-deps")
SUBSET_CASES = (*CASES, "compiler_cache_identity", "function_lowering_cache", "native_object_cache", "lowering_cache_storage")


def workload_cases(scenario):
    return {"all": ["build", "suite"], "standalone": list(CASES),
            "projects": list(PROJECT_CASES)}.get(scenario, [scenario])


def prepare_project(root, source, case):
    """Prepare deterministic executable inputs without invoking a compiler."""
    (root / "src").mkdir(parents=True)
    dependencies = ["path@" + (source / "packages/std").as_posix()]
    imports = ["import std::io::println"]
    calls = []
    if case == "eight-deps":
        for index in range(8):
            package = root / f"dep-{index}"
            (package / "src").mkdir(parents=True)
            (package / "encore.toml").write_text(
                f'[project]\nname="bench_dep_{index}"\nversion="0.0.0"\ndependencies=[]\n')
            (package / "src/lib.enq").write_text(f'pub fn value() -> u32 {{ ret {index + 1}_u32 }}\n')
            dependencies.append(f"path@dep-{index}")
            imports.append(f"import bench_dep_{index}::value as value_{index}")
            calls.append(f"value_{index}()")
    total = " + ".join(calls) or "36_u32"
    (root / "encore.toml").write_text('[project]\nname="cold_benchmark"\nversion="1.2.3"\ndependencies=' + json.dumps(dependencies) + '\n')
    (root / "src/main.enq").write_text('\n'.join(imports) + '\nfn main() -> u32 { println(__project_name__ + "=" + __version__) '
        + 'ret if ' + total + ' == 36_u32 { 0_u32 } else { 1_u32 } }\n')


PROFILE_ENV = ("ENCORE_CODEGEN_PROFILE", "ENCORE_FRONTEND_PROFILE", "ENCORE_KEEP_TEMPS")


def find_bash(explicit=None, windows=None):
    """Native Windows fixtures require Git Bash, not the System32 WSL shim."""
    if explicit:
        candidate = shutil.which(str(explicit)) or str(explicit)
        if Path(candidate).is_file():
            return str(Path(candidate).resolve())
        raise FileNotFoundError("Bash executable does not exist: " + str(explicit))
    if windows is None:
        windows = os.name == "nt"
    if windows:
        git = shutil.which("git")
        if git:
            for root in Path(git).resolve().parents:
                for relative in ("bin/bash.exe", "usr/bin/bash.exe"):
                    candidate = root / relative
                    if candidate.is_file():
                        return str(candidate)
        raise FileNotFoundError("Git Bash was not found; specify --bash with its native executable path")
    candidate = shutil.which("bash")
    if candidate:
        return candidate
    raise FileNotFoundError("Bash was not found; specify --bash")


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_snapshot(source, destination, ref=None):
    """Copy source once, before timing; support a release tag without a worktree."""
    destination.mkdir(parents=True, exist_ok=True)
    if ref:
        archive = subprocess.check_output(["git", "-C", str(source), "archive", ref])
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(destination, filter="data")
        names = [str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()]
    else:
        names = os.fsdecode(subprocess.check_output([
            "git", "-C", str(source), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
        ])).split("\0")
        for name in sorted(set(names) - {""}):
            original = source / name
            if not original.is_file():
                continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    digest = hashlib.sha256()
    for name in sorted(set(names) - {""}):
        path = destination / name
        if path.is_file():
            digest.update(os.fsencode(name))
            digest.update(b"\0")
            digest.update(bytes.fromhex(digest_file(path)))
    return digest.hexdigest()


def prepare_snapshot_repository(snapshot):
    # The complete CI suite exercises Git-based candidate selection helpers.
    # Give it private metadata for this exact frozen tree, never the user's Git
    # directory or an index shared with another repetition.
    git = ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
           "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
           "-c", "user.name=Encore benchmark", "-c", "user.email=benchmark@example.invalid",
           "-C", str(snapshot)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "--force", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "Frozen benchmark input"], check=True)


def archive_snapshot(snapshot, archive_path):
    # Archive measured bytes rather than Git blobs: attributes or a Windows
    # autocrlf setting may normalize the private repository's object contents.
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(snapshot.iterdir()):
            if path.name != ".git":
                archive.add(path, arcname=path.name)


def machine_info():
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    cpu_count = os.cpu_count() or 1
    limit = affinity or cpu_count
    quotas = []
    roots = [Path("/sys/fs/cgroup")]
    membership = Path("/proc/self/cgroup")
    if membership.exists():
        for line in membership.read_text().splitlines():
            if line.startswith("0::"):
                roots.insert(0, roots[-1] / line[3:].lstrip("/"))
    memory_limits = []
    for root in roots:
        try:
            quota, period = (root / "cpu.max").read_text().split()
            if quota != "max":
                quotas.append(int(quota) / int(period))
        except (OSError, ValueError):
            pass
        try:
            value = (root / "memory.max").read_text().strip()
            if value != "max":
                memory_limits.append(int(value))
        except (OSError, ValueError):
            pass
    if quotas:
        limit = min(limit, max(1, math.ceil(min(quotas))))
    memory = None
    try:
        memory = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:"))) * 1024
    except (OSError, StopIteration, ValueError):
        pass
    tools = {}
    cpu_model = platform.processor()
    try:
        if sys.platform.startswith("linux"):
            cpu_model = next(line.split(":", 1)[1].strip() for line in
                             Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name"))
        elif sys.platform == "darwin":
            cpu_model = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                                text=True, timeout=5).strip()
    except (OSError, StopIteration, subprocess.SubprocessError):
        pass
    for name in ("clang", "ld.lld"):
        executable = shutil.which(name)
        if executable:
            try:
                version = subprocess.check_output([executable, "--version"], text=True,
                                                  stderr=subprocess.STDOUT, timeout=10)
                tools[name] = {"path": executable, "version": version.splitlines()[0]}
            except (subprocess.SubprocessError, OSError):
                pass
    return {
        "platform": platform.platform(), "architecture": platform.machine(),
        "processor": platform.processor(), "runner_name": os.environ.get("RUNNER_NAME"),
        "cpu_model": cpu_model,
        "runner_image": {key: os.environ.get(key) for key in ("ImageOS", "ImageVersion")},
        "logical_cpus": cpu_count, "affinity_cpus": affinity,
        "cpu_quota": min(quotas, default=None), "available_cpus": limit,
        "memory_bytes": memory, "cgroup_memory_limit_bytes": min(memory_limits, default=None),
        "python": platform.python_version(), "toolchains": tools,
    }


def job_matrix(value, available):
    """Coalesce equivalent requests, retaining a real automatic-mode invocation."""
    matrix = {}
    for token in value.split(","):
        token = token.strip()
        if token != "auto" and (not token.isdecimal() or int(token) < 1):
            raise ValueError("jobs must be positive integers or auto, separated by commas")
        effective = available if token == "auto" else min(int(token), available)
        item = matrix.setdefault(effective, {"jobs": token, "effective_jobs": effective, "aliases": []})
        if token not in item["aliases"]:
            item["aliases"].append(token)
        if token == "auto":
            item["jobs"] = token
    return list(matrix.values())


def terminate_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        # Native tools may create their own process groups. On Linux include
        # descendants explicitly before killing the coordinator's group.
        if sys.platform.startswith("linux"):
            parents = {}
            for entry in Path("/proc").iterdir():
                if entry.name.isdecimal():
                    try:
                        fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                        parents.setdefault(int(fields[1]), []).append(int(entry.name))
                    except (OSError, ValueError, IndexError):
                        pass
            descendants = []
            pending = [process.pid]
            while pending:
                children = parents.get(pending.pop(), [])
                descendants.extend(children)
                pending.extend(children)
            for pid in reversed(descendants):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def measure(arguments, root, environment, log, timeout):
    started = time.monotonic()
    usage = None
    timed_out = False
    with log.open("wb") as capture:
        process = subprocess.Popen(arguments, cwd=root, env=environment, stdout=capture,
                                   stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            if hasattr(os, "wait4"):
                while True:
                    pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        process.returncode = os.waitstatus_to_exitcode(status)
                        break
                    if time.monotonic() - started > timeout:
                        raise subprocess.TimeoutExpired(arguments, timeout)
                    time.sleep(0.02)
            else:
                process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_tree(process)
        except BaseException:
            terminate_tree(process)
            raise
    elapsed = time.monotonic() - started
    cpu = usage.ru_utime + usage.ru_stime if usage else None
    return {
        "wall_seconds": elapsed, "exit_code": process.returncode, "timed_out": timed_out,
        "cpu_seconds": cpu, "cpu_equivalents": cpu / elapsed if cpu is not None else None,
        # wait4 reports the maximum individual RSS, not simultaneous tree RSS.
        "max_process_rss_kib": (usage.ru_maxrss / (1024 if sys.platform == "darwin" else 1)) if usage else None,
        "log": str(log),
    }


def read_test_report(path, expected_count=None):
    document = json.loads(path.read_text(encoding="utf-8"))
    summary, records = document["summary"], document["tests"]
    names = sorted(record["id"] for record in records)
    if len(set(names)) != len(names):
        raise ValueError("duplicate test IDs in report")
    if (summary["selected"] != len(records) or summary["passed"] != len(records) or
            summary["failed"] != 0 or any(record["status"] != "passed" for record in records)):
        raise ValueError(f"incomplete or failing test report: {summary}")
    if not records or (expected_count is not None and len(records) != expected_count):
        raise ValueError(f"unexpected test count: {len(records)}")
    return summary, names


def disk_usage(root):
    """Measure outside timing; count allocated blocks separately from file bytes."""
    logical = allocated = files = 0
    for directory, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            logical += info.st_size
            allocated += getattr(info, "st_blocks", (info.st_size + 511) // 512) * 512
            files += 1
    return {"bytes": logical, "allocated_bytes": allocated, "files": files}


def preserve_failure_artifacts(root, destination):
    """Keep bounded worker diagnostics before the disposable workspace is removed."""
    remaining = 32 * 1024 * 1024
    skipped = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if not (path.name.endswith(".output.txt") or "diagnostics" in relative.parts):
            continue
        size = path.stat().st_size
        if size > remaining:
            skipped.append(str(relative))
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        remaining -= size
    if skipped:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "omitted-files.json").write_text(json.dumps(skipped, indent=2) + "\n", encoding="utf-8")


def summarize(samples):
    groups = {}
    for sample in samples:
        for kind in ("cold", "warm"):
            result = sample.get(kind)
            if result is not None and not result.get("error") and result["exit_code"] == 0:
                key = (sample["variant"], sample["case"], sample["effective_jobs"], kind)
                groups.setdefault(key, []).append(result["wall_seconds"])
    rows = []
    for (variant, case, jobs, kind), values in groups.items():
        row = {"variant": variant, "case": case, "jobs": jobs, "cache": kind,
               "repetitions": len(values), "median_seconds": statistics.median(values),
               "min_seconds": min(values), "max_seconds": max(values),
               "stdev_seconds": statistics.stdev(values) if len(values) > 1 else None}
        serial = groups.get((variant, case, 1, kind))
        baseline = groups.get(("baseline", case, jobs, kind))
        if serial:
            row["speedup_vs_one_worker"] = statistics.median(serial) / row["median_seconds"]
        if variant == "candidate" and baseline:
            row["speedup_vs_baseline"] = statistics.median(baseline) / row["median_seconds"]
        rows.append(row)
    return rows


def sample_key(sample):
    return sample["repetition"], sample["effective_jobs"], sample["case"], sample["variant"]


def sample_complete(sample, warm):
    return all(kind in sample and sample[kind].get("exit_code") == 0 and
               not sample[kind].get("error") and not sample[kind].get("timed_out")
               for kind in (("cold", "warm") if warm else ("cold",)))


def expected_sample_keys(report):
    scenario = report["scenario"]
    cases = workload_cases(scenario)
    first = report["first_repetition"]
    return {(repetition, jobs["effective_jobs"], case, variant)
            for repetition in range(first, first + report["repetitions"])
            for jobs in report["jobs"] for case in cases for variant in report["variants"]}


def validate_resume(previous, requested):
    for key in ("schema", "benchmark_script_sha256", "profile", "repetitions", "first_repetition", "jobs", "scenario", "warm"):
        if previous.get(key) != requested[key]:
            raise ValueError("resume configuration changed: " + key)
    if previous.get("failed"):
        raise ValueError("cannot resume a failed benchmark; use a new output after fixing the failure")
    for key in ("platform", "architecture", "cpu_model", "logical_cpus", "affinity_cpus", "cpu_quota", "toolchains"):
        if previous["environment"].get(key) != requested["environment"].get(key):
            raise ValueError("resume machine/toolchain changed: " + key)
    keys = [sample_key(sample) for sample in previous["samples"]]
    if len(keys) != len(set(keys)) or set(keys) - expected_sample_keys(previous):
        raise ValueError("resume report has duplicate or unrequested samples")


def markdown_report(report):
    lines = [
        "# Parallel compiler benchmarks", "",
        "Cold: empty project and private compiled/registry caches. Warm: the immediately following run.",
        "Source copying, downloads and toolchain inspection are outside the timed interval.",
        "RSS is a maximum individual process value, not simultaneous memory of all workers.", "",
        "| Compiler | Workload | Jobs | Cache | Runs | Median (s) | Min–max (s) | vs 1 job | vs baseline |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["summary"]:
        serial = f'{row["speedup_vs_one_worker"]:.2f}x' if "speedup_vs_one_worker" in row else "—"
        baseline = f'{row["speedup_vs_baseline"]:.2f}x' if "speedup_vs_baseline" in row else "—"
        lines.append(f'| {row["variant"]} | {row["case"]} | {row["jobs"]} | {row["cache"]} | '
                     f'{row["repetitions"]} | {row["median_seconds"]:.3f} | '
                     f'{row["min_seconds"]:.3f}–{row["max_seconds"]:.3f} | {serial} | {baseline} |')
    if report["failed"]:
        lines.extend(["", "Failures:", *["- " + item for item in report["failed"]]])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-compiler", type=Path)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--baseline-ref", help="Freeze baseline sources with git archive, e.g. v0.1.6-neumann")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("all", "build", "suite", "standalone", "projects", "subset", "incremental"), default="all")
    parser.add_argument("--project-root", type=Path, help="Graphene source root for an incremental edit/build session")
    parser.add_argument("--registry-seed", type=Path, default=Path.home()/".cache/encore/registry",
                        help="Installed registry snapshot copied into private incremental caches")
    parser.add_argument("--baseline-cache-seed", type=Path,
                        help="Copy an existing baseline warm cache before incremental warm-up; use fresh edit IDs")
    parser.add_argument("--candidate-cache-seed", type=Path,
                        help="Copy an existing candidate warm cache before incremental warm-up; use fresh edit IDs")
    parser.add_argument("--verify-clean", action="store_true",
                        help="After incremental samples, compare the candidate with an excluded clean build")
    parser.add_argument("--jobs")
    parser.add_argument("--profile", choices=("dev", "release", "extreme"))
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--first-repetition", type=int, default=1,
                        help="First repetition ID; preserves alternating pair order in separate CI jobs")
    parser.add_argument("--bash", default=os.environ.get("ENCORE_BENCHMARK_BASH"),
                        help="Native Git Bash executable on Windows; auto-detected beside Git otherwise")
    parser.add_argument("--resume", action="store_true", help="Resume complete pairs after interruption; retry partial pairs cold")
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--timeout", type=float, default=7200)
    parser.add_argument("--scratch-dir", type=Path,
                        default=Path(os.environ["RUNNER_TEMP"]) if os.environ.get("RUNNER_TEMP") else None,
                        help="Parent for disposable inputs; CI defaults to RUNNER_TEMP to keep Windows paths short")
    args = parser.parse_args()
    args.jobs = args.jobs or ("auto" if args.scenario == "incremental" else "1,2,4,8,16,auto")
    args.profile = args.profile or ("dev" if args.scenario == "incremental" else "extreme")
    args.repetitions = args.repetitions if args.repetitions is not None else (5 if args.scenario == "incremental" else 3)
    if args.repetitions < 1 or args.first_repetition < 1 or args.timeout <= 0:
        parser.error("repetitions, first repetition and timeout must be positive")
    if (args.baseline_source or args.baseline_ref or args.baseline_cache_seed) and not args.baseline_compiler:
        parser.error("baseline source/ref requires --baseline-compiler")
    if args.verify_clean and args.scenario != "incremental":
        parser.error("--verify-clean requires --scenario incremental")
    if args.scenario == "incremental":
        from compiler_incremental_benchmark import run
        try:
            return run(sys.modules[__name__], args)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            parser.exit(1, "incremental benchmark failed: " + str(error) + "\n")
    try:
        bash = find_bash(args.bash) if args.scenario in ("all", "suite", "subset") else None
    except FileNotFoundError as error:
        parser.error(str(error))
    machine = machine_info()
    try:
        # Encore's available_parallelism currently uses online logical CPUs,
        # not Python's affinity/cgroup budget. Report those restrictions
        # separately rather than mislabelling an automatic 16-worker run as 4.
        matrix = job_matrix(args.jobs, machine["logical_cpus"])
    except ValueError as error:
        parser.error(str(error))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    logs = output.with_suffix(".logs")
    if not args.resume and (output.exists() or logs.exists()):
        parser.error("output/logs already exist; choose a new --output path")
    if args.resume and output.exists() != logs.exists():
        parser.error("resume requires both the report and its raw-log directory")
    previous = json.loads(output.read_text(encoding="utf-8")) if args.resume and output.exists() else None
    logs.mkdir(exist_ok=args.resume)
    report = {
        "schema": 2, "environment": machine, "profile": args.profile,
        "benchmark_script_sha256": digest_file(Path(__file__)),
        "repetitions": args.repetitions, "first_repetition": args.first_repetition,
        "scenario": args.scenario, "warm": args.warm, "completed": False,
        "jobs": matrix, "variants": {},
        "cache_policy": "isolated empty output/compiled/registry caches per cold sample; OS buffers retained",
        "samples": [], "summary": [], "test_catalogs": {}, "failed": [],
    }
    if previous is not None:
        try:
            validate_resume(previous, report)
        except ValueError as error:
            parser.error(str(error))

    def save():
        report["summary"] = summarize(report["samples"])
        for row in report["summary"]:
            row["selected_tests"] = len(report["test_catalogs"].get(row["variant"] + "/" + row["case"], []))
        report["test_catalog_delta"] = {}
        for case in {key.split("/", 1)[1] for key in report["test_catalogs"]}:
            baseline = report["test_catalogs"].get("baseline/" + case)
            candidate = report["test_catalogs"].get("candidate/" + case)
            if baseline is not None and candidate is not None:
                report["test_catalog_delta"][case] = {
                    "baseline_only": sorted(set(baseline) - set(candidate)),
                    "candidate_only": sorted(set(candidate) - set(baseline)),
                }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")

    # The snapshots outlive all samples. Every measured invocation receives an
    # independent copy; preparation does not run a compiler or hydrate any cache.
    with tempfile.TemporaryDirectory(prefix="ecb-", dir=args.scratch_dir) as directory:
        scratch = Path(directory)
        variants = [("candidate", args.compiler.resolve(), args.source.resolve(), None)]
        if args.baseline_compiler:
            variants.insert(0, ("baseline", args.baseline_compiler.resolve(),
                               (args.baseline_source or args.source).resolve(), args.baseline_ref))
        frozen = {}
        for variant, compiler, source, ref in variants:
            snapshot = scratch / variant
            source_digest = source_snapshot(source, snapshot, ref)
            prepare_snapshot_repository(snapshot)
            revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", (ref or "HEAD") + "^{commit}"],
                                               text=True).strip()
            metadata = {
                "compiler": str(compiler), "compiler_sha256": digest_file(compiler),
                "compiler_version": subprocess.check_output([str(compiler), "--version"], text=True).strip(),
                "source_commit": revision, "source_snapshot_sha256": source_digest,
            }
            archive_path = logs / (variant + "-source.tar.gz")
            if previous is not None:
                old = previous["variants"].get(variant, {})
                for key in ("compiler_sha256", "compiler_version", "source_commit", "source_snapshot_sha256"):
                    if metadata[key] != old.get(key):
                        parser.error("resume input changed: " + variant + "/" + key)
                if not archive_path.is_file() or digest_file(archive_path) != old.get("source_archive_sha256"):
                    parser.error("resume source archive is missing or changed: " + variant)
            else:
                archive_snapshot(snapshot, archive_path)
            metadata.update(source_archive=str(archive_path), source_archive_sha256=digest_file(archive_path))
            report["variants"][variant] = metadata
            frozen[variant] = snapshot
        if previous is not None:
            if set(previous["variants"]) != set(report["variants"]):
                parser.error("resume compiler variants changed")
            report.update(samples=[], test_catalogs=previous["test_catalogs"],
                          interrupted_samples=previous.get("interrupted_samples", []),
                          resume_count=previous.get("resume_count", 0) + 1)
            for sample in previous["samples"]:
                if sample_complete(sample, args.warm):
                    report["samples"].append(sample)
                else:
                    report["interrupted_samples"].append(sample)
                    prefix = f"{sample['variant']}-{sample['case']}-j{sample['jobs']}-r{sample['repetition']}-"
                    interrupted = logs / ("interrupted-" + str(report["resume_count"]))
                    for path in logs.glob(prefix + "*"):
                        if path.is_file():
                            interrupted.mkdir(exist_ok=True)
                            shutil.move(str(path), interrupted / path.name)
        completed = {sample_key(sample) for sample in report["samples"]}
        workloads = workload_cases(args.scenario)
        save()
        for repetition in range(args.first_repetition, args.first_repetition + args.repetitions):
            # Alternate pair order to reduce systematic thermal/order bias.
            order = variants if repetition % 2 else list(reversed(variants))
            for configuration in matrix:
                for case in workloads:
                    for variant, compiler, _, _ in order:
                        sample = {"variant": variant, "case": case, "repetition": repetition,
                                  **configuration}
                        if sample_key(sample) in completed:
                            continue
                        report["samples"].append(sample)
                        save()
                        with tempfile.TemporaryDirectory(prefix="ecb-", dir=args.scratch_dir) as sample_dir:
                            private = Path(sample_dir)
                            root = private / "r"
                            shutil.copytree(frozen[variant], root)
                            environment = {k: v for k, v in os.environ.items() if k not in PROFILE_ENV}
                            environment.update({
                                "ENCORE_BUILD_CACHE": str(private / "c"),
                                "ENCORE_REGISTRY_CACHE": str(private / "g"),
                                "ENCORE_CORE_DIR": str(root / "packages/core"),
                                "ENCORE_INDEX_URL": "http://127.0.0.1:9/index",
                            })
                            if os.name == "nt":
                                environment["MSYS2_ARG_CONV_EXCL"] = "*"
                            if case in ("suite", "subset"):
                                environment.update(ENCORE_TEST_COMPILER=str(compiler),
                                                   ENCORE_TEST_REPOSITORY=str(root), CI_TEST_RUN_ID="compiler")
                            jobs = [] if configuration["jobs"] == "auto" else ["--jobs", configuration["jobs"]]
                            native_report = root / "target/test-report.json"
                            project = root
                            if case in PROJECT_CASES:
                                project = private / "project"
                                prepare_project(project, root, case)
                            if case == "build" or case in PROJECT_CASES:
                                arguments = [str(compiler), "build", "--profile", args.profile, "--timings", *jobs]
                            elif case in ("suite", "subset"):
                                # Use the variant's actual CI helper to prepare
                                # its fixture, but do not run a compiler or
                                # populate a compiled cache before cold timing.
                                noop = private / "prepare.sh"
                                # MSYS must receive LF and an absolute POSIX
                                # interpreter, without another native Bash lookup.
                                noop.write_bytes(b"#!/bin/sh\nexit 0\n")
                                noop.chmod(0o755)
                                preparation = logs / f"{variant}-suite-j{configuration['jobs']}-r{repetition}-prepare.log"
                                try:
                                    with preparation.open("wb") as capture:
                                        subprocess.run([bash, "scripts/ci-test.sh", noop.as_posix()],
                                                       cwd=root, env=environment, stdout=capture,
                                                       stderr=subprocess.STDOUT, check=True, timeout=60)
                                except (OSError, subprocess.SubprocessError) as error:
                                    sample["preparation_error"] = str(error)
                                    report["failed"].append(str(preparation) + ": " + str(error))
                                    save()
                                    return 1
                                arguments = [str(compiler), "test", "--report", str(native_report), *jobs]
                                if case == "subset":
                                    fixture = root / "target/ci-tests/compiler/tests"
                                    for selected in SUBSET_CASES:
                                        shutil.copy2(root / "tests" / (selected + ".enq"), fixture / ("benchmark_" + selected + ".enq"))
                                    arguments.extend(["--filter", "tests/benchmark_"])
                            else:
                                arguments = [str(compiler), "test", "--filter", f"tests/{case}.enq",
                                             "--report", str(native_report), *jobs]
                            for kind in ("cold", "warm") if args.warm else ("cold",):
                                label = f"{variant}-{case}-j{configuration['jobs']}-r{repetition}-{kind}"
                                cwd = root / "target/ci-tests/compiler" if case in ("suite", "subset") else project
                                # A failed invocation must never accidentally reuse a stale report.
                                native_report.unlink(missing_ok=True)
                                result = measure(arguments, cwd, environment, logs / (label + ".log"), args.timeout)
                                result["cache_disk"] = disk_usage(private / "c")
                                result["target_disk"] = disk_usage((project if case in PROJECT_CASES else root) / "target")
                                sample[kind] = result
                                print(f"{label}: {result['wall_seconds']:.3f}s exit={result['exit_code']}", flush=True)
                                try:
                                    if native_report.exists():
                                        shutil.copy2(native_report, logs / (label + ".json"))
                                    if result["exit_code"] != 0 or result["timed_out"]:
                                        raise ValueError("command failed or timed out; see raw log")
                                    if case != "build" and case not in PROJECT_CASES:
                                        summary, names = read_test_report(native_report, None if case == "suite" else (len(SUBSET_CASES) if case == "subset" else 1))
                                        result["test_summary"] = summary
                                        result["resolved_test_jobs"] = summary.get("jobs")
                                        key = variant + "/" + case
                                        previous = report["test_catalogs"].setdefault(key, names)
                                        if names != previous:
                                            raise ValueError("test selection changed across jobs/repetitions/cache modes")
                                    else:
                                        timing_path = project / "target" / args.profile / "encore-timings.json"
                                        if timing_path.exists():
                                            result["build_timings"] = json.loads(timing_path.read_text(encoding="utf-8"))
                                        name = "cold_benchmark" if case in PROJECT_CASES else "encore"
                                        binary = project / "target" / args.profile / (name + (".exe" if os.name == "nt" else ""))
                                        if not binary.is_file():
                                            raise ValueError("compiler build produced no executable")
                                        result["built_artifact_sha256" if case in PROJECT_CASES else "built_compiler_sha256"] = digest_file(binary)
                                        if case in PROJECT_CASES:
                                            actual = subprocess.check_output([str(binary)], text=True, timeout=30).strip()
                                            if actual != "cold_benchmark=1.2.3":
                                                raise ValueError("project executable produced incorrect output: " + actual)
                                        else:
                                            subprocess.run([str(binary), "--version"], check=True, stdout=subprocess.DEVNULL,
                                                           stderr=subprocess.DEVNULL, timeout=30)
                                except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                                    result["error"] = str(error)
                                    report["failed"].append(label + ": " + str(error))
                                    preserve_failure_artifacts(root, logs / (label + ".failure"))
                                    save()
                                    return 1
                                save()
    report["completed"] = True
    save()
    print(markdown_report(report))
    return bool(report["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
