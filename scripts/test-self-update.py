#!/usr/bin/env python3
"""Verify Linux self-update transactions in a disposable installation."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile


def main():
    compiler = Path(sys.argv[1]).resolve()
    release = subprocess.check_output([str(compiler), "--version"], text=True).strip().removeprefix("encore ")
    version, name = release.split("-", 1)
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine(), platform.machine())
    assert platform.system() == "Linux", "this fixture checks synchronous Linux activation"
    with tempfile.TemporaryDirectory(prefix="encore-self-update-") as directory:
        root = Path(directory)
        installation = root / "installation with spaces"
        (installation / "bin").mkdir(parents=True)
        shutil.copy2(compiler, installation / "bin/encore")
        (installation / "VERSION").write_text("0.0.0-neumann\n")
        settings = 'channel = "stable"\n'
        (installation / "settings.toml").write_text(settings)
        package = root / "package"
        for path in ("bin", "lib", "share"):
            (package / path).mkdir(parents=True)
        shutil.copy2(compiler, package / "bin/encore")
        (package / "VERSION").write_text(release + "\n")
        archive = root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(package, arcname="encore")
        metadata = {
            "schema": 2, "channel": "stable", "version": version,
            "nametag": name, "release": release, "tag": "v" + release,
            "commit": "fixture", "assets": [{
                "triple": arch + "-unknown-linux-gnu", "url": archive.as_uri(),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "format": "tar.gz"}]}
        channels = root / "channels"
        channels.mkdir()
        manifest = channels / "stable.json"
        manifest.write_text(json.dumps(metadata))
        environment = {**os.environ, "ENCORE_HOME": str(installation),
                       "ENCORE_SELF_UPDATE_BASE_URL": root.as_uri()}

        def update(*args):
            return subprocess.run([str(installation / "bin/encore"), "self", "update", *args],
                                  env=environment, capture_output=True, text=True, timeout=180)

        before = (installation / "bin/encore").read_bytes()
        if "--public-check" in sys.argv[2:]:
            public_environment = dict(environment)
            public_environment.pop("ENCORE_SELF_UPDATE_BASE_URL", None)
            public_environment.pop("ENCORE_SELF_UPDATE_CA_FILE", None)
            public = subprocess.run([str(installation / "bin/encore"), "self", "update", "--check"],
                                    env=public_environment, capture_output=True, text=True, timeout=180)
            assert public.returncode == 0 and "can be updated" in public.stdout, public
            print("public stable channel over native HTTPS: " + public.stdout.strip())
        result = update("--check")
        assert result.returncode == 0 and "can be updated" in result.stdout, result
        assert (installation / "VERSION").read_text() == "0.0.0-neumann\n"
        metadata["assets"][0]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(metadata))
        result = update()
        assert result.returncode != 0 and "Checksum verification failed" in result.stdout + result.stderr, result
        assert (installation / "bin/encore").read_bytes() == before
        assert (installation / "settings.toml").read_text() == settings
        metadata["assets"][0]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(metadata))
        result = update()
        assert result.returncode == 0 and "Updated Encore" in result.stdout, result
        assert (installation / "VERSION").read_text() == release + "\n"
        assert (installation / "settings.toml").read_text() == settings
        assert not (root / ".encore-update").exists()
        result = update()
        assert result.returncode == 0 and "up to date" in result.stdout, result
    print("self update: check, checksum rejection, preserved installation/settings, activation and no-op; ok")


if __name__ == "__main__":
    main()
