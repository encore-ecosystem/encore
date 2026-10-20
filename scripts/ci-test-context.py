#!/usr/bin/env python3
"""Transfer only the verified shared test harness, never entire build caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('operation', choices=['save', 'restore'])
parser.add_argument('compiler', type=Path)
parser.add_argument('fixture', type=Path)
parser.add_argument('context', type=Path)
args = parser.parse_args()
name = '__encore_unit_harness' + ('.exe' if os.name == 'nt' else '')
names = [name, name + '.fingerprint']
binary_dir = args.fixture / 'target/tests/bin'

if args.operation == 'save':
    args.context.mkdir(parents=True, exist_ok=False)
    files = {}
    for name in names:
        source = binary_dir / name
        if not source.is_file():
            raise SystemExit('Missing prepared test harness: ' + str(source))
        shutil.copy2(source, args.context / name)
        files[name] = digest(source)
    shutil.copy2(args.fixture / 'target/test-inventory.json', args.context / 'inventory.json')
    files['inventory.json'] = digest(args.context / 'inventory.json')
    manifest = {'schema': 1, 'commit': os.environ.get('GITHUB_SHA', ''),
                'compiler_sha256': digest(args.compiler), 'files': files}
    (args.context / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
else:
    manifest = json.loads((args.context / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema') != 1 or
            manifest.get('commit') != os.environ.get('GITHUB_SHA', '') or
            manifest.get('compiler_sha256') != digest(args.compiler) or
            set(manifest.get('files', {})) != {*names, 'inventory.json'}):
        raise SystemExit('Test harness provenance does not match this compiler/source')
    for name, checksum in manifest['files'].items():
        if digest(args.context / name) != checksum:
            raise SystemExit('Test harness checksum mismatch: ' + name)
    binary_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(args.context / name, binary_dir / name)
    # Artifact downloads normalize POSIX modes to 0644.
    if os.name != 'nt':
        (binary_dir / names[0]).chmod(0o755)
    # Encore still validates its ordinary source/toolchain fingerprint before
    # accepting this binary. Different source roots therefore remain safe.
    print('Restored verified shared test harness')
