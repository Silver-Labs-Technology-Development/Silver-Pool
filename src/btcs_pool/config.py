import json, os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    @classmethod
    def from_env(cls):
        cfg = cls()
        cfg.rpc_url = os.getenv("BTCS_RPC_URL", cfg.rpc_url)
        cfg.rpc_user = os.getenv("BTCS_RPC_USER", cfg.rpc_user)
        cfg.rpc_password = os.getenv("BTCS_RPC_PASSWORD", cfg.rpc_password)
        cfg.rpc_wallet = os.getenv("BTCS_RPC_WALLET", cfg.rpc_wallet)
        cfg.pool_address = os.getenv("BTCS_POOL_ADDRESS", cfg.pool_address)
        cfg.stratum_host = os.getenv("BTCS_STRATUM_HOST", cfg.stratum_host)
        cfg.stratum_port = int(os.getenv("BTCS_STRATUM_PORT", cfg.stratum_port))
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
