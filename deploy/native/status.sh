#!/bin/sh
# Show service state and live health for the native deployment.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a
    . "$ENV_FILE"
    set +a
fi
API_HOST=${BTCS_POOL_API_HOST:-127.0.0.1}
API_PORT=${BTCS_POOL_API_PORT:-8765}
API_URL="http://${API_HOST}:${API_PORT}"

for unit in silver-pool.service silver-pool-web.service; do
    printf '%s=%s\n' "$unit" "$(systemctl --user is-active "$unit" 2>/dev/null || true)"
done

if curl -fsS --max-time 4 "$API_URL/api/health" >/dev/null 2>&1; then
    health=$(curl -fsS --max-time 4 "$API_URL/api/health")
    ready=$(curl -fsS --max-time 4 "$API_URL/api/ready" || true)
    printf 'health=%s\n' "$health"
    printf 'ready=%s\n' "$ready"
else
    echo "health=unreachable ($API_URL/api/health)"
fi

if curl -fsS --max-time 4 "http://${SILVER_POOL_HTTP_BIND:-127.0.0.1}:${SILVER_POOL_HTTP_PORT:-8080}/" >/dev/null 2>&1; then
    echo "website=reachable"
else
    echo "website=unreachable"
fi

if [ -f "${BTCS_POOL_DB:-$ROOT/data/mainnet/pool.sqlite3}" ]; then
    "$ROOT/.venv/bin/python" - "$ROOT" "${BTCS_POOL_DB:-$ROOT/data/mainnet/pool.sqlite3}" <<'PY'
import sqlite3, sys
from pathlib import Path
root = Path(sys.argv[1])
path = Path(sys.argv[2])
if not path.is_absolute():
    path = root / path
connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
try:
    counts = {}
    for table in ("miners", "shares", "blocks", "payouts"):
        try:
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            counts[table] = None
    print(f"database={path} size={path.stat().st_size} counts={counts}")
finally:
    connection.close()
PY
else
    echo "database=missing (${BTCS_POOL_DB:-$ROOT/data/mainnet/pool.sqlite3})"
fi
