import sqlite3
import time
from pathlib import Path


class Accounting:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
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
            accepted INTEGER NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(miner, job_id, nonce)
        );
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            height INTEGER NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            miner TEXT,
            created_at REAL NOT NULL
        );
        """)
        self.conn.commit()

    def register_miner(self, username: str):
        try:
            self.conn.execute("INSERT INTO miners(username, created_at) VALUES (?,?)", (username, time.time()))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def record_share(self, miner: str, job_id: str, nonce: int, accepted: bool) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO shares(miner, job_id, nonce, accepted, created_at) VALUES (?,?,?,?,?)",
                (miner, job_id, nonce, 1 if accepted else 0, time.time()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # duplicate

    def record_block(self, height: int, block_hash: str, miner: str | None = None):
        self.conn.execute(
            "INSERT OR IGNORE INTO blocks(height, hash, miner, created_at) VALUES (?,?,?,?)",
            (height, block_hash, miner, time.time()),
        )
        self.conn.commit()

    def share_count(self, miner: str | None = None) -> int:
        if miner:
            cur = self.conn.execute("SELECT COUNT(*) FROM shares WHERE miner=? AND accepted=1", (miner,))
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM shares WHERE accepted=1")
        return cur.fetchone()[0]

    def close(self):
        self.conn.close()
