#!/usr/bin/env python3
"""Exercise compiler child ownership, exact argv, log isolation and cancellation."""

import ctypes
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time


RUNNING = -(2**31)


def main():
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-worker-") as directory:
        root = Path(directory) / "working directory with spaces"
        root.mkdir()
        shared = root / ("probe.dll" if os.name == "nt" else "probe.so")
        flags = [] if os.name == "nt" else ["-fPIC"]
        subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-shared", *flags, str(repository / "tests/native/build_process.c"), "-o", str(shared)],
                       check=True, timeout=60)
        library = ctypes.CDLL(str(shared))
        supervisor = root / ("supervisor.exe" if os.name == "nt" else "supervisor")
        subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(repository / "tests/native/build_process_supervisor.c"), "-o", str(supervisor)],
                       check=True, timeout=60)
        library.test_worker_spawn.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_size_t,
                                             ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        library.test_worker_spawn.restype = ctypes.c_size_t
        for name in ("poll", "cancel", "peak_rss", "close"):
            function = getattr(library, "test_worker_" + name)
            function.argtypes = [ctypes.c_size_t]
            function.restype = ctypes.c_uint64 if name == "peak_rss" else (None if name == "close" else ctypes.c_int)
        children = []
        sequence = 0

        def spawn(code, arguments=(), program=sys.executable, cwd=root):
            nonlocal sequence
            sequence += 1
            output, error = root / f"{sequence}.out", root / f"{sequence}.err"
            argv = ["-c", code, *arguments]
            encoded = (ctypes.c_char_p * len(argv))(*(os.fsencode(arg) for arg in argv))
            child = library.test_worker_spawn(os.fsencode(program), encoded, len(argv), os.fsencode(cwd),
                                             os.fsencode(output), os.fsencode(error))
            if child:
                children.append(child)
            return child, output, error

        def wait(child, timeout=15):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                status = library.test_worker_poll(child)
                if status != RUNNING:
                    return status
                time.sleep(0.005)
            raise AssertionError("compiler worker did not terminate")

        def wait_file(path, timeout=15):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if path.exists() and path.stat().st_size:
                    return path.read_text().strip()
                time.sleep(0.005)
            raise AssertionError(f"worker did not write {path}")

        def stopped(pid):
            if os.name == "nt":
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x100000, False, pid)
                if not handle:
                    return True
                try:
                    return kernel.WaitForSingleObject(handle, 0) == 0
                finally:
                    kernel.CloseHandle(handle)
            status = Path(f"/proc/{pid}/stat")
            if sys.platform.startswith("linux") and status.exists():
                return status.read_text().split(") ", 1)[1].startswith("Z")
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                return True

        try:
            arguments = ["", "hello world", 'quote"inside', "trailing\\", 'slashes\\\\"quote',
                         "Русский текст", "$(never-run)", "; no shell ;"]
            child, output, error = spawn("import os,sys,json; print(json.dumps([os.getcwd(),sys.argv[1:]])); "
                                         "print('isolated stderr',file=sys.stderr)", arguments)
            assert child and wait(child) == 0
            assert json.loads(output.read_text()) == [str(root), arguments]
            assert error.read_text().strip() == "isolated stderr"
            assert library.test_worker_poll(child) == 0, "poll did not retain reaped status"
            assert library.test_worker_peak_rss(child) > 0, "missing native peak RSS"
            failed, _, _ = spawn("raise SystemExit(17)")
            assert failed and wait(failed) == 17
            assert not spawn("", program=root / "missing compiler")[0]
            assert not spawn("", cwd=root / "missing directory")[0]

            # Two independently owned workers. Cancellation must not kill the
            # sibling; the long-lived worker's tool must be killed with it.
            code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); " \
                   "print(p.pid,flush=True); time.sleep(60)"
            worker, output, _ = spawn(code)
            sibling, sibling_output, _ = spawn("import time; print('ready',flush=True); time.sleep(60)")
            tool_pid = int(wait_file(output))
            assert wait_file(sibling_output) == "ready"
            assert library.test_worker_poll(worker) == RUNNING
            assert library.test_worker_cancel(worker) not in (RUNNING, 0)
            assert library.test_worker_poll(sibling) == RUNNING, "cancellation killed an unrelated worker"
            deadline = time.monotonic() + 5
            while not stopped(tool_pid) and time.monotonic() < deadline:
                time.sleep(0.005)
            assert stopped(tool_pid), "cancelled worker left a tool running"

            # Close is an ownership operation, not a handle-only free.
            library.test_worker_close(sibling)
            children.remove(sibling)
            library.test_worker_close(sibling)
            assert library.test_worker_poll(sibling) == RUNNING + 1, "closed handle was still addressable"
            replacement, _, _ = spawn("raise SystemExit(0)")
            assert replacement != sibling and wait(replacement) == 0, "stale handle identity was reused"
            if os.name != "nt":
                stubborn, output, _ = spawn("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                                            "print('ready',flush=True); time.sleep(60)")
                wait_file(output)
                assert library.test_worker_cancel(stubborn) == 137
                signalled, _, _ = spawn("import os,signal; os.kill(os.getpid(),signal.SIGTERM)")
                assert wait(signalled) == 143
            # A nominally successful worker also cannot orphan a native tool.
            orphan, output, _ = spawn("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',"
                                       "'import time; time.sleep(60)']); print(p.pid,flush=True)")
            orphan_pid = int(wait_file(output))
            assert wait(orphan) == 0
            deadline = time.monotonic() + 5
            while not stopped(orphan_pid) and time.monotonic() < deadline:
                time.sleep(0.005)
            assert stopped(orphan_pid), "completed compiler worker orphaned a tool"

            # Test the coordinator's own lifecycle, not merely an explicit
            # cancel call. A graceful exit/signal must reap children, and a
            # killed coordinator must not orphan the worker's native tools.
            guard = ("import ctypes,sys; lib=ctypes.CDLL(" + repr(str(shared)) + "); "
                     "lib.test_worker_watch_parent.argtypes=[ctypes.c_uint64]; "
                     "lib.test_worker_watch_parent.restype=ctypes.c_bool; "
                     "assert lib.test_worker_watch_parent(int(sys.argv[1])); ")
            worker_code = guard + "import os,subprocess,time; p=subprocess.Popen([sys.executable,'-c'," \
                          "'import time; time.sleep(60)']); print(os.getpid(),p.pid,flush=True); time.sleep(60)"
            managed_code = guard + (
                "import os,time; "
                "lib.test_worker_spawn.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_char_p),ctypes.c_size_t,"
                "ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p]; "
                "lib.test_worker_spawn.restype=ctypes.c_size_t; "
                "args=(ctypes.c_char_p*2)(b'-c',b'import os,time; print(os.getpid(),flush=True); time.sleep(60)'); "
                "assert lib.test_worker_spawn(os.fsencode(sys.executable),args,2,os.fsencode(os.getcwd()),"
                "b'managed-tool.out',b'managed-tool.err'); "
                "\nwhile not os.path.exists('managed-tool.out') or not os.path.getsize('managed-tool.out'): time.sleep(.005)\n"
                "print(os.getpid(),open('managed-tool.out').read().strip(),flush=True); time.sleep(60)"
            )
            operations = ["exit"] if os.name == "nt" else ["exit", signal.SIGINT, signal.SIGTERM, signal.SIGKILL]
            scenarios = [(code, operation) for code in (worker_code, managed_code) for operation in operations]
            for index, (code, operation) in enumerate(scenarios):
                (root / "managed-tool.out").unlink(missing_ok=True)
                output, error = root / f"supervisor-{index}.out", root / f"supervisor-{index}.err"
                parent = subprocess.Popen([str(supervisor), "exit" if operation == "exit" else "wait",
                                           sys.executable, code, str(root), str(output), str(error)],
                                          stdin=subprocess.PIPE)
                ids = []
                try:
                    ids = list(map(int, wait_file(output).split()))
                    assert len(ids) == 2, output.read_text() + error.read_text()
                    if operation == "exit":
                        parent.communicate(b"\n", timeout=10)
                        assert parent.returncode == 0
                    else:
                        parent.send_signal(operation)
                        parent.wait(timeout=10)
                        assert parent.returncode == (-signal.SIGKILL if operation == signal.SIGKILL else 128 + operation)
                    deadline = time.monotonic() + 5
                    while not all(stopped(pid) for pid in ids) and time.monotonic() < deadline:
                        time.sleep(0.005)
                    assert all(stopped(pid) for pid in ids), f"coordinator {operation} orphaned {ids}"
                finally:
                    if parent.poll() is None:
                        parent.kill()
                        parent.wait(timeout=10)
                    if parent.stdin is not None:
                        parent.stdin.close()
                    # Only fixture-owned PIDs are ever cleanup targets.
                    for pid in ids:
                        if not stopped(pid):
                            if os.name == "nt":
                                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                            else:
                                os.kill(pid, signal.SIGKILL)
        finally:
            for child in children:
                library.test_worker_close(child)
    print("compiler processes: argv/UTF-8/spaces, logs/RSS, stale handles, reap, sibling isolation, tools, coordinator exit/signals/death passed")


if __name__ == "__main__":
    main()
