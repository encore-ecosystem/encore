#!/usr/bin/env bash
# Retained for target-kit consumers of the previous script name.
set -euo pipefail
exec bash "$(dirname "$0")/build-static-openssl.sh" "$@"
