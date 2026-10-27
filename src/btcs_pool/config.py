from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

NETWORKS = {"main", "test", "testnet4", "signet", "regtest"}
DEFAULT_RPC_PORTS = {
    "main": 10567,
    "test": 18332,
    "testnet4": 48332,
    "signet": 38332,
    "regtest": 18443,
}
DEFAULT_P2P_PORTS = {
    "main": 10566,
    "test": 18333,
    "testnet4": 48333,
    "signet": 38333,
    "regtest": 18444,
}


def _parse_float(value, name: str, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if math.isnan(parsed) or math.isinf(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _parse_int(value, name: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _validate_fee(value: float) -> float:
    if value < 0 or value > 5:
        raise ValueError("BTCS_POOL_FEE must be between 0 and 5 percent")
    return round(value, 2)


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _strip_ipv6_brackets(host: str) -> str:
    value = (host or "").strip()
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    return value


def _format_host_port(host: str, port: int) -> str:
    """Format a host and port for URLs and operator documentation.

    Raw IPv6 literals need brackets in URLs. Accept either ``2001:db8::1`` or
    ``[2001:db8::1]`` so an operator cannot accidentally double-bracket a
    configured public host.
    """
    value = _strip_ipv6_brackets(host)
    if ":" in value:
        return f"[{value}]:{port}"
    return f"{value}:{port}"


@dataclass
class PoolConfig:
    network: str = "regtest"
    rpc_url: str = ""
    rpc_user: str = "test"
    rpc_password: str = "test"
    rpc_wallet: str = "pool"
    rpc_timeout_seconds: float = 30.0

    pool_address: str = ""
    pool_script_pubkey: str = ""
    pool_fee: float = 2.0
    pool_fee_address: str = ""
    min_payout: float = 0.01
    payout_interval_seconds: int = 300
    auto_payouts: bool = False
    maturity_confirmations: int = 200

    stratum_host: str = "127.0.0.1"
    stratum_port: int = 3333
    public_stratum_host: str = ""
    public_stratum_port: int = 3333
    stratum_password: str = ""
    difficulty: float = 1.0
    extranonce2_size: int = 4
    poll_interval: float = 5.0
    max_clients: int = 500
    max_line_bytes: int = 8192
    client_timeout_seconds: float = 900.0
    job_history: int = 10

    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        ]
    )
    api_rate_limit_per_minute: int = 240
    trusted_proxies: list[str] = field(default_factory=list)

    db_path: str = "data/pool.sqlite3"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "PoolConfig":
        cfg = cls()
        cfg.network = os.getenv("BTCS_NETWORK", cfg.network).strip().lower()
        if cfg.network not in NETWORKS:
            raise ValueError(f"BTCS_NETWORK must be one of {sorted(NETWORKS)}")

        default_port = DEFAULT_RPC_PORTS[cfg.network]
        cfg.rpc_url = os.getenv(
            "BTCS_RPC_URL", f"http://127.0.0.1:{default_port}"
        ).rstrip("/")
        cfg.rpc_user = os.getenv("BTCS_RPC_USER", cfg.rpc_user)
        cfg.rpc_password = os.getenv("BTCS_RPC_PASSWORD", cfg.rpc_password)
        cfg.rpc_wallet = os.getenv("BTCS_RPC_WALLET", cfg.rpc_wallet)
        cfg.rpc_timeout_seconds = _parse_float(
            os.getenv("BTCS_RPC_TIMEOUT_SECONDS", cfg.rpc_timeout_seconds),
            "BTCS_RPC_TIMEOUT_SECONDS",
            cfg.rpc_timeout_seconds,
        )

        cfg.pool_address = os.getenv("BTCS_POOL_ADDRESS", cfg.pool_address).strip()
        cfg.pool_script_pubkey = os.getenv(
            "BTCS_POOL_SCRIPT_PUBKEY", cfg.pool_script_pubkey
        ).strip()
        cfg.pool_fee = _validate_fee(
            _parse_float(os.getenv("BTCS_POOL_FEE", cfg.pool_fee), "BTCS_POOL_FEE", cfg.pool_fee)
        )
        cfg.pool_fee_address = os.getenv(
            "BTCS_POOL_FEE_ADDRESS", cfg.pool_fee_address
        ).strip()
        cfg.min_payout = _parse_float(
            os.getenv("BTCS_MIN_PAYOUT", cfg.min_payout),
            "BTCS_MIN_PAYOUT",
            cfg.min_payout,
        )
        if cfg.min_payout <= 0:
            raise ValueError("BTCS_MIN_PAYOUT must be positive")
        cfg.payout_interval_seconds = _parse_int(
            os.getenv("BTCS_PAYOUT_INTERVAL_SECONDS", cfg.payout_interval_seconds),
            "BTCS_PAYOUT_INTERVAL_SECONDS",
            cfg.payout_interval_seconds,
        )
        cfg.auto_payouts = os.getenv("BTCS_AUTO_PAYOUTS", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        cfg.maturity_confirmations = _parse_int(
            os.getenv("BTCS_MATURITY_CONFIRMATIONS", cfg.maturity_confirmations),
            "BTCS_MATURITY_CONFIRMATIONS",
            cfg.maturity_confirmations,
        )

        cfg.stratum_host = os.getenv("BTCS_STRATUM_HOST", cfg.stratum_host)
        cfg.stratum_port = _parse_int(
            os.getenv("BTCS_STRATUM_PORT", cfg.stratum_port),
            "BTCS_STRATUM_PORT",
            cfg.stratum_port,
        )
        cfg.public_stratum_host = os.getenv(
            "BTCS_PUBLIC_STRATUM_HOST", cfg.public_stratum_host
        ).strip()
        cfg.public_stratum_port = _parse_int(
            os.getenv("BTCS_PUBLIC_STRATUM_PORT", cfg.public_stratum_port),
            "BTCS_PUBLIC_STRATUM_PORT",
            cfg.public_stratum_port,
        )
        cfg.stratum_password = os.getenv("BTCS_STRATUM_PASSWORD", cfg.stratum_password)
        cfg.difficulty = _parse_float(
            os.getenv("BTCS_POOL_DIFFICULTY", cfg.difficulty),
            "BTCS_POOL_DIFFICULTY",
            cfg.difficulty,
        )
        if cfg.difficulty <= 0:
            raise ValueError("BTCS_POOL_DIFFICULTY must be positive")
        cfg.extranonce2_size = _parse_int(
            os.getenv("BTCS_EXTRANONCE2_SIZE", cfg.extranonce2_size),
            "BTCS_EXTRANONCE2_SIZE",
            cfg.extranonce2_size,
        )
        if not 1 <= cfg.extranonce2_size <= 32:
            raise ValueError("BTCS_EXTRANONCE2_SIZE must be between 1 and 32")
        cfg.poll_interval = _parse_float(
            os.getenv("BTCS_POOL_POLL", cfg.poll_interval),
            "BTCS_POOL_POLL",
            cfg.poll_interval,
        )
        if cfg.poll_interval < 1:
            raise ValueError("BTCS_POOL_POLL must be at least 1 second")
        cfg.max_clients = _parse_int(
            os.getenv("BTCS_MAX_CLIENTS", cfg.max_clients),
            "BTCS_MAX_CLIENTS",
            cfg.max_clients,
        )
        cfg.max_line_bytes = _parse_int(
            os.getenv("BTCS_MAX_LINE_BYTES", cfg.max_line_bytes),
            "BTCS_MAX_LINE_BYTES",
            cfg.max_line_bytes,
        )
        cfg.client_timeout_seconds = _parse_float(
            os.getenv("BTCS_CLIENT_TIMEOUT_SECONDS", cfg.client_timeout_seconds),
            "BTCS_CLIENT_TIMEOUT_SECONDS",
            cfg.client_timeout_seconds,
        )
        cfg.job_history = _parse_int(
            os.getenv("BTCS_JOB_HISTORY", cfg.job_history),
            "BTCS_JOB_HISTORY",
            cfg.job_history,
        )

        cfg.api_host = os.getenv("BTCS_POOL_API_HOST", cfg.api_host)
        cfg.api_port = _parse_int(
            os.getenv("BTCS_POOL_API_PORT", cfg.api_port),
            "BTCS_POOL_API_PORT",
            cfg.api_port,
        )
        cfg.api_cors_origins = _split_csv(
            os.getenv("BTCS_API_CORS_ORIGINS", ",".join(cfg.api_cors_origins))
        )
        cfg.api_rate_limit_per_minute = _parse_int(
            os.getenv(
                "BTCS_API_RATE_LIMIT_PER_MINUTE", cfg.api_rate_limit_per_minute
            ),
            "BTCS_API_RATE_LIMIT_PER_MINUTE",
            cfg.api_rate_limit_per_minute,
        )
        cfg.trusted_proxies = _split_csv(
            os.getenv("BTCS_TRUSTED_PROXIES", ",".join(cfg.trusted_proxies))
        )

        cfg.db_path = os.getenv("BTCS_POOL_DB", cfg.db_path)
        cfg.log_level = os.getenv("BTCS_LOG_LEVEL", cfg.log_level).upper()
        return cfg

    @property
    def public_stratum(self) -> dict:
        host = _strip_ipv6_brackets(self.public_stratum_host)
        configured = bool(host)
        endpoint = _format_host_port(host, self.public_stratum_port) if configured else None
        return {
            "configured": configured,
            "host": host or None,
            "port": self.public_stratum_port,
            "endpoint": endpoint,
            "url": f"stratum+tcp://{endpoint}" if endpoint else None,
            "password_required": bool(self.stratum_password),
        }

    def to_public_dict(self) -> dict:
        return {
            "network": self.network,
            "algorithm": "SHA256d",
            "reward_method": "PPLNS",
            "fee_percent": self.pool_fee,
            "min_payout_btcs": self.min_payout,
            "payout_interval_seconds": self.payout_interval_seconds,
            "auto_payouts": self.auto_payouts,
            "maturity_confirmations": self.maturity_confirmations,
            "stratum": self.public_stratum,
        }

    def to_dict(self) -> dict:
        return {
            key: value
            for key, value in self.__dict__.items()
            if key not in {"rpc_password", "stratum_password"}
        }


def load_config(path: str | None = None) -> PoolConfig:
    cfg = PoolConfig.from_env()
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg
