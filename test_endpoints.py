import asyncio
import aiohttp
import json

BASE = "http://localhost:8765/api"

async def test_endpoints():
    async with aiohttp.ClientSession() as session:
        endpoints = [
            "/pool/status",
            "/pool/statistics",
            "/pool/history/hashrate?range=24h",
            "/pool/miners",
            "/pool/miner/testminer",
            "/pool/miner/testminer/shares",
            "/pool/blocks/recent",
            "/health",
        ]
        for ep in endpoints:
            url = BASE + ep
            try:
                async with session.get(url) as resp:
                    text = await resp.text()
                    data = json.loads(text) if text else None
                    print(f"{ep} -> {resp.status}")
                    if resp.status == 200 and data:
                        # Print relevant fields for each endpoint
                        if 'total_miners' in data:
                            print(f"  total_miners: {data['total_miners']}")
                        if 'total_shares' in data:
                            print(f"  total_shares: {data['total_shares']}")
                        if 'accepted_shares' in data:
                            print(f"  accepted_shares: {data['accepted_shares']}")
                        if 'total_blocks' in data:
                            print(f"  total_blocks: {data['total_blocks']}")
                        if 'database_healthy' in data:
                            print(f"  database_healthy: {data['database_healthy']}")
                        if 'miner_statuses' in data:
                            print(f"  miner_statuses keys: {list(data['miner_statuses'].keys())}")
                        if 'recent_blocks' in data:
                            print(f"  recent_blocks: {data['recent_blocks']}")
                        if 'recent_shares' in data:
                            print(f"  recent_shares: {data['recent_shares']}")
                        if 'fee_ledger' in data:
                            print(f"  fee_ledger: {data['fee_ledger']}")
                    if resp.status >= 400:
                        print(f"  Error body: {text[:200]}")
            except Exception as e:
                print(f"{ep} -> ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_endpoints())