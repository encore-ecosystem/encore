#!/usr/bin/env python3
"""Run SDK HTTP integration tests against an ephemeral local fixture."""
from __future__ import annotations

import argparse
import http.server
import os
from pathlib import Path
import subprocess
import threading
import time


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

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
                body = b"x" * 1000000 if self.path == "/large" else b"a\x00\xffz" if self.path == "/binary" else b"ready"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parent.parent
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = dict(os.environ, JEV_TEST_URL=f"http://127.0.0.1:{server.server_port}", JEV_TEST_CA="")
        for case in ("http_async_network", "http_async_lifetime"):
            subprocess.run([str(compiler), "test", "--filter", case], cwd=root / "packages/std", env=env, check=True, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
