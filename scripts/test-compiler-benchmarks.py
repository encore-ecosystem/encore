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

spec = importlib.util.spec_from_file_location("benchmark", Path(__file__).with_name("benchmark-compiler-tests.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


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
            environment = {**os.environ, "ENCORE_CODEGEN_PROFILE": "1"}
            result = subprocess.run([
                sys.executable, str(Path(benchmark.__file__)), str(compiler),
                "--source", str(repo), "--baseline-compiler", str(compiler),
                "--baseline-ref", "v0.1.6-neumann", "--scenario", "all",
                "--jobs", "1", "--repetitions", "1", "--warm", "--scratch-dir", str(scratch),
                "--output", str(output),
            ], env=environment, text=True, capture_output=True, timeout=30)
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
