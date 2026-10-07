#!/usr/bin/env python3
"""Find a complete green build of the exact tree, without rewriting provenance."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


TARGETS = (
    "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin", "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc", "x86_64-w64-windows-gnu",
    "aarch64-w64-windows-gnu",
)
REQUIRED = {f"release-candidate-{target}" for target in TARGETS} | {
    f"release-candidate-target-kit-{target}" for target in (
        "aarch64-unknown-linux-gnu", "x86_64-w64-windows-gnu",
        "aarch64-w64-windows-gnu",
    )
}


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def eligible(run, pulls, repository, commit):
    if run["conclusion"] != "success" or run["head_repository"]["full_name"] != repository:
        return False
    if run["event"] in ("push", "workflow_dispatch"):
        return run["head_branch"] == "trunk" and run["head_sha"] == commit
    return run["event"] == "pull_request" and any(
        pr["merged_at"] and pr["base"]["ref"] == "trunk"
        and pr["head"]["repo"] and pr["head"]["repo"]["full_name"] == repository
        and pr["head"]["sha"] == run["head_sha"] for pr in pulls
    )


def select(repository, commit):
    tree = subprocess.check_output(["git", "rev-parse", f"{commit}^{{tree}}"], text=True).strip()
    pulls = api(f"repos/{repository}/commits/{commit}/pulls")
    # Search recent successful runs, never use the current (unfinished) run.
    for page in range(1, 6):
        runs = api(f"repos/{repository}/actions/workflows/ci.yml/runs?status=success&per_page=100&page={page}")["workflow_runs"]
        for run in runs:
            if not eligible(run, pulls, repository, commit):
                continue
            artifacts = api(f"repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
            names = {item["name"] for item in artifacts if not item["expired"]}
            if not REQUIRED <= names:
                continue
            if run["event"] != "pull_request":
                return str(run["id"]), commit
            if "build-identity" not in names:
                continue  # Older PR builds cannot prove their synthetic merge tree.
            with tempfile.TemporaryDirectory(prefix="encore-candidate-") as directory:
                subprocess.run(["gh", "run", "download", str(run["id"]), "--repo", repository,
                                "--name", "build-identity", "--dir", directory], check=True)
                identity = json.loads((Path(directory) / "build-identity.json").read_text())
            source = identity["commit"]
            actual_tree = api(f"repos/{repository}/git/commits/{source}")["tree"]["sha"]
            if identity["tree"] == actual_tree == tree:
                return str(run["id"]), source
        if len(runs) < 100:
            break
    return "", ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    run, commit = select(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_id={run}\nsource_commit={commit}\nreused={'true' if run else 'false'}\n")
    if args.required and not run:
        raise SystemExit("No complete green candidate exists for the release source tree")
    print(f"Reuse verified candidate {run} ({commit})" if run else "Full native build required")


if __name__ == "__main__":
    main()
