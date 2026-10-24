# Silver Pool

> **Status: Prototype — local regtest pool operational.**
> Pool server accepts connections, resolves pool address, serves block templates,
> validates shares, submits accepted blocks to the local regtest node, and
> advances chain height.

## Purpose

Silver Pool is the mining-pool product for Silver Labs Technology & Development.
It provides a Bitcoin Silver (BTCS) mining pool with Stratum server, share
validation, block-template handling, and payout accounting.

Pool mining is distinct from BTCS L2 sequencing. L2 block production is not
proof-of-work mining and must not be described as such.

## Mining Instructions

- **Algorithm**: Bitcoin Silver (BTCS) — SHA256d-based proof-of-work
- **Miner software**: Any Stratum-compatible Bitcoin Silver miner
- **Pool server hostname**: `127.0.0.1` (local regtest) or configured endpoint
- **Stratum port**: `3333` (default) or `BTCS_STRATUM_PORT` environment variable
- **Worker naming**: `worker_name` or configured via `BTCS_WORKER_NAME`
- **Pool configuration**: Set `BTCS_RPC_URL`, `BTCS_RPC_USER`, `BTCS_RPC_PASSWORD`,
  `BTCS_RPC_WALLET`, `BTCS_STRATUM_PORT`, and `BTCS_POOL_DB` environment variables

## Pool Configuration

Environment variables controlling pool behavior:

| Variable | Default | Description |
|---|---|---|
| `BTCS_RPC_URL` | `http://127.0.0.1:29444` | BTCS Core RPC endpoint |
| `BTCS_RPC_USER` | `test` | RPC username |
| `BTCS_RPC_PASSWORD` | `test` | RPC password |
| `BTCS_RPC_WALLET` | `pooltest` | RPC wallet name |
| `BTCS_STRATUM_PORT` | `3333` | Stratum server port |
| `BTCS_POOL_DB` | `data/pool.sqlite3` | SQLite database path |
| `BTCS_POOL_ADDRESS` | `` | Pool receiving address |
| `BTCS_WORKER_NAME` | `` | Worker name suffix |

## Proposed scope

- Stratum connection handling and miner authorization
- Job/template distribution and stale-share handling
- Share validation against the configured BTCS network target
- Block submission and confirmation tracking
- Payout accounting with an explicit scheme and audit trail
- Pool operations: health, logging, restart, and reconciliation

## Explicitly out of scope until reviewed and approved

- Real-fund payouts or custody of miner balances
- Mainnet pool operations
- Claims of uptime, hashrate, or profitability
- Copying GPL or other upstream code without preserving notices and meeting
  license obligations

## Integration points

- **BTCS Core** — `getblocktemplate`, `submitblock`, chain state, and mining RPC
- **Silver Scan** — block and payout visibility (future)
- **SilverPay** — future payout-account boundary (if justified)
- **silver-labs-platform** — shared schemas where applicable

## Implementation status

Core modules implemented and verified:

- **block.py**: coinbase TX with witness commitment, merkle root computation,
  80-byte header assembly, double-SHA256 hashing, target-from-bits conversion
- **stratum.py**: subscribe/authorize/notify/submit methods, job polling loop,
  share validation against block hash target, block submission via RPC,
  duplicate-share protection in accounting
- **accounting.py**: SQLite-backed miner/shares/blocks tracking with UNIQUE
  constraints and duplicate detection
- **server.py**: config loading, pool address auto-resolution from RPC, server
  startup

Unit tests: 4/4 passing

End-to-end: miner connects → receives job → finds share → pool validates → block
submitted → chain height increments (tested on local regtest)

## Repository facts

- Local checkout directory: `~/Silver-Labs/Silver-Pool`
- Default branch: `main`
- Remote: `origin` at `https://github.com/Silver-Labs-Technology-Development/Silver-Pool.git`
- License: preserved from original; see `LICENSE`
- Visibility: public development repository

## Repository layout

```text
.
├── README.md
├── LICENSE
├── SECURITY.md
├── .gitignore
├── docs/
│   └── ARCHITECTURE.md
└── src/
    └── btcs_pool/
        ├── block.py
        ├── accounting.py
        ├── stratum.py
        ├── rpc.py
        ├── config.py
        └── server.py
tests/
├── test_block.py
└── test_accounting.py
```

## Architecture note

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) records the component breakdown
and threat model. It is subordinate to the scope above and does not authorize
implementation without proper review.

## Security

See [`SECURITY.md`](SECURITY.md) for the reporting policy and security
boundaries. No production funds should be used until the pool is verified with
a local regtest node and the payout mechanism has been audited.

## License

The original license terms apply. See `LICENSE`. This repository is public for
review and development, not for reuse or redistribution without authorization.

## First milestone

A local regtest pool that accepts a test miner, validates shares, submits a
block through BTCS Core, and produces a reconciled test payout ledger. No real
funds.
