#!/usr/bin/env bash
set -euo pipefail

required=false
case "${1:-}" in
  '') ;;
  --required) required=true ;;
  *) echo 'usage: select-ci-candidate.sh [--required]' >&2; exit 2 ;;
esac
repository=${GITHUB_REPOSITORY:?}
commit=${GITHUB_SHA:?}
tree=$(git rev-parse "$commit^{tree}")
pulls=$(gh api "repos/$repository/commits/$commit/pulls")
artifacts_required='[
  "release-candidate-x86_64-unknown-linux-gnu",
  "release-candidate-aarch64-unknown-linux-gnu",
  "release-candidate-aarch64-apple-darwin",
  "release-candidate-x86_64-pc-windows-msvc",
  "release-candidate-x86_64-w64-windows-gnu",
  "release-candidate-aarch64-w64-windows-gnu",
  "release-candidate-target-kit-aarch64-unknown-linux-gnu",
  "release-candidate-target-kit-x86_64-w64-windows-gnu",
  "release-candidate-target-kit-aarch64-w64-windows-gnu"
]'
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
selected_run=
source_commit=
for page in 1 2 3 4 5; do
  runs=$(gh api "repos/$repository/actions/workflows/ci.yml/runs?status=success&per_page=100&page=$page")
  eligible=$(jq -r --arg repo "$repository" --arg commit "$commit" --argjson pulls "$pulls" '
    .workflow_runs[] | select(.conclusion == "success" and .head_repository.full_name == $repo) |
    select(
      ((.event == "push" or .event == "workflow_dispatch") and .head_branch == "trunk" and .head_sha == $commit)
      or (.event == "pull_request" and (.head_sha as $head |
        any($pulls[]; .merged_at != null and .base.ref == "trunk" and
          .head.repo.full_name == $repo and .head.sha == $head)))
    ) | [.id, .event] | @tsv
  ' <<<"$runs")
  while IFS=$'\t' read -r run event; do
    test -n "$run" || continue
    artifacts=$(gh api "repos/$repository/actions/runs/$run/artifacts?per_page=100")
    if ! jq -e --argjson required "$artifacts_required" '
      [.artifacts[] | select(.expired == false) | .name] as $names |
      ($required - $names | length) == 0
    ' <<<"$artifacts" >/dev/null; then continue; fi
    if [[ "$event" != pull_request ]]; then
      selected_run=$run
      source_commit=$commit
      break
    fi
    if ! jq -e 'any(.artifacts[]; .name == "build-identity" and .expired == false)' \
      <<<"$artifacts" >/dev/null; then continue; fi
    mkdir "$scratch/$run"
    gh run download "$run" --repo "$repository" --name build-identity --dir "$scratch/$run"
    identity="$scratch/$run/build-identity.json"
    source=$(jq -er '.commit | select(type == "string" and test("^[0-9a-f]{40}$"))' "$identity")
    actual_tree=$(gh api "repos/$repository/git/commits/$source" --jq '.tree.sha')
    if [[ "$(jq -r '.tree' "$identity")" == "$actual_tree" && "$actual_tree" == "$tree" ]]; then
      selected_run=$run
      source_commit=$source
      break
    fi
  done <<<"$eligible"
  [[ -z "$selected_run" ]] || break
  [[ "$(jq '.workflow_runs | length' <<<"$runs")" == 100 ]] || break
done
reused=false
[[ -z "$selected_run" ]] || reused=true
printf 'run_id=%s\nsource_commit=%s\nreused=%s\n' \
  "$selected_run" "$source_commit" "$reused" >> "${GITHUB_OUTPUT:?}"
if [[ "$required" == true && -z "$selected_run" ]]; then
  echo 'No complete green candidate exists for the release source tree' >&2
  exit 1
fi
if [[ "$reused" == true ]]; then
  echo "Reuse verified candidate $selected_run ($source_commit)"
else
  echo 'Full native build required'
fi
