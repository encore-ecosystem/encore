#!/usr/bin/env python3
"""Offline regression tests for build-once candidate selection."""

import importlib.util
import json
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
