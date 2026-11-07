#!/usr/bin/env python3
"""Exercise recursive source exports and the SDK provenance/release boundary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import sdk_packages as sdk


class SdkPackagesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="encore SDK ")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.origin = self.directory / "SDK upstream"
        self.root = self.directory / "compiler"
        self.initialize(self.origin)
        self.write(self.origin, "encore.toml", b'[project]\nname="core"\nversion="1.0.0"\n')
        self.write(self.origin, "src/lib.enq", b"pub fn value() -> u32 { ret 1_u32 }\n")
        self.write(self.origin, "runtime.c", b"int runtime(void) { return 1; }\n")
        self.write(self.origin, "native.h", b"int runtime(void);\n")
        self.write(self.origin, "build.enq", b"fn main() -> u32 { ret 0_u32 }\n")
        self.write(self.origin, ".gitignore", b"target/\n")
        self.commit(self.origin)
        self.first = self.run_git(self.origin, "rev-parse", "HEAD").strip()
        self.initialize(self.root)
        self.write(self.root, "encore.toml", b'[project]\nname="compiler"\nversion="1.0.0"\n')
        self.run_git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", "--quiet",
                     str(self.origin), "packages/core")
        self.commit(self.root)
        self.parent = self.run_git(self.root, "rev-parse", "HEAD").strip()
        self.child = self.root / "packages/core"

    def run_git(self, root, *args):
        command = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
                   "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false",
                   "-c", "user.name=Encore SDK tests", "-c", "user.email=sdk@example.invalid",
                   "-C", str(root), *args]
        return subprocess.check_output(command, stderr=subprocess.PIPE, text=True)

    def initialize(self, root):
        root.mkdir(parents=True)
        self.run_git(root, "init", "-q")

    def write(self, root, path, contents):
        path = root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def commit(self, root):
        self.run_git(root, "add", "--all")
        self.run_git(root, "commit", "-qm", "fixture")

    def manifest(self, verify=False):
        return sdk.sdk_manifest(self.root, self.parent, verify, packages=("core",))

    def test_parent_archive_expands_sdk_sources_and_native_inputs(self):
        destination = self.directory / "snapshot"
        sdk.export_tree(self.root, self.parent, destination)
        for name in ("src/lib.enq", "runtime.c", "native.h", "build.enq", "encore.toml"):
            self.assertEqual((destination / "packages/core" / name).read_bytes(), (self.origin / name).read_bytes())
        self.assertFalse((destination / "packages/core/.git").exists())

    def test_export_uses_gitlink_even_when_child_head_and_worktree_change(self):
        self.write(self.child, "runtime.c", b"int runtime(void) { return 2; }\n")
        self.commit(self.child)
        self.write(self.child, "src/lib.enq", b"dirty input\n")
        destination = self.directory / "pinned SDK"
        sdk.export_package(self.root, self.parent, "core", destination)
        self.assertEqual((destination / "runtime.c").read_bytes(), (self.origin / "runtime.c").read_bytes())
        self.assertEqual((destination / "src/lib.enq").read_bytes(), (self.origin / "src/lib.enq").read_bytes())
        self.assertEqual(self.manifest()["packages"][0]["commit"], self.first)
        with self.assertRaisesRegex(ValueError, "differs from the gitlink"):
            self.manifest(verify=True)

    def test_tracked_edits_are_rejected_but_ignored_build_outputs_are_allowed(self):
        before = sdk.manifest_digest(self.manifest(verify=True))
        self.write(self.child, "target/cache", b"build output")
        self.assertEqual(sdk.manifest_digest(self.manifest(verify=True)), before)
        self.write(self.child, "native.h", b"edited native input\n")
        with self.assertRaisesRegex(ValueError, "tracked changes"):
            self.manifest(verify=True)

    def test_uninitialized_submodule_fails_with_recovery_command(self):
        shutil.rmtree(self.child)
        self.child.mkdir()
        with self.assertRaisesRegex(ValueError, "git submodule update --init --recursive"):
            sdk.export_tree(self.root, self.parent, self.directory / "missing SDK")

    def test_partial_export_can_select_a_file_inside_a_gitlink(self):
        destination = self.directory / "partial"
        sdk.export_tree(self.root, self.parent, destination, ("packages/core/src/lib.enq",))
        self.assertEqual((destination / "packages/core/src/lib.enq").read_bytes(), (self.origin / "src/lib.enq").read_bytes())
        self.assertFalse((destination / "packages/core/runtime.c").exists())
        self.assertFalse((destination / "encore.toml").exists())

    def test_working_snapshot_retains_edits_and_new_inputs_without_git_or_caches(self):
        self.write(self.child, "src/lib.enq", b"edited input\n")
        self.write(self.child, "src/new.enq", b"new input\n")
        self.write(self.child, "target/cache", b"excluded")
        destination = self.directory / "benchmark snapshot"
        names = sdk.copy_working_tree(self.root, destination)
        self.assertIn("packages/core/src/new.enq", names)
        self.assertEqual((destination / "packages/core/src/lib.enq").read_bytes(), b"edited input\n")
        self.assertFalse(any(".git" in Path(name).parts or "target" in Path(name).parts for name in names))

    def test_legacy_embedded_package_is_exported_from_the_requested_revision(self):
        legacy = self.directory / "legacy compiler"
        self.initialize(legacy)
        self.write(legacy, "packages/core/src/lib.enq", b"old release source\n")
        self.write(legacy, "packages/core/runtime.c", b"old release runtime\n")
        self.commit(legacy)
        old = self.run_git(legacy, "rev-parse", "HEAD").strip()
        self.write(legacy, "packages/core/runtime.c", b"new checkout runtime\n")
        destination = self.directory / "seed SDK"
        sdk.export_package(legacy, old, "core", destination)
        self.assertEqual((destination / "runtime.c").read_bytes(), b"old release runtime\n")

    def test_nested_gitlinks_are_expanded_at_their_own_pins(self):
        nested = self.directory / "native helper"
        self.initialize(nested)
        self.write(nested, "helper.h", b"native helper\n")
        self.commit(nested)
        self.run_git(self.child, "-c", "protocol.file.allow=always", "submodule", "add", "--quiet",
                     str(nested), "vendor/helper")
        self.commit(self.child)
        self.commit(self.root)
        destination = self.directory / "recursive snapshot"
        sdk.export_tree(self.root, "HEAD", destination)
        self.assertEqual((destination / "packages/core/vendor/helper/helper.h").read_bytes(), b"native helper\n")
        self.assertFalse((destination / "packages/core/vendor/helper/.git").exists())

    def test_manifest_and_digest_have_no_checkout_dependent_paths(self):
        manifest = self.manifest(verify=True)
        self.assertEqual(manifest["packages"][0], {
            "path": "packages/core", "repository": str(self.origin), "commit": self.first,
            "name": "core", "version": "1.0.0"})
        data = sdk.manifest_bytes(manifest)
        self.assertEqual(json.loads(data), manifest)
        self.assertNotIn(str(self.root).encode(), data)
        self.assertEqual(len(sdk.manifest_digest(manifest)), 64)

    def release_archive(self, manifest, replacement=None):
        archive = self.directory / "release.zip"
        prefix = "encore-release"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr(f"{prefix}/SDK.json", sdk.manifest_bytes(manifest))
            for name in ("encore.toml", "src/lib.enq", "runtime.c", "native.h", "build.enq", ".gitignore"):
                contents = replacement if name == "runtime.c" and replacement is not None else (self.origin / name).read_bytes()
                stream.writestr(f"{prefix}/lib/encore/index/core/{name}", contents)
        return archive, prefix

    def test_provenance_binds_both_package_commits_and_manifest_digest(self):
        manifest = self.manifest(verify=True)
        provenance = {"sdk_packages": manifest["packages"], "sdk_sha256": sdk.manifest_digest(manifest)}
        with patch.object(sdk, "sdk_manifest", return_value=manifest):
            sdk.verify_provenance(self.root, provenance)
            with self.assertRaisesRegex(ValueError, "different SDK"):
                sdk.verify_provenance(self.root, {**provenance, "sdk_sha256": "0" * 64})
            with self.assertRaisesRegex(ValueError, "different SDK"):
                sdk.verify_provenance(self.root, {**provenance, "sdk_packages": []})

    def test_archive_checks_every_package_file_against_the_git_commit(self):
        manifest = self.manifest(verify=True)
        with patch.object(sdk, "sdk_manifest", return_value=manifest):
            archive, prefix = self.release_archive(manifest)
            sdk.check_sdk_archive(archive, prefix, manifest, self.root)
            archive, prefix = self.release_archive(manifest, replacement=b"wrong runtime bytes")
            with self.assertRaisesRegex(ValueError, "files differ from the pinned commit"):
                sdk.check_sdk_archive(archive, prefix, manifest, self.root)

    def test_archive_checks_sdk_identity_and_rejects_git_metadata(self):
        manifest = self.manifest()
        archive, prefix = self.release_archive(manifest)
        sdk.check_sdk_archive(archive, prefix, manifest)
        with zipfile.ZipFile(archive, "a") as stream:
            stream.writestr(f"{prefix}/lib/encore/index/core/.git", "gitdir: /runner/metadata")
        with self.assertRaisesRegex(ValueError, "Git metadata"):
            sdk.check_sdk_archive(archive, prefix, manifest)


if __name__ == "__main__":
    unittest.main()
