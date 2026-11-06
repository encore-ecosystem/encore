#!/usr/bin/env python3
"""Check SDK bootstrap compatibility and formatting using a seed on GitHub."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import json
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--seed-tag", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = root / "target/sdk-audit"
output.mkdir(parents=True, exist_ok=True)
asset = "encore-x86_64-unknown-linux-gnu.tar.gz"
subprocess.run(["gh", "release", "download", args.seed_tag, "--repo", "encore-ecosystem/encore",
                "--pattern", asset, "--pattern", asset + ".sha256", "--dir", str(output)], check=True)
expected = (output / (asset + ".sha256")).read_text().split()[0].lower()
assert hashlib.sha256((output / asset).read_bytes()).hexdigest() == expected
with tarfile.open(output / asset) as archive:
    archive.extractall(output / "seed", filter="data")
compiler = next((output / "seed").glob("*/bin/encore"))
compiler.chmod(0o755)
environment = dict(os.environ, ENCORE_CORE_DIR=str(root / "packages/core"), ENCORE_INDEX_URL="http://127.0.0.1:9/index")
failures = []
def run(name, command, cwd=root, extra_environment=None):
    result = subprocess.run(command, cwd=cwd, env=environment | (extra_environment or {}), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / (name + ".log")).write_text(result.stdout)
    if result.returncode:
        failures.append(name)
        print(result.stdout, flush=True)
        binary = root / "tests/fixtures/reflection_codecs/app/target/dev/codec_integration"
        if name == "reflection-codecs" and binary.is_file():
            shutil.copy2(binary, output / "codec-integration")
    print(name, "ok" if result.returncode == 0 else "FAILED", flush=True)
    return result.returncode

def git(*arguments, cwd=root):
    return subprocess.check_output(["git", *arguments], cwd=cwd, text=True).splitlines()

# Fail on native bridge/header conflicts before running the SDK suites. Use the
# full compiler suite's disposable layout without invoking any Encore tests.
if run("compiler-native-runtime", ["bash", "scripts/ci-test.sh", str(compiler)], extra_environment={
        "CI_TEST_RUN_ID": "sdk-native-" + uuid.uuid4().hex,
        "CI_TEST_NATIVE_RUNTIME_ONLY": "1",
}):
    (output / "result.json").write_text(json.dumps({"failed": failures, "formatted": []}, indent=2) + "\n")
    raise SystemExit(1)

# A PR checkout points at GitHub's synthetic merge commit. Use its real source
# head so the previous gitlinks describe exactly the last submitted SDK change.
head = os.environ.get("SDK_AUDIT_HEAD", "HEAD")
changed = [root / path for path in git("diff", "--name-only", head + "^", head) if path.endswith(".enq")]
for line in git("ls-tree", head, "packages/"):
    mode, kind, rest = line.split(None, 2)
    if mode != "160000":
        continue
    commit, package = rest.split("\t", 1)
    previous = git("ls-tree", head + "^", package)
    if not previous or not previous[0].startswith("160000 "):
        continue
    old = previous[0].split()[2]
    if old == commit:
        continue
    changed += [root / package / path for path in git("diff", "--name-only", old, commit, cwd=root / package) if path.endswith(".enq")]
formatted = []
for index, path in enumerate(sorted(set(changed))):
    if not path.is_file():
        continue
    before = path.read_bytes()
    run("format-" + str(index), [str(compiler), "format", str(path)])
    if path.read_bytes() != before:
        formatted.append(path.relative_to(root).as_posix())
with tarfile.open(output / "formatted-sources.tar.gz", "w:gz") as archive:
    for path in formatted:
        archive.add(root / path, arcname=path)
(output / "formatted-files.json").write_text(json.dumps(formatted, indent=2) + "\n")
if formatted:
    failures.append("source formatting")
    print("Formatter changes:", formatted, flush=True)
run("profile-native", ["python3", "scripts/test-profile-runtime.py"])
run("hash-capacity", ["python3", "scripts/test-hash-capacity.py", "--compiler", str(compiler)])
for package in ("json", "toml", "argparse", "binary", "log", "rich", "profile"):
    run("package-" + package, [str(compiler), "test", "--jobs", "2", "--report", "target/test-report.json"], root / "packages" / package)
run("core-hash", [str(compiler), "test", "--jobs", "2", "--filter", "hash_collections"], root / "packages/core")
run("optional-adapters", ["python3", "scripts/test-sdk-adapters.py", str(compiler)])
run("reflection-codecs", ["python3", "tests/fixtures/reflection_codecs/check.py", str(compiler)])
run("compiler-check", [str(compiler), "check"])
(output / "result.json").write_text(json.dumps({"failed": failures, "formatted": formatted}, indent=2) + "\n")
raise SystemExit(bool(failures))
