#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-https-stack.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
temporary=$(mktemp -d "${TMPDIR:-/tmp}/encore-https.XXXXXX")
server_pid=
openssl_bin=$(command -v openssl 2>/dev/null || true)
if [ -z "$openssl_bin" ]; then
    for candidate in \
        "/c/Program Files/OpenSSL/bin/openssl.exe" \
        "/c/Program Files/OpenSSL-Win64/bin/openssl.exe" \
        "/c/Program Files/OpenSSL-Win32/bin/openssl.exe"
    do
        if [ -x "$candidate" ]; then openssl_bin=$candidate; break; fi
    done
fi
if [ -z "$openssl_bin" ]; then
    echo "OpenSSL command is required for the local HTTPS test server" >&2
    exit 1
fi

cleanup() {
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
        server_pid=
    fi
    rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

cat > "$temporary/extensions.cnf" <<'EOF'
subjectAltName=DNS:localhost
extendedKeyUsage=serverAuth
EOF
printf 'secure\n' > "$temporary/index.html"

MSYS2_ARG_CONV_EXCL='/CN=' "$openssl_bin" req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=Encore Test CA" \
    -keyout "$temporary/ca.key" -out "$temporary/ca.pem" >/dev/null
MSYS2_ARG_CONV_EXCL='/CN=' "$openssl_bin" req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
    -keyout "$temporary/server.key" -out "$temporary/server.csr" >/dev/null
"$openssl_bin" x509 -req -in "$temporary/server.csr" -CA "$temporary/ca.pem" \
    -CAkey "$temporary/ca.key" -CAcreateserial -days 1 \
    -extfile "$temporary/extensions.cnf" -out "$temporary/server.pem" >/dev/null

# Use a high randomized port and fail before testing if the local server cannot
# bind. CI machines are isolated, so a collision is exceedingly unlikely.
port=$((20000 + ($$ % 30000)))
(cd "$temporary" && exec "$openssl_bin" s_server -quiet -WWW -accept "$port" \
    -cert server.pem -key server.key </dev/null >/dev/null 2>&1) &
server_pid=$!
sleep 1
if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "local OpenSSL test server failed to start" >&2
    exit 1
fi

(cd "$repo_root/index/std" && \
    ENCORE_HTTPS_TEST_URL="https://localhost:$port" \
    ENCORE_HTTPS_TEST_MISMATCH_URL="https://127.0.0.1:$port" \
    ENCORE_HTTPS_TEST_CA="$temporary/ca.pem" \
    "$compiler" test --filter https_client.enq)

echo "HTTPS trust-store and hostname integration: ok"
