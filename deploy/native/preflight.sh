#!/bin/sh
# Validate the environment, node, template, coinbase, ports and payout lock.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
PYTHON=${PYTHON:-"$ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
exec "$PYTHON" "$ROOT/deploy/native/tools/preflight.py" --env-file "$ENV_FILE" "$@"
