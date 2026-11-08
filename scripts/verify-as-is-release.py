"""Verify the owner's one-time 0.1.15 release exception on GitHub only."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib


REPOSITORY = "encore-ecosystem/encore"
RELEASE_COMMIT = "10f7ecb80b3d0948746aeca74350dc39da31fe61"
FEATURE_COMMIT = "fc27fc054a6d0f14e85753415abe6bf4d1813a23"
BUILD_RUN = 42398340015
VALIDATION_RUN = 42373979388
TARGETS = ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "aarch64-apple-darwin",
           "x86_64-pc-windows-msvc", "x86_64-w64-windows-gnu", "aarch64-w64-windows-gnu"]
REQUIRED_JOBS = [f"Verify {target} / {kind} {target}" for target in TARGETS for kind in ["Converge", "Package"]]
REQUIRED_JOBS += ["Resolve trusted inputs", "kit-windows-gnu-x86 / Target kit x86_64-w64-windows-gnu",
                  "kit-windows-gnu-arm / Target kit aarch64-w64-windows-gnu",
                  "kit-linux-arm / Target kit aarch64-unknown-linux-gnu"]


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPOSITORY}/{path}"], text=True))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


require(os.environ.get("GITHUB_ACTIONS") == "true", "This release verifier runs on GitHub only")
require(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == RELEASE_COMMIT,
        "Unexpected release checkout")
require(os.environ["RELEASE_COMMIT"] == RELEASE_COMMIT and os.environ["RELEASE_TAG"] == "v0.1.15-neumann",
        "This exception applies only to the approved 0.1.15 release")
changes = subprocess.check_output(["git", "diff", "--name-only", FEATURE_COMMIT, RELEASE_COMMIT], text=True).splitlines()
require(set(changes) == {"encore.toml", "docs/sdk-submodules.md"}, "Implementation changed after validation")
before = tomllib.loads(subprocess.check_output(["git", "show", f"{FEATURE_COMMIT}:encore.toml"], text=True))
after = tomllib.loads(Path("encore.toml").read_text())
require(before["project"]["version"] == "0.1.14" and after["project"]["version"] == "0.1.15",
        "Unexpected release version transition")
before["project"]["version"] = after["project"]["version"]
require(before == after, "Manifest changed beyond the release version")

if "--wait" in sys.argv:
    deadline = time.monotonic() + 75 * 60
    previous = None
    while time.monotonic() < deadline:
        pending_run = api(f"actions/runs/{BUILD_RUN}")
        require(pending_run["head_sha"] == RELEASE_COMMIT and pending_run["head_branch"] == "trunk",
                "Refusing to cancel an unexpected build")
        if pending_run["status"] == "completed":
            require(pending_run["conclusion"] == "cancelled", "Unexpected completed build result")
            print("Native build is already cancelled; the next step rechecks every required artifact", flush=True)
            raise SystemExit(0)
        pending_jobs = api(f"actions/runs/{BUILD_RUN}/jobs?per_page=100")["jobs"]
        bad = [job["name"] for job in pending_jobs if job["conclusion"] in ["failure", "timed_out", "action_required"]]
        require(not bad, f"Native build or verification failed: {bad}")
        good = {job["name"] for job in pending_jobs if job["conclusion"] == "success"}
        missing = sorted(set(REQUIRED_JOBS) - good)
        if missing != previous:
            print(f"Required native jobs ready: {len(REQUIRED_JOBS) - len(missing)}/{len(REQUIRED_JOBS)}; remaining: {missing}", flush=True)
            previous = missing
        if not missing:
            subprocess.check_call(["gh", "api", "--method", "POST", f"repos/{REPOSITORY}/actions/runs/{BUILD_RUN}/cancel"])
            while time.monotonic() < deadline:
                if api(f"actions/runs/{BUILD_RUN}")["status"] == "completed":
                    print("Required native artifacts are ready; remaining full suites cancelled at the owner's request", flush=True)
                    raise SystemExit(0)
                time.sleep(10)
            raise SystemExit("Cancellation did not complete before the deadline")
        require(pending_run["status"] != "completed", "Native run ended before required release artifacts were ready")
        time.sleep(30)
    raise SystemExit("Required native artifacts were not ready before the deadline")

run = api(f"actions/runs/{BUILD_RUN}")
require(run["head_sha"] == RELEASE_COMMIT and run["head_branch"] == "trunk" and run["event"] == "push",
        "Release artifacts are not from the intended trunk commit")
require(run["path"] == ".github/workflows/ci.yml" and run["head_repository"]["full_name"] == REPOSITORY,
        "Unexpected build workflow or repository")
require(run["status"] == "completed" and run["conclusion"] == "cancelled",
        "The owner-approved build run must finish cancellation before publication")
jobs = api(f"actions/runs/{BUILD_RUN}/jobs?per_page=100")["jobs"]
require(len(jobs) < 100, "Unexpected job count")
by_name = {job["name"]: job for job in jobs}
for name in REQUIRED_JOBS:
    require(name in by_name and by_name[name]["conclusion"] == "success", f"Required build failed: {name}")
    if "/ Converge " in name:
        runtime = [step for step in by_name[name]["steps"] if step["name"] == "Test native graph and generator lifecycle"]
        require(len(runtime) == 1 and runtime[0]["conclusion"] == "success", f"Native runtime not verified: {name}")
failures = [job["name"] for job in jobs if job["conclusion"] in ["failure", "timed_out", "action_required"]
            and job["name"] != "CI complete"]
require(not failures, f"Unapproved verification failures: {failures}")
artifacts = api(f"actions/runs/{BUILD_RUN}/artifacts?per_page=100")["artifacts"]
names = {item["name"] for item in artifacts if not item["expired"]}
required_artifacts = {f"release-candidate-{target}" for target in TARGETS}
required_artifacts |= {f"release-candidate-target-kit-{target}" for target in
                       ["x86_64-w64-windows-gnu", "aarch64-w64-windows-gnu", "aarch64-unknown-linux-gnu"]}
require(required_artifacts <= names, "Release artifacts are missing or expired")

validation = api(f"actions/runs/{VALIDATION_RUN}")
require(validation["head_sha"] == FEATURE_COMMIT, "Unexpected generator validation candidate")
validated_jobs = api(f"actions/runs/{VALIDATION_RUN}/jobs?per_page=100")["jobs"]
validated = {job["name"]: job for job in validated_jobs}
compiler_targets = [target for target in TARGETS if target != "x86_64-pc-windows-msvc"]
for target in compiler_targets:
    name = f"Verify {target} / Test compiler {target}"
    require(name in validated and validated[name]["conclusion"] == "success", f"Compiler suite not validated: {target}")
for target in TARGETS:
    for kind in ["Converge", "Test libraries and tooling", "Package"]:
        name = f"Verify {target} / {kind} {target}"
        require(name in validated and validated[name]["conclusion"] == "success", f"Source candidate not validated: {name}")

exception = {"schema": 1, "release": "0.1.15-neumann", "release_commit": RELEASE_COMMIT,
             "feature_commit": FEATURE_COMMIT, "build_run_id": BUILD_RUN, "source_validation_run_id": VALIDATION_RUN,
             "full_compiler_tests_complete": False, "full_compiler_targets_passed": compiler_targets,
             "incomplete_target": "x86_64-pc-windows-msvc", "msvc_passing_tests_observed_before_cancellation": 683,
             "msvc_full_suite_expected_tests": 724,
             "approval": "Owner explicitly requested cancelling the remaining MSVC compiler suite, merging as-is and publishing a release on 2026-11-07.",
             "release_rebuild": "All six native bootstrap/convergence and package/installed-SDK checks passed. No implementation changes beyond the validated candidate."}
Path("dist").mkdir(exist_ok=True)
Path("dist/verification-exception.json").write_text(json.dumps(exception, indent=2) + "\n")
with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
    stream.write(f"run_id={BUILD_RUN}\nsource_commit={RELEASE_COMMIT}\n")
print(json.dumps(exception, indent=2))
