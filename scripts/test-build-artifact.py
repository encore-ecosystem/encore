#!/usr/bin/env python3
"""Exercise actual native atomic writes and crash-safe per-unit cache locks."""

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def load_library(path):
    library = ctypes.CDLL(str(path))
    library.test_artifact_write.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
    library.test_artifact_write.restype = ctypes.c_bool
    library.test_cache_lock_open.argtypes = [ctypes.c_char_p]
    library.test_cache_lock_open.restype = ctypes.c_size_t
    library.test_cache_lock_try.argtypes = [ctypes.c_size_t]
    library.test_cache_lock_try.restype = ctypes.c_int
    library.test_cache_lock_close.argtypes = [ctypes.c_size_t]
    return library


def child(library_path, lock_path, mode):
    library = load_library(library_path)
    lock = library.test_cache_lock_open(os.fsencode(lock_path))
    assert lock
    print(library.test_cache_lock_try(lock), flush=True)
    if mode == "crash":
        os._exit(17)
    sys.stdin.readline()
    library.test_cache_lock_close(lock)


def main():
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-artifact-") as directory:
        root = Path(directory) / "cache with spaces"
        root.mkdir()
        shared = root / ("probe.dll" if os.name == "nt" else "probe.so")
        flags = [] if os.name == "nt" else ["-fPIC"]
        subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-shared", *flags, str(repository / "tests/native/build_artifact.c"), "-o", str(shared)],
                       check=True, timeout=60)
        library = load_library(shared)
        path = root / "metadata.ermeta"
        # A leftover name from an earlier process incarnation must not block
        # admission or be removed as if it belonged to this transaction.
        stale = root / f"metadata.ermeta.tmp-{os.getpid()}-0"
        stale.write_bytes(b"previous transaction")
        blobs = [(f"record-{index}:".encode() * 8192) + b"\x00end" for index in range(4)]
        assert library.test_artifact_write(os.fsencode(path), blobs[0], len(blobs[0]))
        assert stale.read_bytes() == b"previous transaction"
        errors = []
        running = threading.Event()
        running.set()

        def reader():
            while running.is_set():
                try:
                    assert path.read_bytes() in blobs, "observed a partial artifact"
                except BaseException as error:
                    errors.append(error)
                    return

        def writer(blob):
            try:
                for _ in range(25):
                    assert library.test_artifact_write(os.fsencode(path), blob, len(blob))
            except BaseException as error:
                errors.append(error)

        observer = threading.Thread(target=reader)
        workers = [threading.Thread(target=writer, args=(blob,)) for blob in blobs]
        observer.start()
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=30)
                assert not worker.is_alive(), "artifact writer stalled"
        finally:
            running.clear()
            observer.join(timeout=10)
        assert not errors, errors
        assert list(root.glob("metadata.ermeta.tmp-*")) == [stale], "write leaked a temporary artifact"
        assert not library.test_artifact_write(os.fsencode(root / "missing/artifact"), b"x", 1)
        assert path.read_bytes() in blobs, "failed write changed an existing artifact"
        assert library.test_artifact_write(os.fsencode(root / "empty"), None, 0)
        assert (root / "empty").read_bytes() == b""

        def start(lock_path, mode):
            return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(shared),
                                     str(lock_path), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)

        lock_path = root / "unit.lock"
        lock = library.test_cache_lock_open(os.fsencode(lock_path))
        assert lock and library.test_cache_lock_try(lock) == 1
        competitor = start(lock_path, "hold")
        try:
            assert competitor.stdout.readline().strip() == "0", "competing build entered the transaction"
            competitor.communicate("done\n", timeout=15)
            assert competitor.returncode == 0
        finally:
            if competitor.poll() is None:
                competitor.kill()
            competitor.communicate(timeout=15)
        library.test_cache_lock_close(lock)
        crashed = start(lock_path, "crash")
        output, error = crashed.communicate(timeout=15)
        assert output.strip() == "1" and crashed.returncode == 17, error
        recovered = library.test_cache_lock_open(os.fsencode(lock_path))
        assert recovered and library.test_cache_lock_try(recovered) == 1, "crash stranded a cache key"
        library.test_cache_lock_close(recovered)
        if os.name != "nt":
            linked = root / "linked.lock"
            linked.symlink_to(lock_path)
            assert not library.test_cache_lock_open(os.fsencode(linked)), "followed a cache-lock symlink"
    print("artifact cache: atomic replacement/readers, binary/empty payloads, concurrent writers, process locks, crash recovery passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:])
    else:
        main()
