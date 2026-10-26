"""Small compatibility helpers for older scripts.

New code should use :mod:`btcs_pool.accounting` or the HTTP API directly.
"""
from __future__ import annotations

import os
from pathlib import Path

from btcs_pool.accounting import Accounting

POOL_DB = Path(
    os.getenv("BTCS_POOL_DB", str(Path(__file__).parent / "data" / "pool.sqlite3"))
)


def _accounting() -> Accounting:
    return Accounting(str(POOL_DB))


async def get_pool_status() -> dict:
    if not Path(POOL_DB).exists():
        return {"error": "Database not found"}
    accounting = _accounting()
    stats = accounting.pool_stats()
    return {
        **stats,
        "recent_blocks": accounting.recent_blocks(5),
        "recent_shares": accounting.recent_shares(10),
        "fee_ledger": accounting.fee_ledger(5),
        "database_healthy": True,
    }


async def get_miner_status(miner: str):
    if not Path(POOL_DB).exists():
        return None
    accounting = _accounting()
    data = accounting.get_miner(miner)
    if not data:
        return None
    return {
        "miner": data["username"],
        "available_satoshi": data["available_btcs"],
        "immature_satoshi": data["immature_btcs"],
        "total_satoshi": data["total_btcs"],
        "available_satoshis": data["available_satoshi"],
        "immature_satoshis": data["immature_satoshi"],
        "total_satoshis": data["total_satoshi"],
    }


async def register_miner(miner: str):
    return _accounting().register_miner(miner)
