"""SQLite persistence with explicit, ordered schema migrations.

The pool uses SQLite in WAL mode with a persistent volume. All writes use
short ``BEGIN IMMEDIATE`` transactions so the Stratum and API processes can
share one database safely on a single node. SQLite is not a horizontally
scalable HA database; the deployment documentation states that limitation.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
LEGACY_TABLES = (
    "miners",
    "workers",
    "shares",
    "rounds",
    "blocks",
    "miner_balances",
    "pool_fee_ledger",
    "payouts",
    "block_candidates",
    "reward_allocations",
    "jobs",
)


class Database:
    def __init__(self, path: str | Path, timeout: float = 30.0):
        self.path = Path(path)
        self.timeout = timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=self.timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        return conn

    def connect(self) -> sqlite3.Connection:
        return self._connect()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetchone(self, sql: str, params: Sequence = ()) -> sqlite3.Row | None:
        conn = self._connect()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def fetchall(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence = ()) -> int:
        with self.transaction() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    def initialize(self) -> None:
        with self.transaction() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "schema_migrations" not in tables:
                if any(name in tables for name in LEGACY_TABLES):
                    log.warning("legacy_database_detected path=%s action=quarantine", self.path)
                    self._quarantine_legacy(conn, tables)
                self._apply_migrations(conn)
                self._import_legacy(conn, tables)
            else:
                self._apply_migrations(conn)

    def _quarantine_legacy(self, conn: sqlite3.Connection, tables: set[str]) -> None:
        existing = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in LEGACY_TABLES:
            if table in existing:
                legacy = f"legacy_{table}"
                conn.execute(f'ALTER TABLE "{table}" RENAME TO "{legacy}"')
                log.info("legacy_table_renamed old=%s new=%s", table, legacy)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   applied_at REAL NOT NULL
               )"""
        )
        applied = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for path in files:
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError:
                log.warning("migration_skipped name=%s reason=bad-name", path.name)
                continue
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                (version, path.name, time.time()),
            )
            log.info("migration_applied version=%s file=%s", version, path.name)

    def _columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {
                row["name"]
                for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
        except sqlite3.Error:
            return set()

    def _import_legacy(self, conn: sqlite3.Connection, original_tables: set[str]) -> None:
        present = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "legacy_miners" not in present:
            return

        now = time.time()
        miner_cols = self._columns(conn, "legacy_miners")
        last_seen_expr = "last_seen_at" if "last_seen_at" in miner_cols else "created_at"
        conn.execute(
            f"""INSERT OR IGNORE INTO miners(username, created_at, last_seen_at)
               SELECT username, created_at, COALESCE({last_seen_expr}, created_at)
               FROM legacy_miners"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO workers(miner_id, name, created_at, last_seen_at)
               SELECT m.id, 'default', m.created_at, m.last_seen_at
               FROM miners m"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO miner_balances(miner_id, available_satoshi, immature_satoshi)
               SELECT m.id, 0, 0 FROM miners m"""
        )

        round_cols = self._columns(conn, "legacy_rounds")
        if {"round_id", "height_start", "total_shares", "total_difficulty", "created_at"} <= round_cols:
            height_end = "height_end" if "height_end" in round_cols else "NULL"
            ended_at = "NULL" if height_end == "NULL" else "created_at"
            conn.execute(
                f"""INSERT OR IGNORE INTO rounds(
                        round_id, height, status, total_shares, total_difficulty,
                        pool_fee_satoshi, started_at, ended_at)
                    SELECT round_id, height_start,
                           CASE WHEN {height_end} IS NULL THEN 'active' ELSE 'completed' END,
                           COALESCE(total_shares, 0), COALESCE(total_difficulty, 0),
                           COALESCE(pool_fee_satoshi, 0), created_at,
                           {ended_at}
                    FROM legacy_rounds"""
            )

        share_cols = self._columns(conn, "legacy_shares")
        if {"miner", "job_id", "nonce", "accepted", "difficulty", "created_at"} <= share_cols:
            round_expr = (
                "CASE WHEN s.round_id IN (SELECT round_id FROM rounds) THEN s.round_id ELSE NULL END"
                if "round_id" in share_cols
                else "NULL"
            )
            stale_expr = "COALESCE(s.stale, 0)" if "stale" in share_cols else "0"
            conn.execute(
                f"""INSERT OR IGNORE INTO shares(
                        miner_id, worker_id, round_id, job_id, extranonce2, ntime,
                        nonce, difficulty, accepted, stale, reject_reason,
                        block_candidate, created_at)
                    SELECT m.id, w.id, {round_expr},
                           s.job_id, '', '', CAST(s.nonce AS TEXT),
                           CAST(s.difficulty AS REAL), s.accepted, {stale_expr},
                           NULL, 0, s.created_at
                    FROM legacy_shares s
                    JOIN miners m ON m.username = s.miner
                    JOIN workers w ON w.miner_id = m.id AND w.name = 'default'"""
            )

        block_cols = self._columns(conn, "legacy_blocks")
        if {"height", "hash", "coinbase_value", "fee_amount", "net_reward", "status", "miner", "created_at"} <= block_cols:
            conn.execute(
                """INSERT OR IGNORE INTO blocks(
                        height, hash, coinbase_value_satoshi, fee_satoshi,
                        net_reward_satoshi, status, miner_id, found_at)
                   SELECT b.height, b.hash, b.coinbase_value, b.fee_amount,
                          b.net_reward,
                          CASE WHEN b.status IN ('immature','mature','orphaned')
                               THEN b.status ELSE 'immature' END,
                          m.id, b.created_at
                   FROM legacy_blocks b
                   LEFT JOIN miners m ON m.username = b.miner"""
            )

        if self._columns(conn, "legacy_miner_balances"):
            conn.execute(
                """UPDATE miner_balances
                   SET available_satoshi = COALESCE((
                           SELECT balance_satoshi FROM legacy_miner_balances b
                           WHERE b.miner = (SELECT username FROM miners m WHERE m.id = miner_balances.miner_id)
                       ), available_satoshi),
                       immature_satoshi = COALESCE((
                           SELECT immature_satoshi FROM legacy_miner_balances b
                           WHERE b.miner = (SELECT username FROM miners m WHERE m.id = miner_balances.miner_id)
                       ), immature_satoshi)"""
            )

        fee_cols = self._columns(conn, "legacy_pool_fee_ledger")
        if {"block_height", "fee_satoshi", "allocated_to_address", "status", "created_at"} <= fee_cols:
            conn.execute(
                """INSERT INTO pool_fee_ledger(
                        block_height, block_hash, fee_satoshi, allocated_to_address,
                        status, created_at, updated_at)
                   SELECT block_height, block_hash, fee_satoshi,
                          COALESCE(allocated_to_address, ''),
                          CASE WHEN status IN ('pending','allocated','orphaned')
                               THEN status ELSE 'pending' END,
                          created_at, ?
                   FROM legacy_pool_fee_ledger"""
                , (now,)
            )

        payout_cols = self._columns(conn, "legacy_payouts")
        if {"miner", "amount_satoshi", "status", "created_at"} <= payout_cols:
            txid = "tx_hash" if "tx_hash" in payout_cols else "NULL"
            processed = "processed_at" if "processed_at" in payout_cols else "NULL"
            conn.execute(
                f"""INSERT INTO payouts(
                        miner_id, address, amount_satoshi, txid, status, created_at,
                        processed_at)
                    SELECT m.id, '', p.amount_satoshi, p.{txid},
                           CASE WHEN p.status IN ('pending','processing','sent','failed','cancelled')
                                THEN p.status ELSE 'pending' END,
                           p.created_at, p.{processed}
                    FROM legacy_payouts p
                    JOIN miners m ON m.username = p.miner"""
            )

        log.info("legacy_import_complete path=%s", self.path)

    def backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination
