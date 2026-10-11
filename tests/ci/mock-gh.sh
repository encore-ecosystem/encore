#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  api)
    case "$2" in
      */pulls)
        merged=now
        [[ "$CI_PROBE_CASE" != unmerged ]] || merged=
        jq -n --arg merged "$merged" --arg repo "$GITHUB_REPOSITORY" --arg head "$CI_PROBE_HEAD" \
          '[{merged_at:(if $merged == "" then null else $merged end), base:{ref:"trunk"}, head:{repo:{full_name:$repo}, sha:$head}}]'
        ;;
      */runs\?*)
        event=pull_request
        [[ "$CI_PROBE_CASE" != exact ]] || event=push
        repo=$GITHUB_REPOSITORY
        [[ "$CI_PROBE_CASE" != fork ]] || repo=untrusted/fork
        conclusion=success
        [[ "$CI_PROBE_CASE" != failed ]] || conclusion=failure
        jq -n --arg event "$event" --arg repo "$repo" --arg sha "$CI_PROBE_HEAD" --arg result "$conclusion" \
          '{workflow_runs:[{id:42, event:$event, head_branch:"trunk", head_sha:$sha, conclusion:$result, head_repository:{full_name:$repo}}]}'
        ;;
      */artifacts\?*)
        jq -n --arg mode "$CI_PROBE_CASE" '
          ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "aarch64-apple-darwin",
           "x86_64-pc-windows-msvc", "x86_64-w64-windows-gnu", "aarch64-w64-windows-gnu"] as $targets |
          ([ $targets[] | "release-candidate-" + . ] +
           ["release-candidate-target-kit-aarch64-unknown-linux-gnu",
            "release-candidate-target-kit-x86_64-w64-windows-gnu",
            "release-candidate-target-kit-aarch64-w64-windows-gnu", "build-identity"]) |
          {artifacts: [ .[] | select($mode != "legacy" or . != "build-identity") |
            select($mode != "incomplete" or . != "release-candidate-aarch64-apple-darwin") |
            {name:., expired:($mode == "expired")} ]}'
        ;;
      */git/commits/*)
        # Production asks --jq .tree.sha; return the selected field, like gh.
        printf '%s\n' "$CI_PROBE_TREE"
        ;;
      *) exit 91 ;;
    esac
    ;;
  run)
    test "$2" = download
    test "$3" = 42
    test "$4" = --repo
    test "$6" = --name
    test "$7" = build-identity
    test "$8" = --dir
    jq -n --arg commit "$CI_PROBE_HEAD" --arg tree "$CI_PROBE_TREE" \
      '{commit:$commit, tree:$tree}' > "$9/build-identity.json"
    ;;
  *) exit 92 ;;
esac
