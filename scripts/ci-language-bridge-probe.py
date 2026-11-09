"""Focused language checks, executed only on GitHub with the built candidate."""
import json
import os
from pathlib import Path
import subprocess
import tarfile

root = Path.cwd()
group = os.environ["LANGUAGE_BRIDGE_GROUP"]
if group not in {"calls", "contracts", "metadata", "generators", "operators", "selfhost", "format", "regressions", "safety", "suite"}:
    raise SystemExit("Unknown verification group: " + group)
output = root / "target/language-bridge-probe" / group
output.mkdir(parents=True, exist_ok=True)
compiler = root / "target/bridge-compiler/encore"
compiler.chmod(0o755)
generated = list((root / "target/bridge-build-input").rglob("generated-sources.tar.gz"))
if len(generated) != 1:
    raise SystemExit("Expected exactly one generated-codec artifact")
with tarfile.open(generated[0]) as stream:
    stream.extractall(root, filter="data")
environment = dict(os.environ, ENCORE_CORE_DIR=str(root / "packages/core"),
                   ENCORE_INDEX_URL="http://127.0.0.1:9/index")
failures = []


def run(label, command, cwd=root, timeout=1800, extra=None):
    try:
        result = subprocess.run(command, cwd=cwd, env=environment | (extra or {}),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        code, text = result.returncode, result.stdout
    except subprocess.TimeoutExpired as error:
        code, text = 124, str(error) + "\n" + str(error.stdout or "")
    (output / (label + ".log")).write_text(text)
    print(label, "passed" if code == 0 else "FAILED", flush=True)
    if code:
        failures.append(label)
        print(text, flush=True)
    return code


if group == "calls":
    for label in ["default_and_named_arguments", "negative_default_", "negative_named_",
                  "negative_positional_after_named", "negative_trait_impl_default", "from_into",
                  "negative_from_narrowing", "negative_into_"]:
        run(label, [str(compiler), "test", "--jobs", "2", "--filter", ":tests/" + label])
if group == "suite":
    run("compiler-suite", ["bash", "scripts/ci-test.sh", str(compiler), "--jobs", "2"], timeout=3000,
        extra={"CI_TEST_RUN_ID": "operator-sdk-suite"})
if group == "contracts":
    run("metadata-codecs", [str(compiler), "test", "--jobs", "2", "--filter", "metadata_codec"])
    run("semantic-interning", [str(compiler), "test", "--jobs", "2", "--filter", ":tests/semantic_index_typed_interning.enq"])
if group == "safety":
    run("safety_plan_dependencies", [str(compiler), "test", "--jobs", "2", "--filter", ":tests/safety_plan_dependencies"])
if group == "regressions":
    for label in ["semantic_shared_views", "safety_plan_dependencies", "poll_payload_binding",
                  "negative_method_missing_argument", "negative_call_argument_mismatch"]:
        run(label, [str(compiler), "test", "--jobs", "2", "--filter", ":tests/" + label])
    run("standalone-arity", ["bash", "scripts/ci-test.sh", str(compiler), "--jobs", "2", "--filter",
                              "open_issue_191_unmarked_standalone_rejects_missing_argument"],
        extra={"CI_TEST_RUN_ID": "language-bridge-arity"})
if group == "metadata":
    run("package-defaults", ["bash", "scripts/ci-test.sh", str(compiler), "--jobs", "2", "--filter", "integration_language_call_metadata"],
        extra={"CI_TEST_RUN_ID": "language-bridge-metadata"})
if group == "generators":
    for label in [":tests/generator", ":tests/negative_generator", ":tests/negative_async_generator"]:
        run(label.replace(":", "").replace("/", "-"), [str(compiler), "test", "--jobs", "2", "--filter", label])
if group == "operators":
    run("next-sdk", ["python3", "scripts/test-operator-contracts.py", "--compiler", str(compiler)])
if group == "selfhost":
    if not run("selfhost-stage2", [str(compiler), "build", "--profile", "extreme", "--jobs", "2"], timeout=2400,
               extra={"ENCORE_BUILD_CACHE": str(root / "target/operator-stage2-cache")}):
        stage2 = root / "target/operator-stage2"
        stage2.mkdir(exist_ok=True)
        (root / "target/extreme/encore").rename(stage2 / "encore")
        if not run("selfhost-stage3", [str(stage2 / "encore"), "build", "--profile", "extreme", "--jobs", "2"], timeout=2400,
                   extra={"ENCORE_BUILD_CACHE": str(root / "target/operator-stage3-cache")}):
            run("convergence", ["cmp", str(stage2 / "encore"), str(root / "target/extreme/encore")])
if group == "format":
    changed = subprocess.check_output(["git", "diff", "--name-only", "origin/trunk...HEAD"], text=True).splitlines()
    changed += ["packages/core/src/lib.enq", "packages/core/src/convert/mod.enq",
                "packages/std/src/lib.enq", "packages/std/src/convert/mod.enq",
                "packages/core/src/ops/mod.enq", "packages/std/src/path/mod.enq"]
    formatted = []
    for index, relative in enumerate(sorted(set(changed))):
        path = root / relative
        if path.is_file() and path.suffix == ".enq":
            previous = path.read_bytes()
            run("format-" + str(index), [str(compiler), "format", str(path)])
            if path.read_bytes() != previous:
                formatted.append(relative)
    with tarfile.open(output / "formatted-sources.tar.gz", "w:gz") as stream:
        for relative in formatted:
            stream.add(root / relative, arcname=relative)
    (output / "formatted.json").write_text(json.dumps(formatted, indent=2))
    for generator in ["generate-frontend-artifact-codec.py", "generate-translation-environment-codec.py",
                      "generate-source-artifact-codec.py"]:
        run(generator, ["python3", "scripts/" + generator, "--check"])
(output / "result.json").write_text(json.dumps({"group": group, "failed": failures}, indent=2))
raise SystemExit(bool(failures))
