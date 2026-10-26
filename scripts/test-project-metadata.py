#!/usr/bin/env python3
"""Check manifest-derived release identity and bootstrap compatibility."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HELPER = Path(__file__).with_name("project-metadata.py")
spec = importlib.util.spec_from_file_location("project_metadata", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProjectMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="encore metadata ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "src").mkdir()
        (self.root / "src/version.enq").write_text(
            'pub fn compiler_version() -> str { ret __version__ }\n'
            'pub fn compiler_release_name() -> str { ret "neumann" }\n', encoding="utf-8")
        self.manifest('name="encore"\nversion="0.1.10"')

    def manifest(self, values):
        (self.root / "encore.toml").write_text('[project]\n' + values + '\n', encoding="utf-8")

    def test_identity_without_version_file(self):
        self.assertEqual(module.metadata(self.root), {
            "name": "encore", "version": "0.1.10", "release_name": "neumann", "release": "0.1.10-neumann"})

    def test_manifest_edits_are_authoritative(self):
        self.manifest('name="новое"\nversion="1.2.3"\ndescription="unicode — and escaped \\"quote\\""')
        values = module.metadata(self.root)
        self.assertEqual(values["name"], "новое")
        self.assertEqual(values["release"], "1.2.3-neumann")

    def test_rejects_invalid_versions_and_missing_fields(self):
        for values in ('name="encore"', 'version="1.2.3"', 'name=""\nversion="1.2.3"',
                       'name="encore"\nversion="1.2"', 'name="encore"\nversion="01.2.3"',
                       'name="encore"\nversion="1.2.3-neumann"', 'name="encore"\nversion=123'):
            with self.subTest(values=values):
                self.manifest(values)
                with self.assertRaises((ValueError, KeyError)):
                    module.metadata(self.root)

    def test_never_evaluates_release_source(self):
        (self.root / "src/version.enq").write_text(
            'pub fn compiler_release_name() -> str { ret dangerous() }\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            module.metadata(self.root)

    def test_rejects_ambiguous_release_names(self):
        source = self.root / "src/version.enq"
        source.write_text(source.read_text() * 2, encoding="utf-8")
        with self.assertRaises(ValueError):
            module.metadata(self.root)

    def test_requires_seed_with_constants(self):
        for tag in ("v0.1.8-neumann", "v0.0.99-neumann", "v0.1.9-beta.1", "latest", "vbroken"):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "0.1.9"):
                module.check_seed(tag)
        for tag in ("v0.1.9-neumann", "v0.1.10-neumann", "v0.2.0-neumann", "v1.0.0"):
            module.check_seed(tag)

    def test_cli_handles_paths_with_spaces(self):
        result = subprocess.run([sys.executable, str(HELPER), "--root", str(self.root),
                                 "--field", "release"], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "0.1.10-neumann\n")

    def test_cli_reports_bad_metadata(self):
        self.manifest('name="encore"\nversion="broken"')
        result = subprocess.run([sys.executable, str(HELPER), "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("project-metadata:", result.stderr)


if __name__ == "__main__":
    unittest.main()
