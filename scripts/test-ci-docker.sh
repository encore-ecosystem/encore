#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=${ENCORE_CI_DOCKER_IMAGE:-encore-ci-local:latest}
ubuntu_mirror=${ENCORE_CI_UBUNTU_MIRROR:-http://archive.ubuntu.com/ubuntu}
temporary=$(mktemp -d "${TMPDIR:-/tmp}/encore-ci-docker.XXXXXX")

cleanup() {
    rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

if "$repo_root/install.sh" --install-dir "$temporary/encore" --update; then
    seed="$temporary/encore/bin/encore"
else
    seed="$temporary/encore-stage0"
    "$repo_root/scripts/verify-stage0.sh"
    gzip -dc "$repo_root/bootstrap/encore-stage0-linux-x86_64.gz" > "$seed"
    chmod +x "$seed"
    echo "No installable native release; using verified bootstrap stage0" >&2
fi
if [ ! -x "$seed" ]; then
    echo "no executable compiler seed is available" >&2
    exit 1
fi
mkdir -p "$temporary/seed"
cp "$seed" "$temporary/seed/encore"

docker build \
    --build-arg "UBUNTU_MIRROR=$ubuntu_mirror" \
    --build-context "compiler_seed=$temporary/seed" \
    --network host \
    --file "$repo_root/scripts/docker-ci.Dockerfile" \
    --tag "$image" \
    "$repo_root"

docker run --rm --network host "$image"
