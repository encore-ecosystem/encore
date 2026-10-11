#!/usr/bin/env bash
set -euo pipefail
triple=${1:?target triple required}
release=${2:?release required}
archive=${3:?archive required}
provenance=${4:?provenance required}
root="encore-$release-$triple"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
extension=
case "$triple" in
  *-windows-*) extension=.exe; unzip -Z1 "$archive" > "$scratch/members" ;;
  *) tar -tzf "$archive" > "$scratch/members" ;;
esac
read_member() {
  local member="$root/$1"
  test "$(awk -v member="$member" '$0 == member {n++} END {print n+0}' "$scratch/members")" = 1
  if [[ -n "$extension" ]]; then
    unzip -p "$archive" "$member"
  else
    # Refuse symlinks, directories and special files, not merely missing names.
    test "$(tar -tvzf "$archive" "$member" | cut -c1)" = '-'
    tar -xOzf "$archive" "$member"
  fi
}
read_member VERSION > "$scratch/VERSION"
test "$(tr -d '\r\n' < "$scratch/VERSION")" = "$release"
for binary in encore encore-lsp; do
  read_member "bin/$binary$extension" > "$scratch/binary"
  key=compiler_sha256
  [[ "$binary" != encore-lsp ]] || key=lsp_sha256
  test "$(sha256sum "$scratch/binary" | awk '{print $1}')" = "$(jq -r --arg key "$key" '.[$key]' "$provenance")"
done
