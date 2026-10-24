# Silver Pool — Implementation Status

**Last updated**: 2026-10-24

## Project Identity

| Field | Value |
|---|---|
| **Product name** | Silver Pool |
| **Organization** | Silver Labs Technology & Development |
| **Primary blockchain** | Bitcoin Silver (BTCS) |
| **GitHub repository** | `https://github.com/Silver-Labs-Technology-Development/Silver-Pool.git` |
| **Local checkout path** | `/home/user/Silver-Labs/Silver-Pool` |
| **Default branch** | `main` |
| **Git remote** | `origin` → `https://github.com/Silver-Labs-Technology-Development/Silver-Pool.git` |

## Source Code Overview

| Module | Status | Key Functions |
|---|---|---|
| `block.py` | Implemented | `dsha256`, `reverse_bytes`, `encode_height`, `varint`, `build_coinbase_tx`, `build_block_bytes`, `block_hash`, `target_from_bits` |
| `stratum.py` | Implemented | Stratum server with `mining.subscribe`, `mining.authorize`, `mining.notify`, `mining.submit`; job polling; share validation; block submission via RPC |
| `accounting.py` | Implemented | SQLite-backed miner/shares/blocks tracking with UNIQUE constraints; duplicate detection |
| `rpc.py` | Implemented | BTCS RPC client: `getblocktemplate`, `submitblock`, `getblockchaininfo`, `getmininginfo`, `getaddressinfo`, `getnewaddress` |
| `config.py` | Implemented | `PoolConfig` dataclass with env-variable overrides; RPC URL, user, password, wallet, pool address, stratum settings, DB path, poll interval, extranonce2 size, difficulty, pool fee (2%) |
| `api_server.py` | Implemented | HTTP API server on port 8080 with endpoints: `/pool/status`, `/pool/miners`, `/pool/statistics`, `/pool/blocks/recent`, `/health` |

## Configuration

- **Pool fee**: 2.0% (default in `config.py`, configurable via `BTCS_POOL_FEE` env var)
- **RPC URL**: `http://127.0.0.1:18443` (overrideable via `BTCS_RPC_URL`)
- **RPC user**: `test` (overrideable via `BTCS_RPC_USER`)
- **RPC password**: `test` (overrideable via `BTCS_RPC_PASSWORD`)
- **Stratum port**: 3333 (overrideable via `BTCS_STRATUM_PORT`)
- **Database**: `data/pool.sqlite3` (SQLite with WAL mode)

## Test Results

| Test File | Tests | Status |
|---|---|---|
| `tests/test_block.py` | 3/3 | PASS (encode_height, varint, dsha256) |
| `tests/test_accounting.py` | 1/1 | PASS (share duplicate detection) |
| **Total** | **4/4** | **PASS** |

## Known Limitations

- No live payouts (payout mechanism disabled until security review)
- No mainnet pool operations (regtest/testnet only)
- Website is developer preview, not production-deployed
- Automatic payouts disabled until verified

## API Endpoints

The following HTTP API endpoints are available on the pool API server (port 8080):

- `GET /pool/status` - Pool status (difficulty, network hashrate, mining status)
- `GET /pool/miners` - List of registered miners with share counts and blocks
- `GET /pool/statistics` - Pool statistics (difficulty, total shares, fee ledger, blocks found)
- `GET /pool/blocks/recent` - Recent blocks found by the pool
- `GET /health` - Health check

## Pool Modes

- **Solo mining**: Each miner submits valid shares; block submitted when conditions met; dashboard shows shares, hashrate, accepted/rejected, blocks found
- **Shared pool mining**: PPLNS-style reward distribution; shares tracked by round; fee calculated as 2% of distributable rewards

## BTCS Node Connection

- Node running in regtest mode
- RPC accessible at `http://127.0.0.1:18443` with `rpcuser=test` and `rpcpassword=test`
- Block templates retrievable via `getblocktemplate`
- Block submission via `submitblock` working
- Block validation and chain tracking functional

## Website

- Vite-based static site in `site/`
- Routes: `/`, `/statistics`, `/miners`, `/miner`, `/blocks`, `/getting-started`, `/pool`, `/api-docs`, `/status`, `/help`
- API base URL configurable via `API_BASE_URL` environment variable
- Currently configured to connect to `http://127.0.0.1:8080` (API server)

## Next Steps

- Implement full PPLNS shared pool accounting
- Add comprehensive test suite (stratum lifecycle, share validation, fee calculation)
- Create miner connection guide documentation
- Implement production deployment configuration
- Add reorganization handling in accounting