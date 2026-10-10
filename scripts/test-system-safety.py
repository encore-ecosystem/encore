#!/usr/bin/env python3
"""Exercise audited primitive boundaries using their actual library bodies."""

import argparse
import os
import re
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("compiler", type=Path)
    args = parser.parse_args()
    compiler = str(args.compiler.resolve())
    index = Path(__file__).resolve().parents[2] / "encore-index"
    operators = (index / "packages/core/src/ops/mod.enq").read_text()
    sources = ["import core::panic::panic\nimport core::vec::Vec\nimport std::os::argv\n"]
    valid = []
    invalid = []
    # Compile the exact implementation bodies as independent entry points.
    # This avoids depending on static operator-trait dispatch to test a guard.
    for match in re.finditer(r"impl (Div|Rem|Shl|Shr)\[([ui](?:8|16|32|64|size))\] for \2 \{", operators):
        operation, typ = match.groups()
        start = operators.index("pub fn op", match.end())
        opening = operators.index("{", start)
        depth, end = 1, opening + 1
        while depth:
            depth += (operators[end] == "{") - (operators[end] == "}")
            end += 1
        name = f"checked_{operation.lower()}_{typ}"
        sources.append(operators[start:end].replace("pub fn op", f"fn {name}", 1))
        left, right, expected = {"Div": (12, 3, 4), "Rem": (12, 5, 2),
                                 "Shl": (1, 3, 8), "Shr": (8, 3, 1)}[operation]
        valid.append(f"if {name}({left}_{typ}, {right}_{typ}) != {expected}_{typ} {{ ret 2 }}")
        if operation in ("Div", "Rem"):
            invalid.append((f"{name}_zero", f"{name}(1_{typ}, 0_{typ})", "integer division by zero"))
            if typ.startswith("i") and operation == "Div":
                minimum = {"i8": "-128_i8", "i16": "-32768_i16", "i32": "-2147483648_i32",
                           "i64": "-9223372036854775808_i64", "isize": "((1_usize << (word_bits() - 1_usize)) as isize)"}[typ]
                invalid.append((f"{name}_overflow", f"{name}({minimum}, -1_{typ})", "integer division overflow"))
            if typ.startswith("i") and operation == "Rem":
                valid.append(f"if {name}(-12_{typ}, -1_{typ}) != 0_{typ} {{ ret 3 }}")
        else:
            width = f"(word_bits() as {typ})" if typ.endswith("size") else f"{typ[1:]}_{typ}"
            invalid.append((f"{name}_wide", f"{name}(1_{typ}, {width})", "integer shift out of range"))
            if typ.startswith("i"):
                invalid.append((f"{name}_negative", f"{name}(1_{typ}, -1_{typ})", "integer shift out of range"))
    assert len(valid) == 45 and len(invalid) == 55, (len(valid), len(invalid))
    sources.append("extern fn encore_word_bits() -> usize\n#attr(safe)\nfn word_bits() -> usize { unsafe { ret encore_word_bits() } }")
    sources.append('fn main() -> u32 { let mode = argv(1_usize).unwrap_or("ok")\nmatch mode {\n')
    sources.append('"vec_capacity" => { let ignored = Vec[u64]::with_capacity(0_usize - 1_usize) ret 99 }\n'
                   '"vec_reserve" => { let mut vec = Vec[u8]::singleton(1_u8) vec.reserve(0_usize - 1_usize) ret 99 }\n')
    sources.extend(f'"{name}" => {{ let ignored = {call} ret 99 }}\n' for name, call, _ in invalid)
    sources.append("_ => {}\n}\n" + "\n".join(valid) + "\nret 0\n}")
    with tempfile.TemporaryDirectory(prefix="encore-system-safety-") as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "encore.toml").write_text(
            '[project]\nname="system_safety"\nversion="0.0.0"\n'
            f'dependencies=["path@{(index / "packages/std").as_posix()}"]\n')
        (root / "src/main.enq").write_text("\n\n".join(sources))
        subprocess.run([compiler, "build", "--jobs", "2"], cwd=root, check=True, timeout=180)
        binary = root / "target/dev" / ("system_safety.exe" if os.name == "nt" else "system_safety")
        subprocess.run([str(binary)], cwd=root, check=True, timeout=10)
        for name, _, message in invalid:
            result = subprocess.run([str(binary), name], cwd=root, capture_output=True, text=True, timeout=10)
            assert result.returncode == 1 and message in result.stderr, (name, result)
        for name in ("vec_capacity", "vec_reserve"):
            result = subprocess.run([str(binary), name], cwd=root, capture_output=True, text=True, timeout=10)
            assert result.returncode == 1 and "Vec capacity overflow" in result.stderr, (name, result)
    print("primitive boundaries: 45 valid cases, 55 rejected arguments, 2 Vec overflow cases; ok")


if __name__ == "__main__":
    main()
