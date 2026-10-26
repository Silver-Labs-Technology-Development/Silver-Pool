#!/bin/sh
set -eu

: "${BTCS_NETWORK:=main}"
export BTCS_NETWORK
: "${BTCS_POOL_DB:=/data/pool.sqlite3}"
export BTCS_POOL_DB
: "${BTCS_POOL_API_HOST:=0.0.0.0}"
export BTCS_POOL_API_HOST
: "${BTCS_STRATUM_HOST:=0.0.0.0}"
export BTCS_STRATUM_HOST

if [ "${BTCS_AUTO_PAYOUTS:-false}" != "false" ]; then
    printf '%s\n' \
        "BTCS_AUTO_PAYOUTS must remain false: this release does not implement" \
        "reward signing, confirmation handling, recovery and payment tests." >&2
    exit 2
fi

mkdir -p "$(dirname "$BTCS_POOL_DB")"
if [ ! -w "$(dirname "$BTCS_POOL_DB")" ]; then
    printf 'database directory %s is not writable by uid %s\n' \
        "$(dirname "$BTCS_POOL_DB")" "$(id -u)" >&2
    exit 2
fi

if [ -z "${BTCS_POOL_ADDRESS:-}" ] && [ -z "${BTCS_POOL_SCRIPT_PUBKEY:-}" ] \
    && [ -z "${BTCS_RPC_WALLET:-}" ]; then
    printf '%s\n' \
        "set BTCS_POOL_ADDRESS, BTCS_POOL_SCRIPT_PUBKEY, or BTCS_RPC_WALLET so" \
        "the pool can resolve a coinbase output." >&2
    exit 2
fi

printf 'silver_pool_starting network=%s api=%s:%s stratum=%s:%s db=%s\n' \
    "$BTCS_NETWORK" "${BTCS_POOL_API_HOST}" "${BTCS_POOL_API_PORT:-8765}" \
    "${BTCS_STRATUM_HOST}" "${BTCS_STRATUM_PORT:-3333}" "$BTCS_POOL_DB"

python /app/wait-for-node.py

exec "$@"
