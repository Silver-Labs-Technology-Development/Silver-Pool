import asyncio
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from aiohttp import web
from pool_api import get_pool_status


POOL_DB = Path(__file__).parent / 'data' / 'pool.sqlite3'


async def pool_status(request):
    """GET /api/pool/status - Return pool status"""
    result = await get_pool_status()
    return web.json_response(result)


async def pool_miner_status(request):
    """GET /api/pool/miner/{username} - Return miner status"""
    username = request.match_info.get('username', '')
    from pool_api import get_miner_status
    result = await get_miner_status(username)
    if result is None:
        return web.json_response({"error": f"Miner {username} not found"}, status=404)
    return web.json_response(result)


async def pool_miners_list(request):
    """GET /api/pool/miners - List all registered miners"""
    import sqlite3
    from decimal import Decimal
    conn = sqlite3.connect(str(POOL_DB))
    try:
        rows = conn.execute("SELECT username FROM miners ORDER BY created_at").fetchall()
        miners = [r[0] for r in rows]
        return web.json_response({"miners": miners})
    finally:
        conn.close()


async def pool_recent_shares(request):
    """GET /api/pool/shares/recent - Return recent shares"""
    from pool_api import get_pool_status
    result = await get_pool_status()
    shares = result.get('recent_shares', [])
    return web.json_response({"shares": shares})


async def pool_recent_blocks(request):
    """GET /api/pool/blocks/recent - Return recent blocks"""
    from pool_api import get_pool_status
    result = await get_pool_status()
    blocks = result.get('recent_blocks', [])
    return web.json_response({"blocks": blocks})


async def pool_fee_ledger(request):
    """GET /api/pool/fee-ledger - Return fee ledger"""
    from pool_api import get_pool_status
    result = await get_pool_status()
    ledger = result.get('fee_ledger', [])
    return web.json_response({"fee_ledger": ledger})


async def pool_statistics(request):
    """GET /api/pool/statistics - Return pool statistics"""
    from pool_api import get_pool_status
    result = await get_pool_status()
    # Extract key stats
    stats = {
        "total_miners": result.get('total_miners', 0),
        "total_shares": result.get('total_shares', 0),
        "accepted_shares": result.get('accepted_shares', 0),
        "total_blocks": result.get('total_blocks', 0),
        "mature_blocks": result.get('mature_blocks', 0),
        "immature_blocks": result.get('immature_blocks', 0),
        "database_healthy": result.get('database_healthy', False),
    }
    return web.json_response(stats)


async def health_check(request):
    """GET /api/health - Health check endpoint"""
    return web.json_response({"status": "ok", "service": "silver-pool"})


async def init_app():
    app = web.Application()
    app.router.add_get('/api/pool/status', pool_status)
    app.router.add_get('/api/pool/miner/{username}', pool_miner_status)
    app.router.add_get('/api/pool/miners', pool_miners_list)
    app.router.add_get('/api/pool/shares/recent', pool_recent_shares)
    app.router.add_get('/api/pool/blocks/recent', pool_recent_blocks)
    app.router.add_get('/api/pool/fee-ledger', pool_fee_ledger)
    app.router.add_get('/api/pool/statistics', pool_statistics)
    app.router.add_get('/api/health', health_check)
    return app


if __name__ == '__main__':
    app = asyncio.run(init_app())
    host = os.getenv('BTCS_POOL_API_HOST', '127.0.0.1')
    port = int(os.getenv('BTCS_POOL_API_PORT', '8765'))
    web.run_app(app, host=host, port=port)