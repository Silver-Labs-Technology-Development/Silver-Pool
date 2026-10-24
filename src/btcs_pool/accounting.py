import sqlite3
import time
from pathlib import Path
from decimal import Decimal, ROUND_DOWN

SATOSHI = Decimal("1")

def _to_satoshi(value) -> Decimal:
    if isinstance(value, Decimal):
        v = value
    else:
        try:
            v = Decimal(str(value))
        except Exception as e:
            raise ValueError(f"Cannot convert {value!r} to Decimal") from e
    return v.quantize(Decimal("1"), rounding=ROUND_DOWN)

def _from_satoshi(satoshis: Decimal) -> Decimal:
    return satoshis / Decimal("100000000")


class Accounting:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self._init()

    def _init(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS miners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            miner TEXT NOT NULL,
            job_id TEXT NOT NULL,
            nonce INTEGER NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            difficulty INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            UNIQUE(miner, job_id, nonce)
        );
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            height INTEGER NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            coinbase_value INTEGER NOT NULL DEFAULT 0,
            fee_amount INTEGER NOT NULL DEFAULT 0,
            net_reward INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT "immature",
            miner TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS miner_balances (
            miner TEXT NOT NULL,
            balance_satoshi INTEGER NOT NULL DEFAULT 0,
            immature_satoshi INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (miner)
        );
        CREATE TABLE IF NOT EXISTS pool_fee_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_height INTEGER,
            block_hash TEXT,
            fee_satoshi INTEGER NOT NULL DEFAULT 0,
            allocated_to_address TEXT,
            status TEXT NOT NULL DEFAULT "pending",
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            miner TEXT NOT NULL,
            amount_satoshi INTEGER NOT NULL DEFAULT 0,
            tx_hash TEXT,
            status TEXT NOT NULL DEFAULT "pending",
            created_at REAL NOT NULL,
            processed_at REAL
        );
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            height_start INTEGER,
            height_end INTEGER,
            total_shares INTEGER NOT NULL DEFAULT 0,
            total_difficulty INTEGER NOT NULL DEFAULT 0,
            pool_fee_satoshi INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(round_id)
        );
        """)
        self.conn.commit()

    def register_miner(self, username: str):
        try:
            self.conn.execute(
                "INSERT INTO miners(username, created_at) VALUES (?,?)", (username, time.time())
            )
            self.conn.execute(
                "INSERT INTO miner_balances(miner, balance_satoshi, immature_satoshi) VALUES (?,0,0)",
                (username,),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def record_share(self, miner: str, job_id: str, nonce: int, accepted: bool, difficulty: int = 1) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO shares(miner, job_id, nonce, accepted, difficulty, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (miner, job_id, nonce, 1 if accepted else 0, difficulty, time.time()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def share_count(self, miner: str | None = None, accepted: bool = True) -> int:
        acc = 1 if accepted else 0
        if miner:
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM shares WHERE miner=? AND accepted=? ", (miner, acc)
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM shares WHERE accepted=? ", (acc,))
        return cur.fetchone()[0]

    def record_block(self,
        height: int,
        block_hash: str,
        coinbase_value_satoshi: int,
        fee_satoshi: int,
        net_reward_satoshi: int,
        miner: str | None = None,
    ):
        self.conn.execute(
            """INSERT INTO blocks(height, hash, coinbase_value, fee_amount, net_reward, status, miner, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                height,
                block_hash,
                coinbase_value_satoshi,
                fee_satoshi,
                net_reward_satoshi,
                "immature",
                miner,
                time.time(),
            ),
        )

        if fee_satoshi > 0:
            self.conn.execute(
                """INSERT INTO pool_fee_ledger(block_height, block_hash, fee_satoshi, allocated_to_address, status, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (height, block_hash, fee_satoshi, "", "pending", time.time()),
            )

        if net_reward_satoshi > 0 and miner:
            self.conn.execute(
                """INSERT INTO miner_balances(miner, balance_satoshi, immature_satoshi)
                   VALUES (?,?,?)
                   ON CONFLICT(miner) DO UPDATE SET
                       immature_satoshi = immature_satoshi + ?""",
                (miner, 0, net_reward_satoshi, net_reward_satoshi),
            )

        self.conn.commit()

    def mature_block_reward(self, height: int, block_hash: str):
        block = self.conn.execute(
            "SELECT miner, net_reward FROM blocks WHERE height=? AND hash=? AND status='immature'",
            (height, block_hash),
        ).fetchone()

        if not block:
            return

        miner, net_reward_satoshi = block

        if net_reward_satoshi <= 0:
            self.conn.execute(
                "UPDATE blocks SET status='mature' WHERE height=? AND hash=?", (height, block_hash)
            )
            self.conn.commit()
            return

        if miner:
            self.conn.execute(
                """INSERT INTO miner_balances(miner, balance_satoshi, immature_satoshi)
                   VALUES (?,?,?)
                   ON CONFLICT(miner) DO UPDATE SET
                       balance_satoshi = balance_satoshi + ?""",
                (miner, 0, 0, net_reward_satoshi),
            )

        self.conn.execute(
            "UPDATE blocks SET status='mature' WHERE height=? AND hash=?", (height, block_hash)
        )

        self.conn.execute(
            "UPDATE pool_fee_ledger SET status='allocated' WHERE block_height=? AND status='pending' LIMIT 1",
            (height,),
        )

        self.conn.commit()

    def request_payout(self, miner: str, amount_satoshi: int, min_payout_satoshi: int = 100000) -> int | None:
        if amount_satoshi < min_payout_satoshi:
            return None

        miner_row = self.conn.execute(
            "SELECT balance_satoshi, immature_satoshi FROM miner_balances WHERE miner=?",
            (miner,),
        ).fetchone()

        if not miner_row:
            return None

        balance_satoshi, immature_satoshi = miner_row
        available = balance_satoshi

        if available < amount_satoshi:
            return None

        payout_id = self.conn.execute(
            """INSERT INTO payouts(miner, amount_satoshi, status, created_at, processed_at)
               VALUES (?,?, 'pending', ?, NULL)""",
            (miner, amount_satoshi, time.time()),
        )
        self.conn.commit()
        return payout_id

    def pay_payout(self, payout_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT id, miner, amount_satoshi, status FROM payouts WHERE id=?", (payout_id,)
        ).fetchone()

        if not row:
            return None

        payout_id_db, miner, amount_satoshi, status = row
        if status != "pending":
            return None

        self.conn.execute(
            "UPDATE miner_balances SET balance_satoshi = balance_satoshi - ? WHERE miner=?",
            (amount_satoshi, miner),
        )
        self.conn.execute(
            "UPDATE payouts SET status='processed', processed_at=? WHERE id=?",
            (time.time(), payout_id_db),
        )

        self.conn.commit()
        return ""

    def get_miner_status(self, miner: str) -> dict | None:
        row = self.conn.execute(
            "SELECT balance_satoshi, immature_satoshi FROM miner_balances WHERE miner=?",
            (miner,),
        ).fetchone()

        if not row:
            return None

        balance_satoshi, immature_satoshi = row
        return {
            "miner": miner,
            "available_satoshi": str(_from_satoshi(balance_satoshi)),
            "immature_satoshi": str(_from_satoshi(immature_satoshi)),
            "total_satoshi": str(_from_satoshi(balance_satoshi + immature_satoshi)),
        }

    def get_pool_fee_ledger(self) -> list:
        cur = self.conn.execute(
            "SELECT block_height, fee_satoshi, allocated_to_address, status, created_at FROM pool_fee_ledger ORDER BY created_at"
        )
        return [
            {
                "block_height": row[0],
                "fee_satoshi": row[1],
                "allocated_to_address": row[2],
                "status": row[3],
                "created_at": row[4],
            }
            for row in cur
        ]

    def close(self):
        self.conn.close()
