"""Paired Graphene edit/build sessions with persistent, private warm caches."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tomllib


CASES = ("unchanged", "method-body", "main-body", "relocate", "interface", "css")
IGNORED = {".git", "target", "__pycache__", "node_modules", ".encore_cache", "artifacts", "bundles"}
PROBE = '''            if command == "__encore_bench_camera" {
                let mut camera = EditorCameraState::new("front", false)
                camera.look(100.0_f32, 0.0_f32, false)
                println(camera.yaw.fmt())
                ret 0_u32
            }
'''


def source_files(root):
    """Git inputs when root is a repository; also support plain path packages."""
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve():
        names = os.fsdecode(subprocess.check_output([
            "git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ])).split("\0")
        return sorted({Path(n) for n in names if n and (root / n).is_file()})
    names = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(n for n in subdirs if n not in IGNORED)
        for name in sorted(files):
            if name == ".env" or name.startswith(".env.") or name.endswith(".log"):
                continue
            path = Path(directory) / name
            if path.is_file():
                names.append(path.relative_to(root))
    return sorted(names)


def tree_digest(root):
    digest = hashlib.sha256()
    for name in source_files(root):
        path = root / name
        digest.update(os.fsencode(name.as_posix()) + b"\0")
        with path.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


def snapshot(root, destination):
    destination.mkdir(parents=True)
    for name in source_files(root):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, path)
    return tree_digest(destination)


def path_packages(project):
    pending, found = [project.resolve()], set()
    while pending:
        root = pending.pop()
        if root in found:
            continue
        found.add(root)
        manifest = tomllib.loads((root / "encore.toml").read_text())
        for reference in manifest["project"].get("dependencies", []):
            if reference.startswith("path@"):
                pending.append((root / reference[5:].split("[", 1)[0]).resolve())
    return sorted(found)


def ensure_probe(project):
    main = project / "src/main.enq"
    text = main.read_text()
    if 'command == "__encore_bench_camera"' not in text:
        anchor = '            if command == "import-character" {'
        if text.count(anchor) != 1:
            raise ValueError("Graphene CLI anchor changed; refusing to patch an unknown workload")
        main.write_text(text.replace(anchor, PROBE + anchor))


def edit(project, case, revision):
    """Every measured edit has new bytes, including across repetitions."""
    main = project / "src/main.enq"
    camera = project / "src/editor_camera.enq"
    if case == "unchanged":
        return
    if case == "method-body":
        text, count = re.subn(r"(self\.yaw = self\.yaw - delta_x \* )\d+\.\d+(_f32)",
                             lambda m: m[1] + f"0.{600 + revision:05d}" + m[2], camera.read_text())
        if count != 1:
            raise ValueError("Graphene camera coefficient anchor changed")
        camera.write_text(text)
    elif case == "main-body":
        text, count = re.subn(r'Usage: graphene cook <project directory>(?: \[encore-bench-[^"\n]+\])?',
                             f"Usage: graphene cook <project directory> [encore-bench-{revision}]", main.read_text())
        if count != 1:
            raise ValueError("Graphene cook message anchor changed")
        main.write_text(text)
    elif case == "relocate":
        text = main.read_text()
        text, count = re.subn(r"(?m)^fn main\(\) -> u32 \{", "\n\n\nfn main() -> u32 {", text)
        if count != 1:
            raise ValueError("Graphene main function anchor changed")
        main.write_text(text)
    elif case == "interface":
        text = camera.read_text()
        match = re.search(r"pub fn (look(?:_bench_\d+)?)\(self: mut Self,", text)
        if not match:
            raise ValueError("Graphene camera method anchor changed")
        old, new = match[1], f"look_bench_{revision}"
        camera.write_text(text.replace("pub fn " + old + "(", "pub fn " + new + "("))
        callers = main.read_text()
        if ("camera." + old + "(") not in callers:
            raise ValueError("Graphene camera caller anchor changed")
        main.write_text(callers.replace("camera." + old + "(", "camera." + new + "("))
    elif case == "css":
        path = project / "styles/theme.css"
        path.write_text(path.read_text() + f"\n.encore-benchmark-{revision} {{ opacity: 0.99; }}\n")
    else:
        raise ValueError("unknown incremental case: " + case)


def verify_binary(project, profile, coefficient, message):
    binary = project / "target" / profile / ("graphene.exe" if os.name == "nt" else "graphene")
    result = subprocess.run([str(binary), "__encore_bench_camera"], cwd=project,
                            capture_output=True, text=True, timeout=30)
    actual = float(result.stdout.strip())
    if result.returncode or not math.isfinite(actual) or abs(actual - (1.5707963 - 100 * coefficient)) > 0.00001:
        raise ValueError("stale or incorrect camera code: " + result.stdout + result.stderr)
    result = subprocess.run([str(binary), "cook"], cwd=project,
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 1 or result.stdout.strip() != message:
        raise ValueError("stale or incorrect main code: " + result.stdout + result.stderr)


def summarize(samples):
    groups = {}
    for sample in samples:
        if sample["role"] != "measurement" or sample["result"]["exit_code"] != 0:
            continue
        groups.setdefault((sample["variant"], sample["case"]), []).append(sample)
    rows = []
    for (variant, case), entries in sorted(groups.items()):
        times = [entry["result"]["wall_seconds"] for entry in entries]
        row = dict(variant=variant, case=case, repetitions=len(times),
                   median_seconds=statistics.median(times), min_seconds=min(times), max_seconds=max(times))
        rss = [e["result"].get("max_process_rss_kib") for e in entries]
        rss = [value for value in rss if value is not None]
        if rss:
            row["median_max_process_rss_kib"] = statistics.median(rss)
        if variant == "candidate" and ("baseline", case) in groups:
            before = {e["repetition"]: e for e in groups[("baseline", case)]}
            pairs = [(before[e["repetition"]]["result"]["wall_seconds"], e["result"]["wall_seconds"])
                     for e in entries if e["repetition"] in before]
            row.update(paired_samples=len(pairs),
                       paired_time_reduction_percent=statistics.median((a-b)/a*100 for a,b in pairs),
                       faster_pairs=sum(b<a for a,b in pairs))
        rows.append(row)
    return rows


def markdown(report):
    lines = ["# Incremental Graphene compilation", "",
             "Dev sessions preserve their private caches across unique source edits. Warm-up and diagnostics are excluded.", "",
             "| Compiler | Edit | Median, s | Paired reduction | Faster pairs |", "|---|---|---:|---:|---:|"]
    for row in report["summary"]:
        reduction = f'{row["paired_time_reduction_percent"]:+.2f}%' if "paired_time_reduction_percent" in row else "—"
        pairs = f'{row["faster_pairs"]}/{row["paired_samples"]}' if "paired_samples" in row else "—"
        lines.append(f'| {row["variant"]} | {row["case"]} | {row["median_seconds"]:.3f} | {reduction} | {pairs} |')
    return "\n".join(lines) + "\n"


def run(bench, args):
    if not args.project_root or args.resume:
        raise ValueError("incremental needs --project-root; interrupted sessions need a new --output")
    project = args.project_root.resolve()
    output = args.output.resolve()
    logs = output.with_suffix(".logs")
    if output.exists() or logs.exists():
        raise ValueError("output/logs already exist; choose a new --output")
    logs.mkdir(parents=True)
    inputs = logs / "inputs"
    roots = path_packages(project)
    common = Path(os.path.commonpath(roots))
    frozen = inputs / "workspace"
    workload = {}
    for root in roots:
        workload[str(root.relative_to(common))] = snapshot(root, frozen / root.relative_to(common))
    relative_project = project.relative_to(common)
    ensure_probe(frozen / relative_project)
    workload["instrumented_project_sha256"] = tree_digest(frozen / relative_project)
    registry = inputs / "registry"
    shutil.copytree(args.registry_seed.expanduser().resolve(), registry,
                    ignore=shutil.ignore_patterns("target", "__pycache__", "install.lock"))
    registries = {p["registry"] for p in tomllib.loads((project/"encore.lock").read_text())["packages"] if "registry" in p}
    if len(registries) != 1:
        raise ValueError("Graphene workload requires exactly one pinned registry")
    registry_url = registries.pop()
    machine = bench.machine_info()
    matrix = bench.job_matrix(args.jobs, machine["logical_cpus"])
    if len(matrix) != 1:
        raise ValueError("incremental takes one jobs setting per session (default: auto)")
    configuration = matrix[0]
    report = dict(schema=1, scenario="incremental", completed=False, profile=args.profile,
                  environment=machine, jobs=configuration, repetitions=args.repetitions,
                  first_repetition=args.first_repetition, workload=workload,
                  benchmark_script_sha256=bench.digest_file(Path(__file__)),
                  driver_script_sha256=bench.digest_file(Path(bench.__file__)),
                  registry_seed_sha256=tree_digest(registry), registry_url=registry_url,
                  memory_metric="wait4 maximum individual process RSS; not simultaneous process-tree RSS",
                  variants={}, samples=[], summary=[], failed=[])

    def save():
        report["summary"] = summarize(report["samples"])
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(output)
        output.with_suffix(".md").write_text(markdown(report))

    variants = [("candidate", args.compiler.resolve(), args.source.resolve(), None)]
    if args.baseline_compiler:
        variants.insert(0, ("baseline", args.baseline_compiler.resolve(),
                            (args.baseline_source or args.source).resolve(), args.baseline_ref))
    sessions = {}
    for name, compiler, source, ref in variants:
        compiler_source = inputs / (name + "-compiler")
        digest = bench.source_snapshot(source, compiler_source, ref) if ref else snapshot(source, compiler_source)
        workspace = logs / name / "workspace"
        shutil.copytree(frozen, workspace)
        private_registry = logs / name / "registry"
        shutil.copytree(registry, private_registry)
        environment = {k:v for k,v in os.environ.items() if k not in bench.PROFILE_ENV}
        environment.update(ENCORE_BUILD_CACHE=str(logs/name/"cache"),
                           ENCORE_REGISTRY_CACHE=str(private_registry),
                           ENCORE_CORE_DIR=str(compiler_source/"packages/core"), ENCORE_INDEX_URL=registry_url)
        sessions[name] = dict(compiler=compiler, project=workspace/relative_project, env=environment,
                              coefficient=0.006, message="Usage: graphene cook <project directory>")
        report["variants"][name] = dict(compiler_sha256=bench.digest_file(compiler),
                                        compiler_version=subprocess.check_output([str(compiler),"--version"],text=True).strip(),
                                        source_snapshot_sha256=digest)
        seed = args.baseline_cache_seed if name == "baseline" else args.candidate_cache_seed
        if seed:
            seed = seed.expanduser().resolve()
            shutil.copytree(seed, logs/name/"cache")
            report["variants"][name]["cache_seed_sha256"] = tree_digest(logs/name/"cache")
    save()

    def build(name, role, case, repetition, detailed):
        session = sessions[name]
        root = session["project"]
        label = f"{name}-{role}-r{repetition}-{case}"
        timing = root/"target"/args.profile/"encore-timings.json"
        timing.unlink(missing_ok=True)
        command = [str(session["compiler"]), "build", "--profile", args.profile]
        if configuration["jobs"] != "auto":
            command += ["--jobs",configuration["jobs"]]
        if detailed:
            command.append("--timings")
        source_digest = tree_digest(root)
        result = bench.measure(command, root, session["env"], logs/(label+".log"), args.timeout)
        sample = dict(variant=name, role=role, case=case, repetition=repetition,
                      source_sha256=source_digest, result=result)
        report["samples"].append(sample)
        save()
        print(f"{label}: {result['wall_seconds']:.3f}s exit={result['exit_code']}",flush=True)
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("build failed: " + str(logs/(label+".log")))
        if role != "warmup" and source_digest != tree_digest(root):
            raise ValueError("compiler changed workload inputs during measurement")
        verify_binary(root,args.profile,session["coefficient"],session["message"])
        sample["built_artifact_sha256"] = bench.digest_file(root/"target"/args.profile/("graphene.exe" if os.name=="nt" else "graphene"))
        if detailed:
            sample["timings"] = json.loads(timing.read_text())
        sample["cache_disk"] = bench.disk_usage(Path(session["env"]["ENCORE_BUILD_CACHE"]))
        sample["target_disk"] = bench.disk_usage(root/"target")
        save()

    try:
        for name,_,_,_ in variants:
            build(name,"warmup","initial",0,True)
        for offset in range(args.repetitions+1):
            repetition = args.first_repetition + offset
            diagnostic = offset == args.repetitions
            role = "diagnostic" if diagnostic else "measurement"
            order = variants if repetition % 2 else list(reversed(variants))
            for name,_,_,_ in order:
                session = sessions[name]
                for case in CASES:
                    edit(session["project"],case,repetition)
                    if case == "method-body":
                        session["coefficient"] = float(f"0.{600+repetition:05d}")
                    elif case == "main-body":
                        session["message"] = f"Usage: graphene cook <project directory> [encore-bench-{repetition}]"
                    build(name,role,case,repetition,diagnostic)
        if args.verify_clean:
            session = sessions["candidate"]
            root = session["project"]
            binary = root/"target"/args.profile/("graphene.exe" if os.name=="nt" else "graphene")
            expected = bench.digest_file(binary)
            shutil.move(root/"target", logs/"candidate/incremental-target")
            session["env"]["ENCORE_BUILD_CACHE"] = str(logs/"candidate/clean-cache")
            build("candidate", "verification", "clean", repetition, True)
            actual = bench.digest_file(binary)
            if actual != expected:
                raise ValueError("clean and incremental Graphene binaries differ")
            report["clean_equivalence"] = dict(incremental_sha256=expected, clean_sha256=actual,
                                                byte_identical=True)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        report["failed"].append(str(error));save();raise
    report["completed"] = True
    save()
    print(markdown(report))
    return 0
