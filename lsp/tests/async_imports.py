#!/usr/bin/env python3
"""Async import boundaries, awaited Result outputs and match-arm block parity."""

from pathlib import Path
import subprocess
import sys
import tempfile

from workspace_graph import diagnostics, response, send


def main() -> None:
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="encore-lsp-async-import-") as temporary:
        root = Path(temporary)
        source = root / "src"
        source.mkdir()
        (root / "encore.toml").write_text(
            '[project]\nname="async_import"\nversion="0.0.0"\ndependencies=[]\n'
        )
        (source / "api.enq").write_text("pub fn answer() -> u32 { ret 42_u32 }\n")
        path = source / "main.enq"
        body = """
async fn identify() -> u32 { ret answer() }
async fn result_value() -> Result[bool, str] { ret Result[bool, str]::Ok(true) }
async fn forward() -> Result[bool, str] { ret await result_value() }
async fn saved() -> Result[bool, str] {
    let pending = result_value()
    let output: Result[bool, str] = await pending
    ret output
}
fn touch() -> u32 { ret 0_u32 }
fn main() -> u32 {
    let value = match true {
        true => 42_u32
        false => { touch() ret 1_u32 }
    }
    ret value
}
"""
        variants = ["import core::result::Result\n" + text for text in [
            "import mod::api::*\n" + body,
            "import mod::api::answer\n" + body,
            "import mod::api::{\nanswer,\n}\n" + body,
            "import mod::api::answer as aliased\n" + body.replace("answer()", "aliased()"),
        ]]
        path.write_text(variants[0])
        uri = path.as_uri()
        process = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            send(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "rootUri": root.as_uri(), "capabilities": {},
                "initializationOptions": {"cache": False, "jobs": 1, "debounceMs": 0},
            }})
            response(process, 1)
            send(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
            send(process, {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                "textDocument": {"uri": uri, "languageId": "encore", "version": 1, "text": variants[0]},
            }})
            found = diagnostics(process, 2, uri)
            assert found == [], found
            for version, text in enumerate(variants[1:], start=2):
                send(process, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                }})
                found = diagnostics(process, version + 1, uri)
                assert found == [], (version, found)
            broken = variants[0].replace("ret value", "ret missing_call()")
            send(process, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": 5}, "contentChanges": [{"text": broken}],
            }})
            found = diagnostics(process, 6, uri)
            assert any(item.get("code") == "unresolved-call" for item in found), found
            send(process, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": 6}, "contentChanges": [{"text": variants[0]}],
            }})
            found = diagnostics(process, 7, uri)
            assert found == [], found
            wrong_output = variants[0].replace(
                "let output: Result[bool, str]", "let output: bool"
            )
            send(process, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": 7}, "contentChanges": [{"text": wrong_output}],
            }})
            found = diagnostics(process, 8, uri)
            assert any(item.get("code") == "type-mismatch" for item in found), found
            send(process, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": 8}, "contentChanges": [{"text": variants[0]}],
            }})
            assert diagnostics(process, 9, uri) == []
            send(process, {"jsonrpc": "2.0", "id": 10, "method": "shutdown", "params": None})
            response(process, 10)
            send(process, {"jsonrpc": "2.0", "method": "exit", "params": None})
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        print("async imports, awaited Result outputs, match blocks and edit diagnostics: OK")


if __name__ == "__main__":
    main()
