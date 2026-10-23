#!/usr/bin/env python3
"""Contracts for reproducible benchmark inputs, reports and process cleanup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from unittest import mock
import copy

spec = importlib.util.spec_from_file_location("benchmark", Path(__file__).with_name("benchmark-compiler-tests.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
aggregate_spec = importlib.util.spec_from_file_location("aggregate", Path(__file__).with_name("aggregate-compiler-benchmarks.py"))
aggregate = importlib.util.module_from_spec(aggregate_spec)
aggregate_spec.loader.exec_module(aggregate)


class BenchmarkContracts(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_paired_cli_preserves_cold_warm_isolation_and_complete_suite_context(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, scratch = base / "repo", base / "scratch"
            (repo / "scripts").mkdir(parents=True)
            scratch.mkdir()
            (repo / ".gitignore").write_text("target/\n")
            compiler = repo / "fake-encore"
            compiler.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json,os,pathlib,shutil,subprocess,sys
                args=sys.argv[1:]
                if args==['--version']:
                    print('encore benchmark-fixture');sys.exit(0)
                with open(os.environ['BENCHMARK_FIXTURE_TRACE'],'a') as trace:
                    trace.write(args[0]+'\\n')
                assert 'ENCORE_CODEGEN_PROFILE' not in os.environ
                assert args[args.index('--jobs')+1]=='1'
                subprocess.run(['git','rev-parse','--is-inside-work-tree'],check=True,stdout=subprocess.DEVNULL)
                cache=pathlib.Path(os.environ['ENCORE_BUILD_CACHE']);cache.mkdir(exist_ok=True)
                marker=cache/args[0];count=int(marker.read_text()) if marker.exists() else 0
                assert count in (0,1)
                marker.write_text(str(count+1))
                if args[0]=='build':
                    out=pathlib.Path('target/extreme');out.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(__file__,out/'encore')
                    (out/'encore-timings.json').write_text(json.dumps({'cache_hit':bool(count)}))
                else:
                    assert os.environ['ENCORE_TEST_COMPILER']
                    assert (pathlib.Path(os.environ['ENCORE_TEST_REPOSITORY'])/'.git').is_dir()
                    report=pathlib.Path(args[args.index('--report')+1]);report.parent.mkdir(exist_ok=True,parents=True)
                    report.write_text(json.dumps({'summary':{'selected':2,'passed':2,'failed':0,'duration_ms':2000},
                                                 'tests':[{'id':'first','status':'passed'},{'id':'second','status':'passed'}]}))
                """))
            compiler.chmod(0o755)
            (repo / "scripts/ci-test.sh").write_text(
                '#!/usr/bin/env bash\nset -eu\nroot=$PWD\nprogram=$1\nshift\nmkdir -p target/ci-tests/compiler\n'
                'cd target/ci-tests/compiler\nexec "$program" test --report "$root/target/test-report.json" "$@"\n')
            git = ["git", "-c", "commit.gpgsign=false", "-c", "user.name=Fixture",
                   "-c", "user.email=fixture@example.invalid", "-C", str(repo)]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "."], check=True)
            subprocess.run([*git, "commit", "-qm", "fixture"], check=True)
            subprocess.run([*git, "tag", "-am", "baseline", "v0.1.6-neumann"], check=True)
            commit = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
            output = base / "results.json"
            trace = base / "trace"
            environment = {**os.environ, "ENCORE_CODEGEN_PROFILE": "1", "BENCHMARK_FIXTURE_TRACE": str(trace)}
            command = [
                sys.executable, str(Path(benchmark.__file__)), str(compiler),
                "--source", str(repo), "--baseline-compiler", str(compiler),
                "--baseline-ref", "v0.1.6-neumann", "--scenario", "all",
                "--jobs", "1", "--repetitions", "1", "--warm", "--scratch-dir", str(scratch),
                "--output", str(output),
            ]
            result = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["failed"], [])
            self.assertEqual(len(report["samples"]), 4)
            self.assertEqual(len(report["summary"]), 8)
            self.assertEqual(report["variants"]["baseline"]["source_commit"], commit)
            for sample in report["samples"]:
                if sample["case"] == "build":
                    self.assertFalse(sample["cold"]["build_timings"]["cache_hit"])
                    self.assertTrue(sample["warm"]["build_timings"]["cache_hit"])
                else:
                    self.assertEqual(sample["warm"]["test_summary"]["selected"], 2)
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertTrue(output.with_suffix(".md").exists())
            self.assertTrue(report["completed"])
            self.assertEqual(len(trace.read_text().splitlines()), 8)
            # A reboot loses the private caches. Retry the entire incomplete
            # cold/warm pair, while retaining the other three completed pairs.
            report["samples"][-1].pop("warm")
            report["completed"] = False
            output.write_text(json.dumps(report))
            resumed = subprocess.run([*command, "--resume"], env=environment, text=True,
                                     capture_output=True, timeout=30)
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            report = json.loads(output.read_text())
            self.assertTrue(report["completed"])
            self.assertEqual(len(report["samples"]), 4)
            self.assertEqual(len(report["interrupted_samples"]), 1)
            self.assertEqual(len(trace.read_text().splitlines()), 10)
            self.assertTrue((output.with_suffix(".logs") / "interrupted-1").is_dir())
            already_done = subprocess.run([*command, "--resume"], env=environment, capture_output=True, timeout=30)
            self.assertEqual(already_done.returncode, 0, already_done.stderr)
            self.assertEqual(len(trace.read_text().splitlines()), 10)
            ci = base / "ci"
            (ci / "r1").mkdir(parents=True)
            (ci / "r1/results.json").write_text(output.read_text())
            for repetition in (2, 3):
                paired = list(command)
                paired[paired.index("--output") + 1] = str(ci / f"r{repetition}/results.json")
                pair = subprocess.run([*paired, "--first-repetition", str(repetition)], env=environment,
                                      text=True, capture_output=True, timeout=30)
                self.assertEqual(pair.returncode, 0, pair.stdout + pair.stderr)
                data = json.loads((ci / f"r{repetition}/results.json").read_text())
                self.assertEqual({sample["repetition"] for sample in data["samples"]}, {repetition})
                self.assertEqual(data["samples"][0]["variant"], "candidate" if repetition == 2 else "baseline")
            combined = base / "combined.json"
            aggregation = subprocess.run([sys.executable, aggregate.__file__, str(ci),
                                          "--output", str(combined)], text=True, capture_output=True, timeout=30)
            self.assertEqual(aggregation.returncode, 0, aggregation.stdout + aggregation.stderr)
            combined_report = json.loads(combined.read_text())
            self.assertTrue(combined_report["completed"])
            self.assertTrue(all(row["repetitions"] == 3 for row in combined_report["summary"]))
            self.assertEqual(len(trace.read_text().splitlines()), 26)
            (repo / "changed.enq").write_text("changed input")
            changed = subprocess.run([*command, "--resume"], env=environment, text=True,
                                     capture_output=True, timeout=30)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("resume input changed", changed.stderr)
            self.assertEqual(len(trace.read_text().splitlines()), 26)

    def test_windows_shell_selection_uses_git_bash_instead_of_the_wsl_shim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git, bash, wsl = root / "Git/cmd/git.exe", root / "Git/bin/bash.exe", root / "Windows/System32/bash.exe"
            for path in (git, bash, wsl):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with mock.patch.object(benchmark.shutil, "which", side_effect=lambda name: str(git if name == "git" else wsl)):
                self.assertEqual(benchmark.find_bash(windows=True), str(bash))
                bash.unlink()
                with self.assertRaises(FileNotFoundError):
                    benchmark.find_bash(windows=True)

    def test_ci_aggregation_uses_within_runner_ratios_and_rejects_incomplete_reports(self):
        documents = []
        for repetition, before, after in ((1, 10, 5), (2, 1000, 500), (3, 30, 20)):
            document = {
                "schema": 2, "completed": True, "first_repetition": repetition, "repetitions": 1,
                "benchmark_script_sha256": "same benchmark protocol",
                "profile": "extreme", "scenario": "suite", "warm": True,
                "environment": {"architecture": "test", "logical_cpus": 4, "runner_name": str(repetition)},
                "jobs": [{"effective_jobs": 4, "jobs": "auto", "aliases": ["auto"]}],
                "variants": {name: {"compiler_sha256": name, "compiler_version": name,
                                    "source_commit": name, "source_snapshot_sha256": name}
                             for name in ("baseline", "candidate")},
                "test_catalogs": {"baseline/suite": ["a"], "candidate/suite": ["a", "b"]},
                "samples": [], "failed": [],
            }
            for variant, seconds in (("baseline", before), ("candidate", after)):
                document["samples"].append({
                    "variant": variant, "case": "suite", "repetition": repetition, "effective_jobs": 4,
                    "cold": {"exit_code": 0, "wall_seconds": seconds},
                    "warm": {"exit_code": 0, "wall_seconds": seconds / 10},
                })
            documents.append(document)
        result = aggregate.aggregate(documents, 3)
        row = next(row for row in result["summary"] if row["variant"] == "candidate" and row["cache"] == "cold")
        self.assertEqual(row["speedup_vs_baseline"], 2)
        self.assertEqual(row["ratio_of_time_medians"], 1.5)
        self.assertEqual(len(result["environments"]), 3)
        for damage in ("completed", "source", "catalog", "missing", "duplicate", "repetition", "workers"):
            broken = copy.deepcopy(documents)
            if damage == "completed": broken[1]["completed"] = False
            elif damage == "source": broken[1]["variants"]["candidate"]["source_snapshot_sha256"] = "changed"
            elif damage == "catalog": broken[1]["test_catalogs"]["candidate/suite"] = ["a"]
            elif damage == "missing": broken[1]["samples"].pop()
            elif damage == "duplicate": broken[1]["samples"].append(copy.deepcopy(broken[1]["samples"][0]))
            elif damage == "repetition": broken[1]["first_repetition"] = 1
            elif damage == "workers": broken[1]["environment"]["logical_cpus"] = 2
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                aggregate.aggregate(broken, 3)

    def test_matrix_runs_automatic_mode_and_coalesces_clipped_requests(self):
        matrix = benchmark.job_matrix("1,2,4,8,16,auto", 4)
        self.assertEqual([row["effective_jobs"] for row in matrix], [1, 2, 4])
        self.assertEqual(matrix[-1]["jobs"], "auto")
        self.assertEqual(matrix[-1]["aliases"], ["4", "8", "16", "auto"])
        for invalid in ("0", "-2", "", "2,", "automatic"):
            with self.assertRaises(ValueError):
                benchmark.job_matrix(invalid, 4)

    def test_snapshot_includes_untracked_binary_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, snapshot = root / "repo", root / "snapshot"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / ".gitignore").write_text("target/\n")
            (source / "tracked.enq").write_text("old")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            (source / "tracked.enq").write_text("edited")
            (source / ".gitattributes").write_text("*.enq text\n")
            (source / "crlf.enq").write_bytes(b"first\r\nsecond\r\n")
            (source / "добавлен файл").write_bytes(b"payload\0\xff")
            (source / "target").mkdir()
            (source / "target/cache").write_text("must not copy")
            digest = benchmark.source_snapshot(source, snapshot)
            self.assertEqual((snapshot / "добавлен файл").read_bytes(), b"payload\0\xff")
            self.assertEqual((snapshot / "tracked.enq").read_text(), "edited")
            self.assertFalse((snapshot / "target").exists())
            benchmark.prepare_snapshot_repository(snapshot)
            self.assertEqual(subprocess.check_output(["git", "-C", str(snapshot), "show",
                                                       "HEAD:tracked.enq"]), b"edited")
            self.assertFalse(os.path.samefile(source / ".git/index", snapshot / ".git/index"))
            # Git text attributes normalize this blob, but a reproducible
            # benchmark archive must preserve the bytes actually measured.
            self.assertEqual(subprocess.check_output(["git", "-C", str(snapshot), "show",
                                                       "HEAD:crlf.enq"]), b"first\nsecond\n")
            archive_path = root / "source.tar.gz"
            benchmark.archive_snapshot(snapshot, archive_path)
            with tarfile.open(archive_path) as archive:
                self.assertEqual(archive.extractfile("crlf.enq").read(), b"first\r\nsecond\r\n")
                self.assertEqual(archive.extractfile("добавлен файл").read(), b"payload\0\xff")
                self.assertFalse(any(name.startswith(".git/") for name in archive.getnames()))
            (source / "tracked.enq").write_text("changed again")
            self.assertNotEqual(digest, benchmark.source_snapshot(source, root / "second"))

    def test_missing_duplicate_or_failed_tests_cannot_be_benchmarked_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            document = {"summary": {"selected": 2, "passed": 2, "failed": 0},
                        "tests": [{"id": "a", "status": "passed"}, {"id": "b", "status": "passed"}]}
            path.write_text(json.dumps(document))
            self.assertEqual(benchmark.read_test_report(path)[1], ["a", "b"])
            document["tests"][1]["id"] = "a"
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                benchmark.read_test_report(path)
            document["tests"].pop()
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                benchmark.read_test_report(path)
            document["summary"] = {"selected": 1, "passed": 0, "failed": 1}
            document["tests"][0]["status"] = "failed"
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                benchmark.read_test_report(path)

    def test_process_failure_is_recorded_with_its_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = benchmark.measure([sys.executable, "-c", "print('compiler diagnostic');exit(7)"],
                                       root, os.environ.copy(), root / "run.log", 10)
            self.assertEqual(result["exit_code"], 7)
            self.assertFalse(result["timed_out"])
            self.assertIn("compiler diagnostic", (root / "run.log").read_text())

    @unittest.skipIf(os.name == "nt", "POSIX process groups; Windows uses taskkill /T")
    def test_timeout_stops_children_as_well_as_the_coordinator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = "import time,pathlib;time.sleep(0.8);pathlib.Path('orphan').write_text('bad')"
            parent = (f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}],"
                      f"start_new_session={sys.platform.startswith('linux')!r});time.sleep(10)")
            result = benchmark.measure([sys.executable, "-c", parent], root, os.environ.copy(),
                                       root / "timeout.log", 0.15)
            self.assertTrue(result["timed_out"])
            subprocess.run([sys.executable, "-c", "import time;time.sleep(1)"], check=True)
            self.assertFalse((root / "orphan").exists())

    def test_summary_separates_parallel_elapsed_time_from_serial_and_failed_samples(self):
        samples = []
        for variant, jobs, seconds in [("baseline", 1, 20), ("baseline", 4, 8),
                                       ("candidate", 1, 12), ("candidate", 4, 4)]:
            samples.append({"variant": variant, "case": "suite", "effective_jobs": jobs,
                            "cold": {"wall_seconds": seconds, "exit_code": 0}})
        samples.append({"variant": "candidate", "case": "suite", "effective_jobs": 4,
                        "cold": {"wall_seconds": 0.1, "exit_code": 1}})
        rows = benchmark.summarize(samples)
        candidate = next(row for row in rows if row["variant"] == "candidate" and row["jobs"] == 4)
        self.assertEqual(candidate["speedup_vs_one_worker"], 3)
        self.assertEqual(candidate["speedup_vs_baseline"], 2)
        self.assertEqual(candidate["repetitions"], 1)


if __name__ == "__main__":
    unittest.main()
