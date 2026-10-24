import asyncio
import os
import sys

from .config import load_config
from .rpc import BTCSRpc
from .accounting import Accounting
from .stratum import StratumServer


def resolve_pool_script(rpc, cfg):
    if cfg.pool_address and not cfg.pool_script_pubkey:
        info = rpc.getaddressinfo(cfg.pool_address)
        cfg.pool_script_pubkey = info["scriptPubKey"]
    if not cfg.pool_script_pubkey:
        # create wallet address
        addr = rpc.getnewaddress("pool")
        cfg.pool_address = addr
        info = rpc.getaddressinfo(addr)
        cfg.pool_script_pubkey = info["scriptPubKey"]


async def main_async(cfg):
    rpc = BTCSRpc(cfg.rpc_url, cfg.rpc_user, cfg.rpc_password, cfg.rpc_wallet)
    resolve_pool_script(rpc, cfg)
    accounting = Accounting(cfg.db_path)
    server = StratumServer(cfg, rpc, accounting, on_block=lambda h, x: None)

    def on_block(height, h):
        print(f"BLOCK FOUND height={height} hash={h}")

    server.on_block = on_block
    # start template poller
    asyncio.create_task(server.poll_templates())
    srv = await asyncio.start_server(server.handle_client, cfg.stratum_host, cfg.stratum_port)
    print(f"Pool listening on {cfg.stratum_host}:{cfg.stratum_port}")
    async with srv:
        await srv.serve_forever()


def main():
    cfg = load_config(os.getenv("BTCS_POOL_CONFIG"))
    try:
        asyncio.run(main_async(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
