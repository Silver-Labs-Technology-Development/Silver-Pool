import asyncio
import json
import struct
import time
from typing import Dict, Any

from .block import build_coinbase_tx, build_block_bytes, block_hash, target_from_bits
from .rpc import BTCSRpc


class StratumServer:
    def __init__(self, config, rpc: BTCSRpc, accounting, on_block):
        self.config = config
        self.rpc = rpc
        self.accounting = accounting
        self.on_block = on_block
        self.clients: set = set()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.current_job_id: str | None = None
        self.current_template = None
        self.job_counter = 0
        self.target = 0
        self.difficulty = config.difficulty

    async def poll_templates(self):
        while True:
            try:
                tpl = self.rpc.getblocktemplate(["segwit"])
                # new job if template changed
                if self.current_template is None or tpl["previousblockhash"] != self.current_template["previousblockhash"] or tpl["transactions"] != self.current_template.get("transactions"):
                    self.current_template = tpl
                    self.target = target_from_bits(tpl["bits"])
                    self.job_counter += 1
                    job_id = str(self.job_counter)
                    spk = self.config.pool_address and None
                    # pool address script pubkey must be resolved; store in config as scriptpubkey
                    pool_spk = self.config.pool_script_pubkey
                    cb_tx, txid = build_coinbase_tx(tpl, pool_spk, b"")
                    coinb1 = cb_tx.hex()
                    coinb2 = ""
                    job = {
                        "job_id": job_id,
                        "template": tpl,
                        "coinbase_tx": cb_tx,
                        "txid": txid,
                        "coinb1": coinb1,
                        "coinb2": coinb2,
                        "ntime": tpl["curtime"],
                    }
                    self.jobs[job_id] = job
                    self.current_job_id = job_id
                    await self.broadcast_job(job, clean=True)
            except Exception as e:
                print("template poll error", e)
            await asyncio.sleep(self.config.poll_interval)

    async def broadcast_job(self, job, clean=False):
        ntime = job["ntime"]
        msg = {
            "id": None,
            "method": "mining.notify",
            "params": [
                job["job_id"],
                reverse_hex(job["template"]["previousblockhash"]),
                job["coinb1"],
                job["coinb2"],
                [],
                hex(job["template"]["version"])[2:],
                job["template"]["bits"],
                hex(ntime)[2:],
                clean,
            ],
        }
        # fix version format: stratum expects hex string without 0x, usually 8 chars
        msg["params"][5] = f"{job['template']['version']:08x}"
        msg["params"][7] = f"{ntime:08x}"
        # prevhash in stratum is byte-reversed? standard uses little-endian prevhash (reversed). We'll send reversed hex.
        data = (json.dumps(msg) + "\n").encode()
        for w in list(self.clients):
            try:
                w.write(data)
                await w.drain()
            except Exception:
                self.clients.discard(w)
        # send difficulty first? clients should already have it.

    async def handle_client(self, reader, writer):
        self.clients.add(writer)
        extranonce1 = "00000000"
        authorized = set()
        # send difficulty
        writer.write((json.dumps({"id": None, "method": "mining.set_difficulty", "params": [self.difficulty]}) + "\n").encode())
        await writer.drain()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except Exception:
                    continue
                method = req.get("method")
                rid = req.get("id")
                params = req.get("params") or []
                if method == "mining.subscribe":
                    res = [["mining.set_difficulty", "mining.notify"], extranonce1, self.config.extranonce2_size]
                    writer.write((json.dumps({"id": rid, "result": res, "error": None}) + "\n").encode())
                    await writer.drain()
                    # send current job
                    if self.current_job_id:
                        job = self.jobs[self.current_job_id]
                        await self.send_job_to(writer, job, clean=True)
                elif method == "mining.authorize":
                    user = params[0] if params else ""
                    authorized.add(user)
                    self.accounting.register_miner(user)
                    writer.write((json.dumps({"id": rid, "result": True, "error": None}) + "\n").encode())
                    await writer.drain()
                elif method == "mining.submit":
                    user = params[0]
                    job_id = params[1]
                    extranonce2 = params[2]
                    ntime_hex = params[3]
                    nonce_hex = params[4]
                    ok = await self.validate_submit(user, job_id, extranonce2, ntime_hex, nonce_hex, writer)
                    writer.write((json.dumps({"id": rid, "result": ok, "error": None if ok else "rejected"}) + "\n").encode())
                    await writer.drain()
                else:
                    writer.write((json.dumps({"id": rid, "result": None, "error": "unknown method"}) + "\n").encode())
                    await writer.drain()
        except Exception as e:
            print("client error", e)
        finally:
            self.clients.discard(writer)
            writer.close()

    async def send_job_to(self, writer, job, clean=False):
        ntime = job["ntime"]
        msg = {
            "id": None,
            "method": "mining.notify",
            "params": [
                job["job_id"],
                reverse_hex(job["template"]["previousblockhash"]),
                job["coinb1"],
                job["coinb2"],
                [],
                f"{job['template']['version']:08x}",
                job["template"]["bits"],
                f"{ntime:08x}",
                clean,
            ],
        }
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()

    async def validate_submit(self, user, job_id, extranonce2, ntime_hex, nonce_hex, writer):
        job = self.jobs.get(job_id)
        if not job:
            return False
        tpl = job["template"]
        try:
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
        except ValueError:
            return False
        cb_tx = job["coinbase_tx"]
        # rebuild block
        block_bytes, header = build_block_bytes(tpl, job["txid"], cb_tx, nonce, ntime)
        h = block_hash(header)
        target = self.target
        if int(h, 16) > target:
            self.accounting.record_share(user, job_id, nonce, False)
            return False
        # accepted share
        is_dup = not self.accounting.record_share(user, job_id, nonce, True)
        if is_dup:
            return False
        # block-level: submit block
        try:
            res = self.rpc.submitblock(block_bytes.hex())
            print("submitblock result", res)
            if res is None:
                # Calculate pool fee from coinbase value
                coinbase_value_satoshi = tpl["coinbasevalue"]
                fee_percent = self.config.pool_fee
                # Fee calculated as percentage of coinbase value
                fee_satoshi = (coinbase_value_satoshi * fee_percent) // 100
                net_reward_satoshi = coinbase_value_satoshi - fee_satoshi
                self.accounting.record_block(
                    tpl["height"],
                    h,
                    coinbase_value_satoshi,
                    fee_satoshi,
                    net_reward_satoshi,
                    user,
                )
                self.on_block(tpl["height"], h)
        except Exception as e:
            print("submit error", e)
        return True


def reverse_hex(h: str) -> str:
    return bytes.fromhex(h)[::-1].hex()
