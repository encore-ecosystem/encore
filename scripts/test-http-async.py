#!/usr/bin/env python3
"""Exercise HTTP clients against disposable HTTP and verified HTTPS fixtures."""
from __future__ import annotations

import argparse
import http.server
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def reply(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            if self.path in ("/slow", "/delayed"):
                time.sleep(2 if self.path == "/slow" else 0.05)
            if self.path == "/ambiguous":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\nConnection: close\r\n\r\nxx")
            elif self.path == "/truncated":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\nConnection: close\r\n\r\nshort")
            elif self.path == "/chunked":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n4\r\na\x00\xffz\r\n0\r\n\r\n")
            else:
                body = {"/large": b"x" * 1000000, "/oversized": b"x" * 100,
                        "/binary": b"a\x00\xffz", "/index.html": b"secure"}.get(self.path, b"ready")
                self.reply(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.reply(self.command.encode() + b":" + body)

    do_PUT = do_POST
    do_DELETE = do_POST


@contextmanager
def server(context: ssl.SSLContext | None = None):
    instance = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.daemon_threads = True
    if context:
        instance.socket = context.wrap_socket(instance.socket, server_side=True)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance.server_port
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parent.parent
    prefix = Path(os.environ.get("OPENSSL_DIR", "/opt/homebrew/opt/openssl@3"))
    openssl = prefix / "bin" / ("openssl.exe" if os.name == "nt" else "openssl")
    tool = str(openssl) if openssl.is_file() else shutil.which("openssl")
    if not tool:
        parser.error("OpenSSL CLI is required for the disposable TLS fixture")
    with tempfile.TemporaryDirectory(prefix="encore-http-") as temporary:
        cert, key = Path(temporary) / "ca.pem", Path(temporary) / "key.pem"
        subprocess.run([tool, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        with server() as local_port, server(context) as secure_port:
            local = f"http://127.0.0.1:{local_port}"
            secure = f"https://localhost:{secure_port}"
            mismatch = f"https://127.0.0.1:{secure_port}"
            env = dict(os.environ, ENCORE_HTTPS_TEST_URL=secure, ENCORE_HTTPS_TEST_CA=str(cert),
                       ENCORE_HTTPS_TEST_MISMATCH_URL=mismatch, ENCORE_HTTP_SEND_TEST_URL=secure,
                       ENCORE_HTTP_SEND_TEST_CA=str(cert), ENCORE_HTTP_LOCAL_TEST_URL=local,
                       JEV_TEST_BAD_HOST=mismatch)
            for base, ca in ((local, ""), (secure, str(cert))):
                print("HTTP fixture:", base, flush=True)
                subprocess.run([str(compiler), "test", "--jobs", "2"], cwd=root / "packages/http",
                               env=dict(env, JEV_TEST_URL=base, JEV_TEST_CA=ca), check=True, timeout=600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
