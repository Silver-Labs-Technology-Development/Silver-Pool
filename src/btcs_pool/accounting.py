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

def calculate_pplns_reward(miner_shares: int, round_total_shares: int, 
                           coinbase_value: int, pool_fee_percent: float) -> dict:
    """Calculate PPLNS reward for a miner.
    
    
    Returns dict with:
    - gross_satoshi: total coinbase value allocated
    - fee_satoshi: pool fee amount
    - net_satoshi: reward after fee
    """
    if round_total_shares == 0:
        return {
            "gross_satoshi": Decimal("0"),
            "fee_satoshi": Decimal("0"),
            "net_satoshi": Decimal("0"),
        }
    
    # Calculate miner's share of the reward
    # Integer-precision arithmetic: (miner_shares * coinbase_value) // round_total_shares
    gross_satoshi = (Decimal(miner_shares) * Decimal(coinbase_value)) / Decimal(round_total_shares)
    
    # Apply pool fee (percentage of gross)
    fee_percent = Decimal(pool_fee_percent)
    fee_satoshi = (gross_satoshi * fee_percent / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    
    # Net reward after fee
    net_satoshi = gross_satoshi - fee_satoshi
    
    return {
        "gross_satoshi": gross_satoshi.quantize(Decimal("1"), rounding=ROUND_DOWN),
        "fee_satoshi": fee_satoshi,
        "net_satoshi": net_satoshi.quantize(Decimal("1"), rounding=ROUND_DOWN),
    }


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
            round_id TEXT,
            UNIQUE(miner, job_id, nonce)
        );
        CREATE TABLE IF NOT EXISTS rounds (
            round_id TEXT PRIMARY KEY NOT NULL,
            height_start INTEGER NOT NULL DEFAULT 0,
            height_end INTEGER DEFAULT 0,
            total_shares INTEGER NOT NULL DEFAULT 0,
            total_difficulty INTEGER NOT NULL DEFAULT 0,
            pool_fee_satoshi INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT \"active\",
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_shares_round ON shares(round_id);
        CREATE INDEX IF NOT EXISTS idx_shares_miner ON shares(miner);
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

        # Migration: add round_id column to existing shares table if missing
        try:
            self.conn.execute("ALTER TABLE shares ADD COLUMN round_id TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
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

    def record_share(self, miner: str, job_id: str, nonce: int, accepted: bool, difficulty: int = 1, round_id: str | None = None) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO shares(miner, job_id, nonce, accepted, difficulty, created_at, round_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (miner, job_id, nonce, 1 if accepted else 0, difficulty, time.time(), round_id),
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
                   VALUES (?,?,?,?,?,?,?)""",
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

    def start_round(self, round_id: str, height_start: int) -> bool:
        """Start a new PPLNS round."""
        try:
            self.conn.execute(
                "INSERT INTO rounds(round_id, height_start, total_shares, total_difficulty, pool_fee_satoshi, status, created_at) VALUES (?,?,0,0,0,'active',?)",
                (round_id, height_start, time.time()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def end_round(self, round_id: str, height_end: int, pool_fee_satoshi: int) -> bool:
        """End a PPLNS round and record its fee."""
        try:
            self.conn.execute(
                "UPDATE rounds SET height_end=?, pool_fee_satoshi=?, status='completed' WHERE round_id=?",
                (height_end, pool_fee_satoshi, round_id),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def get_round(self, round_id: str) -> dict | None:
        """Get round information by round_id."""
        row = self.conn.execute(
            "SELECT round_id, height_start, height_end, total_shares, total_difficulty, pool_fee_satoshi, status, created_at FROM rounds WHERE round_id=?",
            (round_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "round_id": row[0],
            "height_start": row[1],
            "height_end": row[2],
            "total_shares": row[3],
            "total_difficulty": row[4],
            "pool_fee_satoshi": row[5],
            "status": row[6],
            "created_at": row[7],
        }

    def update_round_totals(self, round_id: str, shares_added: int, difficulty_added: int) -> bool:
        """Update cumulative share and difficulty totals for a round."""
        try:
            self.conn.execute(
                "UPDATE rounds SET total_shares = total_shares + ?, total_difficulty = total_difficulty + ? WHERE round_id=?",
                (shares_added, difficulty_added, round_id),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def record_share_round(self, miner: str, job_id: str, nonce: int, accepted: bool, difficulty: int = 1, round_id: str | None = None) -> bool:
        """Record a share and update round totals if round_id is provided."""
        if round_id is None:
            return self.record_share(miner, job_id, nonce, accepted, difficulty)
        try:
            self.conn.execute(
                """INSERT INTO shares(miner, job_id, nonce, accepted, difficulty, created_at, round_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (miner, job_id, nonce, 1 if accepted else 0, difficulty, time.time(), round_id),
            )
            if accepted:
                self.update_round_totals(round_id, 1, difficulty)
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def close(self):
        self.conn.close()
