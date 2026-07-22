#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-self-update.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
executor=${ENCORE_TEST_EXECUTOR:-}
temporary=$(mktemp -d "${TMPDIR:-/tmp}/encore-self-update.XXXXXX")
server_pid=
cleanup() {
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

run_compiler() {
    if [ -n "$executor" ]; then
        "$executor" "$compiler" "$@"
    else
        "$compiler" "$@"
    fi
}

run_installed() {
    if [ -n "$executor" ]; then
        "$executor" "$installed" "$@"
    else
        "$installed" "$@"
    fi
}

run_installed_logged() {
    output=$1
    shift
    set +e
    run_installed "$@" > "$output" 2>&1
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        echo "command failed with status $status: encore $*" >&2
        tr -d '\r' < "$output" >&2
        return "$status"
    fi
}

native_path() {
    source_path=$1
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$source_path"
    elif command -v winepath >/dev/null 2>&1; then
        winepath -w "$source_path"
    elif [ -n "$executor" ]; then
        printf 'Z:%s\n' "$source_path"
    else
        echo "Windows self-update test requires cygpath or winepath" >&2
        return 1
    fi
}

version=$(run_compiler --version | tr -d '\r' | awk '{print $2}')
case "$version" in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "compiler reported an invalid version: $version" >&2; exit 1 ;;
esac

case "${ENCORE_TEST_OS:-$(uname -s)}" in
    Linux) os=linux ;;
    Darwin) os=macos ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) os=windows ;;
    *) echo "unsupported test operating system" >&2; exit 1 ;;
esac
case "${ENCORE_TEST_ARCH:-$(uname -m)}" in
    x86_64|amd64) arch=x86_64 ;;
    arm64|aarch64) arch=aarch64 ;;
    *) echo "unsupported test architecture" >&2; exit 1 ;;
esac
case "$os" in
    linux) triple="${arch}-unknown-linux-gnu"; executable=encore; format=tar.gz ;;
    macos) triple="${arch}-apple-darwin"; executable=encore; format=tar.gz ;;
    windows) triple="${arch}-pc-windows-msvc"; executable=encore.exe; format=zip ;;
esac

install_root="$temporary/install"
mirror="$temporary/mirror"
native_install_root="$install_root"
native_mirror="$mirror"
if [ "$os" = windows ]; then
    native_install_root=$(native_path "$install_root")
    native_mirror=$(native_path "$mirror")
fi
package_name="encore-${version}-${triple}"
package_root="$temporary/package/$package_name"
mkdir -p "$install_root/bin" "$install_root/lib" "$install_root/share" \
    "$mirror/channels" "$mirror/versions" "$package_root/bin" \
    "$package_root/lib/encore" "$package_root/share"
cp "$compiler" "$install_root/bin/$executable"
cp "$compiler" "$package_root/bin/$executable"
chmod +x "$install_root/bin/$executable" "$package_root/bin/$executable" 2>/dev/null || true
printf '%s\n' "$version" > "$install_root/VERSION"
printf '%s\n' "$version" > "$package_root/VERSION"
printf 'old\n' > "$install_root/share/update-marker"
printf 'new\n' > "$package_root/share/update-marker"
printf 'complete distribution\n' > "$package_root/lib/encore/update-marker"

archive="$mirror/encore-${triple}.$format"
if [ "$format" = zip ]; then
    (cd "$temporary/package" && COPYFILE_DISABLE=1 tar -a -cf "$archive" "$package_name")
else
    (cd "$temporary/package" && COPYFILE_DISABLE=1 tar -czf "$archive" "$package_name")
fi
native_archive="$archive"
if [ "$os" = windows ]; then
    native_archive=$(native_path "$archive")
fi
if command -v sha256sum >/dev/null 2>&1; then
    checksum=$(sha256sum "$archive" | awk '{print $1}')
else
    checksum=$(shasum -a 256 "$archive" | awk '{print $1}')
fi

archive_url="file://$native_archive"
write_manifest() {
    destination=$1
    digest=$2
    channel=$3
    cat > "$destination" <<EOF
{"schema":1,"channel":"$channel","version":"$version","tag":"v$version","commit":"test-commit","assets":[{"triple":"$triple","url":"$archive_url","sha256":"$digest","format":"$format"}]}
EOF
}
write_manifest "$mirror/channels/stable.json" "$checksum" stable
write_manifest "$mirror/channels/beta.json" "$checksum" beta
write_manifest "$mirror/channels/nightly.json" "$checksum" nightly
write_manifest "$mirror/versions/$version.json" "$checksum" stable

installed="$install_root/bin/$executable"
base="file://$native_mirror"

wait_for_transaction() {
    attempt=0
    while [ "$attempt" -lt 200 ] && { [ -d "$temporary/.encore-update" ] || [ ! -x "$installed" ]; }; do
        sleep 0.1
        attempt=$((attempt + 1))
    done
    test ! -d "$temporary/.encore-update"
    test -x "$installed"
}

assert_contains() {
    expected=$1
    source=$2
    if ! tr -d '\r' < "$source" | grep -Fq "$expected"; then
        echo "expected '$expected' in $source" >&2
        tr -d '\r' < "$source" >&2
        return 1
    fi
}

assert_line() {
    expected=$1
    source=$2
    if ! tr -d '\r' < "$source" | grep -Fqx "$expected"; then
        echo "expected line '$expected' in $source" >&2
        tr -d '\r' < "$source" >&2
        return 1
    fi
}

assert_installed_version() {
    actual=$(run_installed --version | tr -d '\r')
    if [ "$actual" != "encore $version" ]; then
        echo "installed compiler reported '$actual', expected 'encore $version'" >&2
        return 1
    fi
}

ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/channel-default.log" self channel
assert_line stable "$temporary/channel-default.log"
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/channel-beta.log" self channel beta
assert_contains 'Switched Encore update channel to beta' "$temporary/channel-beta.log"
assert_line 'channel = "beta"' "$install_root/settings.toml"
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/channel-stable.log" self channel stable
assert_line 'channel = "stable"' "$install_root/settings.toml"

ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/check.log" self update --check
assert_contains "Encore $version is up to date on stable" "$temporary/check.log"
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/check-beta.log" self update --channel beta --check
assert_contains "Encore $version is up to date on beta" "$temporary/check-beta.log"
assert_line 'channel = "stable"' "$install_root/settings.toml"
test "$(cat "$install_root/share/update-marker")" = old

ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/update.log" self update --force
attempt=0
while [ "$attempt" -lt 100 ] && [ "$(cat "$install_root/share/update-marker" 2>/dev/null || true)" != new ]; do
    sleep 0.1
    attempt=$((attempt + 1))
done
wait_for_transaction
test "$(cat "$install_root/share/update-marker")" = new
test "$(cat "$install_root/lib/encore/update-marker")" = "complete distribution"
assert_line 'channel = "stable"' "$install_root/settings.toml"
assert_installed_version

# Exercise the updater itself over verified HTTPS rather than relying only on
# the lower-level HTTP client integration test.
openssl_bin=$(command -v openssl 2>/dev/null || true)
if [ -z "$openssl_bin" ]; then
    for candidate in "/c/Program Files/OpenSSL/bin/openssl.exe" "/c/Program Files/OpenSSL-Win64/bin/openssl.exe"; do
        if [ -x "$candidate" ]; then openssl_bin=$candidate; break; fi
    done
fi
test -n "$openssl_bin"
mkdir -p "$temporary/tls"
cat > "$temporary/tls/extensions.cnf" <<'EOF'
subjectAltName=DNS:localhost
extendedKeyUsage=serverAuth
EOF
MSYS2_ARG_CONV_EXCL='/CN=' "$openssl_bin" req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=Encore Self Update Test CA" \
    -keyout "$temporary/tls/ca.key" -out "$temporary/tls/ca.pem" >/dev/null 2>&1
MSYS2_ARG_CONV_EXCL='/CN=' "$openssl_bin" req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
    -keyout "$temporary/tls/server.key" -out "$temporary/tls/server.csr" >/dev/null 2>&1
"$openssl_bin" x509 -req -in "$temporary/tls/server.csr" -CA "$temporary/tls/ca.pem" \
    -CAkey "$temporary/tls/ca.key" -CAcreateserial -days 1 -extfile "$temporary/tls/extensions.cnf" \
    -out "$temporary/tls/server.pem" >/dev/null 2>&1
port=$((25000 + ($$ % 24000)))
server_log="$temporary/tls/server.log"
server_started=false
for offset in 0 1 2 3 4 5 6 7 8 9; do
    candidate_port=$((port + offset))
    (cd "$mirror" && exec "$openssl_bin" s_server -quiet -WWW -accept "$candidate_port" \
        -cert "$temporary/tls/server.pem" -key "$temporary/tls/server.key" </dev/null >"$server_log" 2>&1) &
    server_pid=$!
    sleep 1
    if kill -0 "$server_pid" 2>/dev/null; then
        port=$candidate_port
        server_started=true
        break
    fi
    wait "$server_pid" 2>/dev/null || true
    server_pid=
done
if [ "$server_started" != true ]; then
    cat "$server_log" >&2
    echo "unable to start the local HTTPS update server" >&2
    exit 1
fi
archive_url="https://localhost:$port/$(basename -- "$archive")"
write_manifest "$mirror/channels/stable.json" "$checksum" stable
native_ca="$temporary/tls/ca.pem"
if [ "$os" = windows ]; then
    native_ca=$(native_path "$native_ca")
fi
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="https://localhost:$port" \
    ENCORE_SELF_UPDATE_CA_FILE="$native_ca" \
    run_installed_logged "$temporary/https-update.log" self update --force
wait_for_transaction
kill "$server_pid" 2>/dev/null || true
wait "$server_pid" 2>/dev/null || true
server_pid=
assert_contains "Updated Encore from $version to $version on stable" "$temporary/https-update.log"
assert_installed_version

# Exact installation uses an immutable version manifest and does not alter the
# persisted release channel.
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed_logged "$temporary/install.log" self install "$version" --force
wait_for_transaction
assert_contains "Installed Encore $version" "$temporary/install.log"
assert_line 'channel = "stable"' "$install_root/settings.toml"

# A corrupt or substituted archive must not modify the working installation.
bad_checksum=$(printf '%064d' 0)
archive_url="file://$native_archive"
write_manifest "$mirror/channels/stable.json" "$bad_checksum" stable
set +e
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed self update --force > "$temporary/bad-checksum.log" 2>&1
bad_code=$?
set -e
test "$bad_code" -ne 0
assert_contains 'Checksum verification failed' "$temporary/bad-checksum.log"
test "$(cat "$install_root/share/update-marker")" = new
assert_installed_version

# Invalid manifests, channels and insecure mirrors fail before installation.
printf '{not json}\n' > "$mirror/channels/stable.json"
set +e
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="$base" run_installed self update --force > "$temporary/invalid-manifest.log" 2>&1
manifest_code=$?
ENCORE_HOME="$native_install_root" run_installed self channel alpha > "$temporary/invalid-channel.log" 2>&1
channel_code=$?
ENCORE_HOME="$native_install_root" run_installed self update --version ../../escape > "$temporary/invalid-version.log" 2>&1
version_code=$?
ENCORE_HOME="$native_install_root" ENCORE_SELF_UPDATE_BASE_URL="http://example.invalid" run_installed self update --force > "$temporary/insecure.log" 2>&1
insecure_code=$?
set -e
test "$manifest_code" -ne 0
test "$channel_code" -eq 2
test "$version_code" -ne 0
test "$insecure_code" -ne 0
assert_contains 'Invalid update manifest' "$temporary/invalid-manifest.log"
assert_contains 'stable, beta, or nightly' "$temporary/invalid-channel.log"
assert_contains 'Invalid Encore version' "$temporary/invalid-version.log"
assert_contains 'must use https:// or file://' "$temporary/insecure.log"

echo "Self-update channel, transaction, checksum, and rollback integration: ok"
