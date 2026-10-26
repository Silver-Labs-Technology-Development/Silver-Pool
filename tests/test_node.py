from __future__ import annotations

import asyncio

import pytest

from btcs_pool.node import NodeMonitor, NodeSnapshot
from btcs_pool.rpc import RPCError


class FakeRpc:
    def __init__(self, chain=None, network=None, mempool=None, error=None):
        self.chain = chain or {
            "chain": "regtest",
            "blocks": 500,
            "headers": 500,
            "verificationprogress": 1.0,
            "initialblockdownload": False,
            "difficulty": 1e-9,
            "warnings": [],
        }
        self.network = network or {"connections": 4, "warnings": []}
        self.mempool = mempool or {"size": 7}
        self.error = error
        self.calls = 0

    def getblockchaininfo(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.chain

    def getnetworkinfo(self):
        if self.error:
            raise self.error
        return self.network

    def getmempoolinfo(self):
        if self.error:
            raise self.error
        return self.mempool

    def getblockhash(self, height):
        if self.error:
            raise self.error
        return "aa" * 32


def test_node_snapshot_success_and_cache():
    async def run():
        rpc = FakeRpc()
        monitor = NodeMonitor(rpc, "regtest", cache_seconds=60)
        first = await monitor.snapshot()
        second = await monitor.snapshot()
        assert first is second
        assert rpc.calls == 1
        assert first.connected is True
        assert first.synced is True
        assert first.blocks == 500
        assert first.mempool_transactions == 7
        assert first.to_dict()["chain"] == "regtest"
        assert await monitor.canonical_hash(10) == "aa" * 32

    asyncio.run(run())


def test_node_initial_block_download_is_not_synced():
    async def run():
        rpc = FakeRpc(
            chain={
                "chain": "regtest",
                "blocks": 10,
                "headers": 100,
                "verificationprogress": 0.1,
                "initialblockdownload": True,
                "difficulty": 1,
                "warnings": [],
            }
        )
        snapshot = await NodeMonitor(rpc, "regtest").snapshot()
        assert snapshot.connected is True
        assert snapshot.synced is False

    asyncio.run(run())


def test_node_rpc_failure_is_reported_not_raised():
    async def run():
        rpc = FakeRpc(error=RPCError("getblockchaininfo", "connection refused"))
        snapshot = await NodeMonitor(rpc, "regtest").snapshot()
        assert snapshot.connected is False
        assert snapshot.synced is False
        assert "connection refused" in snapshot.error
        assert snapshot.to_dict()["error"] == snapshot.error
        assert await monitor_hash(rpc) is None

    async def monitor_hash(rpc):
        return await NodeMonitor(rpc, "regtest").canonical_hash(1)

    asyncio.run(run())


def test_node_monitor_does_not_cache_beyond_ttl():
    async def run():
        rpc = FakeRpc()
        monitor = NodeMonitor(rpc, "regtest", cache_seconds=0)
        await monitor.snapshot()
        await monitor.snapshot()
        assert rpc.calls == 2

    asyncio.run(run())


def test_snapshot_dataclass():
    snapshot = NodeSnapshot(
        connected=True,
        network="regtest",
        chain="regtest",
        blocks=1,
        headers=1,
        verification_progress=1.0,
        initial_block_download=False,
        connections=0,
        difficulty=1.0,
        mempool_transactions=0,
        warnings=[],
        error=None,
        checked_at=1.0,
    )
    assert snapshot.synced is True
    assert snapshot.to_dict()["synced"] is True
