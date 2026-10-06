#!/usr/bin/env python3
"""Offline registry-source integration tests using disposable local indexes."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def main():
    compiler = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="encore-registry-sources-") as scratch:
        root = Path(scratch)
        env = {**os.environ, "ENCORE_REGISTRY_CACHE": str(root / "cache")}
        env.pop("ENCORE_INDEX_URL", None)
        env.pop("ENCORE_DEFAULT_INDEX", None)
        indexes = []
        for label in ("first", "second"):
            index = root / label
            for package in ("probe", "leaf"):
                (index / package[:2]).mkdir(parents=True, exist_ok=True)
                archive = index / (package + ".tar.gz")
                dependencies = '["index@leaf"]' if package == "probe" else '[]'
                with tarfile.open(archive, "w:gz") as tar:
                    for name, content in {
                        "encore.toml": f'[project]\nname = "{package}"\nversion = "1.0.0"\ndependencies = {dependencies}\n'
                                       '[registry]\nindex = "file:///nonexistent-dependency-override"\n',
                        "src/lib.enq": f'pub fn origin() -> str {{ ret "{label}" }}\n',
                    }.items():
                        data = content.encode()
                        entry = tarfile.TarInfo(name)
                        entry.size = len(data)
                        tar.addfile(entry, io.BytesIO(data))
                (index / package[:2] / (package + ".json")).write_text(json.dumps({"name": package, "versions": [{
                    "version": "1.0.0", "archive": archive.as_uri(),
                    "checksum": hashlib.sha256(archive.read_bytes()).hexdigest(), "yanked": False,
                }]}))
            indexes.append(index)
        app = root / "app"
        (app / "src").mkdir(parents=True)
        (app / "src/main.enq").write_text('fn main() -> u32 { ret 0_u32 }\n')

        def manifest(index=None):
            (app / "encore.toml").write_text(
                '[project]\nname = "consumer"\nversion = "0.0.0"\n'
                'dependencies = ["index@probe"]\n'
                + (f'\n[registry]\nindex = "{index.as_uri()}"\n' if index else ''))

        def run(*args, success=True, override=None, default=None):
            current = dict(env)
            if override is not None:
                current["ENCORE_INDEX_URL"] = override
            if default is not None:
                current["ENCORE_DEFAULT_INDEX"] = default
            result = subprocess.run([compiler, *args], cwd=app, env=current,
                                    capture_output=True, text=True, timeout=90)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result

        manifest(indexes[0])
        for invalid in ("https://user:secret@example.org/index", "https://example.org/index?token=secret",
                        "https://example.org/index#x", "http://example.org/index",
                        "https://example.org/a/../index", "https://example.org/a/./index",
                        "https://example.org/%2e/index", "https://example.org/\nindex"):
            result = run("sync", success=False, override=invalid)
            assert "Invalid registry index URL" in result.stderr + result.stdout, (invalid, result.stdout, result.stderr)
        run("sync")
        first_lock = (app / "encore.lock").read_text()
        assert f'registry = "{indexes[0].as_uri()}"' in first_lock
        assert 'name = "leaf"' in first_lock
        assert "nonexistent-dependency-override" not in first_lock
        manifest(indexes[1])
        result = run("sync", success=False)
        assert "encore update" in result.stderr + result.stdout
        assert (app / "encore.lock").read_text() == first_lock
        run("update")
        second_lock = (app / "encore.lock").read_text()
        assert f'registry = "{indexes[1].as_uri()}"' in second_lock
        assert first_lock != second_lock
        # Root override and both independently populated cache namespaces.
        run("update", override=indexes[0].as_uri())
        assert (app / "encore.lock").read_text() == first_lock
        assert len(list((root / "cache/sources").rglob("probe.json"))) == 2
        # A user default works without project settings; explicit settings win.
        manifest()
        run("update", default=indexes[1].as_uri() + "/")
        assert (app / "encore.lock").read_text() == second_lock
        result = run("sync", success=False, default=indexes[0].as_uri())
        assert "encore update" in result.stderr + result.stdout
        run("update", default=indexes[1].as_uri(), override=indexes[0].as_uri())
        assert (app / "encore.lock").read_text() == first_lock
        for invalid in (" ", "http://example.org/index", "https://user:secret@example.org/index"):
            result = run("update", success=False, default=invalid)
            assert "Invalid registry index URL" in result.stderr + result.stdout, (invalid, result.stdout, result.stderr)
            assert (app / "encore.lock").read_text() == first_lock
        unavailable = (root / "unavailable").as_uri()
        result = run("update", success=False, default=unavailable)
        assert unavailable in result.stderr + result.stdout
        assert "raw.githubusercontent.com" not in result.stderr + result.stdout
        assert (app / "encore.lock").read_text() == first_lock
        manifest(indexes[0])
        run("update", default=indexes[1].as_uri())
        assert (app / "encore.lock").read_text() == first_lock
        run("sync", default="", override="")
        assert (app / "encore.lock").read_text() == first_lock
        # Ordinary sync works after the selected index becomes unavailable.
        indexes[0].rename(root / "offline-first")
        manifest(indexes[0])
        run("sync")
        # Legacy locks remain pinned and readable without inventing an origin.
        legacy = "\n".join(line for line in first_lock.splitlines()
                           if not line.startswith("registry = ")) + "\n"
        (app / "encore.lock").write_text(legacy)
        # Restore archives; legacy layout can hydrate directly from locked URL.
        (root / "offline-first").rename(indexes[0])
        run("sync")
        assert "registry = " not in (app / "encore.lock").read_text()
        run("update")
        assert "registry = " in (app / "encore.lock").read_text()
    print("registry sources: isolation, default/manifest/override priority, invalid defaults, no fallback, offline and legacy locks passed")


if __name__ == "__main__":
    main()
