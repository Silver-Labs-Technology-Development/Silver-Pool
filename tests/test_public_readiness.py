"""Tests for the read-only public launch probe (no real network calls)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import public_readiness as probe  # noqa: E402


def health():
    return {
        "ok": True,
        "data": {"service": "silver-pool", "status": "ok", "database": {"healthy": True}},
    }


def ready():
    return {
        "ok": True,
        "data": {
            "ready": True,
            "node": {"connected": True, "synced": True},
            "stratum": {"running": True, "template_fresh": True, "current_job_id": "job"},
        },
    }


def config():
    return {
        "ok": True,
        "data": {
            "network": "main",
            "auto_payouts": False,
            "payouts_enabled": False,
            "stratum": {"configured": True, "host": "pool.example", "port": 3333, "endpoint": "pool.example:3333"},
        },
    }


def test_api_origin_requires_https_and_no_credentials_or_path():
    assert probe.api_origin("https://pool.example/") == "https://pool.example"
    for value in (
        "http://pool.example",
        "https://person:password@pool.example",
        "https://pool.example/subpath",
        "https://pool.example/?token=abc",
        "https://pool.example/#fragment",
    ):
        with pytest.raises(ValueError):
            probe.api_origin(value)


def test_api_payloads_validated():
    probe.validate_health(health())
    probe.validate_ready(ready())
    probe.validate_config(config(), "pool.example", 3333)


def test_health_must_be_real_pool_with_healthy_database():
    payload = health()
    payload["data"]["service"] = "another-service"
    with pytest.raises(ValueError, match="wrong service"):
        probe.validate_health(payload)
    payload = health()
    payload["data"]["database"]["healthy"] = False
    with pytest.raises(ValueError, match="database"):
        probe.validate_health(payload)


@pytest.mark.parametrize(
    "path,value",
    [
        (("data", "ready"), False),
        (("data", "node", "synced"), False),
        (("data", "stratum", "template_fresh"), False),
        (("data", "stratum", "current_job_id"), None),
    ],
)
def test_ready_rejects_partial_readiness(path, value):
    payload = ready()
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(ValueError):
        probe.validate_ready(payload)


def test_config_rejects_wrong_host_port_and_payout_flags():
    for field, value in [
        ("payouts_enabled", True),
        ("auto_payouts", True),
        ("network", "regtest"),
    ]:
        payload = config()
        payload["data"][field] = value
        with pytest.raises(ValueError):
            probe.validate_config(payload, "pool.example", 3333)
    with pytest.raises(ValueError, match="host"):
        probe.validate_config(config(), "other.example", 3333)
    with pytest.raises(ValueError, match="port"):
        probe.validate_config(config(), "pool.example", 4444)


def test_stratum_subscription_validation():
    valid = {"id": 1, "result": [[["mining.notify", "notify"]], "01020304", 4], "error": None}
    probe.validate_subscribe(valid)
    for invalid in (
        {"id": 1, "result": False, "error": None},
        {"id": 1, "result": valid["result"], "error": {"code": 20}},
        {"id": 2, "result": valid["result"], "error": None},
        {"id": 1, "result": [[], "", 4], "error": None},
    ):
        with pytest.raises(ValueError):
            probe.validate_subscribe(invalid)


def test_stratum_probe_never_authorizes_or_submits():
    class Connection:
        def __init__(self):
            self.messages = []
            self.reply = (
                b'{"id":1,"result":[[["mining.notify","notify"]],"1234",4],"error":null}\\n'
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, timeout):
            pass

        def sendall(self, data):
            self.messages.append(data)

        def recv(self, nbytes):
            response, self.reply = self.reply, b""
            return response

    connection = Connection()
    with patch.object(probe.socket, "create_connection", return_value=connection):
        probe.probe_stratum("pool.example", 3333, 1)
    assert len(connection.messages) == 1
    assert b"mining.subscribe" in connection.messages[0]
    assert b"mining.authorize" not in connection.messages[0]
    assert b"mining.submit" not in connection.messages[0]


def test_failure_does_not_report_success():
    result = probe.run_check("test", lambda: probe.validate_ready({"ok": False}))
    assert result.passed is False
