#!/bin/sh
# Verify real mainnet templates and the complete Stratum/share/API lifecycle
# against the live node, using an isolated database and no block submission.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
PYTHON=${PYTHON:-"$ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
exec "$PYTHON" "$ROOT/deploy/native/tools/mainnet_smoke.py" --env-file "$ENV_FILE" "$@"
