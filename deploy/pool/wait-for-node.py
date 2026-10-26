#!/usr/bin/env python3
"""Wait until the configured BTCS Core node is reachable and on the expected chain.

This runs inside the pool container before the pool process starts. It never
prints RPC credentials and exits non-zero on a chain mismatch so a mainnet pool
cannot accidentally start against a regtest node (or the reverse).
"""
from __future__ import annotations

import os
import sys
import time

from btcs_pool.rpc import BTCSRpc, RPCError

EXPECTED_CHAIN = {
    "main": "main",
    "test": "test",
    "testnet4": "testnet4",
    "signet": "signet",
    "regtest": "regtest",
}


def main() -> int:
    network = os.environ.get("BTCS_NETWORK", "main").strip().lower()
    expected = EXPECTED_CHAIN.get(network)
    if expected is None:
        print(f"invalid BTCS_NETWORK {network!r}", file=sys.stderr)
        return 2

    rpc_url = os.environ.get("BTCS_RPC_URL", "").rstrip("/")
    if not rpc_url:
        print("BTCS_RPC_URL is required", file=sys.stderr)
        return 2
    rpc_user = os.environ.get("BTCS_RPC_USER", "")
    rpc_password = os.environ.get("BTCS_RPC_PASSWORD", "")
    if not rpc_user or not rpc_password:
        print("BTCS_RPC_USER and BTCS_RPC_PASSWORD are required", file=sys.stderr)
        return 2

    timeout = float(os.environ.get("BTCS_NODE_WAIT_SECONDS", "300"))
    deadline = time.monotonic() + timeout
    rpc = BTCSRpc(
        rpc_url,
        rpc_user,
        rpc_password,
        timeout=min(10.0, max(2.0, timeout)),
    )
    last_error = "no attempt made"
    while time.monotonic() < deadline:
        try:
            info = rpc.getblockchaininfo()
            chain = info.get("chain")
            if chain != expected:
                print(
                    f"refusing to start: BTCS_NETWORK={network!r} expects chain "
                    f"{expected!r}, but the node reports {chain!r}",
                    file=sys.stderr,
                )
                return 3
            print(
                "btcs_node_ready "
                f"chain={chain} blocks={info.get('blocks')} "
                f"headers={info.get('headers')} "
                f"initial_block_download={info.get('initialblockdownload')}",
                flush=True,
            )
            return 0
        except RPCError as exc:
            last_error = str(exc)
            time.sleep(2)
        except Exception as exc:  # noqa: BLE001 - startup diagnostics
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)

    print(
        f"BTCS node was not reachable at {rpc_url} within {timeout:.0f}s: {last_error}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
