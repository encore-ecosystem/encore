#!/usr/bin/env python3
"""Probe foreign-model codec interop using a verified native CI compiler."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
FORMAT_FILES = (
    "src/frontend/translator/mod.enq",
    "tests/module_function_identity.enq",
    "tests/fixtures/reflection_codecs/model/src/lib.enq",
    "tests/fixtures/reflection_codecs/app/src/main.enq",
    "packages/json/src/lib.enq",
)
MODEL = '''import core::option::Option
import core::vec::Vec
pub struct Config {
    #serialize(rename = "stored_name")
    name: str
    count: i64
    samples: Vec[u32]
    optional: Option[str]
}
pub fn sample() -> Config {
    ret Config {
        "external-config", -42_i64,
        vec![1_u32, 2_u32, 4294967295_u32], Option::Some("present")
    }
}
pub fn valid(value: Config) -> bool {
    ret value.name == "external-config" && value.count == -42_i64
        && value.samples.len() == 3_usize
        && value.samples.get(0_usize).unwrap_or(0_u32) == 1_u32
        && value.samples.get(1_usize).unwrap_or(0_u32) == 2_u32
        && value.samples.get(2_usize).unwrap_or(0_u32) == 4294967295_u32
        && value.optional.unwrap_or("") == "present"
}
'''
IMPORTS = '''import binary
import binary::{BinarySerializer, BinaryDeserializer}
import core::result::Result
import interop_model::{Config, sample, valid}
import json
import json::{JsonSerializer, JsonDeserializer}
import serialize::{Serializer, Deserializer}
import std::io::eprintln
import std::os::argv
import toml
import toml::{TomlSerializer, TomlDeserializer}
'''
ROUNDTRIP = '''fn __NAME__() -> u32 {
    let config = sample()
    eprintln("__NAME__ encode")
    let encoded = match __ENCODE__ {
        Ok(value) => value
        Err(error) => { eprintln(error.message()) ret 1 }
    }
    __RENAME__
    eprintln("__NAME__ decode")
    match __DECODE__ {
        Ok(value) => { if !valid(value) { ret 3 } }
        Err(error) => { eprintln(error.message()) ret 4 }
    }
    eprintln("__NAME__: ok")
    ret 0
}
'''
CASES = (
    ("toml_convenience", "toml::encode(config)", "toml::decode[Config](encoded)", True),
    ("toml_traits", "Serializer::serialize(TomlSerializer[Config]::new(config))",
     "TomlDeserializer[Config]::new(encoded).deserialize()", True),
    ("json_convenience", "json::encode(config)", "json::decode[Config](encoded)", True),
    ("json_traits", "Serializer::serialize(JsonSerializer[Config]::new(config))",
     "JsonDeserializer[Config]::new(encoded).deserialize()", True),
    ("binary_convenience", "binary::encode(config)", "binary::decode[Config](encoded)", False),
    ("binary_traits", "Serializer::serialize(BinarySerializer[Config]::new(config))",
     "BinaryDeserializer[Config]::new(encoded).deserialize()", False),
)


def app_source():
    source = IMPORTS
    for name, encode, decode, renamed in CASES:
        source += (ROUNDTRIP.replace("__NAME__", name).replace("__ENCODE__", encode)
                   .replace("__DECODE__", decode).replace("__RENAME__",
                       'if !encoded.contains("stored_name") { ret 2 }' if renamed else ""))
    source += 'fn main() -> u32 {\n    let mode = argv(1_usize).unwrap_or("")\n'
    for name, *_ in CASES:
        source += f'    if mode == "{name}" {{ ret {name}() }}\n'
    return source + "    ret 99\n}\n"


def format_inputs(compiler):
    output = ROOT / "target/probe"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for relative in FORMAT_FILES:
        path = ROOT / relative
        before = path.read_bytes()
        try:
            result = subprocess.run([str(compiler), "format", str(path)], cwd=ROOT,
                                    text=True, capture_output=True, timeout=300)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            code, stdout, stderr = None, "", "formatter timed out after 300s"
        after = path.read_bytes()
        item = dict(path=relative, returncode=code, stdout=stdout, stderr=stderr,
                    changed=before != after, before_sha256=hashlib.sha256(before).hexdigest(),
                    after_sha256=hashlib.sha256(after).hexdigest())
        records.append(item)
        if code != 0:
            failures.append(relative)
        print(json.dumps(item), flush=True)
    changed = [item["path"] for item in records if item["changed"]]
    (output / "format-records.json").write_text(json.dumps(records, indent=2) + "\n")
    (output / "formatted-files.json").write_text(json.dumps(changed, indent=2) + "\n")
    with tarfile.open(output / "formatted-sources.tar.gz", "w:gz") as archive:
        for relative in changed:
            archive.add(ROOT / relative, arcname=relative)
    identity = dict(description="Candidate inputs after the explicitly recorded formatter edits",
                    all_inputs_match_candidate_commit=not changed,
                    sdk_checkout_matches_pins=not any(path.startswith("packages/") for path in changed),
                    formatted_files=records)
    (output / "formatted-input-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps(identity, indent=2), flush=True)
    if failures:
        raise SystemExit("candidate formatter failures: " + ", ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--format-candidates", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    if args.format_candidates:
        format_inputs(compiler)
        return
    output = ROOT / "target/toml-interop-probe"
    output.mkdir(parents=True, exist_ok=True)
    records = []

    def record(name, command, cwd, environment, timeout=600):
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=cwd, env=environment, text=True,
                                    encoding="utf-8", errors="replace", capture_output=True,
                                    timeout=timeout)
            item = dict(name=name, command=command, returncode=result.returncode,
                        stdout=result.stdout, stderr=result.stderr)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""

            item = dict(name=name, command=command, returncode=None, timeout=timeout,
                        stdout=decoded(error.stdout), stderr=decoded(error.stderr))
        item["seconds"] = round(time.monotonic() - start, 3)
        records.append(item)
        (output / (name + ".log")).write_text(item["stdout"] + "\n" + item["stderr"], encoding="utf-8")
        (output / "report.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(item), flush=True)
        return item["returncode"]

    def write_project(project, name, dependencies, source, source_name):
        (project / "src").mkdir(parents=True)
        (project / "encore.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.0.0"\ndependencies='
            + json.dumps(dependencies) + "\n", encoding="utf-8", newline="\n")
        (project / "src" / source_name).write_text(source, encoding="utf-8", newline="\n")

    with tempfile.TemporaryDirectory(prefix="foreign-codecs-", dir=output) as directory:
        temporary = Path(directory)
        model, app = temporary / "model", temporary / "app"
        package = lambda name: f"path@{(ROOT / 'packages' / name).as_posix()}"
        write_project(model, "interop_model", [package("core")], MODEL, "lib.enq")
        source = app_source()
        write_project(app, "toml_interop", [f"path@{model.as_posix()}"] +
                      [package(name) for name in ("core", "platform", "std", "serialize", "toml", "json", "binary")],
                      source, "main.enq")
        (output / "model.enq").write_text(MODEL, encoding="utf-8")
        (output / "app.enq").write_text(source, encoding="utf-8")
        environment = dict(os.environ, ENCORE_CORE_DIR=str(ROOT / "packages/core"),
                           ENCORE_BUILD_CACHE=str(temporary / "cache"),
                           ENCORE_REGISTRY_CACHE=str(temporary / "registry"),
                           ENCORE_INDEX_URL="http://127.0.0.1:9/index")
        if record("build", [str(compiler), "build", "--profile", "dev", "--jobs", "2"], app, environment) != 0:
            raise SystemExit("foreign codec app failed to build; see build.log")
        binary = app / "target/dev/toml_interop"
        failures = []
        for name, *_ in CASES:
            code = record(name, [str(binary), name], app, environment, 30)
            if code != 0:
                failures.append(name)
            if code is not None and code < 0:
                debugger = shutil.which("gdb")
                if debugger is None:
                    installed = record("gdb-install", ["sudo", "apt-get", "install", "-y",
                                                       "--no-install-recommends", "gdb"], app, environment)
                    if installed == 0:
                        debugger = shutil.which("gdb")
                if debugger:
                    record(name + "-backtrace", [debugger, "--batch", "-ex", "set pagination off",
                           "-ex", "run", "-ex", "thread apply all bt full", "-ex", "info registers",
                           "-ex", "x/16i $pc-32", "--args", str(binary), name], app, environment, 90)
        if failures:
            raise SystemExit("foreign codec runtime failures: " + ", ".join(failures))
    print("foreign Config passed all six TOML/JSON/binary codec APIs", flush=True)


if __name__ == "__main__":
    main()
