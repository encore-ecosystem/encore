#!/usr/bin/env python3
"""Exercise std input through real pipes, including prompt flushing and EOF."""

from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


SOURCE = '''import std::io::{input, try_input, println, IoErrorKind}
import core::result::Result
fn main() -> u32 {
    println(input("name> "))
    match try_input("next> ") {
        Result::Ok(line) => { println(line) ret 0 }
        Result::Err(error) => {
            match error.kind {
                IoErrorKind::UnexpectedEof => { println("EOF") ret 2 }
                _ => { println("IO error") ret 3 }
            }
        }
    }
}
'''


def main():
    compiler = str(Path(sys.argv[1]).resolve())
    std = Path(__file__).resolve().parents[2] / "encore-index/packages/std"
    with tempfile.TemporaryDirectory(prefix="encore-input-") as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "src/main.enq").write_text(SOURCE, encoding="utf-8")
        (root / "encore.toml").write_text(
            '[project]\nname = "input_probe"\nversion = "0.0.0"\n'
            f'dependencies = ["path@{std.as_posix()}"]\n', encoding="utf-8")
        subprocess.run([compiler, "build"], cwd=root, check=True, timeout=180)
        binary = root / "target/dev" / ("input_probe.exe" if sys.platform == "win32" else "input_probe")
        for data, expected, status in (
            ("привет\r\nмир\n", "name> привет\nnext> мир\n", 0),
            ("\n\n", "name> \nnext> \n", 0),
            ("first\nlast", "name> first\nnext> last\n", 0),
            ("first\n", "name> first\nnext> EOF\n", 2),
            ("я" * 8192 + "\nend\n", "name> " + "я" * 8192 + "\nnext> end\n", 0),
        ):
            result = subprocess.run([str(binary)], input=data, capture_output=True,
                                    text=True, encoding="utf-8", timeout=10)
            assert (result.stdout, result.returncode) == (expected, status), result
        result = subprocess.run([str(binary)], input="", capture_output=True,
                                text=True, timeout=10)
        assert result.returncode != 0 and "end of input" in result.stdout + result.stderr, result

        # Linux's full device exercises prompt write/flush failure deterministically.
        if Path("/dev/full").exists():
            with open("/dev/full", "wb") as full:
                result = subprocess.run([str(binary)], input=b"unused\n", stdout=full,
                                        stderr=subprocess.PIPE, timeout=10)
                assert result.returncode != 0, result

        # Do not send input until the prompt is visible: buffered output would hang.
        process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            prompt = queue.Queue()
            threading.Thread(target=lambda: prompt.put(process.stdout.read(6)), daemon=True).start()
            assert prompt.get(timeout=5) == b"name> "
            out, err = process.communicate(b"ready\n\n", timeout=5)
            assert process.returncode == 0 and out.replace(b"\r\n", b"\n") == b"ready\nnext> \n", (out, err)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    print("std input: Unicode, long/empty lines, CRLF, EOF, panic, prompt flushing and available device-error checks passed")


if __name__ == "__main__":
    main()
