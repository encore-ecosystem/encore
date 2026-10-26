#!/usr/bin/env python3
"""Package constants retain ownership in editor queries and manifest updates."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from scheduler import response, send, stop


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def main():
    binary = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="encore-lsp-constants-") as directory:
        root = Path(directory)
        app, library = root / "app", root / "library"
        app_source = ('import lsp_dependency::value\n'
                      'fn local_version() -> str {\n    ret __version__\n}\n'
                      'struct Member { __version__: str }\n'
                      'impl for Member { pub fn __project_name__(self: Self) -> str { ret \"method\" } }\n'
                      'enum Qualified { __version__ }\n'
                      'fn main() -> u32 {\n    let _dependency = value()\n'
                      '    let member = Member { \"field\" }\n'
                      '    let _field = member.__version__\n'
                      '    let _method = member.__project_name__()\n'
                      '    let _variant = Qualified::__version__\n'
                      '    let _local = local_version()\n    ret 0_u32\n}\n')
        library_source = 'pub fn value() -> str {\n    ret __version__\n}\n'
        write(app / "src/main.enq", app_source)
        write(library / "src/lib.enq", library_source)

        def manifests(app_version, library_version):
            write(app / "encore.toml", '[project]\nname="metadata_lsp"\nversion=' + json.dumps(app_version)
                  + '\ndependencies=["path@../library"]\n')
            write(library / "encore.toml", '[project]\nname="lsp_dependency"\nversion=' + json.dumps(library_version) + '\n')

        manifests("1.0.0", "2.0.0")
        process = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        number = 0

        def request(method, params):
            nonlocal number
            number += 1
            send(process, dict(jsonrpc="2.0", id=number, method=method, params=params))
            message = response(process, number)
            assert "error" not in message, message
            return message["result"]

        def at(path, source):
            lines = source.splitlines()
            line = next(i for i, text in enumerate(lines) if "ret __version__" in text)
            return dict(textDocument=dict(uri=path.as_uri()),
                        position=dict(line=line, character=lines[line].index("__version__") + 3))

        def check(app_version, library_version):
            for path, source, expected in ((app / "src/main.enq", app_source, app_version),
                                           (library / "src/lib.enq", library_source, library_version)):
                hover = request("textDocument/hover", at(path, source))
                assert expected in hover["contents"]["value"] and "str" in hover["contents"]["value"], hover
                diagnostics = request("textDocument/diagnostic", dict(textDocument=dict(uri=path.as_uri())))
                assert not [d for d in diagnostics.get("items", []) if d.get("severity") == 1], diagnostics
            completion = request("textDocument/completion", at(app / "src/main.enq", app_source))
            items = {x["label"]: x for x in completion["items"]}
            assert items["__version__"]["kind"] == 21 and app_version in items["__version__"]["detail"], items
            assert "metadata_lsp" in items["__project_name__"]["detail"], items
            # Identical names in member/type namespaces keep normal editor queries.
            for fragment, name in (("struct Member", "__version__"),
                                   ("impl for Member", "__project_name__"),
                                   ("enum Qualified", "__version__"),
                                   ("let _field", "__version__"),
                                   ("let _method", "__project_name__"),
                                   ("let _variant", "__version__")):
                lines = app_source.splitlines()
                line = next(i for i, text in enumerate(lines) if fragment in text)
                position = dict(textDocument=dict(uri=(app / "src/main.enq").as_uri()),
                                position=dict(line=line, character=lines[line].index(name) + 3))
                hover = request("textDocument/hover", position)
                assert hover and app_version not in hover["contents"]["value"], (fragment, hover)

        try:
            request("initialize", dict(rootUri=app.as_uri(), initializationOptions=dict(jobs=1, debounceMs=0, cache=True)))
            for path, source in ((app / "src/main.enq", app_source), (library / "src/lib.enq", library_source)):
                send(process, dict(jsonrpc="2.0", method="textDocument/didOpen", params=dict(
                    textDocument=dict(uri=path.as_uri(), version=1, text=source))))
            check("1.0.0", "2.0.0")
            manifests("1.1.0", "2.1.0")
            send(process, dict(jsonrpc="2.0", method="workspace/didChangeWatchedFiles", params=dict(changes=[
                dict(uri=(app / "encore.toml").as_uri(), type=2),
                dict(uri=(library / "encore.toml").as_uri(), type=2)])))
            check("1.1.0", "2.1.0")
            stop(process)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    print("project constants: hover, completion, semantic ownership and manifest invalidation passed")


if __name__ == "__main__":
    main()
