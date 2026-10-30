#!/usr/bin/env python3
"""Check node ownership, cycles and bounded owner-search behavior natively."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='encore-node-') as directory:
        for name, sources in (
            ('node-runtime', ['packages/core/tests/node_runtime.c', 'packages/core/node_runtime.c']),
            ('node-owner-search', ['packages/core/tests/node_owner_search.c']),
        ):
            binary = Path(directory) / (name + ('.exe' if os.name == 'nt' else ''))
            command = [args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']
            if args.sanitize:
                command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            command += [str(root / source) for source in sources] + ['-o', str(binary)]
            subprocess.run(command, check=True, timeout=120)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            print(name + ': ' + ('ok' if result.returncode == 0 else 'FAILED'), flush=True)
            print(result.stdout, end='')
            print(result.stderr, end='')
            if result.returncode:
                raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
