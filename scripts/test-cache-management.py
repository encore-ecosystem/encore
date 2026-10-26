#!/usr/bin/env python3
"""Exercise the real cache CLI in disposable directories, never the user's cache."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import struct
import tempfile

compiler = Path(sys.argv[1]).resolve()
checks = []


def snapshot(root, open_files=()):
    streams = {Path(stream.name): stream for stream in open_files}

    def contents(path):
        stream = streams.get(path)
        if stream is None:
            return path.read_bytes()
        # Windows byte-range locks also deny reads through a second handle
        # in this process. Inspect the lease through the handle owning its lock.
        position = stream.tell()
        try:
            stream.seek(0)
            return stream.read()
        finally:
            stream.seek(position)

    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns,
                   hashlib.sha256(contents(p)).hexdigest())
                  for p in root.rglob('*') if p.is_file() and not p.is_symlink())


def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    stream = path.open('r+b')
    if os.name == 'nt':
        import msvcrt
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return stream


with tempfile.TemporaryDirectory(prefix='encore-cache-policy-') as temporary:
    root = Path(temporary).resolve()
    cache = root / 'cache'
    cache.mkdir()
    project = root / 'project'
    project.mkdir()
    (project / 'encore.toml').write_text('[project]\nname="fixture"\nversion="0.0.0"\n')
    environment = {**os.environ, 'ENCORE_BUILD_CACHE': str(cache),
                   'ENCORE_BUILD_CACHE_MAX_SIZE': '20GiB'}

    def invoke(*args, code=0):
        result = subprocess.run([str(compiler), 'cache', *args], env=environment,
                                cwd=project, capture_output=True, text=True, timeout=60)
        assert result.returncode == code, (args, result.returncode, result.stdout, result.stderr)
        return json.loads(result.stdout) if code == 0 else result.stderr

    def entry(name, used, size=700000, category='units'):
        key = hashlib.sha256(name.encode()).hexdigest()
        parent = cache if category == 'units' else cache / category
        directory = parent / key
        directory.mkdir(parents=True)
        (directory / ('unit.complete' if category == 'units' else 'commit')).write_text('{}')
        (directory / 'payload').write_bytes(b'x' * size)
        (directory / '.last-used').write_text(str(used))
        return directory

    oldest = entry('old', 1)
    middle = entry('middle', 2, category='lowering-v1')
    newest = entry('new', 3, category='objects-v1')
    unknown = cache / 'unmanaged'
    unknown.mkdir()
    (unknown / 'notes').write_text('preserve')
    before = snapshot(cache)
    estimate = invoke('prune', '--dry-run', '--max-size', '1MiB', '--json')
    assert snapshot(cache) == before
    assert estimate['cache_reclaimed_bytes'] > 0
    checks.append('dry run is read-only')
    invoke('prune', '--max-size', '18446744073709551616', code=2)
    invoke('prune', '--max-size', '-1', code=2)
    invoke('status', '--unexpected', code=2)
    assert snapshot(cache) == before
    checks.append('invalid sizes/options reject without mutation')
    result = invoke('prune', '--max-size', '1MiB', '--json')
    assert not oldest.exists() and not middle.exists() and newest.exists()
    assert result['after_bytes'] <= 1048576
    assert unknown.exists()
    checks.append('LRU eviction spans all cache stages and preserves unknown files')
    held_path = newest.parent / (newest.name + '.lock')
    with lock(held_path):
        actual = invoke('prune', '--all', '--json')
        predicted = invoke('prune', '--all', '--dry-run', '--json')
        assert newest.exists() and actual['busy_entries'] == 1 and predicted['busy_entries'] == 1
    invoke('prune', '--all', '--json')
    assert not newest.exists() and held_path.exists()
    checks.append('active cache locks protect payloads and lock files survive eviction')
    key = hashlib.sha256(b'flat-record').hexdigest()
    flat = cache / 'lowering-v2' / key[:2] / (key + '.entry')
    flat.parent.mkdir(parents=True)
    content = b'flat payload'
    envelope = b'ENQCP001' + bytes(8) + struct.pack('<QQ', len(content), len(content)) + hashlib.sha256(content).hexdigest().encode() + content
    flat.write_bytes(envelope)
    stable_lock = cache / 'lowering-v1' / (key + '.lock')
    status = invoke('status', '--json')
    assert status['categories']['lowering-v2'] == len(envelope)
    assert status['logical_bytes'] == len(content) and status['files'] == 1
    before = snapshot(cache)
    invoke('prune', '--all', '--dry-run', '--json')
    assert snapshot(cache) == before
    with lock(stable_lock):
        assert invoke('prune', '--all', '--json')['busy_entries'] == 1
        assert flat.exists()
    invoke('prune', '--all', '--json')
    assert not flat.exists() and stable_lock.exists()
    checks.append('flat records share legacy locks, report decoded size and survive read-only dry runs')

    victim = root / 'victim'
    victim.mkdir()
    (victim / 'unit.complete').write_text('{}')
    (victim / 'payload').write_text('keep')
    if os.name != 'nt':
        (cache / ('a' * 64)).symlink_to(victim, target_is_directory=True)
        invoke('prune', '--all', '--json')
        assert (victim / 'payload').read_text() == 'keep'
        checks.append('symlink entries are never followed')

    def workspace(name, retained=False, outcome='success'):
        directory = project / 'target/dev' / name
        directory.mkdir(parents=True)
        (directory / '.encore-workspace.json').write_text(json.dumps({
            'schema': 'encore-build-workspace-1', 'path': str(directory), 'retained': retained}))
        lease = directory.parent / '.encore-leases' / (name + '.lock')
        lease.parent.mkdir(exist_ok=True)
        lease.touch(mode=0o600)
        lease.chmod(0o600)
        if outcome is not None:
            (directory / '.outcome').write_text(outcome)
        (directory / 'module.ll').write_text('discard intermediate IR')
        return directory, lease

    active, lease = workspace('packages-active')
    retained, _ = workspace('packages-retained', retained=True)
    stale, _ = workspace('packages-stale')
    failed, _ = workspace('packages-failed', outcome=None)
    (failed / 'worker.stderr').write_text('compiler error evidence')
    legacy = project / 'target/dev/packages-legacy'
    legacy.mkdir()
    (legacy / 'user-file').write_text('unregistered workspace')
    binary = project / 'target/dev/fixture'
    binary.write_text('final binary')
    with lock(lease) as held_lease:
        status = invoke('status', '--json')
        states = {Path(item['path']).name: item['state'] for item in status['workspaces']}
        assert states['packages-active'] == 'active'
        assert states['packages-retained'] == 'retained'
        before = snapshot(project, (held_lease,))
        invoke('prune', '--dry-run', '--json')
        assert snapshot(project, (held_lease,)) == before
        invoke('prune', '--json')
        assert active.exists() and retained.exists() and not stale.exists() and not failed.exists()
    invoke('prune', '--json')
    assert not active.exists() and retained.exists() and legacy.exists() and binary.exists()
    report = project / 'target/diagnostics/packages-failed'
    assert (report / 'worker.stderr').read_text() == 'compiler error evidence'
    assert not (report / 'module.ll').exists()
    checks.append('active/retained workspaces, legacy directories and final outputs stay intact')
    checks.append('crashed workspace saves diagnostic text and discards IR')
    for index in range(12):
        workspace('packages-error-' + str(index), outcome='failure\nmessage')
    invoke('prune', '--json')
    reports = list((project / 'target/diagnostics').iterdir())
    assert len(reports) == 10
    checks.append('diagnostic history is bounded')
    assert invoke('status', '--json')['limit_bytes'] == 20 * 1024 ** 3
    checks.append('default budget is 20 GiB')
    for index in range(4000):
        (cache / (hashlib.sha256(str(index).encode()).hexdigest() + '.lock')).touch()
    assert invoke('status', '--json')['limit_bytes'] == 20 * 1024 ** 3
    assert len(list(cache.glob('*.lock'))) >= 4000
    checks.append('large directories are scanned within the command timeout')
    if sys.platform == 'linux':
        native = Path(__file__).resolve().parents[1] / 'tests/native/cache_payload_allocation.c'
        cc = os.environ.get('ENCORE_CC') or shutil.which('clang')
        assert cc, 'Clang is required for the native allocation-failure contract'
        probe = root / 'allocation-probe'
        subprocess.run([cc, '-std=c11', '-O1', str(native), '-pthread', '-o', str(probe)],
                       check=True, capture_output=True, text=True, timeout=60)
        subprocess.run([str(probe), str(root / 'allocation-payload')], check=True, timeout=30)
        checks.append('SHA allocation failure is a cache miss and never frees immortal strings')


print(json.dumps({'passed': len(checks), 'checks': checks}, indent=2))
