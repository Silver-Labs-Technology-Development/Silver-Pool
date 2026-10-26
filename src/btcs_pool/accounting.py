"""Persistent mining accounting.

Shares are weighted by difficulty for PPLNS. A block reward is allocated when
the block is recorded, held as immature, then moved to available balances when
the node reports the block matured. Every transition is retained for audit.
"""
from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, ROUND_DOWN
from typing import Iterable

from .db import Database

log = logging.getLogger(__name__)

SATOSHI = Decimal("1")
SATOSHIS_PER_COIN = Decimal("100000000")
HASHES_PER_DIFFICULTY = 2**32
IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.:@+\-]{1,160}$")
HASHRATE_RANGES = {
    "1h": (3600, 60),
    "6h": (6 * 3600, 300),
    "24h": (24 * 3600, 900),
    "7d": (7 * 24 * 3600, 3600),
}


def _to_satoshi(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(SATOSHI, rounding=ROUND_DOWN)
    except Exception as exc:  # noqa: BLE001 - convert to a domain error
        raise ValueError(f"Cannot convert {value!r} to satoshis") from exc


def _from_satoshi(satoshis: int | Decimal) -> Decimal:
    return Decimal(int(satoshis)) / SATOSHIS_PER_COIN


def parse_identity(username: str) -> tuple[str, str]:
    username = (username or "").strip()
    if not IDENTITY_RE.fullmatch(username):
        raise ValueError("invalid miner name")
    if "." in username:
        account, worker = username.rsplit(".", 1)
        if not account or not worker:
            raise ValueError("invalid miner.worker name")
        return account, worker[:64]
    return username, "default"


def calculate_pplns_reward(
    miner_shares: int,
    round_total_shares: int,
    coinbase_value: int,
    pool_fee_percent: float,
) -> dict:
    """Compatibility helper used by tests and external tooling."""
    if round_total_shares <= 0:
        return {
            "gross_satoshi": Decimal("0"),
            "fee_satoshi": Decimal("0"),
            "net_satoshi": Decimal("0"),
        }
    gross = (
        Decimal(int(miner_shares)) * Decimal(int(coinbase_value))
        / Decimal(int(round_total_shares))
    ).quantize(SATOSHI, rounding=ROUND_DOWN)
    fee = (gross * Decimal(str(pool_fee_percent)) / Decimal(100)).quantize(
        SATOSHI, rounding=ROUND_DOWN
    )
    return {
        "gross_satoshi": gross,
        "fee_satoshi": fee,
        "net_satoshi": gross - fee,
    }


class Accounting:
    def __init__(self, db_path_or_db: str | Database):
        self.db = (
            db_path_or_db
            if isinstance(db_path_or_db, Database)
            else Database(db_path_or_db)
        )

    # ------------------------------------------------------------------
    # Identity and share recording
    # ------------------------------------------------------------------
    def register_miner(self, username: str) -> dict:
        account, worker = parse_identity(username)
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO miners(username, created_at, last_seen_at)
                   VALUES (?,?,?)
                   ON CONFLICT(username) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (account, now, now),
            )
            miner = conn.execute(
                "SELECT id, username FROM miners WHERE username=?", (account,)
            ).fetchone()
            conn.execute(
                """INSERT INTO workers(miner_id, name, created_at, last_seen_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(miner_id, name) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (miner["id"], worker, now, now),
            )
            conn.execute(
                """INSERT OR IGNORE INTO miner_balances(miner_id, available_satoshi, immature_satoshi)
                   VALUES (?,0,0)""",
                (miner["id"],),
            )
            worker_row = conn.execute(
                "SELECT id FROM workers WHERE miner_id=? AND name=?",
                (miner["id"], worker),
            ).fetchone()
            return {
                "miner_id": miner["id"],
                "worker_id": worker_row["id"],
                "miner": account,
                "worker": worker,
                "identity": f"{account}.{worker}",
            }

    def record_share(
        self,
        username: str,
        job_id: str,
        extranonce2: str,
        ntime: str,
        nonce: str,
        difficulty: float,
        accepted: bool,
        round_id: str | None = None,
        stale: bool = False,
        reject_reason: str | None = None,
        block_candidate: bool = False,
        identity: dict | None = None,
    ) -> tuple[bool, bool, int | None]:
        """Record one submitted share.

        Returns ``(recorded, duplicate, share_id)``. A duplicate is rejected by
        the UNIQUE constraint and is not counted in round totals again.
        """
        ident = identity or self.register_miner(username)
        now = time.time()
        try:
            with self.db.transaction() as conn:
                cur = conn.execute(
                    """INSERT INTO shares(
                           miner_id, worker_id, round_id, job_id, extranonce2,
                           ntime, nonce, difficulty, accepted, stale,
                           reject_reason, block_candidate, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ident["miner_id"],
                        ident["worker_id"],
                        round_id,
                        job_id,
                        extranonce2,
                        ntime,
                        nonce,
                        float(difficulty),
                        1 if accepted else 0,
                        1 if stale else 0,
                        reject_reason,
                        1 if block_candidate else 0,
                        now,
                    ),
                )
                if accepted and round_id:
                    conn.execute(
                        """UPDATE rounds
                           SET total_shares = total_shares + 1,
                               total_difficulty = total_difficulty + ?
                           WHERE round_id=?""",
                        (float(difficulty), round_id),
                    )
                return True, False, cur.lastrowid
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False, True, None
            raise

    def start_round(self, round_id: str, height: int) -> bool:
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO rounds(round_id, height, status, started_at)
                       VALUES (?,?,'active',?)""",
                    (round_id, int(height), time.time()),
                )
            return True
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False
            raise

    def rotate_round(self, new_round_id: str, height: int) -> None:
        """End any active round for an earlier height and start a new one."""
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE rounds SET status='completed', ended_at=?
                   WHERE status='active' AND round_id<>?""",
                (time.time(), new_round_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO rounds(round_id, height, status, started_at)
                   VALUES (?,?,'active',?)""",
                (new_round_id, int(height), time.time()),
            )

    def current_round(self) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM rounds WHERE status='active' ORDER BY started_at DESC LIMIT 1"
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Blocks, PPLNS allocation and maturity
    # ------------------------------------------------------------------
    def record_block(
        self,
        *,
        height: int,
        block_hash: str,
        coinbase_value_satoshi: int,
        fee_satoshi: int,
        net_reward_satoshi: int,
        miner_username: str,
        round_id: str,
        header_hex: str,
        block_hex: str,
        job_id: str,
        node_result: str | None = None,
        worker_username: str | None = None,
    ) -> int:
        ident = self.register_miner(worker_username or miner_username)
        now = time.time()
        with self.db.transaction() as conn:
            candidate = conn.execute(
                """INSERT INTO block_candidates(
                       round_id, job_id, miner_id, worker_id, height, hash,
                       header_hex, block_hex, status, node_result,
                       created_at, submitted_at)
                   VALUES (?,?,?,?,?,?,?,?,'accepted',?,?,?)""",
                (
                    round_id,
                    job_id,
                    ident["miner_id"],
                    ident["worker_id"],
                    int(height),
                    block_hash,
                    header_hex,
                    block_hex,
                    node_result,
                    now,
                    now,
                ),
            )
            block = conn.execute(
                """INSERT INTO blocks(
                       height, hash, candidate_id, coinbase_value_satoshi,
                       fee_satoshi, net_reward_satoshi, status, miner_id,
                       round_id, found_at)
                   VALUES (?,?,?,?,?,?,'immature',?,?,?)""",
                (
                    int(height),
                    block_hash,
                    candidate.lastrowid,
                    int(coinbase_value_satoshi),
                    int(fee_satoshi),
                    int(net_reward_satoshi),
                    ident["miner_id"],
                    round_id,
                    now,
                ),
            )
            block_id = block.lastrowid

            weights = conn.execute(
                """SELECT miner_id, SUM(difficulty) AS weight
                   FROM shares
                   WHERE round_id=? AND accepted=1 AND stale=0
                   GROUP BY miner_id
                   ORDER BY miner_id""",
                (round_id,),
            ).fetchall()
            if not weights:
                weights = [
                    {
                        "miner_id": ident["miner_id"],
                        "weight": 1.0,
                    }
                ]

            total_weight = sum(Decimal(str(row["weight"])) for row in weights)
            remaining_net = int(net_reward_satoshi)
            remaining_gross = int(coinbase_value_satoshi)
            remaining_fee = int(fee_satoshi)

            for index, row in enumerate(weights):
                weight = Decimal(str(row["weight"]))
                if index == len(weights) - 1:
                    gross = remaining_gross
                    net = remaining_net
                    fee = remaining_fee
                else:
                    gross = int(
                        (
                            Decimal(int(coinbase_value_satoshi))
                            * weight
                            / total_weight
                        ).to_integral_value(rounding=ROUND_DOWN)
                    )
                    net = int(
                        (
                            Decimal(int(net_reward_satoshi))
                            * weight
                            / total_weight
                        ).to_integral_value(rounding=ROUND_DOWN)
                    )
                    fee = max(0, gross - net)
                    remaining_gross -= gross
                    remaining_net -= net
                    remaining_fee -= fee
                conn.execute(
                    """INSERT INTO reward_allocations(
                           block_id, round_id, miner_id, difficulty, gross_satoshi,
                           fee_satoshi, net_satoshi, status, created_at)
                       VALUES (?,?,?,?,?,?,?,'pending',?)""",
                    (
                        block_id,
                        round_id,
                        row["miner_id"],
                        float(row["weight"]),
                        gross,
                        fee,
                        net,
                        now,
                    ),
                )
                if net:
                    conn.execute(
                        """INSERT INTO miner_balances(miner_id, available_satoshi, immature_satoshi)
                           VALUES (?,0,?)
                           ON CONFLICT(miner_id) DO UPDATE SET
                               immature_satoshi = immature_satoshi + excluded.immature_satoshi""",
                        (row["miner_id"], net),
                    )

            if fee_satoshi:
                conn.execute(
                    """INSERT INTO pool_fee_ledger(
                           block_id, block_height, block_hash, fee_satoshi,
                           status, created_at, updated_at)
                       VALUES (?,?,?,?,'pending',?,?)""",
                    (block_id, int(height), block_hash, int(fee_satoshi), now, now),
                )
            conn.execute(
                """UPDATE rounds
                   SET status='completed', ended_at=?, height=?,
                       pool_fee_satoshi=?
                   WHERE round_id=?""",
                (now, int(height), int(fee_satoshi), round_id),
            )
            return block_id

    def record_rejected_candidate(
        self,
        *,
        height: int,
        block_hash: str,
        header_hex: str,
        block_hex: str,
        job_id: str,
        round_id: str | None,
        miner_username: str,
        node_result: str,
    ) -> None:
        ident = self.register_miner(miner_username)
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO block_candidates(
                       round_id, job_id, miner_id, worker_id, height, hash,
                       header_hex, block_hex, status, node_result,
                       created_at, submitted_at)
                   VALUES (?,?,?,?,?,?,?,?,'rejected',?,?,?)""",
                (
                    round_id,
                    job_id,
                    ident["miner_id"],
                    ident["worker_id"],
                    int(height),
                    block_hash,
                    header_hex,
                    block_hex,
                    node_result,
                    now,
                    now,
                ),
            )

    def reconcile_blocks(
        self,
        current_height: int,
        maturity: int,
        canonical_hash: callable,
    ) -> dict:
        """Mature or orphan immature blocks and update confirmations."""
        rows = self.db.fetchall(
            """SELECT id, height, hash FROM blocks
               WHERE status='immature' AND height <= ?
               ORDER BY height""",
            (int(current_height) - int(maturity) + 1,),
        )
        matured = 0
        orphaned = 0
        for row in rows:
            canonical = canonical_hash(int(row["height"]))
            if canonical and canonical != row["hash"]:
                self._orphan_block(row["id"])
                orphaned += 1
            elif canonical and canonical == row["hash"]:
                self._mature_block(row["id"])
                matured += 1

        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE blocks
                   SET confirmations = MAX(0, ? - height + 1)
                   WHERE status IN ('immature','mature') AND height <= ?""",
                (int(current_height), int(current_height)),
            )
        return {"matured": matured, "orphaned": orphaned, "checked": len(rows)}

    def _mature_block(self, block_id: int) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            allocations = conn.execute(
                "SELECT miner_id, net_satoshi FROM reward_allocations WHERE block_id=? AND status='pending'",
                (block_id,),
            ).fetchall()
            for row in allocations:
                conn.execute(
                    """UPDATE miner_balances
                       SET available_satoshi = available_satoshi + ?,
                           immature_satoshi = MAX(0, immature_satoshi - ?)
                       WHERE miner_id=?""",
                    (row["net_satoshi"], row["net_satoshi"], row["miner_id"]),
                )
            conn.execute(
                "UPDATE reward_allocations SET status='confirmed' WHERE block_id=? AND status='pending'",
                (block_id,),
            )
            conn.execute(
                "UPDATE pool_fee_ledger SET status='allocated', updated_at=? WHERE block_id=? AND status='pending'",
                (now, block_id),
            )
            conn.execute(
                "UPDATE blocks SET status='mature', matured_at=? WHERE id=? AND status='immature'",
                (now, block_id),
            )

    def _orphan_block(self, block_id: int) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            allocations = conn.execute(
                "SELECT miner_id, net_satoshi FROM reward_allocations WHERE block_id=? AND status='pending'",
                (block_id,),
            ).fetchall()
            for row in allocations:
                conn.execute(
                    """UPDATE miner_balances
                       SET immature_satoshi = MAX(0, immature_satoshi - ?)
                       WHERE miner_id=?""",
                    (row["net_satoshi"], row["miner_id"]),
                )
            conn.execute(
                "UPDATE reward_allocations SET status='orphaned' WHERE block_id=? AND status='pending'",
                (block_id,),
            )
            conn.execute(
                "UPDATE pool_fee_ledger SET status='orphaned', updated_at=? WHERE block_id=? AND status='pending'",
                (now, block_id),
            )
            conn.execute(
                "UPDATE blocks SET status='orphaned', matured_at=? WHERE id=? AND status='immature'",
                (now, block_id),
            )

    # ------------------------------------------------------------------
    # Payout boundary (disabled by default)
    # ------------------------------------------------------------------
    def request_payout(self, miner: str, amount_satoshi: int, address: str, min_payout_satoshi: int = 1_000_000) -> int | None:
        if amount_satoshi < min_payout_satoshi or not address:
            return None
        account, _ = parse_identity(miner)
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT m.id, b.available_satoshi
                   FROM miners m JOIN miner_balances b ON b.miner_id=m.id
                   WHERE m.username=?""",
                (account,),
            ).fetchone()
            if not row or row["available_satoshi"] < amount_satoshi:
                return None
            cur = conn.execute(
                """INSERT INTO payouts(miner_id, address, amount_satoshi, status, created_at)
                   VALUES (?,?,?,'pending',?)""",
                (row["id"], address, int(amount_satoshi), time.time()),
            )
            conn.execute(
                "UPDATE miner_balances SET available_satoshi=available_satoshi-? WHERE miner_id=?",
                (int(amount_satoshi), row["id"]),
            )
            return cur.lastrowid

    def cancel_payout(self, payout_id: int) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT miner_id, amount_satoshi FROM payouts WHERE id=? AND status='pending'",
                (payout_id,),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE miner_balances SET available_satoshi=available_satoshi+? WHERE miner_id=?",
                (row["amount_satoshi"], row["miner_id"]),
            )
            conn.execute(
                "UPDATE payouts SET status='cancelled', processed_at=? WHERE id=?",
                (time.time(), payout_id),
            )
            return True

    def mark_payout_sent(self, payout_id: int, txid: str) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM payouts WHERE id=? AND status='pending'", (payout_id,)
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE payouts SET status='sent', txid=?, processed_at=? WHERE id=?",
                (txid, time.time(), payout_id),
            )
            return True

    # ------------------------------------------------------------------
    # Read models used by the HTTP API and tests
    # ------------------------------------------------------------------
    def pool_stats(self) -> dict:
        now = time.time()
        row = self.db.fetchone(
            """SELECT
                 (SELECT COUNT(*) FROM miners) AS total_miners,
                 (SELECT COUNT(*) FROM workers) AS total_workers,
                 (SELECT COUNT(*) FROM shares) AS total_shares,
                 (SELECT COUNT(*) FROM shares WHERE accepted=1) AS accepted_shares,
                 (SELECT COUNT(*) FROM shares WHERE accepted=0) AS rejected_shares,
                 (SELECT COUNT(*) FROM blocks) AS total_blocks,
                 (SELECT COUNT(*) FROM blocks WHERE status='mature') AS mature_blocks,
                 (SELECT COUNT(*) FROM blocks WHERE status='immature') AS immature_blocks,
                 (SELECT COUNT(*) FROM blocks WHERE status='orphaned') AS orphaned_blocks,
                 (SELECT COUNT(DISTINCT miner_id) FROM shares WHERE created_at>=?) AS active_miners_24h,
                 (SELECT COALESCE(SUM(difficulty),0) FROM shares
                  WHERE accepted=1 AND created_at>=?) AS difficulty_24h
            """,
            (now - 86400, now - 86400),
        )
        data = dict(row)
        data["estimated_hashrate_24h"] = (
            float(data.pop("difficulty_24h")) * HASHES_PER_DIFFICULTY / 86400
        )
        return data

    def resolve_account(self, username: str) -> str:
        username = (username or "").strip()
        row = self.db.fetchone("SELECT username FROM miners WHERE username=?", (username,))
        if row:
            return row["username"]
        if "." in username:
            account = username.rsplit(".", 1)[0]
            row = self.db.fetchone("SELECT username FROM miners WHERE username=?", (account,))
            if row:
                return row["username"]
        return username

    def list_miners(self, limit: int = 50, search: str = "") -> list[dict]:
        limit = max(1, min(int(limit), 200))
        pattern = f"%{search.strip()}%"
        rows = self.db.fetchall(
            """SELECT m.id, m.username, m.created_at, m.last_seen_at,
                      COALESCE(b.available_satoshi,0) AS available_satoshi,
                      COALESCE(b.immature_satoshi,0) AS immature_satoshi,
                      (SELECT COUNT(*) FROM workers w WHERE w.miner_id=m.id) AS workers,
                      (SELECT COUNT(*) FROM shares s WHERE s.miner_id=m.id AND s.accepted=1) AS accepted_shares,
                      (SELECT COUNT(*) FROM shares s WHERE s.miner_id=m.id AND s.accepted=0) AS rejected_shares
               FROM miners m LEFT JOIN miner_balances b ON b.miner_id=m.id
               WHERE m.username LIKE ?
               ORDER BY COALESCE(m.last_seen_at, m.created_at) DESC
               LIMIT ?""",
            (pattern, limit),
        )
        return [self._miner_row(row) for row in rows]

    def get_miner(self, username: str) -> dict | None:
        account = self.resolve_account(username)
        row = self.db.fetchone(
            """SELECT m.id, m.username, m.created_at, m.last_seen_at,
                      COALESCE(b.available_satoshi,0) AS available_satoshi,
                      COALESCE(b.immature_satoshi,0) AS immature_satoshi,
                      (SELECT COUNT(*) FROM workers w WHERE w.miner_id=m.id) AS workers,
                      (SELECT COUNT(*) FROM shares s WHERE s.miner_id=m.id AND s.accepted=1) AS accepted_shares,
                      (SELECT COUNT(*) FROM shares s WHERE s.miner_id=m.id AND s.accepted=0) AS rejected_shares
               FROM miners m LEFT JOIN miner_balances b ON b.miner_id=m.id
               WHERE m.username=?""",
            (account,),
        )
        if not row:
            return None
        data = self._miner_row(row)
        data["worker_rows"] = [
            dict(worker)
            for worker in self.db.fetchall(
                """SELECT w.name, w.created_at, w.last_seen_at,
                          (SELECT COUNT(*) FROM shares s WHERE s.worker_id=w.id AND s.accepted=1) AS accepted_shares
                   FROM workers w WHERE w.miner_id=? ORDER BY w.last_seen_at DESC""",
                (row["id"],),
            )
        ]
        data["recent_blocks"] = self._blocks_for_miner(row["id"], 5)
        return data

    def _miner_row(self, row) -> dict:
        return {
            "username": row["username"],
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "available_satoshi": int(row["available_satoshi"]),
            "immature_satoshi": int(row["immature_satoshi"]),
            "total_satoshi": int(row["available_satoshi"]) + int(row["immature_satoshi"]),
            "available_btcs": str(_from_satoshi(row["available_satoshi"])),
            "immature_btcs": str(_from_satoshi(row["immature_satoshi"])),
            "total_btcs": str(_from_satoshi(int(row["available_satoshi"]) + int(row["immature_satoshi"]))),
            "workers": int(row["workers"]),
            "accepted_shares": int(row["accepted_shares"]),
            "rejected_shares": int(row["rejected_shares"]),
        }

    def miner_shares(self, username: str, limit: int = 50) -> list[dict]:
        account = self.resolve_account(username)
        limit = max(1, min(int(limit), 200))
        rows = self.db.fetchall(
            """SELECT s.job_id, s.extranonce2, s.ntime, s.nonce, s.difficulty,
                      s.accepted, s.stale, s.reject_reason, s.created_at,
                      w.name AS worker, r.height AS round_height
               FROM shares s
               JOIN miners m ON m.id=s.miner_id
               JOIN workers w ON w.id=s.worker_id
               LEFT JOIN rounds r ON r.round_id=s.round_id
               WHERE m.username=?
               ORDER BY s.id DESC LIMIT ?""",
            (account, limit),
        )
        return [dict(row) for row in rows]

    def recent_shares(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        rows = self.db.fetchall(
            """SELECT m.username AS miner, w.name AS worker, s.job_id,
                      s.difficulty, s.accepted, s.stale, s.reject_reason,
                      s.created_at, r.height AS round_height
               FROM shares s
               JOIN miners m ON m.id=s.miner_id
               JOIN workers w ON w.id=s.worker_id
               LEFT JOIN rounds r ON r.round_id=s.round_id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in rows]

    def recent_blocks(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        rows = self.db.fetchall(
            """SELECT b.height, b.hash, b.coinbase_value_satoshi, b.fee_satoshi,
                      b.net_reward_satoshi, b.status, b.found_at, b.matured_at,
                      b.confirmations, m.username AS miner, b.round_id
               FROM blocks b LEFT JOIN miners m ON m.id=b.miner_id
               ORDER BY b.height DESC, b.id DESC LIMIT ?""",
            (limit,),
        )
        return [self._block_row(row) for row in rows]

    def _blocks_for_miner(self, miner_id: int, limit: int) -> list[dict]:
        rows = self.db.fetchall(
            """SELECT b.height, b.hash, b.coinbase_value_satoshi, b.fee_satoshi,
                      b.net_reward_satoshi, b.status, b.found_at, b.matured_at,
                      b.confirmations, m.username AS miner, b.round_id
               FROM blocks b JOIN miners m ON m.id=b.miner_id
               WHERE b.miner_id=? ORDER BY b.height DESC LIMIT ?""",
            (miner_id, limit),
        )
        return [self._block_row(row) for row in rows]

    def _block_row(self, row) -> dict:
        return {
            "height": int(row["height"]),
            "hash": row["hash"],
            "coinbase_value_satoshi": int(row["coinbase_value_satoshi"]),
            "fee_satoshi": int(row["fee_satoshi"]),
            "net_reward_satoshi": int(row["net_reward_satoshi"]),
            "coinbase_value_btcs": str(_from_satoshi(row["coinbase_value_satoshi"])),
            "net_reward_btcs": str(_from_satoshi(row["net_reward_satoshi"])),
            "status": row["status"],
            "miner": row["miner"],
            "round_id": row["round_id"],
            "found_at": row["found_at"],
            "matured_at": row["matured_at"],
            "confirmations": int(row["confirmations"]),
        }

    def hashrate_history(self, range_name: str) -> dict:
        if range_name not in HASHRATE_RANGES:
            raise ValueError("range must be one of 1h, 6h, 24h, 7d")
        seconds, bucket_seconds = HASHRATE_RANGES[range_name]
        now = int(time.time())
        start = now - seconds
        rows = self.db.fetchall(
            """SELECT CAST(created_at / ? AS INTEGER) AS bucket,
                      SUM(difficulty) AS difficulty, COUNT(*) AS shares
               FROM shares
               WHERE accepted=1 AND created_at>=?
               GROUP BY bucket ORDER BY bucket""",
            (bucket_seconds, start),
        )
        by_bucket = {
            int(row["bucket"]): {
                "difficulty": float(row["difficulty"] or 0),
                "shares": int(row["shares"]),
            }
            for row in rows
        }
        first_bucket = start // bucket_seconds
        last_bucket = now // bucket_seconds
        history = []
        for bucket in range(first_bucket, last_bucket + 1):
            values = by_bucket.get(bucket, {"difficulty": 0.0, "shares": 0})
            history.append(
                {
                    "timestamp": bucket * bucket_seconds,
                    "difficulty": values["difficulty"],
                    "shares": values["shares"],
                    "hashrate": values["difficulty"]
                    * HASHES_PER_DIFFICULTY
                    / bucket_seconds,
                }
            )
        return {
            "range": range_name,
            "bucket_seconds": bucket_seconds,
            "history": history,
        }

    def fee_ledger(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        rows = self.db.fetchall(
            """SELECT block_height, block_hash, fee_satoshi,
                      allocated_to_address, status, created_at
               FROM pool_fee_ledger ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
        return [
            {
                **dict(row),
                "fee_btcs": str(_from_satoshi(row["fee_satoshi"])),
            }
            for row in rows
        ]

    # Compatibility helpers retained for existing integrations.
    def share_count(self, miner: str | None = None, accepted: bool = True) -> int:
        account = self.resolve_account(miner) if miner else None
        if account:
            row = self.db.fetchone(
                """SELECT COUNT(*) AS n FROM shares s JOIN miners m ON m.id=s.miner_id
                   WHERE m.username=? AND s.accepted=?""",
                (account, 1 if accepted else 0),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS n FROM shares WHERE accepted=?",
                (1 if accepted else 0,),
            )
        return int(row["n"])

    def get_miner_status(self, miner: str) -> dict | None:
        data = self.get_miner(miner)
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

    def get_pool_fee_ledger(self) -> list:
        return self.fee_ledger()

    def get_round(self, round_id: str) -> dict | None:
        row = self.db.fetchone("SELECT * FROM rounds WHERE round_id=?", (round_id,))
        return dict(row) if row else None

    def close(self):
        # Connections are short-lived; kept for API compatibility.
        return None


def sum_allocations(allocations: Iterable[dict]) -> int:
    return sum(int(item["net_satoshi"]) for item in allocations)
