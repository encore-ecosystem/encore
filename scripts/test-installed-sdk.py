#!/usr/bin/env python3
"""Build a cold and warm application using only the extracted release SDK."""

import argparse
import http.server
import threading
import json
import os
import shutil
import ssl
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def verify(archive: Path, release: str, triple: str, scratch: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as stream:
            stream.extractall(scratch)
    else:
        with tarfile.open(archive, "r:gz") as stream:
            stream.extractall(scratch, filter="data")
    installation = scratch / f"encore-{release}-{triple}"
    executable = "encore.exe" if "-windows-" in triple else "encore"
    compiler = installation / "bin" / executable
    compiler.chmod(0o755)
    project = scratch / "application"
    (project / "src").mkdir(parents=True)
    sdk = installation / "lib/encore/index"
    dependencies = ["sys@std", f"path@{(sdk / 'json').as_posix()}"]
    (project / "encore.toml").write_text(
        '[project]\nname="installed_sdk_probe"\nversion="0.0.0"\ndependencies='
        + json.dumps(dependencies) + '\n', encoding="utf-8")
    (project / "src/main.enq").write_text('''import core::testing::assert
import std::io::println
import json::{Json, parse, stringify}
fn main() -> u32 {
    let value = parse("42").unwrap_or(Json::Null)
    if !assert(stringify(value) == "42") { ret 1_u32 }
    println("installed-sdk-ok")
    ret 0_u32
}
''', encoding="utf-8")
    env = dict(os.environ)
    for name in ("ENCORE_CORE_DIR", "ENCORE_HOME", "ENCORE_DEFAULT_INDEX", "OPENSSL_DIR"):
        env.pop(name, None)
    env.pop("SSL_CERT_FILE", None)
    env.pop("SSL_CERT_DIR", None)
    env.update(ENCORE_BUILD_CACHE=str(scratch / "compiled-cache"),
               ENCORE_REGISTRY_CACHE=str(scratch / "empty-registry"),
               ENCORE_INDEX_URL="http://127.0.0.1:9/index")
    for _ in range(2):
        result = subprocess.run([str(compiler), "run", "--jobs", "2"], cwd=project,
                                env=env, capture_output=True, text=True, timeout=600)
        if result.returncode != 0 or "installed-sdk-ok" not in result.stdout:
            raise AssertionError(f"installed SDK failed ({result.returncode})\n{result.stdout}\n{result.stderr}")
    runtime = scratch / "runtime"
    (runtime / "src").mkdir(parents=True)
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "asyncio" / "src" / "main.enq"
    (runtime / "src/main.enq").write_bytes(fixture.read_bytes())
    (runtime / "encore.toml").write_text(
        '[project]\nname="installed_asyncio_probe"\nversion="0.0.0"\n'
        'dependencies=["sys@asyncio", "sys@ipc"]\n', encoding="utf-8"
    )
    result = subprocess.run([str(compiler), "run", "--jobs", "2"], cwd=runtime,
                            env=env, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(f"installed asyncio failed ({result.returncode})\n{result.stdout}\n{result.stderr}")
    http_project = scratch / "http-client"
    (http_project / "src").mkdir(parents=True)
    (http_project / "encore.toml").write_text(
        '[project]\nname="installed_http_probe"\nversion="0.0.0"\ndependencies=["sys@std", "sys@http"]\n', encoding="utf-8")
    (http_project / "src/main.enq").write_text('''import core::result::Result
import http::HttpClient
import std::os::env
fn main() -> u32 {
    match HttpClient::new().get(env("ENCORE_SDK_HTTP_URL").unwrap_or("")) {
        Result::Ok(response) => { ret if response.body() == "installed-http-ok" { 0_u32 } else { 1_u32 } }
        Result::Err(_) => { ret 2_u32 }
    }
}
''', encoding="utf-8")
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            body = b"installed-http-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    # Verify default trust after relocation, without a caller-provided ca_file.
    cert, key = scratch / "http-ca.pem", scratch / "http-key.pem"
    brew_openssl = Path("/opt/homebrew/opt/openssl@3/bin/openssl")
    tool = str(brew_openssl) if brew_openssl.is_file() else shutil.which("openssl")
    if not tool:
        raise AssertionError("OpenSSL CLI is required for the installed SDK TLS fixture")
    subprocess.run([tool, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost"], capture_output=True, check=True)
    bundle = sdk / "openssl" / triple / "cert.pem"
    if sys.platform == "darwin" or os.name == "nt":
        assert bundle.is_file(), "SDK is missing its default CA bundle"
        bundle.write_text(bundle.read_text() + cert.read_text())
    else:
        env["SSL_CERT_FILE"] = str(cert)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        subprocess.run([str(compiler), "run", "--jobs", "2"], cwd=http_project,
                       env=dict(env, ENCORE_SDK_HTTP_URL=f"https://localhost:{server.server_port}"),
                       check=True, timeout=600)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("extracted release SDK: cold/warm std, asyncio and HTTPS applications verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--triple", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore installed SDK ") as directory:
        verify(args.archive.resolve(), args.release, args.triple, Path(directory))


if __name__ == "__main__":
    main()
