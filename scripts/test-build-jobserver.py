#!/usr/bin/env python3
"""Exercise one CPU/RAM budget across real processes, including worker crashes."""

from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def load_library(path):
    library = ctypes.CDLL(str(path))
    for name, parameters, result in (
        ("create", [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint64], ctypes.c_size_t),
        ("attach", [ctypes.c_char_p, ctypes.c_uint64], ctypes.c_size_t),
        ("acquire", [ctypes.c_size_t], ctypes.c_int),
        ("release", [ctypes.c_size_t], ctypes.c_bool),
        ("cancel", [ctypes.c_size_t], None),
        ("used", [ctypes.c_size_t], ctypes.c_size_t),
        ("close", [ctypes.c_size_t], None),
    ):
        function = getattr(library, "test_jobserver_" + name)
        function.argtypes = parameters
        function.restype = result
        setattr(library, name, function)
    return library


def child(library_path, server_path, memory, mode):
    library = load_library(library_path)
    server = library.attach(os.fsencode(server_path), int(memory))
    if not server:
        print("rejected", flush=True)
        return
    result = library.acquire(server)
    print(result, flush=True)
    if mode == "crash":
        os._exit(17)
    command = sys.stdin.readline().strip()
    if command == "acquire":
        print(library.acquire(server), flush=True)
    library.close(server)


def main():
    repository = Path(__file__).resolve().parents[1]
    processes = []
    with tempfile.TemporaryDirectory(prefix="encore-jobserver-") as directory:
        root = Path(directory)
        library_path = root / ("probe.dll" if os.name == "nt" else "probe.so")
        native_flags = [] if os.name == "nt" else ["-pthread", "-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        if sys.platform == "darwin":
            native_flags.append("-D_DARWIN_C_SOURCE")
        subprocess.run([
            os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-shared", *native_flags, str(repository / "tests/native/build_jobserver.c"),
            "-o", str(library_path),
        ], check=True, timeout=60)
        library = load_library(library_path)

        def start(path, memory=10, mode="hold"):
            process = subprocess.Popen([
                sys.executable, str(Path(__file__).resolve()), "--child", str(library_path),
                str(path), str(memory), mode,
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                response = executor.submit(process.stdout.readline).result(timeout=15).strip()
            except BaseException:
                process.kill()
                process.communicate(timeout=10)
                raise
            finally:
                executor.shutdown(wait=True)
            assert response, process.stderr.read()
            return process, response

        def finish(process, command="done"):
            output, error = process.communicate(command + "\n", timeout=15)
            assert process.returncode == 0, (output, error)
            return output.strip()

        try:
            for jobs in (1, 2, 4, 8):
                path = root / f"jobs-{jobs}"
                server = library.create(os.fsencode(path), jobs, 1000)
                assert server
                assert not library.create(os.fsencode(path), jobs, 1000), "overwrote an active jobserver"
                assert not library.release(server), "lease underflow"
                workers = []
                for _ in range(jobs):
                    process, response = start(path)
                    assert response == "1", response
                    workers.append(process)
                assert library.used(server) == jobs
                extra, response = start(path)
                assert response == "0", response
                finish(workers.pop())
                assert library.used(server) == jobs - 1
                # The waiting child acquires the released token; no extra token
                # or implicit nested-worker budget appears at jobs=1.
                assert finish(extra, "acquire") == "1"
                for process in workers:
                    finish(process)
                assert library.used(server) == 0
                crashed, response = start(path, mode="crash")
                assert response == "1"
                assert crashed.wait(timeout=15) == 17
                assert library.used(server) == 0, "worker crash stranded CPU/RAM"
                for _ in range(jobs):
                    assert library.acquire(server) == 1
                assert library.acquire(server) == 0
                for _ in range(jobs):
                    assert library.release(server)
                assert not library.release(server)
                library.cancel(server)
                assert library.acquire(server) == -1
                rejected, response = start(path)
                assert response == "rejected"
                finish(rejected)
                library.close(server)

            path = root / "ram"
            server = library.create(os.fsencode(path), 2, 15)
            first, response = start(path)
            assert response == "1"
            too_large, response = start(path)
            assert response == "rejected"
            finish(too_large)
            finish(first)
            # Admission succeeds after both lease and RAM have been returned.
            admitted, response = start(path)
            assert response == "1"
            library.close(server)
            assert finish(admitted, "acquire") == "-1", "coordinator close did not cancel children"

            path = root / "processes"
            server = library.create(os.fsencode(path), 1, 0)
            first, response = start(path)
            assert response == "1"
            second, response = start(path)
            assert response == "0"
            third, response = start(path)
            assert response == "rejected", "exceeded 2 * jobs live compiler slots"
            finish(third)
            finish(first)
            finish(second)
            library.close(server)

            path = root / "ram-overflow"
            server = library.create(os.fsencode(path), 2, 0)
            largest, response = start(path, memory=2**64 - 1)
            assert response == "1"
            overflow, response = start(path, memory=1)
            assert response == "rejected", "unknown RAM budget allowed accounting overflow"
            finish(overflow)
            finish(largest)
            recovered, response = start(path, memory=1)
            assert response == "1"
            finish(recovered)
            library.close(server)
            malformed = root / "malformed"
            malformed.write_bytes(b"not a shared jobserver")
            assert not library.attach(os.fsencode(malformed), 0)
            assert not library.create(os.fsencode(root / "zero"), 0, 0)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=15)
    print("jobserver: jobs=1/2/4/8, cross-process leases, RAM, process limit, crash recovery, cancellation passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:])
    else:
        main()
