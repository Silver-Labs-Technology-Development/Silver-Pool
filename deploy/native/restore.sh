#!/bin/sh
# Restore a SQLite backup. The service is stopped first; a safety copy of the
# current database is written before the restore and the target is verified.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
PYTHON=${PYTHON:-"$ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
if [ "$#" -lt 1 ]; then
    echo "usage: $0 <backup.sqlite3> [--yes]" >&2
    exit 2
fi
BACKUP=$1
shift
if [ ! -f "$BACKUP" ]; then
    echo "backup not found: $BACKUP" >&2
    exit 2
fi
systemctl --user stop silver-pool-web.service 2>/dev/null || true
systemctl --user stop silver-pool.service 2>/dev/null || true
"$PYTHON" "$ROOT/deploy/native/tools/restore.py" "$BACKUP" --env-file "$ENV_FILE" --yes "$@"
echo "restore complete; start with: $ROOT/deploy/native/start.sh"
