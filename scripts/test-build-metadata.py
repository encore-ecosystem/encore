#!/usr/bin/env python3
"""Exercise the actual dependency declaration codec without publishing its API."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    repository = Path(__file__).resolve().parents[1]
    compiler = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="encore-metadata-") as directory:
        root = Path(directory) / "fixture with spaces"
        shutil.copytree(repository / "src", root / "src")
        (root / "src/lib.enq").write_text(
            'pub import refrain::frontend::metadata_ast\n'
            'pub import refrain::frontend::translator\n'
            'pub import refrain::modes::build_metadata\n'
            'pub import refrain::modes::build_request\n'
            'pub import refrain::modes::build_requirements\n'
            'pub import refrain::modes::build_artifacts\n'
            'pub import refrain::modes::build_archive\n'
            'pub import refrain::modes::build_fingerprint\n'
            'pub import refrain::modes::build_unit\n'
            'pub import refrain::modes::build_scheduler\n'
            'pub import refrain::modes::build_native_inputs\n'
            'pub import refrain::modes::build_resources\n', encoding="utf-8")
        manifest = (repository / "encore.toml").read_text(encoding="utf-8")
        manifest = re.sub(r'"path@([^"\n]+)"', lambda match:
                          '"path@' + (repository / match.group(1)).resolve().as_posix() + '"', manifest)
        (root / "encore.toml").write_text(manifest, encoding="utf-8")
        source = (repository / "runtime.c").as_posix().replace('"', '\\"')
        (root / "runtime.c").write_text(f'#include "{source}"\n', encoding="utf-8")
        result = subprocess.run([str(compiler), "test", "--filter", "metadata_", "--jobs", "2",
                                 "--report", "report.json"], cwd=root, capture_output=True, text=True,
                                env={**os.environ, "ENCORE_KEEP_TEMPS": "1",
                                     "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")},
                                timeout=900)
        if result.returncode != 0:
            log = root / "target/tests/__encore_unit_harness.output.txt"
            details = log.read_text(encoding="utf-8") if log.exists() else ""
            evidence_parent = repository / "target/refrain-compilation-verification"
            evidence_parent.mkdir(parents=True, exist_ok=True)
            evidence = Path(tempfile.mkdtemp(prefix="metadata-failure-", dir=evidence_parent))
            # Keep the complete generated input/IR, not just the CLI's shortened
            # diagnostic. Evidence is local, ignored, and never published.
            shutil.copytree(root, evidence / "fixture")
            raise AssertionError(result.stdout + result.stderr + "\n" + details + "\nEvidence: " + str(evidence))
        print(result.stdout + result.stderr, end="", flush=True)
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        assert report["summary"]["passed"] == 82 and report["summary"]["failed"] == 0, report
        indexed = subprocess.run(
            [str(compiler), "test", "--filter", "index_matches_reverse_scan_contract",
             "--jobs", "2", "--report", "index-report.json"], cwd=root,
            capture_output=True, text=True, timeout=900,
            env={**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")})
        assert indexed.returncode == 0, indexed.stdout + indexed.stderr
        index_report = json.loads((root / "index-report.json").read_text())
        assert index_report["summary"]["passed"] == 2 and index_report["summary"]["failed"] == 0, index_report
        print(indexed.stdout + indexed.stderr, end="", flush=True)
    print("metadata: structured AST, capabilities, precise cfg spans, malformed data, body-free interfaces and phase cache fingerprints passed")


if __name__ == "__main__":
    main()
