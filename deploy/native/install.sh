#!/bin/sh
# Install the native Silver Pool runtime into this repository.
#
# This script creates .venv, installs pinned Python runtime dependencies,
# builds the static site, creates runtime directories and optionally installs
# systemd user units. It never edits .env.native, starts a node, or changes
# firewall/DNS settings.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}
NODE=${NODE:-$(command -v node || true)}
if [ -n "$NODE" ]; then
    NODE=$(readlink -f "$NODE" 2>/dev/null || printf '%s' "$NODE")
fi
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}
INSTALL_UNITS=0
BUILD=1
PREFLIGHT=1
START=0

usage() {
    cat <<EOF
Usage: $0 [--install-units] [--start] [--no-build] [--no-preflight]

  --install-units   render and enable systemd user units
  --start           start the services after a successful install
  --no-build        skip npm ci / npm run build
  --no-preflight    skip the live-node preflight
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-units) INSTALL_UNITS=1 ;;
        --start) START=1 ;;
        --no-build) BUILD=0 ;;
        --no-preflight) PREFLIGHT=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [ ! -f "$ENV_FILE" ]; then
    echo "missing $ENV_FILE" >&2
    echo "  cp $ROOT/.env.native.example $ENV_FILE" >&2
    echo "  chmod 600 $ENV_FILE" >&2
    echo "  \$EDITOR $ENV_FILE   # set RPC credentials and a mainnet pool address" >&2
    exit 2
fi
if [ "$(stat -c '%a' "$ENV_FILE")" != "600" ]; then
    echo "$ENV_FILE must have mode 600 (currently $(stat -c '%a' "$ENV_FILE"))" >&2
    echo "  chmod 600 $ENV_FILE" >&2
    exit 2
fi
if [ -z "$NODE" ] || [ ! -x "$NODE" ]; then
    echo "node is required (Node.js 22+); set NODE=/path/to/node" >&2
    exit 2
fi

echo "repo=$ROOT"
echo "python=$PYTHON"
echo "node=$NODE"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "creating .venv"
    "$PYTHON" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements.lock"

if [ "$BUILD" -eq 1 ]; then
    echo "building static site"
    (cd "$ROOT/site" && npm ci --no-audit --no-fund >/dev/null && npm run build)
fi

mkdir -p "$ROOT/data/mainnet" "$ROOT/logs" "$ROOT/run" "$ROOT/backups"
chmod 700 "$ROOT/data" "$ROOT/data/mainnet" "$ROOT/logs" "$ROOT/run" "$ROOT/backups"

if [ "$INSTALL_UNITS" -eq 1 ]; then
    echo "installing systemd user units"
    "$ROOT/.venv/bin/python" "$ROOT/deploy/native/tools/render_units.py" \
        --repo "$ROOT" --venv "$ROOT/.venv" --node "$NODE"
    systemctl --user enable silver-pool.service silver-pool-web.service
fi

if [ "$PREFLIGHT" -eq 1 ]; then
    echo "running preflight"
    "$ROOT/.venv/bin/python" "$ROOT/deploy/native/tools/preflight.py" --env-file "$ENV_FILE"
fi

if [ "$START" -eq 1 ]; then
    "$ROOT/deploy/native/start.sh"
fi

cat <<EOF

Install complete.
  preflight:  $ROOT/deploy/native/preflight.sh
  verify:     $ROOT/deploy/native/verify-mainnet.sh
  start:      $ROOT/deploy/native/start.sh
  status:     $ROOT/deploy/native/status.sh
  backup:     $ROOT/deploy/native/backup.sh
EOF
