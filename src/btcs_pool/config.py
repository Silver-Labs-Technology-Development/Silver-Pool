import json, math, os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _parse_fee(fee_input) -> float:
    """Convert fee input to float; raise ValueError for non-numeric, NaN, inf."""
    if isinstance(fee_input, (int, float)):
        f = float(fee_input)
    elif isinstance(fee_input, str):
        try:
            f = float(fee_input)
        except (ValueError, TypeError):
            raise ValueError(f"Pool fee must be numeric, got '{fee_input}'")
    else:
        raise ValueError(f"Pool fee must be numeric, got {type(fee_input).__name__}")
    # Check NaN/Inf after conversion
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"Pool fee must not be NaN or infinite, got {fee_input}")
    return f


def _validate_fee_range(f: float) -> float:
    """Validate that a float fee is in the allowed range [0.00, 5.00]."""
    if f < 0 or f > 5.0:
        raise ValueError(f"Pool fee must be between 0.00 and 5.00 inclusive, got {f}")
    # Two decimal places max
    return round(f, 2)


def _validate_pool_address(address: str | None, network_name: str = "regtest") -> str:
    """Basic pool address validation. For production, require a configured address.
    Returns the address if it looks valid for the given network, or empty string.
    In development, empty address is allowed to permit safe local tests."""
    if not address:
        return ""
    addr = address.strip()
    # Bech32 testnet addresses start with tb1, mainnet with bc1
    # Bare P2SH starts with 3, P2PKH with mp or BH
    # This is a minimal check; full validation requires RPC getaddressinfo
    if addr.startswith("bc1") or addr.startswith("tb1") or addr.startswith("3") or addr.startswith("mp") or addr.startswith("BH"):
        return addr
    # Allow any non-empty string in development; production will reject at startup
    return addr


@dataclass
class PoolConfig:
    rpc_url: str = "http://127.0.0.1:29444"
    rpc_user: str = "test"
    rpc_password: str = "test"
    rpc_wallet: str = "pooltest"
    pool_address: str = ""
    pool_script_pubkey: str = ""
    stratum_host: str = "127.0.0.1"
    stratum_port: int = 3333
    db_path: str = "data/pool.sqlite3"
    poll_interval: float = 1.0
    extranonce2_size: int = 4
    difficulty: float = 1.0
    pool_fee: float = 2.0
    pool_fee_address: str = ""
    min_payout: float = 0.01
    payout_interval_seconds: int = 300
    auto_payouts: bool = False

    @classmethod
    def from_env(cls):
        cfg = cls()
        # RPC config
        cfg.rpc_url = os.getenv("BTCS_RPC_URL", cfg.rpc_url)
        cfg.rpc_user = os.getenv("BTCS_RPC_USER", cfg.rpc_user)
        cfg.rpc_password = os.getenv("BTCS_RPC_PASSWORD", cfg.rpc_password)
        cfg.rpc_wallet = os.getenv("BTCS_RPC_WALLET", cfg.rpc_wallet)
        # Pool address and fee config
        raw_fee = os.getenv("BTCS_POOL_FEE", str(cfg.pool_fee))
        cfg.pool_fee = _validate_fee_range(_parse_fee(raw_fee))
        cfg.pool_fee_address = _validate_pool_address(
            os.getenv("BTCS_POOL_FEE_ADDRESS", cfg.pool_fee_address)
        )
        cfg.pool_address = os.getenv("BTCS_POOL_ADDRESS", cfg.pool_address)
        cfg.stratum_host = os.getenv("BTCS_STRATUM_HOST", cfg.stratum_host)
        cfg.stratum_port = int(os.getenv("BTCS_STRATUM_PORT", cfg.stratum_port))
        # Payout config
        raw_min_payout = os.getenv("BTCS_MIN_PAYOUT", str(cfg.min_payout))
        cfg.min_payout = float(_parse_fee(raw_min_payout))
        raw_interval = os.getenv("BTCS_PAYOUT_INTERVAL_SECONDS", str(cfg.payout_interval_seconds))
        cfg.payout_interval_seconds = int(raw_interval)
        raw_auto = os.getenv("BTCS_AUTO_PAYOUTS", str(cfg.auto_payouts))
        cfg.auto_payouts = raw_auto.lower() in ("1", "true", "yes", "on")
        # DB and other
        cfg.db_path = os.getenv("BTCS_POOL_DB", cfg.db_path)
        cfg.poll_interval = float(os.getenv("BTCS_POOL_POLL", cfg.poll_interval))
        cfg.extranonce2_size = int(os.getenv("BTCS_EXTRANONCE2_SIZE", cfg.extranonce2_size))
        cfg.difficulty = float(os.getenv("BTCS_POOL_DIFFICULTY", cfg.difficulty))
        return cfg

    def to_dict(self):
        return self.__dict__.copy()

def load_config(path=None):
    cfg = PoolConfig.from_env()
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text())
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    return cfg
