#!/usr/bin/env python3
"""Exercise native TCP, TLS and IPC on the current host."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    default = '/opt/homebrew/opt/openssl@3' if sys.platform == 'darwin' else '/usr'
    prefix = Path(os.environ.get('OPENSSL_DIR', default))
    windows = os.name == 'nt'
    openssl = prefix / 'bin' / ('openssl.exe' if windows else 'openssl')
    executable = str(openssl) if openssl.is_file() else shutil.which('openssl')
    if not executable:
        raise SystemExit('OpenSSL CLI is required to generate the test certificate')
    with tempfile.TemporaryDirectory(prefix='encore-network-test-') as directory:
        output = Path(directory)
        key, cert = output / 'key.pem', output / 'cert.pem'
        subprocess.run([executable, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       capture_output=True, check=True)
        binary = output / ('network-test.exe' if windows else 'network-test')
        flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g', '-I' + str(prefix / 'include')]
        if windows:
            flags.append('-D_WIN32_WINNT=0x0601')
            library_dir = prefix / 'lib'
            suffix = '.lib' if (library_dir / 'libssl.lib').is_file() else '.a'
            links = [str(library_dir / ('libssl' + suffix)), str(library_dir / ('libcrypto' + suffix)),
                     '-lcrypt32', '-lws2_32', '-lbcrypt', '-ladvapi32', '-luser32']
        else:
            flags.extend(['-fsanitize=address,undefined', '-fno-omit-frame-pointer'])
            links = ['-L' + str(prefix / 'lib'), '-lssl', '-lcrypto', '-pthread']
        subprocess.run([os.environ.get('CC', 'clang'), *flags, str(ROOT / 'tests' / 'native.c'),
                        *links, '-o', str(binary)], check=True)
        subprocess.run([str(binary), str(cert), str(key)], timeout=120, check=True,
                       env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})


if __name__ == '__main__':
    main()
