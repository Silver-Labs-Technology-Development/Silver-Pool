import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, 'src')
from btcs_pool.accounting import Accounting, _from_satoshi, _to_satoshi

POOL_DB = Path('data/pool.sqlite3')

async def get_pool_status():
    """Get overall pool status from the accounting database."""
    db_path = str(POOL_DB)
    if not Path(db_path).exists():
        return {"error": "Database not found"}
    
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    
    try:
        # Total miners
        total_miners = conn.execute("SELECT COUNT(*) FROM miners").fetchone()[0]
        
        # Total shares
        total_shares = conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0]
        
        # Accepted shares
        accepted_shares = conn.execute("SELECT COUNT(*) FROM shares WHERE accepted=1").fetchone()[0]
        
        # Total blocks
        total_blocks = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        
        # Mature blocks
        mature_blocks = conn.execute("SELECT COUNT(*) FROM blocks WHERE status='mature'").fetchone()[0]
        
        # Immature blocks
        immature_blocks = conn.execute("SELECT COUNT(*) FROM blocks WHERE status='immature'").fetchone()[0]
        
        # Recent blocks (last 5, ordered by height desc)
        recent_blocks = conn.execute(
            "SELECT height, hash, coinbase_value, fee_amount, net_reward, status, miner FROM blocks ORDER BY height DESC LIMIT 5"
        ).fetchall()
        
        # Recent shares (last 10)
        recent_shares = conn.execute(
            "SELECT miner, job_id, nonce, accepted, difficulty, created_at FROM shares ORDER BY id DESC LIMIT 10"
        ).fetchall()
        
        # Miner status for top miners
        miners_rows = conn.execute("SELECT username FROM miners ORDER BY created_at LIMIT 10").fetchall()
        miners = [r[0] for r in miners_rows]
        
        # Get balances for miners
        miner_statuses = {}
        for miner in miners:
            row = conn.execute("SELECT balance_satoshi, immature_satoshi FROM miner_balances WHERE miner=?", (miner,)).fetchone()
            if row:
                balance_satoshi, immature_satoshi = row
                miner_statuses[miner] = {
                    "available_satoshi": str(_from_satoshi(balance_satoshi)),
                    "immature_satoshi": str(_from_satoshi(immature_satoshi)),
                    "total_satoshi": str(_from_satoshi(balance_satoshi + immature_satoshi)),
                }
        
        # Pool fee ledger
        fee_ledger_rows = conn.execute("SELECT block_height, fee_satoshi, allocated_to_address, status, created_at FROM pool_fee_ledger ORDER BY created_at DESC LIMIT 5").fetchall()
        fee_ledger = []
        for row in fee_ledger_rows:
            fee_ledger.append({
                "block_height": row[0],
                "fee_satoshi": row[1],
                "allocated_to_address": row[2],
                "status": row[3],
                "created_at": row[4],
            })
        
        return {
            "total_miners": total_miners,
            "total_shares": total_shares,
            "accepted_shares": accepted_shares,
            "total_blocks": total_blocks,
            "mature_blocks": mature_blocks,
            "immature_blocks": immature_blocks,
            "recent_blocks": [
                {
                    "height": b[0],
                    "hash": b[1],
                    "coinbase_value": b[2],
                    "fee_amount": b[3],
                    "net_reward": b[4],
                    "status": b[5],
                    "miner": b[6],
                } for b in recent_blocks
            ],
            "recent_shares": [
                {
                    "miner": s[0],
                    "job_id": s[1],
                    "nonce": s[2],
                    "accepted": s[3],
                    "difficulty": s[4],
                    "created_at": s[5],
                } for s in recent_shares
            ],
            "miner_statuses": miner_statuses,
            "fee_ledger": fee_ledger,
            "database_healthy": True,
        }
    finally:
        conn.close()

async def get_miner_status(miner: str):
    """Get status for a specific miner."""
    accounting = Accounting(str(POOL_DB))
    status = accounting.get_miner_status(miner)
    accounting.close()
    if status:
        return status
    # Return basic info if miner not in accounting DB
    conn = sqlite3.connect(str(POOL_DB))
    row = conn.execute("SELECT COUNT(*) FROM miners WHERE username=?", (miner,)).fetchone()[0]
    conn.close()
    if row:
        return {"miner": miner, "available_satoshi": "0", "immature_satoshi": "0", "total_satoshi": "0"}
    return None

async def register_miner(miner: str):
    """Register a new miner."""
    accounting = Accounting(str(POOL_DB))
    result = accounting.register_miner(miner)
    accounting.close()
    return result