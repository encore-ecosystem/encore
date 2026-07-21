#!/usr/bin/env python3

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def send_message(process: subprocess.Popen[bytes], payload: object) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    assert process.stdin is not None
    process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    process.stdin.flush()


def read_message(process: subprocess.Popen[bytes]) -> dict:
    assert process.stdout is not None
    length = None
    while True:
        raw = process.stdout.readline()
        if not raw:
            raise RuntimeError("LSP server closed its output")
        line = raw.decode().strip()
        if not line:
            break
        name, value = line.split(":", 1)
        if name.lower() == "content-length":
            length = int(value.strip())
    if length is None:
        raise RuntimeError("LSP message has no Content-Length")
    return json.loads(process.stdout.read(length))


def response_for(process: subprocess.Popen[bytes], request_id: int) -> dict:
    while True:
        message = read_message(process)
        if message.get("id") == request_id:
            return message


def main() -> None:
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="encore-lsp-docstrings-") as temporary:
        root = Path(temporary)
        source_dir = root / "src"
        source_dir.mkdir()
        (root / "encore.toml").write_text(
            '[project]\nname = "doc_hover"\nversion = "0.1.0"\ndependencies = []\n'
        )

        net_source = """//! Networking primitives.

/// Opens a connection.
///
/// # Errors
/// Returns an error when the peer is unavailable.
pub fn connect() -> u32 { ret 0_u32 }
"""
        main_source = """import doc_hover::net::connect
fn main() -> u32 { ret connect() }
"""
        net_path = source_dir / "net.enq"
        main_path = source_dir / "main.enq"
        net_path.write_text(net_source)
        main_path.write_text(main_source)

        process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            root_uri = root.as_uri()
            send_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "rootUri": root_uri,
                        "workspaceFolders": [{"uri": root_uri, "name": "doc_hover"}],
                    },
                },
            )
            initialized = response_for(process, 1)
            if "error" in initialized:
                raise RuntimeError(f"initialize failed: {initialized}")
            send_message(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})

            for uri, text in ((net_path.as_uri(), net_source), (main_path.as_uri(), main_source)):
                send_message(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/didOpen",
                        "params": {
                            "textDocument": {
                                "uri": uri,
                                "languageId": "encore",
                                "version": 1,
                                "text": text,
                            }
                        },
                    },
                )

            character = main_source.splitlines()[1].index("connect") + 2
            send_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/hover",
                    "params": {
                        "textDocument": {"uri": main_path.as_uri()},
                        "position": {"line": 1, "character": character},
                    },
                },
            )
            hover = response_for(process, 2)["result"]
            contents = hover["contents"]
            value = contents["value"]
            assert contents["kind"] == "markdown"
            assert "```encore\nfn connect\n```" in value, value
            assert "Opens a connection." in value, value
            assert "# Errors" in value, value

            send_message(process, {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None})
            response_for(process, 3)
            send_message(process, {"jsonrpc": "2.0", "method": "exit", "params": None})
            assert process.stdin is not None
            process.stdin.close()
            return_code = process.wait(timeout=5)
            if return_code != 0:
                assert process.stderr is not None
                raise RuntimeError(process.stderr.read().decode())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
    print("docstring hover integration: ok")
