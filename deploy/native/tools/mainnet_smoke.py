#!/usr/bin/env python3
"""Mainnet smoke verification for Silver Pool.

This tool talks to the live BTCS mainnet node over its private RPC endpoint,
uses a throwaway database, opens ephemeral local API/Stratum ports, and
exercises the real template -> Stratum -> share -> API -> restart path.

Block submission is deliberately intercepted and refused. A hash that meets
the network target is treated as a test failure, never sent to the node.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(TOOLS))

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402

from _env import load_environment  # noqa: E402
from btcs_pool.accounting import Accounting  # noqa: E402
from btcs_pool.api import create_app  # noqa: E402
from btcs_pool.block import (  # noqa: E402
    build_block,
    build_coinbase_tx,
    difficulty_to_target,
    hash_meets_target,
    target_from_bits,
)
from btcs_pool.config import PoolConfig  # noqa: E402
from btcs_pool.db import Database  # noqa: E402
from btcs_pool.node import NodeMonitor  # noqa: E402
from btcs_pool.rpc import BTCSRpc, RPCError  # noqa: E402
from btcs_pool.server import resolve_pool_script  # noqa: E402
from btcs_pool.stratum import StratumServer  # noqa: E402

log = logging.getLogger("mainnet-smoke")


class NoSubmitRPC:
    """Delegate RPC calls but refuse submitblock during the smoke test."""

    def __init__(self, inner: BTCSRpc):
        self._inner = inner
        self.submit_attempts = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def submitblock(self, block_hex: str):
        self.submit_attempts += 1
        raise RPCError("submitblock", "mainnet smoke refuses block submission")


class StratumClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.counter = 0

    async def send(self, method: str, params: list) -> int:
        self.counter += 1
        self.writer.write(
            (json.dumps({"id": self.counter, "method": method, "params": params}) + "\n").encode()
        )
        await self.writer.drain()
        return self.counter

    async def recv(self, timeout: float = 10.0) -> dict:
        line = await asyncio.wait_for(self.reader.readline(), timeout)
        if not line:
            raise RuntimeError("Stratum connection closed")
        return json.loads(line)

    async def wait_id(self, request_id: int, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            message = await self.recv(max(0.1, deadline - time.monotonic()))
            if message.get("id") == request_id:
                return message

    async def wait_method(self, method: str, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            message = await self.recv(max(0.1, deadline - time.monotonic()))
            if message.get("method") == method:
                return message

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_nonce(
    template: dict,
    script: str,
    extranonce1: bytes,
    extranonce2: bytes,
    ntime: int,
    share_target: int,
    block_target: int,
    *,
    want_share: bool,
    start: int = 0,
    limit: int = 2_000_000,
) -> tuple[int, str]:
    coinbase, txid = build_coinbase_tx(
        template, script, extranonce1, extranonce2
    )
    for nonce in range(start, start + limit):
        _block, _header, block_hash = build_block(
            template, txid, coinbase, nonce, ntime
        )
        is_block = hash_meets_target(block_hash, block_target)
        if is_block:
            raise RuntimeError(
                "a block candidate was found; refusing to submit it during the mainnet smoke test"
            )
        if hash_meets_target(block_hash, share_target) is want_share:
            return nonce, block_hash
    raise RuntimeError(f"no nonce found in {limit} attempts (want_share={want_share})")


async def api_get(base: str, path: str) -> tuple[int, dict]:
    async with aiohttp.ClientSession() as session:
        async with session.get(base + path, timeout=aiohttp.ClientTimeout(total=10)) as response:
            return response.status, await response.json()


async def start_api(db: Database, cfg: PoolConfig, monitor: NodeMonitor, server: StratumServer):
    runner = web.AppRunner(create_app(db, cfg, monitor, server.status), access_log=None)
    await runner.setup()
    port = free_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner, f"http://127.0.0.1:{port}"


async def open_stratum(server: StratumServer) -> tuple[asyncio.AbstractServer, int]:
    tcp = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    return tcp, int(tcp.sockets[0].getsockname()[1])


async def subscribe_and_authorize(
    port: int, username: str, password: str
) -> tuple[StratumClient, dict, dict, dict]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    client = StratumClient(reader, writer)
    subscribe_id = await client.send("mining.subscribe", ["silver-pool-mainnet-smoke/1.0"])
    subscription = await client.wait_id(subscribe_id)
    if subscription.get("error") is not None:
        raise RuntimeError(f"subscription failed: {subscription}")
    difficulty = await client.wait_method("mining.set_difficulty")
    authorize_id = await client.send("mining.authorize", [username, password])
    authorization = await client.wait_id(authorize_id)
    if authorization.get("result") is not True:
        raise RuntimeError(f"authorization failed: {authorization}")
    notify = await client.wait_method("mining.notify")
    return client, subscription, difficulty, notify


async def main_async(args) -> tuple[dict, int]:
    load_environment(args.env_file)
    cfg = PoolConfig.from_env()
    if cfg.network != "main":
        raise RuntimeError(f"BTCS_NETWORK is {cfg.network!r}, expected 'main'")
    if cfg.auto_payouts:
        raise RuntimeError("BTCS_AUTO_PAYOUTS must remain false")
    if not cfg.pool_address and not cfg.pool_script_pubkey:
        raise RuntimeError("set BTCS_POOL_ADDRESS or BTCS_POOL_SCRIPT_PUBKEY")
    cfg.difficulty = args.share_difficulty
    cfg.poll_interval = 60
    cfg.client_timeout_seconds = 30
    cfg.api_rate_limit_per_minute = 0
    cfg.public_stratum_host = ""

    rpc = BTCSRpc(
        cfg.rpc_url,
        cfg.rpc_user,
        cfg.rpc_password,
        cfg.rpc_wallet,
        timeout=cfg.rpc_timeout_seconds,
    )
    resolve_pool_script(rpc, cfg)
    chain = rpc.getblockchaininfo()
    network = rpc.getnetworkinfo()
    if chain.get("chain") != "main":
        raise RuntimeError(f"node chain is {chain.get('chain')!r}, expected 'main'")
    if chain.get("initialblockdownload"):
        raise RuntimeError("node is in initial block download")
    if float(chain.get("verificationprogress", 0)) < 0.999:
        raise RuntimeError("node verification progress is below 0.999")
    blocks = int(chain.get("blocks", 0))
    template = rpc.getblocktemplate(["segwit"])
    if int(template.get("height", 0)) != blocks + 1:
        raise RuntimeError("template height is not node height + 1")
    best_hash = rpc.getbestblockhash()
    if template.get("previousblockhash") != best_hash:
        raise RuntimeError("template previousblockhash is not the current best block")
    block_target = target_from_bits(str(template["bits"]))
    share_target = max(block_target, difficulty_to_target(cfg.difficulty))
    if share_target <= block_target:
        raise RuntimeError(
            "configured share difficulty is not easier than mainnet difficulty; "
            "refusing a test that could submit a block"
        )

    report: dict = {
        "ok": False,
        "env_file": str(Path(args.env_file).resolve()),
        "chain": chain.get("chain"),
        "node_height": blocks,
        "node_headers": chain.get("headers"),
        "node_verification_progress": chain.get("verificationprogress"),
        "node_difficulty": chain.get("difficulty"),
        "node_connections": network.get("connections"),
        "node_version": network.get("subversion"),
        "template_height": template.get("height"),
        "template_bits": template.get("bits"),
        "template_previousblockhash": template.get("previousblockhash"),
        "template_coinbase_value_satoshi": template.get("coinbasevalue"),
        "template_transactions": len(template.get("transactions", [])),
        "share_difficulty": cfg.difficulty,
        "block_target": f"0x{block_target:064x}",
        "share_target": f"0x{share_target:064x}",
        "coinbase_script_bytes": len(bytes.fromhex(cfg.pool_script_pubkey)),
    }

    with tempfile.TemporaryDirectory(prefix="silver-pool-mainnet-smoke-") as temporary:
        cfg.db_path = str(Path(temporary) / "pool.sqlite3")
        db = Database(cfg.db_path)
        accounting = Accounting(db)
        monitor = NodeMonitor(rpc, "main", cache_seconds=0)
        guarded = NoSubmitRPC(rpc)
        server = StratumServer(cfg, guarded, accounting, node_monitor=monitor)
        api_runner = None
        tcp = None
        client = None
        checks: list[str] = []

        async def check(name: str, condition: bool, detail: str = "") -> None:
            if not condition:
                raise RuntimeError(f"{name} failed{': ' + detail if detail else ''}")
            checks.append(name)
            log.info("check_passed name=%s %s", name, detail)

        try:
            job = await server.refresh_job()
            await check("template_job_created", job is not None)
            assert job is not None
            job_template = job["template"]
            block_target = target_from_bits(str(job_template["bits"]))
            share_target = max(block_target, difficulty_to_target(cfg.difficulty))
            if share_target <= block_target:
                raise RuntimeError(
                    "job share difficulty is not easier than mainnet difficulty"
                )
            await check(
                "job_matches_template",
                job_template.get("previousblockhash") == template.get("previousblockhash")
                and int(job_template.get("height", 0)) == int(template.get("height", 0)),
            )
            report["template_height"] = job_template.get("height")
            report["template_bits"] = job_template.get("bits")
            report["template_previousblockhash"] = job_template.get("previousblockhash")
            report["template_coinbase_value_satoshi"] = job_template.get("coinbasevalue")
            report["template_transactions"] = len(job_template.get("transactions", []))
            report["block_target"] = f"0x{block_target:064x}"
            report["share_target"] = f"0x{share_target:064x}"
            api_runner, api_base = await start_api(db, cfg, monitor, server)
            tcp, stratum_port = await open_stratum(server)

            client, subscription, difficulty_msg, notify = await subscribe_and_authorize(
                stratum_port, "smoke.worker", cfg.stratum_password
            )
            extranonce1 = bytes.fromhex(subscription["result"][1])
            extranonce2_size = int(subscription["result"][2])
            await check("subscribe_extranonce", extranonce2_size == cfg.extranonce2_size)
            await check(
                "difficulty_sent",
                abs(float(difficulty_msg["params"][0]) - cfg.difficulty) < 1e-12,
            )
            await check("job_notified", notify["params"][0] == job["job_id"])
            ntime = int(notify["params"][7], 16)
            extranonce2 = b"\x00" * extranonce2_size
            extranonce2_hex = extranonce2.hex()
            ntime_hex = notify["params"][7]
            nonce, share_hash = find_nonce(
                job_template,
                cfg.pool_script_pubkey,
                extranonce1,
                extranonce2,
                ntime,
                share_target,
                block_target,
                want_share=True,
            )
            report["share_hash"] = share_hash
            report["share_nonce"] = f"{nonce:08x}"
            await check(
                "share_is_not_block",
                not hash_meets_target(share_hash, block_target),
            )

            submit = ["smoke.worker", job["job_id"], extranonce2_hex, ntime_hex, f"{nonce:08x}"]
            submit_id = await client.send("mining.submit", submit)
            result = await client.wait_id(submit_id)
            await check("valid_share_accepted", result.get("result") is True, str(result))

            duplicate_id = await client.send("mining.submit", submit)
            duplicate = await client.wait_id(duplicate_id)
            await check(
                "duplicate_rejected",
                duplicate.get("result") is False
                and duplicate.get("error", {}).get("message") == "duplicate-share",
            )
            await check(
                "duplicate_not_credited",
                accounting.get_miner("smoke")["accepted_shares"] == 1,
            )

            invalid_nonce, invalid_hash = find_nonce(
                job_template,
                cfg.pool_script_pubkey,
                extranonce1,
                extranonce2,
                ntime,
                share_target,
                block_target,
                want_share=False,
            )
            await check("invalid_share_is_not_block", not hash_meets_target(invalid_hash, block_target))
            invalid_submit = [
                "smoke.worker",
                job["job_id"],
                extranonce2_hex,
                ntime_hex,
                f"{invalid_nonce:08x}",
            ]
            invalid_id = await client.send("mining.submit", invalid_submit)
            invalid = await client.wait_id(invalid_id)
            await check(
                "invalid_share_rejected",
                invalid.get("result") is False
                and invalid.get("error", {}).get("message") == "low-difficulty",
            )

            # Simulate a new chain tip on a copy only. The live node is not touched.
            original_template = server.current_template
            simulated = dict(original_template)
            simulated["previousblockhash"] = "00" * 32
            server.current_template = simulated
            try:
                stale_nonce, stale_hash = find_nonce(
                    job_template,
                    cfg.pool_script_pubkey,
                    extranonce1,
                    extranonce2,
                    ntime,
                    share_target,
                    block_target,
                    want_share=True,
                    start=nonce + 1,
                )
                await check(
                    "stale_share_is_not_block",
                    not hash_meets_target(stale_hash, block_target),
                )
                stale_submit = [
                    "smoke.worker",
                    job["job_id"],
                    extranonce2_hex,
                    ntime_hex,
                    f"{stale_nonce:08x}",
                ]
                stale_id = await client.send("mining.submit", stale_submit)
                stale = await client.wait_id(stale_id)
                await check(
                    "stale_share_rejected",
                    stale.get("result") is False
                    and stale.get("error", {}).get("message") == "stale-job",
                )
            finally:
                server.current_template = original_template

            await client.close()
            client = None

            # Unauthorized submit.
            reader, writer = await asyncio.open_connection("127.0.0.1", stratum_port)
            unauthorized = StratumClient(reader, writer)
            try:
                subscribe_id = await unauthorized.send("mining.subscribe", ["smoke-unauthorized"])
                await unauthorized.wait_id(subscribe_id)
                response_id = await unauthorized.send(
                    "mining.submit", ["smoke.worker", job["job_id"], extranonce2_hex, ntime_hex, f"{nonce:08x}"]
                )
                response = await unauthorized.wait_id(response_id)
                await check(
                    "unauthorized_submit_rejected",
                    response.get("result") is False
                    and response.get("error", {}).get("message") == "not authorized",
                )
            finally:
                await unauthorized.close()

            if cfg.stratum_password:
                reader, writer = await asyncio.open_connection("127.0.0.1", stratum_port)
                wrong = StratumClient(reader, writer)
                try:
                    subscribe_id = await wrong.send("mining.subscribe", ["smoke-wrong-password"])
                    await wrong.wait_id(subscribe_id)
                    response_id = await wrong.send(
                        "mining.authorize", ["smoke.worker", "wrong-password"]
                    )
                    response = await wrong.wait_id(response_id)
                    await check(
                        "wrong_password_rejected",
                        response.get("result") is False
                        and response.get("error", {}).get("message") == "unauthorized",
                    )
                finally:
                    await wrong.close()

            status, health = await api_get(api_base, "/api/health")
            await check("api_health", status == 200 and health.get("ok") is True)
            status, ready = await api_get(api_base, "/api/ready")
            await check(
                "api_ready",
                status == 200 and ready.get("data", {}).get("ready") is True,
                str(ready.get("data", {}).get("ready")),
            )
            status, status_body = await api_get(api_base, "/api/status")
            await check(
                "api_status_node",
                status == 200
                and status_body.get("data", {}).get("node", {}).get("blocks") == blocks,
            )
            status, miner = await api_get(api_base, "/api/pool/miner/smoke")
            miner_data = miner.get("data", {})
            await check(
                "api_miner_accounting",
                status == 200
                and miner_data.get("accepted_shares") == 1
                and miner_data.get("rejected_shares") == 2,
                str({k: miner_data.get(k) for k in ("accepted_shares", "rejected_shares")}),
            )
            status, shares = await api_get(api_base, "/api/pool/shares/recent")
            share_rows = shares.get("data", {}).get("shares", [])
            await check(
                "api_recent_shares",
                status == 200
                and any(row.get("accepted") for row in share_rows)
                and any(row.get("reject_reason") == "low-difficulty" for row in share_rows)
                and any(row.get("stale") for row in share_rows),
            )
            status, block_body = await api_get(api_base, "/api/pool/blocks")
            await check(
                "api_no_fake_blocks",
                status == 200 and block_body.get("data", {}).get("count") == 0,
            )
            status, public_config = await api_get(api_base, "/api/pool/config")
            config_data = public_config.get("data", {})
            await check(
                "api_payouts_disabled",
                status == 200 and config_data.get("auto_payouts") is False,
            )
            await check(
                "api_public_stratum_not_invented",
                config_data.get("stratum", {}).get("configured") is False,
            )

            tcp.close()
            await tcp.wait_closed()
            tcp = None
            await server.shutdown()
            await api_runner.cleanup()
            api_runner = None

            await check("no_block_submission", guarded.submit_attempts == 0)

            reopened = Database(cfg.db_path)
            reopened_accounting = Accounting(reopened)
            persisted = reopened_accounting.get_miner("smoke")
            await check(
                "restart_persistence",
                persisted is not None
                and persisted["accepted_shares"] == 1
                and persisted["rejected_shares"] == 2,
            )
            blocks_in_db = reopened.fetchone("SELECT COUNT(*) AS n FROM blocks")["n"]
            await check("restart_no_blocks", blocks_in_db == 0)

            # Restart a fresh server on the same database and verify replays are
            # still rejected without double credit.
            monitor2 = NodeMonitor(rpc, "main", cache_seconds=0)
            guarded2 = NoSubmitRPC(rpc)
            server2 = StratumServer(cfg, guarded2, reopened_accounting, node_monitor=monitor2)
            job2 = await server2.refresh_job()
            await check("restart_job_created", job2 is not None)
            assert job2 is not None
            job2_template = job2["template"]
            block_target2 = target_from_bits(str(job2_template["bits"]))
            share_target2 = max(block_target2, difficulty_to_target(cfg.difficulty))
            tcp2, port2 = await open_stratum(server2)
            client2, subscription2, _difficulty2, notify2 = await subscribe_and_authorize(
                port2, "smoke.worker", cfg.stratum_password
            )
            try:
                extranonce1_2 = bytes.fromhex(subscription2["result"][1])
                ntime2 = int(notify2["params"][7], 16)
                nonce2, hash2 = find_nonce(
                    job2_template,
                    cfg.pool_script_pubkey,
                    extranonce1_2,
                    extranonce2,
                    ntime2,
                    share_target2,
                    block_target2,
                    want_share=True,
                    start=nonce + 10_000,
                )
                await check("restart_share_is_not_block", not hash_meets_target(hash2, block_target2))
                submit2 = [
                    "smoke.worker",
                    job2["job_id"],
                    extranonce2_hex,
                    f"{ntime2:08x}",
                    f"{nonce2:08x}",
                ]
                response_id = await client2.send("mining.submit", submit2)
                response = await client2.wait_id(response_id)
                await check("restart_share_accepted", response.get("result") is True, str(response))
                replay_id = await client2.send("mining.submit", submit2)
                replay = await client2.wait_id(replay_id)
                await check(
                    "restart_replay_rejected",
                    replay.get("result") is False
                    and replay.get("error", {}).get("message") == "duplicate-share",
                )
                after = reopened_accounting.get_miner("smoke")
                await check(
                    "restart_no_double_credit",
                    after["accepted_shares"] == 2,
                    str(after["accepted_shares"]),
                )
            finally:
                await client2.close()
                tcp2.close()
                await tcp2.wait_closed()
                await server2.shutdown()

            api2_runner, api2_base = await start_api(reopened, cfg, monitor2, server2)
            try:
                status, persisted_api = await api_get(api2_base, "/api/pool/miner/smoke")
                await check(
                    "restart_api_persistence",
                    status == 200
                    and persisted_api.get("data", {}).get("accepted_shares") == 2,
                )
            finally:
                await api2_runner.cleanup()

            await check("no_block_submission_after_restart", guarded2.submit_attempts == 0)
            report.update(
                {
                    "ok": True,
                    "checks": checks,
                    "accepted_shares": 2,
                    "rejected_shares": 2,
                    "blocks_recorded": blocks_in_db,
                    "block_submission_attempts": guarded.submit_attempts
                    + guarded2.submit_attempts,
                    "database": "throwaway; deleted after verification",
                }
            )
            return report, 0
        finally:
            if client:
                await client.close()
            if tcp:
                tcp.close()
                await tcp.wait_closed()
            if api_runner:
                await api_runner.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", default=str(REPO_ROOT / ".env.native"), help="native environment file"
    )
    parser.add_argument(
        "--share-difficulty",
        type=float,
        default=1e-6,
        help="test-only share difficulty; must be far easier than mainnet difficulty",
    )
    parser.add_argument("--json", action="store_true", help="print JSON evidence")
    parser.add_argument("--report", help="write JSON evidence to this path")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        report, code = asyncio.run(main_async(args))
    except Exception as exc:  # noqa: BLE001 - operator-facing failure
        report = {"ok": False, "error": str(exc)}
        code = 1
        if args.debug:
            log.exception("mainnet_smoke_failed")
        else:
            log.error("mainnet_smoke_failed error=%s", exc)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report.get("ok"):
        print("MAINNET SMOKE PASS")
        print(
            f"chain={report['chain']} height={report['node_height']} "
            f"template={report['template_height']} bits={report['template_bits']} "
            f"coinbase={report['template_coinbase_value_satoshi']} sat"
        )
        print(
            f"share_difficulty={report['share_difficulty']} "
            f"accepted={report['accepted_shares']} rejected={report['rejected_shares']} "
            f"block_submissions={report['block_submission_attempts']}"
        )
        print(f"checks={len(report['checks'])}")
    else:
        print("MAINNET SMOKE FAIL", file=sys.stderr)
        print(report.get("error", "unknown error"), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
