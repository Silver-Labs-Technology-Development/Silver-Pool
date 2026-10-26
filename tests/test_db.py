from __future__ import annotations

import sqlite3
import time

import pytest

from btcs_pool.db import Database


def test_fresh_database_migrations_and_wal(db_path):
    database = Database(db_path)
    migrations = database.fetchall("SELECT * FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in migrations] == [1]
    tables = {
        row["name"]
        for row in database.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    }
    assert {
        "miners",
        "workers",
        "shares",
        "rounds",
        "blocks",
        "block_candidates",
        "reward_allocations",
        "miner_balances",
        "pool_fee_ledger",
        "payouts",
        "schema_migrations",
    } <= tables
    mode = database.fetchone("PRAGMA journal_mode")[0]
    assert mode.lower() == "wal"
    assert database.fetchall("PRAGMA foreign_key_check") == []


def test_reopen_is_idempotent_and_persistent(db_path):
    first = Database(db_path)
    first.execute(
        "INSERT INTO miners(username, created_at, last_seen_at) VALUES (?,?,?)",
        ("alice", 100.0, 100.0),
    )
    second = Database(db_path)
    assert second.fetchone("SELECT COUNT(*) AS n FROM miners")["n"] == 1
    versions = second.fetchall("SELECT version FROM schema_migrations")
    assert [row["version"] for row in versions] == [1]


def test_transaction_rolls_back_on_constraint_failure(db_path):
    database = Database(db_path)
    database.execute(
        "INSERT INTO miners(username, created_at, last_seen_at) VALUES (?,?,?)",
        ("alice", 1.0, 1.0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO miners(username, created_at, last_seen_at) VALUES (?,?,?)",
                ("bob", 1.0, 1.0),
            )
            conn.execute(
                "INSERT INTO miners(username, created_at, last_seen_at) VALUES (?,?,?)",
                ("alice", 1.0, 1.0),
            )
    assert database.fetchone("SELECT COUNT(*) AS n FROM miners")["n"] == 1


def test_backup_is_readable(db_path, tmp_path):
    database = Database(db_path)
    database.execute(
        "INSERT INTO miners(username, created_at, last_seen_at) VALUES (?,?,?)",
        ("alice", 1.0, 1.0),
    )
    destination = tmp_path / "backup.sqlite3"
    database.backup(destination)
    copy = sqlite3.connect(destination)
    try:
        assert copy.execute("SELECT username FROM miners").fetchone()[0] == "alice"
    finally:
        copy.close()


def _legacy_database(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE miners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE TABLE shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner TEXT NOT NULL,
                job_id TEXT NOT NULL,
                nonce INTEGER NOT NULL,
                accepted INTEGER NOT NULL,
                difficulty REAL NOT NULL,
                created_at REAL NOT NULL,
                round_id TEXT
            );
            CREATE TABLE rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id TEXT NOT NULL,
                height_start INTEGER NOT NULL,
                height_end INTEGER,
                total_shares INTEGER NOT NULL,
                total_difficulty REAL NOT NULL,
                pool_fee_satoshi INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                height INTEGER NOT NULL,
                hash TEXT NOT NULL,
                coinbase_value INTEGER NOT NULL,
                fee_amount INTEGER NOT NULL,
                net_reward INTEGER NOT NULL,
                status TEXT NOT NULL,
                miner TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE miner_balances (
                miner TEXT PRIMARY KEY,
                balance_satoshi INTEGER NOT NULL,
                immature_satoshi INTEGER NOT NULL
            );
            CREATE TABLE pool_fee_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_height INTEGER NOT NULL,
                block_hash TEXT,
                fee_satoshi INTEGER NOT NULL,
                allocated_to_address TEXT,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner TEXT NOT NULL,
                amount_satoshi INTEGER NOT NULL,
                tx_hash TEXT,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                processed_at REAL
            );
            """
        )
        conn.execute(
            "INSERT INTO miners(username, created_at) VALUES (?,?)", ("miner1", 1000.0)
        )
        conn.execute(
            """INSERT INTO rounds(
                   round_id, height_start, height_end, total_shares,
                   total_difficulty, pool_fee_satoshi, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("round-1", 100, 101, 2, 3.5, 100000, 1000.0),
        )
        conn.execute(
            """INSERT INTO shares(
                   miner, job_id, nonce, accepted, difficulty, created_at, round_id)
               VALUES (?,?,?,?,?,?,?)""",
            ("miner1", "job1", 123, 1, 1.5, 1001.0, "round-1"),
        )
        conn.execute(
            """INSERT INTO blocks(
                   height, hash, coinbase_value, fee_amount, net_reward, status, miner, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (100, "aa" * 32, 5_000_000_000, 100_000_000, 4_900_000_000, "mature", "miner1", 1000.0),
        )
        conn.execute(
            "INSERT INTO miner_balances(miner, balance_satoshi, immature_satoshi) VALUES (?,?,?)",
            ("miner1", 4_900_000_000, 0),
        )
        conn.execute(
            """INSERT INTO pool_fee_ledger(
                   block_height, block_hash, fee_satoshi, allocated_to_address, status, created_at)
               VALUES (?,?,?,?,?,?)""",
            (100, "aa" * 32, 100_000_000, "fee-address", "allocated", 1000.0),
        )
        conn.execute(
            """INSERT INTO payouts(
                   miner, amount_satoshi, tx_hash, status, created_at, processed_at)
               VALUES (?,?,?,?,?,?)""",
            ("miner1", 500_000, "txid-1", "sent", 1002.0, 1003.0),
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_schema_is_quarantined_and_imported(tmp_path):
    path = str(tmp_path / "legacy.sqlite3")
    _legacy_database(path)
    database = Database(path)

    tables = {
        row["name"] for row in database.fetchall("SELECT name FROM sqlite_master")
    }
    assert {"legacy_miners", "legacy_shares", "legacy_blocks"} <= tables
    assert database.fetchone("SELECT COUNT(*) AS n FROM miners")["n"] == 1
    miner = database.fetchone("SELECT * FROM miners")
    assert miner["username"] == "miner1"
    assert miner["last_seen_at"] == 1000.0
    assert database.fetchone("SELECT COUNT(*) AS n FROM workers")["n"] == 1
    assert database.fetchone("SELECT COUNT(*) AS n FROM shares")["n"] == 1
    share = database.fetchone("SELECT * FROM shares")
    assert share["round_id"] == "round-1"
    assert share["accepted"] == 1
    round_row = database.fetchone("SELECT * FROM rounds")
    assert round_row["status"] == "completed"
    assert round_row["total_difficulty"] == 3.5
    block = database.fetchone("SELECT * FROM blocks")
    assert block["height"] == 100
    assert block["net_reward_satoshi"] == 4_900_000_000
    balance = database.fetchone("SELECT * FROM miner_balances")
    assert balance["available_satoshi"] == 4_900_000_000
    fee = database.fetchone("SELECT * FROM pool_fee_ledger")
    assert fee["status"] == "allocated"
    payout = database.fetchone("SELECT * FROM payouts")
    assert payout["status"] == "sent"
    assert payout["txid"] == "txid-1"
    assert database.fetchall("PRAGMA foreign_key_check") == []

    # Reopening must not duplicate imported rows.
    Database(path)
    assert database.fetchone("SELECT COUNT(*) AS n FROM miners")["n"] == 1
    assert database.fetchone("SELECT COUNT(*) AS n FROM shares")["n"] == 1
    assert database.fetchone("SELECT COUNT(*) AS n FROM payouts")["n"] == 1


def test_database_requires_explicit_path(tmp_path):
    with pytest.raises(TypeError):
        Database()  # type: ignore[call-arg]
