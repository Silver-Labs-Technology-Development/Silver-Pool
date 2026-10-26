from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .rpc import BTCSRpc, RPCError


@dataclass
class NodeSnapshot:
    connected: bool
    network: str
    chain: str | None
    blocks: int
    headers: int
    verification_progress: float
    initial_block_download: bool
    connections: int
    difficulty: float | None
    mempool_transactions: int
    warnings: list[str]
    error: str | None
    checked_at: float

    @property
    def synced(self) -> bool:
        return (
            self.connected
            and not self.initial_block_download
            and self.verification_progress >= 0.999
        )

    def to_dict(self) -> dict:
        return {
            "connected": self.connected,
            "network": self.network,
            "chain": self.chain,
            "blocks": self.blocks,
            "headers": self.headers,
            "verification_progress": self.verification_progress,
            "initial_block_download": self.initial_block_download,
            "synced": self.synced,
            "connections": self.connections,
            "difficulty": self.difficulty,
            "mempool_transactions": self.mempool_transactions,
            "warnings": self.warnings,
            "error": self.error,
            "checked_at": self.checked_at,
        }


class NodeMonitor:
    """Caches node health so public API traffic cannot hammer the node RPC."""

    def __init__(self, rpc: BTCSRpc, network: str, cache_seconds: float = 5.0):
        self.rpc = rpc
        self.network = network
        self.cache_seconds = cache_seconds
        self._cached: NodeSnapshot | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> NodeSnapshot:
        checked_at = time.time()
        try:
            chain = self.rpc.getblockchaininfo()
            network = self.rpc.getnetworkinfo()
            mempool = self.rpc.getmempoolinfo()
            warnings = list(chain.get("warnings") or []) + list(
                network.get("warnings") or []
            )
            return NodeSnapshot(
                connected=True,
                network=self.network,
                chain=chain.get("chain"),
                blocks=int(chain.get("blocks", 0)),
                headers=int(chain.get("headers", 0)),
                verification_progress=float(chain.get("verificationprogress", 0)),
                initial_block_download=bool(chain.get("initialblockdownload", True)),
                connections=int(network.get("connections", 0)),
                difficulty=chain.get("difficulty"),
                mempool_transactions=int(mempool.get("size", 0)),
                warnings=warnings,
                error=None,
                checked_at=checked_at,
            )
        except (RPCError, OSError, ValueError) as exc:
            return NodeSnapshot(
                connected=False,
                network=self.network,
                chain=None,
                blocks=0,
                headers=0,
                verification_progress=0,
                initial_block_download=True,
                connections=0,
                difficulty=None,
                mempool_transactions=0,
                warnings=[],
                error=str(exc),
                checked_at=checked_at,
            )

    async def snapshot(self) -> NodeSnapshot:
        if self._cached and time.time() - self._cached.checked_at < self.cache_seconds:
            return self._cached
        async with self._lock:
            if self._cached and time.time() - self._cached.checked_at < self.cache_seconds:
                return self._cached
            self._cached = await asyncio.to_thread(self._load)
            return self._cached

    async def canonical_hash(self, height: int) -> str | None:
        try:
            return await asyncio.to_thread(self.rpc.getblockhash, int(height))
        except RPCError:
            return None
