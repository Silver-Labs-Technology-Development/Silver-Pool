"""Integrated Silver Pool process: RPC, Stratum, accounting and HTTP API."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiohttp import web

from .accounting import Accounting
from .api import create_app
from .config import PoolConfig, load_config
from .db import Database
from .node import NodeMonitor
from .rpc import BTCSRpc, RPCError
from .stratum import StratumServer

log = logging.getLogger(__name__)

MATURITY_CHECK_SECONDS = 120.0


def resolve_pool_script(rpc: BTCSRpc, cfg: PoolConfig) -> None:
    """Resolve the coinbase output script without assuming a hot wallet if a
    script or address is supplied by the operator."""
    if cfg.pool_script_pubkey:
        try:
            script = bytes.fromhex(cfg.pool_script_pubkey)
        except ValueError as exc:
            raise ValueError("BTCS_POOL_SCRIPT_PUBKEY must be hex") from exc
        if not 2 <= len(script) <= 10_000:
            raise ValueError("BTCS_POOL_SCRIPT_PUBKEY has an invalid length")
        log.info("pool_script_configured bytes=%s", len(script))
        return

    if cfg.pool_address:
        last_error: Exception | None = None
        for method in ("validateaddress", "getaddressinfo"):
            try:
                if method == "validateaddress":
                    info = rpc.validateaddress(cfg.pool_address)
                else:
                    info = rpc.getaddressinfo(cfg.pool_address)
                script = info.get("scriptPubKey")
                if isinstance(script, str) and script:
                    cfg.pool_script_pubkey = script
                    log.info("pool_address_resolved address=%s", cfg.pool_address)
                    return
            except RPCError as exc:
                last_error = exc
        raise ValueError(
            f"Could not resolve BTCS_POOL_ADDRESS {cfg.pool_address!r}: {last_error}"
        )

    if not cfg.rpc_wallet:
        raise ValueError(
            "Set BTCS_POOL_ADDRESS or BTCS_POOL_SCRIPT_PUBKEY, or configure "
            "BTCS_RPC_WALLET so the pool can create a coinbase address"
        )

    rpc.ensure_wallet()
    address = rpc.getnewaddress("pool")
    info = rpc.getaddressinfo(address)
    script = info.get("scriptPubKey")
    if not isinstance(script, str) or not script:
        raise RPCError("getaddressinfo", "wallet returned no scriptPubKey")
    cfg.pool_address = address
    cfg.pool_script_pubkey = script
    log.info("pool_address_created address=%s", address)


async def maturity_loop(
    cfg: PoolConfig,
    accounting: Accounting,
    rpc: BTCSRpc,
    node_monitor: NodeMonitor,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            snapshot = await node_monitor.snapshot()
            if snapshot.connected and not snapshot.initial_block_download:
                def canonical(height: int) -> str | None:
                    try:
                        return rpc.getblockhash(height)
                    except RPCError:
                        return None

                result = await asyncio.to_thread(
                    accounting.reconcile_blocks,
                    snapshot.blocks,
                    cfg.maturity_confirmations,
                    canonical,
                )
                if result["matured"] or result["orphaned"]:
                    log.info(
                        "maturity_reconciled checked=%s matured=%s orphaned=%s",
                        result["checked"],
                        result["matured"],
                        result["orphaned"],
                    )
        except Exception:  # noqa: BLE001 - a monitor failure must not stop mining
            log.exception("maturity_loop_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=MATURITY_CHECK_SECONDS)
        except asyncio.TimeoutError:
            continue


async def main_async(cfg: PoolConfig) -> None:
    rpc = BTCSRpc(
        cfg.rpc_url,
        cfg.rpc_user,
        cfg.rpc_password,
        cfg.rpc_wallet,
        timeout=cfg.rpc_timeout_seconds,
    )
    resolve_pool_script(rpc, cfg)

    db = Database(cfg.db_path)
    accounting = Accounting(db)
    node_monitor = NodeMonitor(rpc, cfg.network)

    def on_block(height: int, block_hash: str) -> None:
        log.info("block_found height=%s hash=%s", height, block_hash)

    stratum = StratumServer(
        cfg, rpc, accounting, node_monitor=node_monitor, on_block=on_block
    )
    app = create_app(db, cfg, node_monitor, stratum.status)

    runner = web.AppRunner(app, access_log=log)
    await runner.setup()
    api_site = web.TCPSite(runner, cfg.api_host, cfg.api_port)
    await api_site.start()
    log.info("api_listening host=%s port=%s", cfg.api_host, cfg.api_port)

    tcp_server = await asyncio.start_server(
        stratum.handle_client,
        cfg.stratum_host,
        cfg.stratum_port,
        limit=max(1024, cfg.max_line_bytes + 1),
    )
    log.info(
        "stratum_listening host=%s port=%s network=%s",
        cfg.stratum_host,
        cfg.stratum_port,
        cfg.network,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    template_task = asyncio.create_task(stratum.poll_templates())
    maturity_task = asyncio.create_task(
        maturity_loop(cfg, accounting, rpc, node_monitor, stop)
    )

    await stop.wait()
    log.info("shutdown_requested")

    template_task.cancel()
    maturity_task.cancel()
    for task in (template_task, maturity_task):
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    tcp_server.close()
    await tcp_server.wait_closed()
    await stratum.shutdown()
    await runner.cleanup()
    log.info("shutdown_complete")


def main() -> None:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(main_async(cfg))
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001 - startup errors must be explicit
        log.error("startup_failed error=%s", exc)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
