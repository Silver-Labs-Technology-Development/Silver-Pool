#!/bin/sh
set -eu

: "${BTCS_NETWORK:=main}"
case "$BTCS_NETWORK" in
    main) network_flags="" ;;
    test) network_flags="-testnet" ;;
    testnet4) network_flags="-testnet4" ;;
    signet) network_flags="-signet" ;;
    regtest) network_flags="-regtest" ;;
    *)
        printf 'invalid BTCS_NETWORK %s\n' "$BTCS_NETWORK" >&2
        exit 2
        ;;
esac

# shellcheck disable=SC2086
exec bitcoinsilver-cli \
    -datadir="${BTCS_NODE_DATADIR:-/data}" \
    $network_flags \
    getblockchaininfo >/dev/null
