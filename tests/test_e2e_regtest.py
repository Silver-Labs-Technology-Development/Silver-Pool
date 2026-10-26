"""End-to-end pool test against a real, isolated Bitcoin Silver Core regtest node.

The daemon is started with a throwaway datadir and random loopback ports. No
chain data, wallet material or credentials from a developer machine are used.
The test is skipped when the BTCS binaries are not present.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from btcs_pool.accounting import Accounting
from btcs_pool.api import create_app
from btcs_pool.block import (
    build_block,
    build_coinbase_tx,
    hash_meets_target,
    target_from_bits,
)
from btcs_pool.config import PoolConfig
from btcs_pool.db import Database
from btcs_pool.node import NodeMonitor
from btcs_pool.rpc import BTCSRpc, RPCError
from btcs_pool.stratum import StratumServer

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAEMON = Path("/home/user/Silver-Labs/btcs-core/build/bin/bitcoinsilverd")
DAEMON = Path(
    os.environ.get("BTCS_DAEMON")
    or shutil.which("bitcoinsilverd")
    or DEFAULT_DAEMON
)
pytestmark = pytest.mark.skipif(
    not DAEMON.is_file(),
    reason="bitcoinsilverd is not installed; set BTCS_DAEMON to run the real-node E2E",
)

POOL_SCRIPT = "0014" + "22" * 20


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RegtestNode:
    def __init__(self, tmp_path: Path):
        self.datadir = tmp_path / "node"
        self.datadir.mkdir(parents=True)
        self.log_path = tmp_path / "bitcoinsilverd.log"
        self.rpc_port = free_port()
        self.p2p_port = free_port()
        self.user = "pool-e2e"
        self.password = "pool-e2e-secret"
        self.process: subprocess.Popen | None = None
        self.rpc = BTCSRpc(
            f"http://127.0.0.1:{self.rpc_port}", self.user, self.password, "pooltest"
        )

    def start(self) -> None:
        args = [
            str(DAEMON),
            "-regtest",
            f"-datadir={self.datadir}",
            "-server=1",
            "-listen=0",
            "-discover=0",
            "-dnsseed=0",
            f"-rpcport={self.rpc_port}",
            f"-port={self.p2p_port}",
            f"-rpcuser={self.user}",
            f"-rpcpassword={self.password}",
            "-fallbackfee=0.0001",
            "-printtoconsole=0",
        ]
        log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            args,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    "bitcoinsilverd exited during startup:\n"
                    + self.log_path.read_text(encoding="utf-8", errors="replace")
                )
            try:
                self.rpc.getblockchaininfo()
                return
            except RPCError:
                time.sleep(0.2)
        raise RuntimeError(
            "bitcoinsilverd did not become ready:\n"
            + self.log_path.read_text(encoding="utf-8", errors="replace")
        )

    def prepare_chain(self) -> None:
        self.rpc.ensure_wallet()
        address = self.rpc.getnewaddress("pool-e2e")
        self.rpc.generatetoaddress(10, address)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.rpc.getblockcount() >= 10:
                return
            time.sleep(0.1)
        raise RuntimeError("regtest node did not reach height 10")

    def stop(self) -> None:
        if not self.process:
            return
        try:
            self.rpc.call_base("stop")
        except Exception:  # noqa: BLE001 - shutdown may close the socket first
            pass
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


class StratumClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.counter = 0

    async def send(self, method: str, params: list) -> int:
        self.counter += 1
        payload = {"id": self.counter, "method": method, "params": params}
        self.writer.write((json.dumps(payload) + "\n").encode())
        await self.writer.drain()
        return self.counter

    async def recv(self, timeout: float = 5.0):
        line = await asyncio.wait_for(self.reader.readline(), timeout)
        return json.loads(line) if line else None

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


async def recv_until(reader: asyncio.StreamReader, method: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = await asyncio.wait_for(
            reader.readline(), max(0.05, deadline - time.monotonic())
        )
        if not line:
            raise AssertionError("Stratum connection closed while waiting for a message")
        payload = json.loads(line)
        if payload.get("method") == method:
            return payload
    raise AssertionError(f"did not receive {method} before timeout")


def test_real_regtest_stratum_blocks_api_and_restart(tmp_path):
    node = RegtestNode(tmp_path)
    db = None
    server = None
    tcp_server = None
    client = None
    try:
        node.start()
        node.prepare_chain()
        info = node.rpc.getblockchaininfo()
        assert info["chain"] == "regtest"
        assert info["blocks"] >= 10

        template = node.rpc.getblocktemplate(["segwit"])
        assert template["height"] >= 11
        assert template["bits"] == "207fffff"
        assert int(template["coinbasevalue"]) > 0

        config = PoolConfig(
            network="regtest",
            rpc_url=f"http://127.0.0.1:{node.rpc_port}",
            rpc_user=node.user,
            rpc_password=node.password,
            rpc_wallet="pooltest",
            pool_script_pubkey=POOL_SCRIPT,
            db_path=str(tmp_path / "pool.sqlite3"),
            difficulty=1.0,
            extranonce2_size=4,
            poll_interval=60,
            client_timeout_seconds=10,
            api_rate_limit_per_minute=0,
        )
        db = Database(config.db_path)
        accounting = Accounting(db)
        monitor = NodeMonitor(node.rpc, "regtest", cache_seconds=0)
        server = StratumServer(config, node.rpc, accounting, node_monitor=monitor)

        async def run_all():
            nonlocal client, tcp_server
            from aiohttp.test_utils import TestClient, TestServer

            job = await server.refresh_job()
            assert job is not None
            assert job["height"] == template["height"]
            tcp_server = await asyncio.start_server(
                server.handle_client, "127.0.0.1", 0
            )
            port = tcp_server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            client = StratumClient(reader, writer)
            try:
                subscribe_id = await client.send("mining.subscribe", ["e2e-miner/1.0"])
                subscription = await client.recv()
                assert subscription["id"] == subscribe_id
                assert subscription["error"] is None
                extranonce1 = bytes.fromhex(subscription["result"][1])
                assert subscription["result"][2] == 4
                difficulty = await client.recv()
                assert difficulty["method"] == "mining.set_difficulty"

                authorize_id = await client.send("mining.authorize", ["e2e.rig1", "x"])
                authorization = await client.recv()
                assert authorization == {"id": authorize_id, "result": True, "error": None}
                notify = await client.recv()
                assert notify["method"] == "mining.notify"
                assert notify["params"][0] == job["job_id"]
                ntime = int(notify["params"][7], 16)

                block_target = target_from_bits(template["bits"])
                coinbase, txid = build_coinbase_tx(
                    template, POOL_SCRIPT, extranonce1, b"\x00\x00\x00\x00"
                )
                nonce = None
                expected_hash = None
                for candidate in range(100_000):
                    _block, _header, block_hash = build_block(
                        template, txid, coinbase, candidate, ntime
                    )
                    if hash_meets_target(block_hash, block_target):
                        nonce = candidate
                        expected_hash = block_hash
                        break
                assert nonce is not None

                submit = [
                    "e2e.rig1",
                    job["job_id"],
                    "00000000",
                    notify["params"][7],
                    f"{nonce:08x}",
                ]
                submit_id = await client.send("mining.submit", submit)
                result = await client.recv()
                assert result == {"id": submit_id, "result": True, "error": None}

                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if node.rpc.getblockcount() >= template["height"]:
                        break
                    await asyncio.sleep(0.2)
                assert node.rpc.getblockcount() >= template["height"]
                canonical = node.rpc.getblockhash(template["height"])
                assert canonical == expected_hash

                block = accounting.recent_blocks(1)[0]
                assert block["hash"] == expected_hash
                assert block["height"] == template["height"]
                assert block["status"] == "immature"
                assert block["miner"] == "e2e"
                assert accounting.get_miner("e2e")["immature_satoshi"] == int(
                    template["coinbasevalue"]
                ) - int(int(template["coinbasevalue"]) * config.pool_fee / 100)

                duplicate_id = await client.send("mining.submit", submit)
                duplicate = await client.recv()
                assert duplicate["id"] == duplicate_id
                assert duplicate["result"] is False
                assert duplicate["error"]["message"] == "duplicate-share"

                await server.refresh_job()
                new_job = await recv_until(reader, "mining.notify")
                assert new_job["params"][0] != job["job_id"]
                assert new_job["params"][1] != notify["params"][1]
                new_job_id = server.current_job_id

                # Use a different nonce so the stale rejection is a distinct
                # share record rather than the duplicate constraint hit by the
                # exact accepted submission above.
                stale_submit = [
                    *submit[:4],
                    f"{(nonce + 1) % 0xFFFFFFFF:08x}",
                ]
                stale_id = await client.send("mining.submit", stale_submit)
                stale = await client.recv()
                assert stale["id"] == stale_id
                assert stale["result"] is False
                assert stale["error"]["message"] == "stale-job"

                app = create_app(db, config, monitor, server.status)
                test_client = TestClient(TestServer(app))
                await test_client.start_server()
                try:
                    async with test_client.get("/api/status") as response:
                        assert response.status == 200
                        payload = await response.json()
                    assert payload["data"]["ready"] is True
                    assert payload["data"]["node"]["blocks"] >= template["height"]
                    assert payload["data"]["stratum"]["current_job_id"] == new_job_id

                    async with test_client.get("/api/pool/blocks") as response:
                        payload = await response.json()
                    assert payload["data"]["count"] == 1
                    assert payload["data"]["blocks"][0]["hash"] == expected_hash

                    async with test_client.get("/api/pool/miner/e2e") as response:
                        assert response.status == 200
                        payload = await response.json()
                    assert payload["data"]["accepted_shares"] == 1
                    assert payload["data"]["rejected_shares"] == 1
                finally:
                    await test_client.close()

                return expected_hash
            finally:
                await client.close()
                client = None
                tcp_server.close()
                await tcp_server.wait_closed()
                tcp_server = None
                await server.shutdown()

        expected_hash = asyncio.run(run_all())

        # Restart persistence: a new Database instance sees the accepted block
        # and the rejected stale share; no in-memory state is required.
        reopened = Database(config.db_path)
        block_row = reopened.fetchone("SELECT * FROM blocks WHERE hash=?", (expected_hash,))
        assert block_row is not None
        assert reopened.fetchone(
            "SELECT COUNT(*) AS n FROM shares WHERE accepted=0 AND stale=1"
        )["n"] == 1
    finally:
        if client:
            asyncio.run(client.close())
        if tcp_server:
            tcp_server.close()
            asyncio.run(tcp_server.wait_closed())
        if server:
            asyncio.run(server.shutdown())
        node.stop()
