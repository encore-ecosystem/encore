#!/usr/bin/env python3
"""Offline regression tests for build-once candidate selection."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("candidate", Path(__file__).with_name("select-ci-candidate.py"))
candidate = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=42, conclusion="success", head_repository={"full_name": "org/repo"},
                        event="pull_request", head_branch="feature", head_sha="head")
        self.pr = dict(merged_at="now", base={"ref": "trunk"},
                       head={"sha": "head", "repo": {"full_name": "org/repo"}})

    def choose(self, tree="tree", expired=False, identity=True, complete=True):
        names = set(candidate.REQUIRED)
        if not complete:
            names.pop()
        if identity:
            names.add("build-identity")

        def api(path):
            if path.endswith("/pulls"):
                return [self.pr]
            if "workflows/ci.yml/runs" in path:
                return {"workflow_runs": [self.run]}
            if "/artifacts?" in path:
                return {"artifacts": [dict(name=name, expired=expired) for name in names]}
            if "/git/commits/" in path:
                return {"tree": {"sha": tree}}
            raise AssertionError(path)

        def download(args, **kwargs):
            directory = Path(args[args.index("--dir") + 1])
            (directory / "build-identity.json").write_text(json.dumps(dict(commit="synthetic", tree=tree)))

        with patch.object(candidate, "api", side_effect=api), \
                patch.object(candidate.subprocess, "check_output", return_value="tree\n"), \
                patch.object(candidate.subprocess, "run", side_effect=download):
            return candidate.select("org/repo", "merged")

    def test_identical_merge_tree_preserves_original_commit(self):
        self.assertEqual(self.choose(), ("42", "synthetic"))

    def test_changed_tree_rebuilds(self):
        self.assertEqual(self.choose(tree="different"), ("", ""))

    def test_expired_missing_and_legacy_artifacts_rebuild(self):
        for options in (dict(expired=True), dict(identity=False), dict(complete=False)):
            with self.subTest(options=options):
                self.assertEqual(self.choose(**options), ("", ""))

    def test_unmerged_fork_failed_and_old_head_are_rejected(self):
        for location, key, value in ((self.pr, "merged_at", None),
                                     (self.run, "head_repository", {"full_name": "fork/repo"}),
                                     (self.run, "conclusion", "failure"),
                                     (self.run, "head_sha", "old")):
            old = location[key]
            location[key] = value
            self.assertEqual(self.choose(), ("", ""))
            location[key] = old

    def test_exact_trunk_build_works_without_identity(self):
        self.run.update(event="push", head_branch="trunk", head_sha="merged")
        self.assertEqual(self.choose(identity=False), ("42", "merged"))

    def test_lightweight_skipped_trunk_run_is_not_candidate(self):
        self.run.update(event="push", head_branch="trunk", head_sha="merged")
        self.assertEqual(self.choose(complete=False), ("", ""))

    def test_release_and_ci_targets_match_without_intel_macos(self):
        root = Path(__file__).resolve().parents[1]
        ci = (root / ".github/workflows/ci.yml").read_text()
        release = (root / ".github/workflows/release.yml").read_text()
        expected = set(candidate.TARGETS)
        self.assertEqual(len(expected), 6)
        self.assertNotIn("x86_64-apple-darwin", expected)
        self.assertIn("aarch64-apple-darwin", expected)
        for workflow in (ci, release):
            self.assertNotIn("x86_64-apple-darwin", workflow)
            self.assertNotIn("darwin-intel", workflow)
            self.assertNotIn("macos-15-intel", workflow)
        # Both convergence and testing must cover every published platform.
        triples = re.findall(r"^\s+triple: (\S+)$", ci, re.MULTILINE)
        self.assertEqual(set(triples), expected)
        self.assertIn(f"length == {len(expected)} and", release)
        for triple in expected:
            self.assertEqual(triples.count(triple), 2)
        promotion_lists = re.findall(r"for triple in \\\n(.*?)\n\s+do", release, re.DOTALL)
        self.assertEqual(len(promotion_lists), 2)
        for entries in promotion_lists:
            self.assertEqual(set(entries.replace("\\", "").split()), expected)

    @unittest.skipIf(os.name == "nt", "POSIX installer")
    def test_installer_rejects_intel_macos_before_downloading(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="encore-platform-") as directory:
            scratch = Path(directory)
            uname = scratch / "uname"
            uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Darwin ;; -m) echo x86_64 ;; *) exit 1 ;; esac\n')
            uname.chmod(0o755)
            curl = scratch / "curl"
            curl.write_text('#!/bin/sh\nprintf "download attempted\\n" >&2\nexit 99\n')
            curl.chmod(0o755)
            result = subprocess.run(
                ["sh", str(root / "install.sh"), "--install-dir", str(scratch / "installation")],
                env={**os.environ, "PATH": str(scratch) + os.pathsep + os.environ["PATH"]},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result)
            self.assertIn("Apple Silicon", result.stderr)
            self.assertNotIn("download attempted", result.stderr)
            self.assertFalse((scratch / "installation").exists())


if __name__ == "__main__":
    unittest.main()
