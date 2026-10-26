from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from .accounting import Accounting, parse_identity
from .block import (
    build_block,
    build_coinbase_parts,
    build_coinbase_tx,
    difficulty_to_target,
    hash_meets_target,
    merkle_branch,
    reverse_hex,
    target_from_bits,
    template_txids,
)
from .node import NodeMonitor
from .rpc import BTCSRpc, RPCError

log = logging.getLogger(__name__)


@dataclass(eq=False)
class ClientSession:
    writer: asyncio.StreamWriter
    extranonce1: bytes
    peer: str
    difficulty: float
    connected_at: float = field(default_factory=time.time)
    subscribed: bool = False
    authorized: bool = False
    identity: dict | None = None
    username: str = ""
    last_activity: float = field(default_factory=time.time)

    @property
    def closed(self) -> bool:
        return self.writer.is_closing()

    def share_target(self, block_target: int) -> int:
        # A block candidate must always also count as an accepted share. On
        # regtest the block target is much easier than difficulty 1, so the
        # share target must never be numerically smaller than the block target.
        return max(block_target, difficulty_to_target(self.difficulty))


class StratumServer:
    """Stratum V1 server backed by real BTCS ``getblocktemplate`` jobs."""

    def __init__(
        self,
        config,
        rpc: BTCSRpc,
        accounting: Accounting,
        node_monitor: NodeMonitor | None = None,
        on_block=None,
    ):
        self.config = config
        self.rpc = rpc
        self.accounting = accounting
        self.node_monitor = node_monitor
        self.on_block = on_block
        self.clients: set[ClientSession] = set()
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.current_job_id: str | None = None
        self.current_template: dict | None = None
        self.current_signature: tuple | None = None
        self.current_round_id: str | None = None
        self.current_height: int | None = None
        self.job_counter = 0
        self.block_target = 0
        self.started_at = time.time()
        self.last_template_error: str | None = None
        self.last_template_at: float | None = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Job creation / distribution
    # ------------------------------------------------------------------
    async def refresh_job(self) -> dict | None:
        template = await asyncio.to_thread(self.rpc.getblocktemplate, ["segwit"])
        if not template:
            raise RPCError("getblocktemplate", "empty template")

        txids = tuple(tx["txid"] for tx in template.get("transactions", []))
        signature = (
            template["previousblockhash"],
            int(template["height"]),
            int(template["version"]),
            template["bits"],
            txids,
        )
        if signature == self.current_signature:
            self.last_template_at = time.time()
            return None

        self.job_counter += 1
        job_id = str(self.job_counter)
        height = int(template["height"])
        previous = template["previousblockhash"]

        if self.current_height != height or self.current_round_id is None:
            self.current_round_id = f"{height}-{secrets.token_hex(4)}"
            self.current_height = height
            self.accounting.rotate_round(self.current_round_id, height)
        clean = (
            self.current_template is None
            or self.current_template.get("previousblockhash") != previous
        )

        leaves = [b"\x00" * 32] + template_txids(template)
        job = {
            "job_id": job_id,
            "template": template,
            "height": height,
            "previousblockhash": previous,
            "version": int(template["version"]),
            "bits": template["bits"],
            "ntime": int(template["curtime"]),
            "target": target_from_bits(template["bits"]),
            "round_id": self.current_round_id,
            "merkle_branches": merkle_branch(leaves, 0),
            "clean": clean,
            "created_at": time.time(),
        }
        self.jobs[job_id] = job
        while len(self.jobs) > max(1, self.config.job_history):
            self.jobs.popitem(last=False)

        self.current_job_id = job_id
        self.current_template = template
        self.current_signature = signature
        self.block_target = job["target"]
        self.last_template_at = time.time()
        self.last_template_error = None
        log.info(
            "stratum_job_created job=%s height=%s txs=%s clean=%s",
            job_id,
            height,
            len(template.get("transactions", [])),
            clean,
        )
        await self.broadcast_job(job, clean=clean)
        return job

    async def poll_templates(self) -> None:
        while not self._stop.is_set():
            try:
                await self.refresh_job()
            except Exception as exc:  # noqa: BLE001 - keep serving existing jobs
                self.last_template_error = str(exc)
                log.warning("template_poll_failed error=%s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.config.poll_interval)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    def _job_message(self, session: ClientSession, job: dict, clean: bool) -> dict:
        parts = build_coinbase_parts(
            job["template"],
            self.config.pool_script_pubkey,
            session.extranonce1,
            self.config.extranonce2_size,
        )
        return {
            "id": None,
            "method": "mining.notify",
            "params": [
                job["job_id"],
                reverse_hex(job["previousblockhash"]),
                parts["coinb1"],
                parts["coinb2"],
                job["merkle_branches"],
                f"{job['version']:08x}",
                job["bits"],
                f"{job['ntime']:08x}",
                bool(clean),
            ],
        }

    async def send_job_to(self, session: ClientSession, job: dict, clean: bool = False) -> None:
        await self._send(session, self._job_message(session, job, clean))

    async def broadcast_job(self, job: dict, clean: bool = False) -> None:
        for session in list(self.clients):
            if not session.subscribed or session.closed:
                continue
            try:
                await self.send_job_to(session, job, clean)
            except (ConnectionError, asyncio.CancelledError):
                self.clients.discard(session)
            except Exception as exc:  # noqa: BLE001
                log.warning("broadcast_failed peer=%s error=%s", session.peer, exc)
                self.clients.discard(session)

    # ------------------------------------------------------------------
    # Client handling
    # ------------------------------------------------------------------
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(self.clients) >= self.config.max_clients:
            writer.close()
            await writer.wait_closed()
            return
        peername = writer.get_extra_info("peername")
        peer = str(peername[0]) if isinstance(peername, tuple) else str(peername)
        extranonce1 = secrets.token_bytes(4)
        session = ClientSession(
            writer=writer,
            extranonce1=extranonce1,
            peer=peer,
            difficulty=self.config.difficulty,
        )
        self.clients.add(session)
        log.info("stratum_client_connected peer=%s", peer)
        try:
            while not self._stop.is_set():
                try:
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=self.config.client_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    await self._send_error(session, None, 20, "idle timeout")
                    break
                if not line:
                    break
                if len(line) > self.config.max_line_bytes:
                    await self._send_error(session, None, 20, "message too large")
                    break
                try:
                    request = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._send_error(session, None, 20, "invalid JSON")
                    continue
                if not isinstance(request, dict):
                    await self._send_error(session, None, 20, "invalid request")
                    continue
                session.last_activity = time.time()
                await self._dispatch(session, request)
        except (ConnectionError, asyncio.IncompleteReadError, ValueError) as exc:
            log.info("stratum_client_disconnected peer=%s reason=%s", peer, exc)
        except Exception:  # noqa: BLE001
            log.exception("stratum_client_error peer=%s", peer)
        finally:
            self.clients.discard(session)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass
            log.info("stratum_client_closed peer=%s", peer)

    async def _dispatch(self, session: ClientSession, request: dict) -> None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or []

        if method == "mining.subscribe":
            session.subscribed = True
            result = [
                [
                    ["mining.set_difficulty", "difficulty"],
                    ["mining.notify", "notify"],
                ],
                session.extranonce1.hex(),
                self.config.extranonce2_size,
            ]
            await self._send(session, {"id": request_id, "result": result, "error": None})
            await self._send(
                session,
                {
                    "id": None,
                    "method": "mining.set_difficulty",
                    "params": [session.difficulty],
                },
            )
            if self.current_job_id and session.authorized:
                await self.send_job_to(
                    session, self.jobs[self.current_job_id], clean=True
                )
            return

        if method == "mining.authorize":
            username = str(params[0]) if params else ""
            password = str(params[1]) if len(params) > 1 else ""
            if self.config.stratum_password and password != self.config.stratum_password:
                await self._send(
                    session,
                    {
                        "id": request_id,
                        "result": False,
                        "error": {"code": 24, "message": "unauthorized"},
                    },
                )
                return
            try:
                identity = self.accounting.register_miner(username)
            except ValueError:
                await self._send(
                    session,
                    {
                        "id": request_id,
                        "result": False,
                        "error": {"code": 20, "message": "invalid worker name"},
                    },
                )
                return
            session.identity = identity
            session.username = username
            session.authorized = True
            log.info(
                "stratum_worker_authorized peer=%s worker=%s",
                session.peer,
                identity["identity"],
            )
            await self._send(
                session, {"id": request_id, "result": True, "error": None}
            )
            if session.subscribed and self.current_job_id:
                await self.send_job_to(
                    session, self.jobs[self.current_job_id], clean=True
                )
            return

        if method == "mining.submit":
            if not session.subscribed or not session.authorized or not session.identity:
                await self._send(
                    session,
                    {
                        "id": request_id,
                        "result": False,
                        "error": {"code": 24, "message": "not authorized"},
                    },
                )
                return
            if len(params) < 5:
                await self._send(
                    session,
                    {
                        "id": request_id,
                        "result": False,
                        "error": {"code": 20, "message": "invalid submit parameters"},
                    },
                )
                return
            ok, reason = await self.validate_submit(
                session,
                str(params[1]),
                str(params[2]),
                str(params[3]),
                str(params[4]),
            )
            await self._send(
                session,
                {
                    "id": request_id,
                    "result": ok,
                    "error": None if ok else {"code": 23, "message": reason},
                },
            )
            return

        if method == "mining.extranonce.subscribe":
            await self._send(
                session, {"id": request_id, "result": True, "error": None}
            )
            return

        if method == "mining.suggest_difficulty":
            try:
                suggested = float(params[0])
            except (IndexError, TypeError, ValueError):
                await self._send_error(session, request_id, 20, "invalid difficulty")
                return
            if not (suggested > 0 and suggested < 1e12):
                await self._send_error(session, request_id, 20, "invalid difficulty")
                return
            session.difficulty = suggested
            await self._send(
                session, {"id": request_id, "result": True, "error": None}
            )
            await self._send(
                session,
                {
                    "id": None,
                    "method": "mining.set_difficulty",
                    "params": [session.difficulty],
                },
            )
            if session.subscribed and session.authorized and self.current_job_id:
                await self.send_job_to(
                    session, self.jobs[self.current_job_id], clean=True
                )
            return

        if method == "mining.configure":
            await self._send(
                session,
                {"id": request_id, "result": {"version-rolling": False}, "error": None},
            )
            return

        await self._send_error(session, request_id, 20, "unknown method")

    async def _send(self, session: ClientSession, payload: dict) -> None:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        session.writer.write(data)
        await session.writer.drain()

    async def _send_error(
        self, session: ClientSession, request_id, code: int, message: str
    ) -> None:
        await self._send(
            session,
            {"id": request_id, "result": None, "error": {"code": code, "message": message}},
        )

    # ------------------------------------------------------------------
    # Share / block validation
    # ------------------------------------------------------------------
    async def validate_submit(
        self,
        session: ClientSession,
        job_id: str,
        extranonce2: str,
        ntime_hex: str,
        nonce_hex: str,
    ) -> tuple[bool, str]:
        job = self.jobs.get(job_id)
        identity = session.identity
        if not job or not identity:
            await self._record_reject(session, job_id, extranonce2, ntime_hex, nonce_hex, "unknown-job")
            return False, "unknown-job"

        current_previous = (
            self.current_template.get("previousblockhash")
            if self.current_template
            else None
        )
        if current_previous and job["previousblockhash"] != current_previous:
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "stale-job", stale=True
            )
            return False, "stale-job"

        expected_len = self.config.extranonce2_size * 2
        if len(extranonce2) != expected_len:
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "invalid-extranonce2"
            )
            return False, "invalid-extranonce2"
        try:
            extranonce2_bytes = bytes.fromhex(extranonce2)
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
        except ValueError:
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "invalid-hex"
            )
            return False, "invalid-hex"
        if len(ntime_hex) != 8 or len(nonce_hex) != 8:
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "invalid-field-length"
            )
            return False, "invalid-field-length"
        if not (job["ntime"] - 7200 <= ntime <= job["ntime"] + 7200):
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "time-out-of-range"
            )
            return False, "time-out-of-range"

        coinbase, coinbase_txid = build_coinbase_tx(
            job["template"],
            self.config.pool_script_pubkey,
            session.extranonce1,
            extranonce2_bytes,
        )
        block, header, block_hash = build_block(
            job["template"], coinbase_txid, coinbase, nonce, ntime
        )
        meets_share = hash_meets_target(
            block_hash, session.share_target(job["target"])
        )
        if not meets_share:
            await self._record_reject(
                session, job_id, extranonce2, ntime_hex, nonce_hex, "low-difficulty"
            )
            return False, "low-difficulty"

        is_block = hash_meets_target(block_hash, job["target"])
        recorded, duplicate, _share_id = self.accounting.record_share(
            session.username,
            job_id,
            extranonce2,
            ntime_hex,
            nonce_hex,
            session.difficulty,
            True,
            round_id=job["round_id"],
            block_candidate=is_block,
            identity=identity,
        )
        if duplicate:
            return False, "duplicate-share"
        if not recorded:
            return False, "share-not-recorded"

        if is_block:
            await self._submit_block(job, session, block, header, block_hash, coinbase_txid)
        return True, ""

    async def _record_reject(
        self,
        session: ClientSession,
        job_id: str,
        extranonce2: str,
        ntime: str,
        nonce: str,
        reason: str,
        stale: bool = False,
    ) -> None:
        if not session.identity:
            return
        job = self.jobs.get(job_id)
        try:
            self.accounting.record_share(
                session.username,
                job_id,
                extranonce2,
                ntime,
                nonce,
                session.difficulty,
                False,
                round_id=job["round_id"] if job else self.current_round_id,
                stale=stale,
                reject_reason=reason,
                identity=session.identity,
            )
        except Exception:  # noqa: BLE001 - rejection must not kill the client
            log.exception("record_reject_failed job=%s reason=%s", job_id, reason)

    async def _submit_block(
        self,
        job: dict,
        session: ClientSession,
        block: bytes,
        header: bytes,
        block_hash: str,
        coinbase_txid: str,
    ) -> None:
        template = job["template"]
        coinbase_value = int(template["coinbasevalue"])
        fee_satoshi = int(coinbase_value * self.config.pool_fee / 100)
        net_reward = coinbase_value - fee_satoshi
        result = None
        accepted = False
        try:
            result = await asyncio.to_thread(self.rpc.submitblock, block.hex())
            accepted = result is None
            if result == "duplicate":
                canonical = await asyncio.to_thread(
                    self.rpc.getblockhash, int(template["height"])
                )
                accepted = canonical == block_hash
        except Exception as exc:  # noqa: BLE001
            result = str(exc)
            log.warning("submitblock_failed hash=%s error=%s", block_hash, exc)

        if accepted:
            try:
                block_id = self.accounting.record_block(
                    height=int(template["height"]),
                    block_hash=block_hash,
                    coinbase_value_satoshi=coinbase_value,
                    fee_satoshi=fee_satoshi,
                    net_reward_satoshi=net_reward,
                    miner_username=session.username,
                    round_id=job["round_id"],
                    header_hex=header.hex(),
                    block_hex=block.hex(),
                    job_id=job["job_id"],
                    node_result=result,
                    worker_username=session.identity["identity"] if session.identity else None,
                )
                log.info(
                    "block_accepted height=%s hash=%s miner=%s block_id=%s coinbase_txid=%s",
                    template["height"],
                    block_hash,
                    session.username,
                    block_id,
                    coinbase_txid,
                )
                if self.on_block:
                    try:
                        self.on_block(int(template["height"]), block_hash)
                    except Exception:  # noqa: BLE001
                        log.exception("on_block_callback_failed")
            except Exception:  # noqa: BLE001
                log.exception("record_block_failed hash=%s", block_hash)
        else:
            log.warning(
                "block_rejected height=%s hash=%s result=%s",
                template["height"],
                block_hash,
                result,
            )
            try:
                self.accounting.record_rejected_candidate(
                    height=int(template["height"]),
                    block_hash=block_hash,
                    header_hex=header.hex(),
                    block_hex=block.hex(),
                    job_id=job["job_id"],
                    round_id=job["round_id"],
                    miner_username=session.username,
                    node_result=str(result),
                )
            except Exception:  # noqa: BLE001
                log.exception("record_rejected_candidate_failed")

    async def shutdown(self) -> None:
        """Stop polling, disconnect miners and wait for handlers to finish."""
        self.stop()
        for session in list(self.clients):
            try:
                await self._send_error(session, None, 20, "pool shutting down")
            except Exception:  # noqa: BLE001
                pass
            session.writer.close()
        self.clients.clear()

    def status(self) -> dict:
        return {
            "listening": not self._stop.is_set(),
            "clients": len(self.clients),
            "authorized_clients": sum(1 for c in self.clients if c.authorized),
            "current_job_id": self.current_job_id,
            "current_height": self.current_height,
            "current_round_id": self.current_round_id,
            "current_difficulty": self.config.difficulty,
            "last_template_at": self.last_template_at,
            "last_template_error": self.last_template_error,
            "uptime_seconds": time.time() - self.started_at,
        }
