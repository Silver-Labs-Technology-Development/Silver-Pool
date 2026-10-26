from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "pool.sqlite3")


@pytest.fixture()
def accounting(db_path: str):
    from btcs_pool.accounting import Accounting

    instance = Accounting(db_path)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture()
def config(db_path: str):
    from btcs_pool.config import PoolConfig

    return PoolConfig(
        network="regtest",
        rpc_url="http://127.0.0.1:1",
        rpc_user="test",
        rpc_password="test",
        rpc_wallet="",
        pool_script_pubkey="0014" + "11" * 20,
        db_path=db_path,
        difficulty=1.0,
        extranonce2_size=4,
        api_rate_limit_per_minute=0,
        api_cors_origins=["http://127.0.0.1:4173"],
    )
