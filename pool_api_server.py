"""Run only the Silver Pool HTTP API (development / split deployment).

The production entrypoint is ``python -m btcs_pool.server``, which runs Stratum,
accounting and the API together. This module is useful when developing the
website against an API process without opening the Stratum port.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web

from btcs_pool.api import create_app
from btcs_pool.config import load_config
from btcs_pool.db import Database
from btcs_pool.node import NodeMonitor
from btcs_pool.rpc import BTCSRpc

log = logging.getLogger(__name__)


async def main_async() -> None:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db = Database(cfg.db_path)
    rpc = BTCSRpc(
        cfg.rpc_url,
        cfg.rpc_user,
        cfg.rpc_password,
        cfg.rpc_wallet,
        timeout=cfg.rpc_timeout_seconds,
    )
    monitor = NodeMonitor(rpc, cfg.network)
    app = create_app(db, cfg, monitor)
    runner = web.AppRunner(app, access_log=log)
    await runner.setup()
    site = web.TCPSite(runner, cfg.api_host, cfg.api_port)
    await site.start()
    log.info("api_only_listening host=%s port=%s", cfg.api_host, cfg.api_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await stop.wait()
    await runner.cleanup()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
