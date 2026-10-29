"""Public status responses must not serialize private failure diagnostics."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from btcs_pool.api import create_app
from btcs_pool.db import Database
from btcs_pool.node import NodeMonitor
from btcs_pool.rpc import RPCError


PRIVATE_DETAIL = (
    "rpc-password-SENTINEL at http://10.77.1.4:10567 "
    "/srv/private/wallet.dat"
)


class BrokenRpc:
    def __init__(self, error):
        self.error = error

    def getblockchaininfo(self):
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        RPCError("getblockchaininfo", PRIVATE_DETAIL),
        OSError(PRIVATE_DETAIL),
        ValueError(PRIVATE_DETAIL),
    ],
)
def test_node_serialization_keeps_private_error_in_local_diagnostics(error, caplog):
    async def run():
        monitor = NodeMonitor(BrokenRpc(error), "regtest")
        snapshot = await monitor.snapshot()
        public = snapshot.to_dict()
        assert public["connected"] is False
        assert public["error"] == "Node RPC unavailable"
        assert PRIVATE_DETAIL not in json.dumps(public)
        assert "rpc-password-SENTINEL" not in json.dumps(public)
        assert PRIVATE_DETAIL in snapshot.error

    caplog.set_level(logging.WARNING, logger="btcs_pool.node")
    asyncio.run(run())
    assert PRIVATE_DETAIL in caplog.text


def test_public_health_readiness_and_status_hide_dependency_exceptions(
    config, monkeypatch, caplog
):
    async def run():
        db = Database(config.db_path)
        original_fetchone = db.fetchone

        def broken_health(sql, *args, **kwargs):
            if sql == "SELECT 1 AS ok":
                raise OSError(PRIVATE_DETAIL)
            return original_fetchone(sql, *args, **kwargs)

        monkeypatch.setattr(db, "fetchone", broken_health)
        monitor = NodeMonitor(
            BrokenRpc(RPCError("getblockchaininfo", PRIVATE_DETAIL)), "regtest"
        )
        stratum = {
            "listening": True,
            "last_template_at": time.time(),
            "current_job_id": None,
            "last_template_error": PRIVATE_DETAIL,
        }
        app = create_app(db, config, monitor, lambda: stratum)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for endpoint, expected_status in (
                ("/api/health", 200),
                ("/api/ready", 503),
                ("/api/status", 200),
                ("/api/pool/status", 200),
            ):
                async with client.get(endpoint) as response:
                    assert response.status == expected_status
                    body = await response.text()
                    payload = json.loads(body)
                for private in (
                    "rpc-password-SENTINEL", "10.77.1.4", "/srv/private", "wallet.dat"
                ):
                    assert private not in body, endpoint
                if endpoint == "/api/health":
                    assert payload["data"]["database"] == {
                        "healthy": False, "error": "Database unavailable"
                    }
                elif endpoint == "/api/ready":
                    checks = payload["error"]["details"]
                    assert checks["database"]["error"] == "Database unavailable"
                    assert checks["node"]["error"] == "Node RPC unavailable"
                    assert checks["stratum"]["last_template_error"] == (
                        "Node template unavailable"
                    )
                else:
                    assert payload["data"]["node"]["error"] == "Node RPC unavailable"
                    assert payload["data"]["stratum"]["last_template_error"] == (
                        "Node template unavailable"
                    )
            # Sanitizing a response must not overwrite the service's private
            # diagnostics, which remain available to local operator tools.
            assert stratum["last_template_error"] == PRIVATE_DETAIL
        finally:
            await client.close()

    caplog.set_level(logging.WARNING)
    asyncio.run(run())
    assert "database_health_failed" in caplog.text
    assert "node_rpc_unavailable" in caplog.text
    assert PRIVATE_DETAIL in caplog.text


def test_unhandled_public_api_error_remains_generic(config, monkeypatch, caplog):
    async def run():
        db = Database(config.db_path)
        monitor = NodeMonitor(BrokenRpc(OSError(PRIVATE_DETAIL)), "regtest")
        app = create_app(db, config, monitor)

        def broken_stats():
            raise RuntimeError(PRIVATE_DETAIL)

        monkeypatch.setattr(app["api"].accounting, "pool_stats", broken_stats)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            async with client.get("/api/pool/statistics") as response:
                assert response.status == 500
                body = await response.text()
                payload = json.loads(body)
            assert payload["error"] == {
                "code": "internal_error", "message": "internal server error"
            }
            assert PRIVATE_DETAIL not in body
            assert "rpc-password-SENTINEL" not in body
        finally:
            await client.close()

    caplog.set_level(logging.ERROR, logger="btcs_pool.api")
    asyncio.run(run())
    assert PRIVATE_DETAIL in caplog.text
