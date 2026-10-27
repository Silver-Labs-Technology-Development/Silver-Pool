from __future__ import annotations

import pytest

from btcs_pool.config import PoolConfig, load_config


def test_defaults_are_loopback_and_payouts_disabled():
    config = PoolConfig()
    assert config.network == "regtest"
    assert config.stratum_host == "127.0.0.1"
    assert config.api_host == "127.0.0.1"
    assert config.auto_payouts is False
    assert config.maturity_confirmations == 200
    public = config.to_public_dict()
    assert public["auto_payouts"] is False
    assert public["stratum"]["configured"] is False
    assert public["stratum"]["endpoint"] is None


def test_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("BTCS_NETWORK", "main")
    monkeypatch.setenv("BTCS_RPC_URL", "http://10.0.0.2:10567/")
    monkeypatch.setenv("BTCS_RPC_USER", "rpcuser")
    monkeypatch.setenv("BTCS_RPC_PASSWORD", "rpcpass")
    monkeypatch.setenv("BTCS_RPC_WALLET", "poolwallet")
    monkeypatch.setenv("BTCS_POOL_FEE", "1.25")
    monkeypatch.setenv("BTCS_AUTO_PAYOUTS", "true")
    monkeypatch.setenv("BTCS_PUBLIC_STRATUM_HOST", "pool.example.net")
    monkeypatch.setenv("BTCS_PUBLIC_STRATUM_PORT", "3456")
    monkeypatch.setenv("BTCS_STRATUM_PASSWORD", "secret")
    monkeypatch.setenv("BTCS_POOL_DB", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("BTCS_API_CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("BTCS_TRUSTED_PROXIES", "172.16.0.0/12, 10.0.0.0/8")
    monkeypatch.setenv("BTCS_POOL_DIFFICULTY", "0.25")
    monkeypatch.setenv("BTCS_EXTRANONCE2_SIZE", "8")

    config = PoolConfig.from_env()
    assert config.network == "main"
    assert config.rpc_url == "http://10.0.0.2:10567"
    assert config.rpc_user == "rpcuser"
    assert config.rpc_password == "rpcpass"
    assert config.rpc_wallet == "poolwallet"
    assert config.pool_fee == 1.25
    assert config.auto_payouts is True
    assert config.public_stratum_host == "pool.example.net"
    assert config.public_stratum["endpoint"] == "pool.example.net:3456"
    assert config.public_stratum["url"] == "stratum+tcp://pool.example.net:3456"
    assert config.public_stratum["password_required"] is True
    assert config.api_cors_origins == ["https://a.example", "https://b.example"]
    assert config.trusted_proxies == ["172.16.0.0/12", "10.0.0.0/8"]
    assert config.difficulty == 0.25
    assert config.extranonce2_size == 8
    assert config.db_path.endswith("db.sqlite3")


def test_ipv6_public_endpoint_is_bracketed(monkeypatch):
    monkeypatch.setenv("BTCS_PUBLIC_STRATUM_HOST", "2605:8d80:5b40:6451:a18d:8adc:7cd1:87c0")
    monkeypatch.setenv("BTCS_PUBLIC_STRATUM_PORT", "3333")
    config = PoolConfig.from_env()
    public = config.public_stratum
    assert public["host"] == "2605:8d80:5b40:6451:a18d:8adc:7cd1:87c0"
    assert public["endpoint"] == "[2605:8d80:5b40:6451:a18d:8adc:7cd1:87c0]:3333"
    assert public["url"] == "stratum+tcp://[2605:8d80:5b40:6451:a18d:8adc:7cd1:87c0]:3333"

    monkeypatch.setenv("BTCS_PUBLIC_STRATUM_HOST", "[2605:8d80:5b40:6451:a18d:8adc:7cd1:87c0]")
    config = PoolConfig.from_env()
    assert config.public_stratum["endpoint"].count("[") == 1
    assert config.public_stratum["endpoint"].endswith("]:3333")


def test_default_ports_follow_network(monkeypatch):
    monkeypatch.setenv("BTCS_NETWORK", "main")
    assert PoolConfig.from_env().rpc_url == "http://127.0.0.1:10567"
    monkeypatch.setenv("BTCS_NETWORK", "regtest")
    assert PoolConfig.from_env().rpc_url == "http://127.0.0.1:18443"


@pytest.mark.parametrize(
    ("name", "value", "match"),
    [
        ("BTCS_NETWORK", "moon", "BTCS_NETWORK"),
        ("BTCS_POOL_FEE", "10", "between 0 and 5"),
        ("BTCS_POOL_FEE", "nan", "must be finite"),
        ("BTCS_MIN_PAYOUT", "0", "must be positive"),
        ("BTCS_POOL_DIFFICULTY", "0", "must be positive"),
        ("BTCS_EXTRANONCE2_SIZE", "0", "between 1 and 32"),
        ("BTCS_POOL_POLL", "0.1", "at least 1"),
    ],
)
def test_invalid_environment_fails(monkeypatch, name, value, match):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=match):
        PoolConfig.from_env()


def test_public_dict_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("BTCS_RPC_PASSWORD", "super-secret")
    monkeypatch.setenv("BTCS_STRATUM_PASSWORD", "pool-secret")
    config = PoolConfig.from_env()
    public = config.to_public_dict()
    assert "super-secret" not in repr(public)
    assert "pool-secret" not in repr(public)
    assert "rpc_password" not in config.to_dict()
    assert "stratum_password" not in config.to_dict()


def test_load_json_config_file(monkeypatch, tmp_path):
    import json

    monkeypatch.delenv("BTCS_POOL_FEE", raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"pool_fee": 3.5, "min_payout": 1}), encoding="utf-8")
    config = load_config(str(path))
    assert config.pool_fee == 3.5
    assert config.min_payout == 1.0
