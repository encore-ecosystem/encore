#!/usr/bin/env python3
"""Organize imports preserves source boundaries and current document versions."""
from pathlib import Path
import subprocess
import sys
import tempfile

from protocol_features import request, send


def offset(source, position):
    lines = source.splitlines(keepends=True)
    line = lines[position['line']]
    prefix = line.encode('utf-16-le')[:position['character'] * 2].decode('utf-16-le')
    return sum(map(len, lines[:position['line']])) + len(prefix)


def main():
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='encore-organize-imports-') as directory:
        root = Path(directory)
        (root / 'src/tools').mkdir(parents=True)
        (root / 'encore.toml').write_text('[project]\nname="organize"\nversion="0.0.0"\ndependencies=[]\n')
        (root / 'src/tools/mod.enq').write_text(
            'pub fn used() -> u32 { ret 1 }\npub fn unused() -> u32 { ret 2 }\n'
            'pub fn reexported() -> u32 { ret 3 }\npub fn comment_only() -> u32 { ret 4 }\n')
        (root / 'src/tools/nested.enq').write_text(
            'pub fn used_nested() -> u32 { ret 1 }\npub fn spare() -> u32 { ret 2 }\n')
        (root / 'src/other.enq').write_text('pub fn globbed() -> u32 { ret 0 }\n')
        source = ('// 🦊 Preserve Unicode and comments.\nimport mod::tools::{\n'
                  '    used as kept,\n    unused,\n'
                  '    nested::{used_nested as visible, spare},\n}\n'
                  'pub import mod::tools::reexported\nimport mod::other::*\n'
                  'import mod::tools::{ /* retain context */ comment_only }\n'
                  'fn main() -> u32 { ret kept() + visible() }\n')
        path = root / 'src/main.enq'
        path.write_text(source)
        uri = path.as_uri()
        process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            info = request(process, 1, 'initialize', {'rootUri': root.as_uri()})
            assert 'source.organizeImports' in info['capabilities']['codeActionProvider']['codeActionKinds']
            send(process, {'jsonrpc': '2.0', 'method': 'textDocument/didOpen', 'params': {
                'textDocument': {'uri': uri, 'languageId': 'encore', 'version': 11, 'text': source}}})
            request(process, 2, 'textDocument/diagnostic', {'textDocument': {'uri': uri}})
            params = {'textDocument': {'uri': uri}, 'range': {
                'start': {'line': 0, 'character': 0}, 'end': {'line': 10, 'character': 0}},
                'context': {'diagnostics': [], 'only': ['source.organizeImports']}}
            actions = request(process, 3, 'textDocument/codeAction', params)
            assert len(actions) == 1 and actions[0]['kind'] == 'source.organizeImports', actions
            change = actions[0]['edit']['documentChanges'][0]
            assert change['textDocument'] == {'uri': uri, 'version': 11}, change
            edits = sorted((offset(source, edit['range']['start']),
                            offset(source, edit['range']['end']), edit['newText'])
                           for edit in change['edits'])
            assert len(edits) == 1, edits
            for start, end, replacement in reversed(edits):
                source = source[:start] + replacement + source[end:]
            assert 'unused' not in source and 'spare' not in source, source
            for retained in ['used as kept', 'used_nested as visible',
                             'pub import mod::tools::reexported', 'import mod::other::*',
                             '/* retain context */ comment_only', '// 🦊']:
                assert retained in source, (retained, source)
            send(process, {'jsonrpc': '2.0', 'method': 'textDocument/didChange', 'params': {
                'textDocument': {'uri': uri, 'version': 12}, 'contentChanges': [{'text': source}]}})
            request(process, 4, 'textDocument/diagnostic', {'textDocument': {'uri': uri}})
            assert request(process, 5, 'textDocument/codeAction', params) == []
            request(process, 6, 'shutdown', {})
            send(process, {'jsonrpc': '2.0', 'method': 'exit', 'params': {}})
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    print('organize imports, aliases, nested groups, comments and document versions: ok')


if __name__ == '__main__':
    main()
