#!/usr/bin/env python3
"""Exercise API discovery/resolution and Git dependencies without external services."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading


def main():
    compiler = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="encore-api-") as directory:
        root = Path(directory)
        requests = []
        mode = {"value": "valid"}
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, source in {
                "encore.toml": '[project]\nname="probe"\nversion="1.0.0"\ndependencies=[]\n',
                "src/lib.enq": "pub fn value() -> u32 { ret 42 }\n",
            }.items():
                data = source.encode()
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        payload = output.getvalue()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append(self.path)
                status, body = 200, b""
                if self.path == "/index/config.json":
                    config = {"schema": 1, "api": "/api/v1"}
                    if mode["value"] == "cross-origin":
                        config["api"] = "https://example.org/api/v1"
                    if mode["value"] == "schema":
                        config["schema"] = 999
                    body = json.dumps(config).encode()
                elif self.path == "/api/v1/packages/probe":
                    if mode["value"] == "missing":
                        status, body = 404, b"{}"
                    elif mode["value"] == "redirect":
                        self.send_response(302)
                        self.send_header("Location", "/must-not-follow")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    elif mode["value"] == "invalid":
                        body = b"not JSON"
                    else:
                        body = json.dumps({"name": "probe", "versions": [{
                            "version": "1.0.0", "archive": base + "/archive.tar.gz",
                            "checksum": hashlib.sha256(payload).hexdigest(), "yanked": False,
                        }]}).encode()
                elif self.path == "/archive.tar.gz":
                    body = payload
                else:
                    status, body = 404, b"{}"
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base = "http://127.0.0.1:" + str(server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {key: value for key, value in os.environ.items()
               if key not in ("ENCORE_INDEX_URL", "ENCORE_DEFAULT_INDEX")}
        env["ENCORE_REGISTRY_CACHE"] = str(root / "cache")
        env["ENCORE_DEFAULT_INDEX"] = base + "/index"
        app = root / "app"
        (app / "src").mkdir(parents=True)
        (app / "encore.toml").write_text('[project]\nname="consumer"\nversion="0.0.0"\ndependencies=[]\n')
        (app / "src/main.enq").write_text('fn main() -> u32 { ret 0 }\n')

        def run(*args, success=True, environment=None):
            result = subprocess.run([compiler, *args], cwd=app, env=environment or env,
                                    capture_output=True, text=True, timeout=90)
            assert (result.returncode == 0) == success, (args, result.stdout, result.stderr)
            return result.stdout + result.stderr

        try:
            run("add", "probe")
            assert "index@probe" in (app / "encore.toml").read_text()
            assert "/api/v1/packages/probe" in requests
            assert "/index/pr/probe.json" not in requests
            locked = (app / "encore.lock").read_text()
            assert 'registry = "' + base + '/index"' in locked
            for state in ("cross-origin", "schema", "missing", "redirect", "invalid"):
                mode["value"] = state
                run("update", success=False)
                assert (app / "encore.lock").read_text() == locked
                assert "/must-not-follow" not in requests
            mode["value"] = "valid"
            run("update")
            count = len(requests)
            run("sync")
            assert len(requests) == count, "locked sync must not contact the registry"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        run("sync")
        pinned_env = dict(env)
        pinned_env.pop("ENCORE_DEFAULT_INDEX")
        run("sync", environment=pinned_env)
        assert (app / "encore.lock").read_text() == locked

        # No registry is needed for a direct Git dependency, including GitHub URLs.
        repo = root / "gitprobe"
        (repo / "src").mkdir(parents=True)
        (repo / "encore.toml").write_text('[project]\nname="gitprobe"\nversion="1.0.0"\ndependencies=[]\n')
        (repo / "src/lib.enq").write_text('pub fn value() -> u32 { ret 7 }\n')
        for args in (("init",), ("add", "."),
                     ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        (app / "encore.toml").write_text('[project]\nname="consumer"\nversion="0.0.0"\ndependencies=[]\n')
        (app / "encore.lock").unlink()
        direct_env = dict(env)
        direct_env.pop("ENCORE_DEFAULT_INDEX")
        reference = "git@" + repo.as_uri()
        git_cache = Path.home() / ".cache/encore/git" / root.name / "gitprobe"
        assert not git_cache.exists(), "fixture must own its new Git cache entry"
        try:
            run("add", reference, environment=direct_env)
            assert reference in (app / "encore.toml").read_text()
            assert reference in (app / "encore.lock").read_text()
            run("sync", environment=direct_env)
        finally:
            if git_cache.is_dir():
                shutil.rmtree(git_cache)
    print("registry API: discovery, native HTTP, no redirects/fallback, failure atomicity, offline locks and git@ passed")


if __name__ == "__main__":
    main()
