import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from aiohttp import web
from pool_api import get_pool_status, get_miner_status
from btcs_pool.accounting import Accounting, _from_satoshi


POOL_DB = Path(os.getenv('BTCS_POOL_DB', str(Path(__file__).parent / 'data' / 'pool.sqlite3')))


def _unavailable(message: str) -> dict:
    """Return an explicit unavailable/unknown state."""
    return {"available": False, "reason": message, "timestamp": time.time()}


def _ok(data: dict) -> dict:
    data["available"] = True
    data["timestamp"] = time.time()
    return data


async def pool_status(request):
    """GET /api/pool/status - Return pool status"""
    try:
        result = await get_pool_status()
        return web.json_response(_ok(result))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_miner_status(request):
    """GET /api/pool/miner/{username} - Return miner status"""
    username = request.match_info.get('username', '')
    if not username:
        return web.json_response(_unavailable("Miner username required"), status=400)
    try:
        result = await get_miner_status(username)
        if result is None:
            return web.json_response(_unavailable(f"Miner {username} not found"), status=404)
        return web.json_response(_ok(result))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_miner_shares(request):
    """GET /api/pool/miner/{username}/shares - Return share history for a miner"""
    username = request.match_info.get('username', '')
    if not username:
        return web.json_response(_unavailable("Miner username required"), status=400)
    db_path = str(POOL_DB)
    if not Path(db_path).exists():
        return web.json_response(_unavailable("Database not found"), status=503)
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT job_id, nonce, accepted, difficulty, created_at FROM shares WHERE miner=? ORDER BY id DESC LIMIT 50",
                (username,),
            ).fetchall()
            shares = [
                {
                    "job_id": r[0],
                    "nonce": r[1],
                    "accepted": bool(r[2]),
                    "difficulty": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
            return web.json_response(_ok({"miner": username, "shares": shares}))
        finally:
            conn.close()
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_miners_list(request):
    """GET /api/pool/miners - List all registered miners"""
    db_path = str(POOL_DB)
    if not Path(db_path).exists():
        return web.json_response(_unavailable("Database not found"), status=503)
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT username FROM miners ORDER BY created_at").fetchall()
            miners = [r[0] for r in rows]
            return web.json_response(_ok({"miners": miners}))
        finally:
            conn.close()
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_recent_shares(request):
    """GET /api/pool/shares/recent - Return recent shares"""
    try:
        result = await get_pool_status()
        shares = result.get('recent_shares', [])
        return web.json_response(_ok({"shares": shares}))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_recent_blocks(request):
    """GET /api/pool/blocks/recent - Return recent blocks"""
    try:
        result = await get_pool_status()
        blocks = result.get('recent_blocks', [])
        return web.json_response(_ok({"blocks": blocks}))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_fee_ledger(request):
    """GET /api/pool/fee-ledger - Return fee ledger"""
    try:
        result = await get_pool_status()
        ledger = result.get('fee_ledger', [])
        return web.json_response(_ok({"fee_ledger": ledger}))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_statistics(request):
    """GET /api/pool/statistics - Return pool statistics"""
    try:
        result = await get_pool_status()
        stats = {
            "total_miners": result.get('total_miners', 0),
            "total_shares": result.get('total_shares', 0),
            "accepted_shares": result.get('accepted_shares', 0),
            "total_blocks": result.get('total_blocks', 0),
            "mature_blocks": result.get('mature_blocks', 0),
            "immature_blocks": result.get('immature_blocks', 0),
            "database_healthy": result.get('database_healthy', False),
        }
        return web.json_response(_ok(stats))
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def pool_hashrate_history(request):
    """GET /api/pool/history/hashrate?range=24h - Return historical hashrate data"""
    db_path = str(POOL_DB)
    if not Path(db_path).exists():
        return web.json_response(_unavailable("Database not found"), status=503)
    try:
        conn = sqlite3.connect(db_path)
        try:
            cutoff = time.time() - 86400  # 24 hours ago
            rows = conn.execute(
                "SELECT created_at, difficulty, accepted FROM shares WHERE created_at >= ? ORDER BY created_at",
                (cutoff,),
            ).fetchall()
            buckets = {}
            for r in rows:
                hour_bucket = int(r[0] // 3600) * 3600
                accepted = bool(r[2])
                if accepted:
                    buckets[hour_bucket] = buckets.get(hour_bucket, 0) + r[1]
            history = [
                {"timestamp": bucket, "hashrate": shares_diff}
                for bucket, shares_diff in sorted(buckets.items())
            ]
            return web.json_response(_ok({"range": "24h", "history": history}))
        finally:
            conn.close()
    except Exception as e:
        return web.json_response(_unavailable(str(e)), status=503)


async def health_check(request):
    """GET /api/health - Health check endpoint"""
    db_path = str(POOL_DB)
    db_healthy = Path(db_path).exists()
    return web.json_response({
        "status": "ok" if db_healthy else "degraded",
        "service": "silver-pool",
        "database": db_healthy,
    })


async def init_app():
    app = web.Application()
    app.router.add_get('/api/pool/status', pool_status)
    app.router.add_get('/api/pool/miner/{username}', pool_miner_status)
    app.router.add_get('/api/pool/miner/{username}/shares', pool_miner_shares)
    app.router.add_get('/api/pool/miners', pool_miners_list)
    app.router.add_get('/api/pool/shares/recent', pool_recent_shares)
    app.router.add_get('/api/pool/blocks/recent', pool_recent_blocks)
    app.router.add_get('/api/pool/fee-ledger', pool_fee_ledger)
    app.router.add_get('/api/pool/statistics', pool_statistics)
    app.router.add_get('/api/pool/history/hashrate', pool_hashrate_history)
    app.router.add_get('/api/health', health_check)
    return app


if __name__ == '__main__':
    app = asyncio.run(init_app())
    host = os.getenv('BTCS_POOL_API_HOST', '127.0.0.1')
    port = int(os.getenv('BTCS_POOL_API_PORT', '8765'))
    web.run_app(app, host=host, port=port)