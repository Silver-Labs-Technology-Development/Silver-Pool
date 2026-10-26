from __future__ import annotations

import asyncio
import copy
import json
import time

import pytest

from btcs_pool.accounting import Accounting
from btcs_pool.block import (
    build_block,
    build_coinbase_tx,
    difficulty_to_target,
    hash_meets_target,
    target_from_bits,
)
from btcs_pool.config import PoolConfig
from btcs_pool.stratum import StratumServer

POOL_SCRIPT = "0014" + "11" * 20


def make_template(
    *,
    previous: str = "22" * 32,
    height: int = 500,
    curtime: int | None = None,
) -> dict:
    return {
        "version": 0x20000000,
        "previousblockhash": previous,
        "transactions": [
            {"txid": "33" * 32, "data": "0100000001" + "00" * 8},
            {"txid": "44" * 32, "data": "0200000001" + "00" * 8},
        ],
        "coinbasevalue": 5_000_000_000,
        "default_witness_commitment": "6a24aa21a9ed" + "44" * 32,
        "bits": "207fffff",
        "height": height,
        "curtime": curtime or int(time.time()),
    }


class FakeRpc:
    def __init__(self, template: dict | None = None):
        self.template = template or make_template()
        self.submitted: list[str] = []
        self.submit_result = None
        self.hash_by_height: dict[int, str] = {}

    def getblocktemplate(self, rules=None):
        assert rules == ["segwit"]
        return copy.deepcopy(self.template)

    def submitblock(self, block_hex: str):
        self.submitted.append(block_hex)
        return self.submit_result

    def getblockhash(self, height: int):
        return self.hash_by_height.get(height, "aa" * 32)


def make_config(tmp_path, **overrides) -> PoolConfig:
    values = {
        "network": "regtest",
        "rpc_url": "http://127.0.0.1:1",
        "rpc_user": "test",
        "rpc_password": "test",
        "rpc_wallet": "",
        "pool_script_pubkey": POOL_SCRIPT,
        "db_path": str(tmp_path / "stratum.sqlite3"),
        "difficulty": 1.0,
        "extranonce2_size": 4,
        "poll_interval": 60,
        "client_timeout_seconds": 5,
        "job_history": 10,
        "api_rate_limit_per_minute": 0,
        "api_cors_origins": ["http://127.0.0.1:4173"],
    }
    values.update(overrides)
    return PoolConfig(**values)


class Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.counter = 0

    async def send(self, method: str, params: list, request_id=None):
        if request_id is None:
            self.counter += 1
            request_id = self.counter
        payload = {"id": request_id, "method": method, "params": params}
        self.writer.write((json.dumps(payload) + "\n").encode())
        await self.writer.drain()
        return request_id

    async def raw(self, data: bytes):
        self.writer.write(data)
        await self.writer.drain()

    async def recv(self, timeout: float = 3.0):
        line = await asyncio.wait_for(self.reader.readline(), timeout)
        if not line:
            return None
        return json.loads(line)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


class Harness:
    def __init__(self, accounting: Accounting, server: StratumServer, tcp_server, port: int):
        self.accounting = accounting
        self.server = server
        self.tcp_server = tcp_server
        self.port = port
        self.clients: list[Client] = []

    async def connect(self) -> Client:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        client = Client(reader, writer)
        self.clients.append(client)
        return client

    async def close(self):
        for client in self.clients:
            await client.close()
        self.tcp_server.close()
        await self.tcp_server.wait_closed()
        await self.server.shutdown()


async def start_harness(tmp_path, *, template=None, config=None):
    rpc = FakeRpc(template)
    accounting = Accounting(str(tmp_path / "stratum.sqlite3"))
    cfg = config or make_config(tmp_path)
    server = StratumServer(cfg, rpc, accounting)
    job = await server.refresh_job()
    assert job is not None
    tcp_server = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    port = tcp_server.sockets[0].getsockname()[1]
    harness = Harness(accounting, server, tcp_server, port)
    return harness, server, rpc, accounting


async def subscribe_and_authorize(client: Client, username="alice.rig1"):
    subscription_id = await client.send("mining.subscribe", ["test-miner/1.0"])
    subscription = await client.recv()
    difficulty = await client.recv()
    assert subscription["id"] == subscription_id
    assert subscription["error"] is None
    assert difficulty["method"] == "mining.set_difficulty"

    authorization_id = await client.send("mining.authorize", [username, "x"])
    authorization = await client.recv()
    notify = await client.recv()
    assert authorization == {"id": authorization_id, "result": True, "error": None}
    assert notify["method"] == "mining.notify"
    return subscription["result"], difficulty["params"][0], notify["params"]


def find_nonce(template: dict, extranonce1: bytes, ntime: int, predicate) -> int:
    coinbase, txid = build_coinbase_tx(
        template, POOL_SCRIPT, extranonce1, b"\x00\x00\x00\x00"
    )
    for nonce in range(10_000):
        _block, _header, block_hash = build_block(template, txid, coinbase, nonce, ntime)
        if predicate(block_hash):
            return nonce
    raise AssertionError("could not find a nonce matching the predicate")


def submit_params(notify: list, nonce: int, extranonce2="00000000") -> list:
    return [
        "alice.rig1",
        notify[0],
        extranonce2,
        notify[7],
        f"{nonce:08x}",
    ]


def test_subscribe_authorize_job_and_unique_extranonce(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            first = await harness.connect()
            sub, difficulty, notify = await subscribe_and_authorize(first)
            methods, extranonce1, extranonce2_size = sub
            assert ["mining.set_difficulty", "difficulty"] in methods
            assert ["mining.notify", "notify"] in methods
            assert len(extranonce1) == 8
            assert extranonce2_size == 4
            assert difficulty == 1.0
            assert notify[0] == "1"
            assert notify[1] == "22" * 32
            assert bytes.fromhex(extranonce1).hex() in notify[2]
            assert notify[5] == "20000000"
            assert notify[6] == "207fffff"
            assert len(notify[7]) == 8
            assert notify[8] is True
            assert server.status()["authorized_clients"] == 1
            assert accounting.get_miner("alice")["accepted_shares"] == 0

            second = await harness.connect()
            sub2, _difficulty2, notify2 = await subscribe_and_authorize(
                second, "bob.rig9"
            )
            assert sub2[1] != extranonce1
            assert notify2[0] == notify[0]
            assert notify2[2] != notify[2]
            assert server.status()["clients"] == 2
            assert server.status()["authorized_clients"] == 2
            assert accounting.get_miner("bob")["workers"] == 1
        finally:
            await harness.close()

    asyncio.run(run())


def test_authorization_rejections_and_unknown_methods(tmp_path):
    async def run():
        config = make_config(tmp_path, stratum_password="pool-secret")
        harness, server, rpc, accounting = await start_harness(
            tmp_path, config=config
        )
        try:
            client = await harness.connect()
            request_id = await client.send("mining.subscribe", ["miner/1.0"])
            await client.recv()
            await client.recv()

            request_id = await client.send("mining.authorize", ["alice", "wrong"])
            message = await client.recv()
            assert message["id"] == request_id
            assert message["result"] is False
            assert message["error"]["code"] == 24

            request_id = await client.send("mining.authorize", ["bad name", "pool-secret"])
            message = await client.recv()
            assert message["error"]["code"] == 20
            assert message["error"]["message"] == "invalid worker name"

            request_id = await client.send("mining.authorize", ["alice", "pool-secret"])
            message = await client.recv()
            assert message["result"] is True
            assert (await client.recv())["method"] == "mining.notify"

            request_id = await client.send("mining.configure", [["version-rolling"], {}])
            message = await client.recv()
            assert message["result"] == {"version-rolling": False}

            request_id = await client.send("mining.extranonce.subscribe", [])
            message = await client.recv()
            assert message["result"] is True

            request_id = await client.send("mining.nope", [])
            message = await client.recv()
            assert message["id"] == request_id
            assert message["error"]["code"] == 20
            assert "unknown method" in message["error"]["message"]

            await client.raw(b"not json\n")
            message = await client.recv()
            assert message["error"]["message"] == "invalid JSON"

            await client.raw(b"[]\n")
            message = await client.recv()
            assert message["error"]["message"] == "invalid request"
        finally:
            await harness.close()

    asyncio.run(run())


def test_per_session_difficulty_accepted_share_and_duplicate(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            client = await harness.connect()
            subscription, _difficulty, notify = await subscribe_and_authorize(client)
            extranonce1 = bytes.fromhex(subscription[1])
            template = rpc.template
            block_target = target_from_bits(template["bits"])
            ntime = int(notify[7], 16)

            request_id = await client.send("mining.suggest_difficulty", [1e-12])
            message = await client.recv()
            assert message["id"] == request_id
            assert message["result"] is True
            difficulty_message = await client.recv()
            assert difficulty_message["method"] == "mining.set_difficulty"
            assert difficulty_message["params"] == [1e-12]
            refreshed = await client.recv()
            assert refreshed["method"] == "mining.notify"
            assert refreshed["params"][0] == notify[0]

            # Tiny difficulty makes any hash a valid share. Choose a nonce that
            # is not also a block so this test exercises share accounting only.
            nonce = find_nonce(
                template,
                extranonce1,
                ntime,
                lambda block_hash: not hash_meets_target(block_hash, block_target),
            )
            params = submit_params(notify, nonce)
            request_id = await client.send("mining.submit", params)
            message = await client.recv()
            assert message == {"id": request_id, "result": True, "error": None}
            assert accounting.share_count("alice") == 1
            assert accounting.pool_stats()["total_blocks"] == 0
            assert accounting.current_round()["total_difficulty"] == pytest.approx(1e-12)

            request_id = await client.send("mining.submit", params)
            message = await client.recv()
            assert message["id"] == request_id
            assert message["result"] is False
            assert message["error"]["code"] == 23
            assert message["error"]["message"] == "duplicate-share"
            assert accounting.share_count("alice") == 1
            # Duplicate submissions hit the UNIQUE constraint and are not
            # inserted as a second rejected share row.
            assert accounting.share_count("alice", accepted=False) == 0
        finally:
            await harness.close()

    asyncio.run(run())


def test_share_validation_rejections(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            client = await harness.connect()
            subscription, _difficulty, notify = await subscribe_and_authorize(client)
            extranonce1 = bytes.fromhex(subscription[1])
            template = rpc.template
            ntime = int(notify[7], 16)

            # Request a difficulty high enough that ordinary hashes fail.
            # (The protocol caps suggestions below 1e12.)
            await client.send("mining.suggest_difficulty", [1e11])
            await client.recv()
            await client.recv()
            await client.recv()

            # With regtest bits the block target is easier than the requested
            # share difficulty, so the share target is the block target. A
            # hash above the block target is therefore a low-difficulty share
            # and is not also a block candidate.
            nonce = find_nonce(
                template,
                extranonce1,
                ntime,
                lambda block_hash: not hash_meets_target(block_hash, target_from_bits(template["bits"])),
            )
            cases = [
                (["alice.rig1", notify[0], "00", notify[7], f"{nonce:08x}"], "invalid-extranonce2"),
                (["alice.rig1", notify[0], "zzzzzzzz", notify[7], f"{nonce:08x}"], "invalid-hex"),
                (["alice.rig1", notify[0], "00000000", "010203", f"{nonce:08x}"], "invalid-field-length"),
                (["alice.rig1", notify[0], "00000000", notify[7], "zzzzzzzz"], "invalid-hex"),
                (
                    ["alice.rig1", notify[0], "00000000", f"{ntime + 10_000:08x}", f"{nonce:08x}"],
                    "time-out-of-range",
                ),
                (["alice.rig1", notify[0], "00000000", notify[7], f"{nonce:08x}"], "low-difficulty"),
                (["alice.rig1", "999999", "00000000", notify[7], f"{nonce:08x}"], "unknown-job"),
                (["alice.rig1", notify[0]], "invalid submit parameters"),
            ]
            for params, expected in cases:
                request_id = await client.send("mining.submit", params)
                message = await client.recv()
                assert message["id"] == request_id, (params, message)
                assert message["result"] is False, (params, message)
                assert message["error"]["message"] == expected, (params, message)

            assert accounting.share_count("alice") == 0
            rejected = accounting.miner_shares("alice")
            reasons = [share["reject_reason"] for share in rejected]
            for expected in (
                "invalid-extranonce2",
                "invalid-hex",
                "invalid-field-length",
                "time-out-of-range",
                "low-difficulty",
                "unknown-job",
            ):
                assert expected in reasons

            unauthorized = await harness.connect()
            await unauthorized.send("mining.subscribe", ["miner/1.0"])
            await unauthorized.recv()
            await unauthorized.recv()
            request_id = await unauthorized.send(
                "mining.submit", ["alice.rig1", notify[0], "00000000", notify[7], "00000000"]
            )
            message = await unauthorized.recv()
            assert message["error"]["code"] == 24
            assert message["error"]["message"] == "not authorized"
        finally:
            await harness.close()

    asyncio.run(run())


def test_stale_job_after_new_tip(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            client = await harness.connect()
            _sub, _difficulty, notify = await subscribe_and_authorize(client)
            old_job = notify[0]

            rpc.template = make_template(previous="55" * 32, height=501)
            await server.refresh_job()
            broadcast = await client.recv()
            assert broadcast["method"] == "mining.notify"
            assert broadcast["params"][0] != old_job
            assert broadcast["params"][1] == "55" * 32
            assert broadcast["params"][8] is True
            assert server.current_round_id.startswith("501-")

            request_id = await client.send(
                "mining.submit",
                ["alice.rig1", old_job, "00000000", notify[7], "00000000"],
            )
            message = await client.recv()
            assert message["id"] == request_id
            assert message["result"] is False
            assert message["error"]["message"] == "stale-job"
            shares = accounting.miner_shares("alice")
            assert shares[0]["stale"] == 1
            assert shares[0]["reject_reason"] == "stale-job"
        finally:
            await harness.close()

    asyncio.run(run())


def test_valid_block_candidate_is_submitted_and_recorded(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            client = await harness.connect()
            subscription, _difficulty, notify = await subscribe_and_authorize(client)
            extranonce1 = bytes.fromhex(subscription[1])
            template = rpc.template
            block_target = target_from_bits(template["bits"])
            ntime = int(notify[7], 16)
            nonce = find_nonce(
                template,
                extranonce1,
                ntime,
                lambda block_hash: hash_meets_target(block_hash, block_target),
            )

            request_id = await client.send("mining.submit", submit_params(notify, nonce))
            message = await client.recv()
            assert message == {"id": request_id, "result": True, "error": None}
            assert len(rpc.submitted) == 1
            bytes.fromhex(rpc.submitted[0])
            stats = accounting.pool_stats()
            assert stats["total_blocks"] == 1
            assert stats["immature_blocks"] == 1
            block = accounting.recent_blocks(1)[0]
            assert block["height"] == 500
            assert block["status"] == "immature"
            assert block["miner"] == "alice"
            assert block["confirmations"] == 0
            assert accounting.fee_ledger(1)[0]["fee_satoshi"] == 100_000_000
            assert accounting.get_miner("alice")["immature_satoshi"] == 4_900_000_000
            # Finding a block closes the round in which it was found.
            assert accounting.current_round() is None
            assert accounting.db.fetchone(
                "SELECT status FROM rounds WHERE round_id=?", (block["round_id"],)
            )["status"] == "completed"
        finally:
            await harness.close()

    asyncio.run(run())


def test_submitblock_rejection_is_audited_not_counted(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        rpc.submit_result = "bad-prevblk"
        try:
            client = await harness.connect()
            subscription, _difficulty, notify = await subscribe_and_authorize(client)
            template = rpc.template
            block_target = target_from_bits(template["bits"])
            nonce = find_nonce(
                template,
                bytes.fromhex(subscription[1]),
                int(notify[7], 16),
                lambda block_hash: hash_meets_target(block_hash, block_target),
            )
            request_id = await client.send("mining.submit", submit_params(notify, nonce))
            message = await client.recv()
            assert message["result"] is True
            assert accounting.pool_stats()["total_blocks"] == 0
            candidates = accounting.db.fetchall("SELECT * FROM block_candidates")
            assert len(candidates) == 1
            assert candidates[0]["node_result"] == "bad-prevblk"
            assert candidates[0]["height"] == 500
        finally:
            await harness.close()

    asyncio.run(run())


def test_shutdown_disconnects_clients_and_stops_status(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        first = await harness.connect()
        second = await harness.connect()
        await subscribe_and_authorize(first)
        await subscribe_and_authorize(second, "bob.rig1")
        assert server.status()["clients"] == 2

        await server.shutdown()
        for client in (first, second):
            message = await client.recv()
            assert message["error"]["message"] == "pool shutting down"
            assert await client.recv() is None
        assert server.status()["listening"] is False
        assert server.status()["clients"] == 0

        harness.tcp_server.close()
        await harness.tcp_server.wait_closed()

    asyncio.run(run())


def test_reconnect_after_disconnect_receives_current_job(tmp_path):
    async def run():
        harness, server, rpc, accounting = await start_harness(tmp_path)
        try:
            first = await harness.connect()
            subscription, _difficulty, notify = await subscribe_and_authorize(first)
            await first.close()
            for _ in range(50):
                if server.status()["clients"] == 0:
                    break
                await asyncio.sleep(0.02)
            assert server.status()["clients"] == 0

            second = await harness.connect()
            reconnected, _difficulty2, notify2 = await subscribe_and_authorize(second)
            assert reconnected[1] != subscription[1]
            assert notify2[0] == notify[0]
            assert server.status()["authorized_clients"] == 1
            assert accounting.get_miner("alice")["workers"] == 1
        finally:
            await harness.close()

    asyncio.run(run())
