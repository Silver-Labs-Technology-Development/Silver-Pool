#!/bin/sh
# Create a consistent SQLite backup while the pool is running.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
PYTHON=${PYTHON:-"$ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
exec "$PYTHON" "$ROOT/deploy/native/tools/backup.py" --env-file "$ENV_FILE" "$@"
