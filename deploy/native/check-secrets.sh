#!/bin/sh
# Scan tracked files and optional release archives for secrets.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
exec python3 "$ROOT/deploy/native/tools/secret_scan.py" "$@"
