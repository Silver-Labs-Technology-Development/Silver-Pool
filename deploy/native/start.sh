#!/bin/sh
# Start the native Silver Pool backend and website.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.native"}

if [ ! -f "$ENV_FILE" ]; then
    echo "missing $ENV_FILE" >&2
    exit 2
fi
load_state=$(systemctl --user show -p LoadState --value silver-pool.service 2>/dev/null || true)
if [ "$load_state" != "loaded" ]; then
    echo "silver-pool.service is not installed; run: $ROOT/deploy/native/install.sh --install-units" >&2
    exit 2
fi

systemctl --user start silver-pool.service

# shellcheck disable=SC1090
set -a
. "$ENV_FILE"
set +a
API_HOST=${BTCS_POOL_API_HOST:-127.0.0.1}
API_PORT=${BTCS_POOL_API_PORT:-8765}
API_URL="http://${API_HOST}:${API_PORT}"

ready=0
attempt=0
while [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    if curl -fsS --max-time 2 "$API_URL/api/ready" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    echo "backend did not become ready; recent logs:" >&2
    journalctl --user -u silver-pool.service -n 40 --no-pager >&2 || true
    exit 1
fi

systemctl --user start silver-pool-web.service

SITE_HOST=${SILVER_POOL_HTTP_BIND:-127.0.0.1}
SITE_PORT=${SILVER_POOL_HTTP_PORT:-8080}
SITE_CHECK_HOST=$SITE_HOST
if [ "$SITE_CHECK_HOST" = "0.0.0.0" ] || [ "$SITE_CHECK_HOST" = "::" ]; then
    SITE_CHECK_HOST=127.0.0.1
fi
site_ready=0
attempt=0
while [ "$attempt" -lt 20 ]; do
    attempt=$((attempt + 1))
    if curl -fsS --max-time 2 "http://${SITE_CHECK_HOST}:${SITE_PORT}/" >/dev/null 2>&1; then
        site_ready=1
        break
    fi
    sleep 1
done
if [ "$site_ready" -ne 1 ]; then
    echo "website did not become reachable; recent logs:" >&2
    journalctl --user -u silver-pool-web.service -n 40 --no-pager >&2 || true
    exit 1
fi

echo "backend:  $API_URL/api/ready"
echo "website:  http://${SILVER_POOL_HTTP_BIND:-127.0.0.1}:${SILVER_POOL_HTTP_PORT:-8080}/"
echo "stratum:  ${BTCS_STRATUM_HOST:-127.0.0.1}:${BTCS_STRATUM_PORT:-3333}"
echo "payouts:  disabled (BTCS_AUTO_PAYOUTS=${BTCS_AUTO_PAYOUTS:-false})"
if [ -n "${BTCS_PUBLIC_STRATUM_HOST:-}" ]; then
    echo "public:   ${BTCS_PUBLIC_STRATUM_HOST}:${BTCS_PUBLIC_STRATUM_PORT:-3333} (external reachability is not verified)"
else
    echo "public:   not configured"
fi
