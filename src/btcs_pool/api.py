"""HTTP API for Silver Pool.

All JSON endpoints return a consistent envelope::

    {"ok": true, "data": {...}, "meta": {"timestamp": ..., "request_id": ...}}

Errors use ``{"ok": false, "error": {"code", "message", "details"}, "meta": ...}``.
The OpenAPI document itself is served as raw OpenAPI JSON, which is the one
documented exception required by tooling.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import secrets
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiohttp import web

from . import __version__
from .accounting import Accounting, HASHRATE_RANGES, parse_identity
from .config import PoolConfig
from .db import Database
from .node import NodeMonitor

log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.:@+\-]{1,160}$")
BLOCK_STATUSES = {"immature", "mature", "orphaned"}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def _meta(request: web.Request) -> dict:
    return {
        "timestamp": time.time(),
        "request_id": request.get("request_id", ""),
    }


def _ok(request: web.Request, data: Any, status: int = 200, headers=None) -> web.Response:
    return web.json_response(
        {"ok": True, "data": data, "meta": _meta(request)},
        status=status,
        headers=headers,
    )


def _error(
    request: web.Request,
    status: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers=None,
) -> web.Response:
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message},
        "meta": _meta(request),
    }
    if details is not None:
        payload["error"]["details"] = details
    return web.json_response(payload, status=status, headers=headers)


def _query_int(
    request: web.Request,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_query", f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def _query_choice(
    request: web.Request, name: str, choices: set[str], default: str
) -> str:
    value = request.query.get(name, default)
    if value not in choices:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be one of {', '.join(sorted(choices))}",
        )
    return value


def _username(raw: str) -> str:
    value = raw or ""
    if not USERNAME_RE.fullmatch(value):
        raise ApiError(400, "invalid_username", "invalid miner username")
    try:
        parse_identity(value)
    except ValueError as exc:
        raise ApiError(400, "invalid_username", str(exc)) from exc
    return value


def _public_config(config: PoolConfig) -> dict:
    stratum = config.public_stratum
    return {
        "network": config.network,
        "algorithm": "SHA256d",
        "reward_method": "PPLNS",
        "fee_percent": config.pool_fee,
        "min_payout_btcs": config.min_payout,
        "payout_interval_seconds": config.payout_interval_seconds,
        "auto_payouts": False,
        "payouts_enabled": False,
        "payouts_note": (
            "Payouts are disabled until reward accounting, signing boundaries, "
            "confirmation handling, recovery and payment tests are complete."
        ),
        "maturity_confirmations": config.maturity_confirmations,
        "stratum": {
            **stratum,
            "difficulty": config.difficulty,
            "extranonce2_size": config.extranonce2_size,
        },
        "api": {
            "version": __version__,
            "rate_limit_per_minute": config.api_rate_limit_per_minute,
        },
    }


def _db_healthy(db: Database) -> tuple[bool, str | None]:
    try:
        db.fetchone("SELECT 1 AS ok")
        return True, None
    except Exception as exc:  # noqa: BLE001
        log.warning("database_health_failed error=%s", exc)
        return False, "Database unavailable"


class Api:
    def __init__(
        self,
        db: Database,
        config: PoolConfig,
        node_monitor: NodeMonitor,
        stratum_status: Callable[[], dict] | None = None,
    ):
        self.db = db
        self.config = config
        self.accounting = Accounting(db)
        self.node_monitor = node_monitor
        self.stratum_status = stratum_status or (
            lambda: {
                "listening": False,
                "available": False,
                "reason": "Stratum is not running in this process",
            }
        )
        self._rate: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self._rate_lock = asyncio.Lock()
        try:
            self._trusted_networks = [
                ipaddress.ip_network(value, strict=False)
                for value in config.trusted_proxies
            ]
        except ValueError as exc:
            raise ValueError(
                f"BTCS_TRUSTED_PROXIES contains an invalid network: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Middleware helpers
    # ------------------------------------------------------------------
    def _client_key(self, request: web.Request) -> str:
        """Return the rate-limit key for a request.

        X-Forwarded-For is honoured only when the direct peer is a configured
        trusted proxy (for example the Caddy container). Otherwise a client
        could spoof a new key for every request.
        """
        peer = request.remote or "unknown"
        if not self._trusted_networks:
            return peer
        try:
            peer_address = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        if not any(peer_address in network for network in self._trusted_networks):
            return peer
        forwarded = request.headers.get("X-Forwarded-For", "")
        candidate = forwarded.split(",", 1)[0].strip()
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                return peer
        return peer
    def _cors_headers(self, request: web.Request) -> dict[str, str]:
        origin = request.headers.get("Origin")
        allowed = self.config.api_cors_origins
        headers = {"Vary": "Origin"}
        if origin and ("*" in allowed or origin in allowed):
            headers["Access-Control-Allow-Origin"] = origin if "*" not in allowed else "*"
            headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            headers["Access-Control-Allow-Headers"] = "Content-Type, X-Request-ID"
            headers["Access-Control-Max-Age"] = "600"
        return headers

    async def _rate_limit(self, request: web.Request) -> None:
        limit = self.config.api_rate_limit_per_minute
        if limit <= 0:
            return
        peer = self._client_key(request)
        now = time.monotonic()
        async with self._rate_lock:
            window = self._rate[peer]
            if now - window[0] >= 60:
                window[0] = now
                window[1] = 0
            window[1] += 1
            if window[1] > limit:
                retry = max(1, int(60 - (now - window[0])))
                raise ApiError(
                    429,
                    "rate_limited",
                    "too many requests",
                    {"retry_after_seconds": retry},
                    headers={"Retry-After": str(retry)},
                )
            if len(self._rate) > 10_000:
                cutoff = now - 60
                for key in [k for k, v in self._rate.items() if v[0] < cutoff]:
                    self._rate.pop(key, None)

    @web.middleware
    async def middleware(self, request: web.Request, handler):
        request["request_id"] = (
            request.headers.get("X-Request-ID", "")[:64] or secrets.token_hex(8)
        )
        cors = self._cors_headers(request)
        if request.method == "OPTIONS":
            headers = {
                **cors,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "X-Request-ID": request["request_id"],
            }
            return web.Response(status=204, headers=headers)
        try:
            await self._rate_limit(request)
            response = await handler(request)
        except ApiError as exc:
            response = _error(
                request,
                exc.status,
                exc.code,
                exc.message,
                exc.details,
                headers=exc.headers,
            )
        except web.HTTPException as exc:
            code = "not_found" if exc.status == 404 else "http_error"
            headers = {}
            if exc.status == 405:
                code = "method_not_allowed"
                allowed = getattr(exc, "allowed_methods", None)
                if allowed:
                    headers["Allow"] = ", ".join(sorted(allowed))
            response = _error(
                request,
                exc.status,
                code,
                exc.reason or "request failed",
                headers=headers,
            )
            if exc.status == 429:
                response.headers["Retry-After"] = "60"
        except Exception as exc:  # noqa: BLE001
            log.exception("api_unhandled_error path=%s", request.path)
            response = _error(request, 500, "internal_error", "internal server error")
        response.headers.update(cors)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Request-ID", request["request_id"])
        return response

    # ------------------------------------------------------------------
    # Readiness helpers
    # ------------------------------------------------------------------
    async def _node_data(self) -> dict:
        snapshot = await self.node_monitor.snapshot()
        return snapshot.to_dict()

    def _stratum_data(self) -> dict:
        data = dict(self.stratum_status())
        # The Stratum service logs the detailed failure privately. Never
        # forward its upstream RPC exception text to public visitors.
        if data.get("last_template_error"):
            data["last_template_error"] = "Node template unavailable"
        return data

    async def _checks(self) -> dict:
        db_ok, db_error = await asyncio.to_thread(_db_healthy, self.db)
        node = await self._node_data()
        stratum = self._stratum_data()
        stratum_running = bool(stratum.get("listening"))
        template_fresh = False
        last_template = stratum.get("last_template_at")
        if last_template:
            template_fresh = (
                time.time() - float(last_template)
                <= max(60.0, self.config.poll_interval * 6)
            )
        node_synced = bool(node.get("synced"))
        ready = (
            db_ok
            and node.get("connected")
            and node_synced
            and stratum_running
            and bool(stratum.get("current_job_id"))
            and template_fresh
        )
        return {
            "ready": ready,
            "database": {"healthy": db_ok, "error": db_error},
            "node": {
                "connected": bool(node.get("connected")),
                "synced": node_synced,
                "initial_block_download": bool(node.get("initial_block_download")),
                "error": node.get("error"),
            },
            "stratum": {
                "running": stratum_running,
                "current_job_id": stratum.get("current_job_id"),
                "template_fresh": template_fresh,
                "last_template_error": stratum.get("last_template_error"),
            },
        }

    # ------------------------------------------------------------------
    # Handlers: health and status
    # ------------------------------------------------------------------
    async def health(self, request: web.Request) -> web.Response:
        db_ok, db_error = await asyncio.to_thread(_db_healthy, self.db)
        return _ok(
            request,
            {
                "status": "ok" if db_ok else "degraded",
                "service": "silver-pool",
                "version": __version__,
                "database": {"healthy": db_ok, "error": db_error},
            },
            status=200,
        )

    async def ready(self, request: web.Request) -> web.Response:
        checks = await self._checks()
        if checks["ready"]:
            return _ok(request, checks)
        return _error(
            request,
            503,
            "not_ready",
            "pool is not ready to accept miners",
            checks,
        )

    async def status(self, request: web.Request) -> web.Response:
        checks = await self._checks()
        node = await self._node_data()
        stats = await asyncio.to_thread(self.accounting.pool_stats)
        return _ok(
            request,
            {
                "service": "silver-pool",
                "version": __version__,
                "ready": checks["ready"],
                "checks": checks,
                "node": node,
                "stratum": self._stratum_data(),
                "pool": stats,
                "database": {"healthy": checks["database"]["healthy"]},
                "timestamp": time.time(),
            },
        )

    async def pool_status(self, request: web.Request) -> web.Response:
        stats, blocks, shares, round_row, node = await asyncio.gather(
            asyncio.to_thread(self.accounting.pool_stats),
            asyncio.to_thread(self.accounting.recent_blocks, 5),
            asyncio.to_thread(self.accounting.recent_shares, 10),
            asyncio.to_thread(self.accounting.current_round),
            self._node_data(),
        )
        return _ok(
            request,
            {
                "pool": stats,
                "hashrate": {
                    "estimate_24h": stats.get("estimated_hashrate_24h", 0.0),
                    "unit": "H/s",
                    "window": "24h",
                },
                "recent_blocks": blocks,
                "recent_shares": shares,
                "round": round_row,
                "node": node,
                "stratum": self._stratum_data(),
                "config": _public_config(self.config),
            },
        )

    async def statistics(self, request: web.Request) -> web.Response:
        stats = await asyncio.to_thread(self.accounting.pool_stats)
        return _ok(
            request,
            {
                "totals": stats,
                "hashrate": {
                    "estimate_24h": stats.get("estimated_hashrate_24h", 0.0),
                    "unit": "H/s",
                    "window": "24h",
                },
            },
        )

    async def hashrate_history(self, request: web.Request) -> web.Response:
        range_name = _query_choice(
            request, "range", set(HASHRATE_RANGES), "24h"
        )
        data = await asyncio.to_thread(
            self.accounting.hashrate_history, range_name
        )
        return _ok(request, data)

    # ------------------------------------------------------------------
    # Handlers: miners and shares
    # ------------------------------------------------------------------
    async def miners(self, request: web.Request) -> web.Response:
        limit = _query_int(request, "limit", 50, 1, 200)
        search = (request.query.get("search") or "").strip()
        if len(search) > 80:
            raise ApiError(400, "invalid_query", "search must be 80 characters or fewer")
        rows = await asyncio.to_thread(self.accounting.list_miners, limit, search)
        return _ok(
            request,
            {
                "miners": rows,
                "count": len(rows),
                "limit": limit,
                "search": search,
            },
        )

    async def miner(self, request: web.Request) -> web.Response:
        username = _username(request.match_info.get("username", ""))
        data = await asyncio.to_thread(self.accounting.get_miner, username)
        if not data:
            raise ApiError(404, "miner_not_found", f"miner {username} was not found")
        return _ok(request, data)

    async def miner_shares(self, request: web.Request) -> web.Response:
        username = _username(request.match_info.get("username", ""))
        limit = _query_int(request, "limit", 50, 1, 200)
        miner = await asyncio.to_thread(self.accounting.get_miner, username)
        if not miner:
            raise ApiError(404, "miner_not_found", f"miner {username} was not found")
        shares = await asyncio.to_thread(
            self.accounting.miner_shares, username, limit
        )
        return _ok(
            request,
            {
                "miner": miner["username"],
                "shares": shares,
                "count": len(shares),
                "limit": limit,
            },
        )

    async def recent_shares(self, request: web.Request) -> web.Response:
        limit = _query_int(request, "limit", 20, 1, 200)
        shares = await asyncio.to_thread(self.accounting.recent_shares, limit)
        return _ok(request, {"shares": shares, "count": len(shares), "limit": limit})

    # ------------------------------------------------------------------
    # Handlers: blocks, fees and rounds
    # ------------------------------------------------------------------
    async def blocks(self, request: web.Request) -> web.Response:
        limit = _query_int(request, "limit", 50, 1, 200)
        status = _query_choice(
            request, "status", BLOCK_STATUSES | {"all"}, "all"
        )
        rows = await asyncio.to_thread(self.accounting.recent_blocks, limit)
        if status != "all":
            rows = [row for row in rows if row["status"] == status]
        return _ok(
            request,
            {
                "blocks": rows,
                "count": len(rows),
                "limit": limit,
                "status": status,
            },
        )

    async def recent_blocks(self, request: web.Request) -> web.Response:
        limit = _query_int(request, "limit", 20, 1, 200)
        rows = await asyncio.to_thread(self.accounting.recent_blocks, limit)
        return _ok(request, {"blocks": rows, "count": len(rows), "limit": limit})

    async def fee_ledger(self, request: web.Request) -> web.Response:
        limit = _query_int(request, "limit", 50, 1, 200)
        rows = await asyncio.to_thread(self.accounting.fee_ledger, limit)
        return _ok(
            request,
            {"fee_ledger": rows, "count": len(rows), "limit": limit},
        )

    async def current_round(self, request: web.Request) -> web.Response:
        row = await asyncio.to_thread(self.accounting.current_round)
        return _ok(request, {"round": row})

    # ------------------------------------------------------------------
    # Handlers: configuration and API docs
    # ------------------------------------------------------------------
    async def public_config(self, request: web.Request) -> web.Response:
        return _ok(request, _public_config(self.config))

    async def docs(self, request: web.Request) -> web.Response:
        return _ok(
            request,
            {
                "openapi": "/api/openapi.json",
                "version": __version__,
                "authentication": "none",
                "rate_limit_per_minute": self.config.api_rate_limit_per_minute,
                "envelope": {
                    "success": {"ok": True, "data": {}, "meta": {}},
                    "error": {"ok": False, "error": {}, "meta": {}},
                },
                "endpoints": [
                    {"method": "GET", "path": "/api/health", "description": "Liveness"},
                    {"method": "GET", "path": "/api/ready", "description": "Readiness"},
                    {"method": "GET", "path": "/api/status", "description": "Overall status"},
                    {"method": "GET", "path": "/api/pool/status", "description": "Overview"},
                    {"method": "GET", "path": "/api/pool/statistics", "description": "Totals"},
                    {"method": "GET", "path": "/api/pool/history/hashrate?range=24h", "description": "Hashrate history"},
                    {"method": "GET", "path": "/api/pool/miners?limit=50&search=", "description": "Miner list"},
                    {"method": "GET", "path": "/api/pool/miner/{username}", "description": "Miner detail"},
                    {"method": "GET", "path": "/api/pool/miner/{username}/shares?limit=50", "description": "Miner shares"},
                    {"method": "GET", "path": "/api/pool/shares/recent?limit=20", "description": "Recent shares"},
                    {"method": "GET", "path": "/api/pool/blocks?limit=50&status=all", "description": "Blocks"},
                    {"method": "GET", "path": "/api/pool/blocks/recent?limit=20", "description": "Recent blocks"},
                    {"method": "GET", "path": "/api/pool/fee-ledger?limit=50", "description": "Pool fee ledger"},
                    {"method": "GET", "path": "/api/pool/rounds/current", "description": "Current round"},
                    {"method": "GET", "path": "/api/pool/config", "description": "Public configuration"},
                ],
            },
        )

    async def openapi(self, request: web.Request) -> web.Response:
        return web.json_response(_openapi_document())

    async def not_found(self, request: web.Request) -> web.Response:
        raise ApiError(404, "not_found", "API endpoint not found")

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.middleware])
        app["api"] = self
        r = app.router
        r.add_get("/api/health", self.health)
        r.add_get("/api/ready", self.ready)
        r.add_get("/api/status", self.status)
        r.add_get("/api/pool/status", self.pool_status)
        r.add_get("/api/pool/statistics", self.statistics)
        r.add_get("/api/pool/history/hashrate", self.hashrate_history)
        r.add_get("/api/pool/miners", self.miners)
        r.add_get("/api/pool/miner/{username}", self.miner)
        r.add_get("/api/pool/miner/{username}/shares", self.miner_shares)
        r.add_get("/api/pool/shares/recent", self.recent_shares)
        r.add_get("/api/pool/blocks", self.blocks)
        r.add_get("/api/pool/blocks/recent", self.recent_blocks)
        r.add_get("/api/pool/fee-ledger", self.fee_ledger)
        r.add_get("/api/pool/rounds/current", self.current_round)
        r.add_get("/api/pool/config", self.public_config)
        r.add_get("/api/docs", self.docs)
        r.add_get("/api/openapi.json", self.openapi)
        return app


def _openapi_document() -> dict:
    envelope = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "data": {},
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {},
                },
            },
            "meta": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "number"},
                    "request_id": {"type": "string"},
                },
            },
        },
    }
    paths: dict[str, Any] = {}
    for path, summary in {
        "/api/health": "Liveness",
        "/api/ready": "Readiness",
        "/api/status": "Overall status",
        "/api/pool/status": "Pool overview",
        "/api/pool/statistics": "Pool totals",
        "/api/pool/history/hashrate": "Hashrate history",
        "/api/pool/miners": "Miner list",
        "/api/pool/shares/recent": "Recent shares",
        "/api/pool/blocks": "Blocks",
        "/api/pool/blocks/recent": "Recent blocks",
        "/api/pool/fee-ledger": "Pool fee ledger",
        "/api/pool/rounds/current": "Current round",
        "/api/pool/config": "Public pool configuration",
        "/api/docs": "API index",
    }.items():
        paths[path] = {
            "get": {
                "summary": summary,
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": envelope,
                            }
                        },
                    }
                },
            }
        }
    for path, summary in {
        "/api/pool/miner/{username}": "Miner detail",
        "/api/pool/miner/{username}/shares": "Miner shares",
    }.items():
        paths[path] = {
            "get": {
                "summary": summary,
                "parameters": [
                    {
                        "name": "username",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Successful response"},
                    "404": {"description": "Miner not found"},
                },
            }
        }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Silver Pool API",
            "version": __version__,
            "description": "Read-only pool statistics and status API.",
        },
        "servers": [{"url": "/"}],
        "paths": paths,
    }


def create_app(
    db: Database,
    config: PoolConfig,
    node_monitor: NodeMonitor,
    stratum_status: Callable[[], dict] | None = None,
) -> web.Application:
    return Api(db, config, node_monitor, stratum_status).app()
