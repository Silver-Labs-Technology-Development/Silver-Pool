-- Silver Pool initial schema.
-- All monetary amounts are integer satoshis. Timestamps are Unix seconds.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS miners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_seen_at REAL
);

CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    miner_id INTEGER NOT NULL REFERENCES miners(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    UNIQUE (miner_id, name)
);

CREATE TABLE IF NOT EXISTS rounds (
    round_id TEXT PRIMARY KEY,
    height INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'orphaned')),
    total_shares INTEGER NOT NULL DEFAULT 0,
    total_difficulty REAL NOT NULL DEFAULT 0,
    pool_fee_satoshi INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    ended_at REAL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    height INTEGER NOT NULL,
    previousblockhash TEXT NOT NULL,
    clean INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    miner_id INTEGER NOT NULL REFERENCES miners(id),
    worker_id INTEGER NOT NULL REFERENCES workers(id),
    round_id TEXT REFERENCES rounds(round_id),
    job_id TEXT NOT NULL,
    extranonce2 TEXT NOT NULL DEFAULT '',
    ntime TEXT NOT NULL DEFAULT '',
    nonce TEXT NOT NULL DEFAULT '',
    difficulty REAL NOT NULL DEFAULT 1,
    accepted INTEGER NOT NULL DEFAULT 0,
    stale INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    block_candidate INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE (miner_id, job_id, extranonce2, ntime, nonce)
);

CREATE INDEX IF NOT EXISTS idx_shares_round ON shares(round_id);
CREATE INDEX IF NOT EXISTS idx_shares_miner_time ON shares(miner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shares_time ON shares(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shares_accepted_time ON shares(accepted, created_at DESC);

CREATE TABLE IF NOT EXISTS block_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id TEXT REFERENCES rounds(round_id),
    job_id TEXT,
    miner_id INTEGER REFERENCES miners(id),
    worker_id INTEGER REFERENCES workers(id),
    height INTEGER NOT NULL,
    hash TEXT NOT NULL,
    header_hex TEXT NOT NULL,
    block_hex TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'accepted', 'rejected')),
    node_result TEXT,
    created_at REAL NOT NULL,
    submitted_at REAL
);

CREATE INDEX IF NOT EXISTS idx_block_candidates_height ON block_candidates(height);

CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    height INTEGER NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    candidate_id INTEGER REFERENCES block_candidates(id),
    coinbase_value_satoshi INTEGER NOT NULL DEFAULT 0,
    fee_satoshi INTEGER NOT NULL DEFAULT 0,
    net_reward_satoshi INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'immature'
        CHECK (status IN ('immature', 'mature', 'orphaned')),
    miner_id INTEGER REFERENCES miners(id),
    round_id TEXT REFERENCES rounds(round_id),
    found_at REAL NOT NULL,
    matured_at REAL,
    confirmations INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(height DESC);
CREATE INDEX IF NOT EXISTS idx_blocks_status ON blocks(status);

CREATE TABLE IF NOT EXISTS reward_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    round_id TEXT NOT NULL,
    miner_id INTEGER NOT NULL REFERENCES miners(id),
    difficulty REAL NOT NULL,
    gross_satoshi INTEGER NOT NULL,
    fee_satoshi INTEGER NOT NULL,
    net_satoshi INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'orphaned')),
    created_at REAL NOT NULL,
    UNIQUE (block_id, miner_id)
);

CREATE INDEX IF NOT EXISTS idx_allocations_miner ON reward_allocations(miner_id, status);

CREATE TABLE IF NOT EXISTS miner_balances (
    miner_id INTEGER PRIMARY KEY REFERENCES miners(id) ON DELETE CASCADE,
    available_satoshi INTEGER NOT NULL DEFAULT 0,
    immature_satoshi INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pool_fee_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id INTEGER REFERENCES blocks(id),
    block_height INTEGER NOT NULL,
    block_hash TEXT,
    fee_satoshi INTEGER NOT NULL DEFAULT 0,
    allocated_to_address TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'allocated', 'orphaned')),
    created_at REAL NOT NULL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    miner_id INTEGER NOT NULL REFERENCES miners(id),
    address TEXT NOT NULL,
    amount_satoshi INTEGER NOT NULL CHECK (amount_satoshi > 0),
    txid TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'cancelled')),
    error TEXT,
    created_at REAL NOT NULL,
    processed_at REAL,
    UNIQUE (miner_id, txid)
);

CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status, created_at);
