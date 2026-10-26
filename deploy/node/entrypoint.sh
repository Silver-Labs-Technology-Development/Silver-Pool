#!/bin/sh
set -eu

: "${BTCS_NETWORK:=main}"
case "$BTCS_NETWORK" in
    main)
        network_flags=""
        default_rpc_port=10567
        default_p2p_port=10566
        ;;
    test)
        network_flags="-testnet"
        default_rpc_port=18332
        default_p2p_port=18333
        ;;
    testnet4)
        network_flags="-testnet4"
        default_rpc_port=48332
        default_p2p_port=48333
        ;;
    signet)
        network_flags="-signet"
        default_rpc_port=38332
        default_p2p_port=38333
        ;;
    regtest)
        network_flags="-regtest"
        default_rpc_port=18443
        default_p2p_port=18444
        ;;
    *)
        printf 'invalid BTCS_NETWORK %s\n' "$BTCS_NETWORK" >&2
        exit 2
        ;;
esac

: "${BTCS_RPC_USER:?BTCS_RPC_USER is required}"
: "${BTCS_RPC_PASSWORD:?BTCS_RPC_PASSWORD is required}"
: "${BTCS_RPC_PORT:=$default_rpc_port}"
: "${BTCS_P2P_PORT:=$default_p2p_port}"
: "${BTCS_RPC_ALLOW_CIDR:=172.16.0.0/12}"
: "${BTCS_NODE_DATADIR:=/data}"
: "${BTCS_NODE_MAX_CONNECTIONS:=64}"
: "${BTCS_NODE_DBCACHE_MB:=300}"

mkdir -p "$BTCS_NODE_DATADIR"
umask 077
conf="$BTCS_NODE_DATADIR/bitcoin.conf"
cat > "$conf" <<EOF
server=1
daemon=0
printtoconsole=1
listen=1
dnsseed=1
rpcbind=0.0.0.0
rpcallowip=${BTCS_RPC_ALLOW_CIDR}
rpcuser=${BTCS_RPC_USER}
rpcpassword=${BTCS_RPC_PASSWORD}
rpcport=${BTCS_RPC_PORT}
port=${BTCS_P2P_PORT}
maxconnections=${BTCS_NODE_MAX_CONNECTIONS}
dbcache=${BTCS_NODE_DBCACHE_MB}
fallbackfee=0.0002
EOF
chmod 0600 "$conf"

printf 'btcs_node_starting network=%s datadir=%s rpc_port=%s p2p_port=%s\n' \
    "$BTCS_NETWORK" "$BTCS_NODE_DATADIR" "$BTCS_RPC_PORT" "$BTCS_P2P_PORT"

# shellcheck disable=SC2086
exec bitcoinsilverd -datadir="$BTCS_NODE_DATADIR" $network_flags
