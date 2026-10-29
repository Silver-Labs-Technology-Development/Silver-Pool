from __future__ import annotations

import asyncio
import contextlib
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from btcs_pool.accounting import Accounting
from btcs_pool.api import create_app
from btcs_pool.config import PoolConfig
from btcs_pool.db import Database
from btcs_pool.node import NodeMonitor
from btcs_pool.rpc import RPCError


class FakeRpc:
    def __init__(self, online: bool = True):
        self.online = online
        self.chain = {
            "chain": "regtest",
            "blocks": 500,
            "headers": 500,
            "verificationprogress": 1.0,
            "initialblockdownload": False,
            "difficulty": 4.65e-10,
            "warnings": [],
        }
        self.network = {"connections": 2, "warnings": []}
        self.mempool = {"size": 3}

    def _check(self):
        if not self.online:
            raise RPCError("getblockchaininfo", "connection refused")

    def getblockchaininfo(self):
        self._check()
        return self.chain

    def getnetworkinfo(self):
        self._check()
        return self.network

    def getmempoolinfo(self):
        self._check()
        return self.mempool

    def getblockhash(self, height: int):
        self._check()
        return "aa" * 32


def online_stratum() -> dict:
    return {
        "listening": True,
        "clients": 0,
        "authorized_clients": 0,
        "current_job_id": "7",
        "current_height": 500,
        "current_round_id": "500-deadbeef",
        "current_difficulty": 1.0,
        "last_template_at": time.time(),
        "last_template_error": None,
        "uptime_seconds": 12.5,
    }


def offline_stratum() -> dict:
    return {
        "listening": False,
        "clients": 0,
        "authorized_clients": 0,
        "current_job_id": None,
        "current_height": None,
        "current_round_id": None,
        "current_difficulty": 1.0,
        "last_template_at": None,
        "last_template_error": "RPC unavailable",
        "uptime_seconds": 0.0,
    }


def make_app(
    tmp_path,
    *,
    online: bool = True,
    stratum=None,
    rate_limit: int = 0,
    origins: list[str] | None = None,
    trusted_proxies: list[str] | None = None,
):
    db = Database(str(tmp_path / "pool.sqlite3"))
    config = PoolConfig(
        network="regtest",
        rpc_url="http://127.0.0.1:1",
        rpc_user="test",
        rpc_password="test",
        rpc_wallet="",
        pool_script_pubkey="0014" + "11" * 20,
        db_path=str(tmp_path / "pool.sqlite3"),
        api_rate_limit_per_minute=rate_limit,
        api_cors_origins=origins or ["http://127.0.0.1:4173"],
        trusted_proxies=trusted_proxies or [],
    )
    rpc = FakeRpc(online=online)
    monitor = NodeMonitor(rpc, "regtest", cache_seconds=0)
    app = create_app(db, config, monitor, stratum or online_stratum)
    return db, config, app


def seed_pool(db: Database) -> Accounting:
    accounting = Accounting(db)
    accounting.register_miner("alice.rig1")
    accounting.register_miner("alice.rig2")
    accounting.register_miner("bob.rig1")
    accounting.start_round("round-1", 500)
    accounting.record_share(
        "alice.rig1", "job-1", "aabbccdd", "01020304", "00000001", 2.0, True,
        round_id="round-1",
    )
    accounting.record_share(
        "bob.rig1", "job-1", "aabbccdd", "01020304", "00000002", 1.0, True,
        round_id="round-1",
    )
    accounting.record_share(
        "alice.rig1", "job-1", "aabbccdd", "01020304", "00000003", 2.0, False,
        round_id="round-1", reject_reason="low-difficulty",
    )
    accounting.record_block(
        height=500,
        block_hash="aa" * 32,
        coinbase_value_satoshi=5_000_000_000,
        fee_satoshi=100_000_000,
        net_reward_satoshi=4_900_000_000,
        miner_username="alice.rig1",
        round_id="round-1",
        header_hex="00",
        block_hex="00",
        job_id="job-1",
    )
    return accounting


@contextlib.asynccontextmanager
async def api_client(app):
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def test_health_envelope_request_id_and_headers(tmp_path):
    async def run():
        _db, _config, app = make_app(tmp_path)
        async with api_client(app) as client:
            async with client.get("/api/health", headers={"X-Request-ID": "req-123"}) as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["ok"] is True
                assert payload["data"]["status"] == "ok"
                assert payload["data"]["service"] == "silver-pool"
                assert payload["data"]["database"] == {"healthy": True, "error": None}
                assert payload["meta"]["request_id"] == "req-123"
                assert isinstance(payload["meta"]["timestamp"], float)
                assert response.headers["X-Request-ID"] == "req-123"
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Content-Type-Options"] == "nosniff"

    asyncio.run(run())


def test_status_online_is_live_and_payouts_disabled(tmp_path):
    async def run():
        _db, _config, app = make_app(tmp_path)
        async with api_client(app) as client:
            async with client.get("/api/status") as response:
                assert response.status == 200
                payload = await response.json()
            data = payload["data"]
            assert data["ready"] is True
            assert data["checks"]["node"]["synced"] is True
            assert data["node"]["blocks"] == 500
            assert data["stratum"]["current_job_id"] == "7"
            assert data["pool"]["total_miners"] == 0
            assert data["pool"]["total_blocks"] == 0

            async with client.get("/api/pool/status") as response:
                assert response.status == 200
                payload = await response.json()
            config = payload["data"]["config"]
            assert config["auto_payouts"] is False
            assert config["payouts_enabled"] is False
            assert config["stratum"]["endpoint"] is None

    asyncio.run(run())


def test_ready_success_and_failure_envelopes(tmp_path):
    async def run():
        _db, _config, app = make_app(tmp_path)
        async with api_client(app) as client:
            async with client.get("/api/ready") as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["ok"] is True
                assert payload["data"]["ready"] is True
                assert payload["data"]["stratum"]["template_fresh"] is True

        _db2, _config2, offline_app = make_app(
            tmp_path / "offline", online=False, stratum=offline_stratum
        )
        async with api_client(offline_app) as client:
            async with client.get("/api/ready") as response:
                assert response.status == 503
                payload = await response.json()
                assert payload["ok"] is False
                assert payload["error"]["code"] == "not_ready"
                details = payload["error"]["details"]
                assert details["ready"] is False
                assert details["node"]["connected"] is False
                assert details["stratum"]["running"] is False

            async with client.get("/api/status") as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["ok"] is True
                assert payload["data"]["ready"] is False
                assert payload["data"]["node"]["connected"] is False
                assert payload["data"]["node"]["error"] == "Node RPC unavailable"

    asyncio.run(run())


def test_health_degrades_but_stays_liveness_200(tmp_path, monkeypatch):
    async def run():
        db, _config, app = make_app(tmp_path)

        def broken(*args, **kwargs):
            raise RuntimeError("database file is unavailable")

        monkeypatch.setattr(db, "fetchone", broken)
        async with api_client(app) as client:
            async with client.get("/api/health") as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["data"]["status"] == "degraded"
                assert payload["data"]["database"]["healthy"] is False
                assert payload["data"]["database"]["error"] == "Database unavailable"

            async with client.get("/api/ready") as response:
                assert response.status == 503
                payload = await response.json()
                assert payload["error"]["details"]["database"]["healthy"] is False

    asyncio.run(run())


def test_miner_list_detail_shares_and_search(tmp_path):
    async def run():
        db, _config, app = make_app(tmp_path)
        seed_pool(db)
        async with api_client(app) as client:
            async with client.get("/api/pool/miners") as response:
                assert response.status == 200
                payload = await response.json()
            data = payload["data"]
            assert data["count"] == 2
            assert data["limit"] == 50
            assert {row["username"] for row in data["miners"]} == {"alice", "bob"}
            alice = next(row for row in data["miners"] if row["username"] == "alice")
            assert alice["workers"] == 2
            assert alice["accepted_shares"] == 1
            assert alice["rejected_shares"] == 1
            assert alice["immature_satoshi"] == 3_266_666_666
            assert alice["available_satoshi"] == 0

            async with client.get(
                "/api/pool/miners", params={"search": "bo", "limit": 1}
            ) as response:
                payload = await response.json()
                assert payload["data"]["search"] == "bo"
                assert payload["data"]["count"] == 1
                assert payload["data"]["miners"][0]["username"] == "bob"

            async with client.get("/api/pool/miner/alice") as response:
                assert response.status == 200
                payload = await response.json()
                detail = payload["data"]
                assert detail["username"] == "alice"
                assert detail["workers"] == 2
                assert len(detail["worker_rows"]) == 2
                assert detail["recent_blocks"][0]["height"] == 500

            async with client.get("/api/pool/miner/alice.rig1/shares") as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["data"]["miner"] == "alice"
                assert payload["data"]["count"] == 2
                assert {share["accepted"] for share in payload["data"]["shares"]} == {0, 1}

            async with client.get("/api/pool/miner/carol") as response:
                assert response.status == 404
                payload = await response.json()
                assert payload["ok"] is False
                assert payload["error"]["code"] == "miner_not_found"

            async with client.get("/api/pool/miner/bad%20name") as response:
                assert response.status == 400
                payload = await response.json()
                assert payload["error"]["code"] == "invalid_username"

            async with client.get("/api/pool/miner/alice/shares", params={"limit": 0}) as response:
                assert response.status == 400
                payload = await response.json()
                assert payload["error"]["code"] == "invalid_query"

            async with client.get("/api/pool/miners", params={"search": "x" * 81}) as response:
                assert response.status == 400
                payload = await response.json()
                assert payload["error"]["code"] == "invalid_query"

    asyncio.run(run())


def test_statistics_blocks_hashrate_round_and_fee_ledger(tmp_path):
    async def run():
        db, _config, app = make_app(tmp_path)
        seed_pool(db)
        async with api_client(app) as client:
            async with client.get("/api/pool/statistics") as response:
                assert response.status == 200
                payload = await response.json()
                totals = payload["data"]["totals"]
                assert totals["total_miners"] == 2
                assert totals["total_workers"] == 3
                assert totals["accepted_shares"] == 2
                assert totals["rejected_shares"] == 1
                assert totals["total_blocks"] == 1
                assert totals["immature_blocks"] == 1
                assert payload["data"]["hashrate"]["unit"] == "H/s"

            async with client.get("/api/pool/history/hashrate", params={"range": "1h"}) as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["data"]["range"] == "1h"
                assert payload["data"]["bucket_seconds"] == 60
                assert len(payload["data"]["history"]) >= 60

            async with client.get("/api/pool/history/hashrate", params={"range": "2h"}) as response:
                assert response.status == 400
                payload = await response.json()
                assert payload["error"]["code"] == "invalid_query"

            async with client.get("/api/pool/blocks") as response:
                payload = await response.json()
                assert payload["data"]["count"] == 1
                assert payload["data"]["blocks"][0]["status"] == "immature"
                assert payload["data"]["blocks"][0]["miner"] == "alice"

            async with client.get("/api/pool/blocks", params={"status": "mature"}) as response:
                payload = await response.json()
                assert payload["data"]["count"] == 0

            async with client.get("/api/pool/blocks", params={"status": "sidechain"}) as response:
                assert response.status == 400
                payload = await response.json()
                assert payload["error"]["code"] == "invalid_query"

            async with client.get("/api/pool/blocks/recent", params={"limit": 1}) as response:
                payload = await response.json()
                assert payload["data"]["count"] == 1
                assert payload["data"]["limit"] == 1

            async with client.get("/api/pool/shares/recent") as response:
                payload = await response.json()
                assert payload["data"]["count"] == 3
                assert payload["data"]["shares"][0]["miner"] == "alice"

            async with client.get("/api/pool/fee-ledger") as response:
                payload = await response.json()
                assert payload["data"]["count"] == 1
                assert payload["data"]["fee_ledger"][0]["fee_satoshi"] == 100_000_000
                assert payload["data"]["fee_ledger"][0]["status"] == "pending"

            # A block closes the round in which it was found. A new stratum job
            # then opens the next round; verify the endpoint reports that live
            # round rather than the completed one.
            accounting = Accounting(db)
            accounting.start_round("round-2", 501)
            accounting.record_share(
                "bob.rig1", "job-2", "aabbccdd", "01020304", "00000009", 4.0, True,
                round_id="round-2",
            )
            async with client.get("/api/pool/rounds/current") as response:
                payload = await response.json()
                assert payload["data"]["round"]["round_id"] == "round-2"
                assert payload["data"]["round"]["total_shares"] == 1
                assert payload["data"]["round"]["total_difficulty"] == 4.0

    asyncio.run(run())


def test_public_config_does_not_advertise_unconfigured_endpoint_or_secrets(tmp_path, monkeypatch):
    async def run():
        _db, _config, app = make_app(tmp_path)
        async with api_client(app) as client:
            for endpoint in ("/api/pool/config", "/api/pool/status"):
                async with client.get(endpoint) as response:
                    assert response.status == 200
                    text = await response.text()
                    payload = await response.json()
                config = payload["data"] if endpoint.endswith("config") else payload["data"]["config"]
                assert config["stratum"]["configured"] is False
                assert config["stratum"]["endpoint"] is None
                assert config["auto_payouts"] is False
                assert config["payouts_enabled"] is False
                assert "stratum.silver-pool.example" not in text
                assert "rpc_password" not in text
                assert "stratum_password" not in text

            async with client.get("/api/docs") as response:
                payload = await response.json()
                assert payload["data"]["authentication"] == "none"
                paths = {item["path"] for item in payload["data"]["endpoints"]}
                assert "/api/health" in paths
                assert "/api/pool/miner/{username}" in paths

            async with client.get("/api/openapi.json") as response:
                assert response.status == 200
                assert response.content_type == "application/json"
                document = await response.json()
                assert document["openapi"] == "3.0.3"
                assert "/api/pool/status" in document["paths"]
                assert "ok" not in document

    asyncio.run(run())


def test_cors_preflight_allowed_and_disallowed_origins(tmp_path):
    async def run():
        _db, _config, app = make_app(tmp_path)
        async with api_client(app) as client:
            async with client.get(
                "/api/health", headers={"Origin": "http://127.0.0.1:4173"}
            ) as response:
                assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:4173"
                assert response.headers["Vary"] == "Origin"

            async with client.get(
                "/api/health", headers={"Origin": "https://evil.example"}
            ) as response:
                assert "Access-Control-Allow-Origin" not in response.headers

            async with client.options(
                "/api/pool/status",
                headers={
                    "Origin": "http://127.0.0.1:4173",
                    "Access-Control-Request-Method": "GET",
                },
            ) as response:
                assert response.status == 204
                assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:4173"
                assert "GET" in response.headers["Access-Control-Allow-Methods"]
                assert response.headers["Access-Control-Max-Age"] == "600"

    asyncio.run(run())


def test_rate_limit_returns_retry_after(tmp_path):
    async def run():
        _db, _config, app = make_app(tmp_path, rate_limit=2)
        async with api_client(app) as client:
            for _ in range(2):
                async with client.get("/api/health") as response:
                    assert response.status == 200
            async with client.get("/api/health") as response:
                assert response.status == 429
                assert response.headers["Retry-After"]
                payload = await response.json()
                assert payload["ok"] is False
                assert payload["error"]["code"] == "rate_limited"
                assert payload["error"]["details"]["retry_after_seconds"] >= 1

    asyncio.run(run())


def test_rate_limit_uses_forwarded_ip_only_from_trusted_proxy(tmp_path):
    async def run():
        _db, _config, app = make_app(
            tmp_path, rate_limit=2, trusted_proxies=["127.0.0.1/32"]
        )
        async with api_client(app) as client:
            for _ in range(2):
                async with client.get(
                    "/api/health", headers={"X-Forwarded-For": "203.0.113.10"}
                ) as response:
                    assert response.status == 200
            async with client.get(
                "/api/health", headers={"X-Forwarded-For": "203.0.113.10"}
            ) as response:
                assert response.status == 429

            # A different real client behind the same proxy has its own bucket.
            async with client.get(
                "/api/health", headers={"X-Forwarded-For": "203.0.113.11"}
            ) as response:
                assert response.status == 200

        _db2, _config2, untrusted_app = make_app(
            tmp_path / "untrusted", rate_limit=2, trusted_proxies=[]
        )
        async with api_client(untrusted_app) as client:
            for spoof in ("203.0.113.20", "203.0.113.21", "203.0.113.22"):
                async with client.get(
                    "/api/health", headers={"X-Forwarded-For": spoof}
                ) as response:
                    if spoof == "203.0.113.22":
                        assert response.status == 429
                    else:
                        assert response.status == 200

    asyncio.run(run())


def test_not_found_method_not_allowed_and_internal_error(tmp_path, monkeypatch):
    async def run():
        _db, _config, app = make_app(tmp_path)
        api = app["api"]
        async with api_client(app) as client:
            async with client.get("/api/does-not-exist") as response:
                assert response.status == 404
                payload = await response.json()
                assert payload["ok"] is False
                assert payload["error"]["code"] == "not_found"

            async with client.post("/api/health") as response:
                assert response.status == 405
                assert response.headers["Allow"] == "GET, HEAD"
                payload = await response.json()
                assert payload["error"]["code"] == "method_not_allowed"

            def boom():
                raise RuntimeError("unexpected accounting failure")

            monkeypatch.setattr(api.accounting, "pool_stats", boom)
            async with client.get("/api/pool/statistics") as response:
                assert response.status == 500
                payload = await response.json()
                assert payload["ok"] is False
                assert payload["error"]["code"] == "internal_error"
                assert payload["meta"]["request_id"]

    asyncio.run(run())
