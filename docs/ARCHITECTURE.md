# Silver Pool architecture

**Status:** describes the implemented local prototype, verified against a real
Bitcoin Silver Core `v31.1.3` regtest node on 2026-10-26. It does not describe a
live public or mainnet deployment.

## Process topology

```text
                       Bitcoin Silver P2P
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│ BTCS Core (bitcoinsilverd)                                    │
│  • chain, mempool, wallet                                     │
│  • getblocktemplate / submitblock / getblockchaininfo         │
│  • RPC bound to the private Compose network, never published  │
└──────────────────────────────┬────────────────────────────────┘
                               │ JSON-RPC (Basic auth)
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ silver-pool process (python -m btcs_pool.server)              │
│                                                               │
│  stratum.py ── jobs/shares ──► accounting.py ──► SQLite WAL   │
│      ▲                              │                         │
│      │ TCP :3333                    │ read models             │
│      │                              ▼                         │
│  miners                       api.py (aiohttp) :8765          │
│                                     ▲                         │
└─────────────────────────────────────┼─────────────────────────┘
                                      │ /api reverse proxy
                                      │
                              ┌───────┴────────┐
                              │ Caddy  (web)   │
                              │ static site    │
                              └───────┬────────┘
                                      │ HTTPS
                                   browsers
```

One pool process owns both Stratum and the HTTP API so they share the same
in-memory node monitor, job state and SQLite database. The API-only helper
`pool_api_server.py` can run separately during frontend development, but it is
not the deployment entrypoint.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Environment/JSON configuration, validation, public redacted view |
| `rpc.py` | Minimal authenticated BTCS Core JSON-RPC client; base and wallet endpoints |
| `node.py` | Cached node snapshot: chain, sync progress, connections, mempool, errors |
| `block.py` | BIP34 height, varint, coinbase with witness commitment, merkle root/branch, header, target arithmetic |
| `db.py` | SQLite WAL connection, ordered SQL migrations, short `BEGIN IMMEDIATE` transactions, legacy import |
| `migrations/001_initial.sql` | Miners, workers, rounds, jobs, shares, block candidates, blocks, allocations, balances, fee ledger, payouts |
| `accounting.py` | Share recording, round rotation, difficulty-weighted PPLNS, maturity/orphan reconciliation, read models |
| `stratum.py` | Stratum V1 sessions, authorization, jobs, difficulty, share validation, block submission |
| `api.py` | Read-only aiohttp API, envelopes, CORS, rate limiting, validation, health/readiness, OpenAPI |
| `server.py` | Startup, coinbase script resolution, API and Stratum listeners, template and maturity tasks, shutdown |

## Stratum flow

1. **Subscribe** — the server returns a fresh `extranonce1` and the configured
   `extranonce2_size`.
2. **Difficulty** — the server sends the configured static difficulty. A miner
   may request `mining.suggest_difficulty`; the server clamps/validates it and
   applies it to that session. There is no automatic vardiff.
3. **Authorize** — the username is parsed as `account` or `account.worker`.
   The account owns balances; the worker is the suffix after the final dot.
   A configured `BTCS_STRATUM_PASSWORD` is required; otherwise any non-empty
   password is accepted. Invalid identities are rejected.
4. **Notify** — after authorization, the current job is sent. A new job is
   created when the template signature changes: previous block hash, height,
   version, bits or transaction IDs. A changed previous hash produces a clean
   job.
5. **Submit** — the server checks the job exists, the previous hash still
   matches the current template, `extranonce2` length, hex fields, `ntime`
   range, and proof of work. The share target is
   `max(block_target, difficulty_target)` so a block candidate is always also a
   valid share.
6. **Duplicate protection** — `(miner_id, job_id, extranonce2, ntime, nonce)` is
   unique. A duplicate is rejected without double-counting.
7. **Stale shares** — a submitted job whose previous hash no longer matches the
   current template is recorded as rejected and stale.
8. **Block candidate** — if the hash meets the node target, the pool assembles
   the full block and calls `submitblock`. `None` means accepted; `"duplicate"`
   is accepted only if `getblockhash(height)` equals the candidate hash. Other
   results are recorded as rejected candidates, not blocks.

## Block assembly

`build_coinbase_parts` splits the coinbase transaction around the miner's
`extranonce1 + extranonce2` so `mining.notify` can send `coinb1`/`coinb2`.
The coinbase:

- pays `coinbasevalue` to the configured pool script,
- includes the template's `default_witness_commitment` when present,
- encodes the height with BIP34 rules (including the `OP_0` and `OP_1`–`OP_16`
  cases),
- includes the witness reserved value in the segwit block serialization; the
  coinbase txid is the double-SHA256 of the legacy serialization.

`build_block` reverses template txids from display order to internal byte order,
builds the merkle root from the coinbase plus template transactions, assembles
the 80-byte header, and returns the block bytes and display-order hash. The
submit path reconstructs the same coinbase from the miner's extranonces, so the
hash the miner reports and the block the node receives are consistent.

## Accounting model

- All money is integer satoshis. Display values derive from satoshis.
- A round starts when the template height changes and is identified by
  `height-<random>`.
- Accepted, non-stale shares increment the round's share and difficulty totals.
- When a block is accepted, allocation weights are
  `SUM(difficulty)` per miner for accepted, non-stale shares in that round.
  If the round has no recorded shares, the finder receives the full reward.
- Gross, fee and net amounts are split proportionally. Integer division uses
  `ROUND_DOWN`; the last miner receives the remainder so the allocation sums
  exactly to the block value.
- The pool fee (default 2%, maximum 5%) is written to `pool_fee_ledger`.
- Rewards start as immature miner balances and pending allocations. They are
  immature until `current_height - maturity + 1 >= block.height` (default
  maturity 200).
- `reconcile_blocks` checks the canonical hash at each immature height:
  matching hashes mature the block and move balances to available; a mismatch
  marks the block, allocations and fee ledger entries as orphaned and reverses
  the immature balance.
- A rejected `submitblock` candidate is retained in `block_candidates` for
  audit. It does not create a block or credit balances.
- Only immature blocks are reorg-checked. A reorg that rewrites an already
  matured block is outside the current reconciliation model; payouts are
  disabled, so this has not been exercised with real funds.

PPLNS here means **difficulty-weighted, per-round, all accepted shares**. There
is no rolling N-share window. That distinction is important when comparing this
implementation with pools that use a sliding PPLNS window.

## Persistence

- SQLite in WAL mode, `synchronous=NORMAL`, foreign keys on, 30-second busy
  timeout.
- Every write uses a short `BEGIN IMMEDIATE` transaction. Multiple readers and
  one writer fit the single-node deployment; this is not an HA database.
- `schema_migrations` records applied SQL files. Migrations are ordered by the
  numeric filename prefix.
- A database with legacy tables but no `schema_migrations` is quarantined:
  old tables are renamed `legacy_*`, the new schema is applied, and compatible
  rows are imported. No in-memory database fallback exists; the path is
  required and its parent directory is created.
- The database file lives on the `pool-data` volume in Compose.

## HTTP API

- Read-only: no endpoint mutates accounting, miners or payouts.
- Success: `{"ok": true, "data": ..., "meta": {...}}`.
- Error: `{"ok": false, "error": {"code", "message", "details"}, "meta": {...}}`.
- `meta` carries Unix timestamp and a request ID. An incoming `X-Request-ID` is
  preserved (bounded) and otherwise a random one is generated.
- CORS is an allowlist; `OPTIONS` preflight is supported.
- Rate limiting is a fixed one-minute window keyed by client IP. Forwarded IPs
  are trusted only when the direct peer matches `BTCS_TRUSTED_PROXIES`.
- Validation covers limits, search length, enum values, block statuses and
  miner usernames. Errors use stable codes such as `invalid_query`,
  `miner_not_found`, `rate_limited`, `not_found`, `method_not_allowed`.
- `/api/health` reports database liveness and stays HTTP 200 even when degraded
  so a process supervisor does not restart a database-only failure loop.
- `/api/ready` returns HTTP 503 until the database is healthy, the node is
  connected and synced, Stratum is listening, a current job exists and the
  template is fresh.
- `/api/status` combines checks, node, Stratum and pool totals.
- `/api/pool/config` and `/api/pool/status` expose only the public,
  secret-free configuration. RPC credentials and the Stratum password are
  never included.
- OpenAPI is served raw at `/api/openapi.json`; `/api/docs` is the enveloped
  endpoint index.

## Deployment topology

`deploy/docker-compose.yml` defines three services:

| Service | Image | Persistence | Exposure |
|---|---|---|---|
| `node` | BTCS Core `31.1.3`, checksum-verified official tarball | `node-data:/data` | P2P port only |
| `pool` | Python 3.12 slim, non-root uid 10001 | `pool-data:/data` | Stratum port; API `expose` only |
| `web` | Caddy 2.10 Alpine, non-root-capable | `caddy-data`, `caddy-config` | `127.0.0.1:8080` by default; 80/443 in the TLS overlay |

- `pool` waits for `node` to be healthy, then the entrypoint additionally
  verifies the RPC chain matches `BTCS_NETWORK` before starting.
- The pool entrypoint refuses `BTCS_AUTO_PAYOUTS` values other than `false`.
- RPC and API ports are never published. Caddy proxies `/api` to `pool:8765`
  over the private Compose network.
- Healthchecks: node `getblockchaininfo`, pool `/api/health`, web Caddy admin
  configuration endpoint on loopback. Caddy also serves `/healthz` for an
  external liveness probe.
- Restart policy is `unless-stopped`; all services use `init: true`, log
  rotation and `no-new-privileges`.
- The production overlay adds Caddy automatic TLS and publishes 80/443; it
  requires `SILVER_POOL_SITE_ADDRESS`.

## Failure behavior

| Failure | Behavior |
|---|---|
| Node RPC down | Node snapshot reports disconnected; readiness fails; existing Stratum jobs remain until a new template is required; template poll logs the error |
| Node not synced / IBD | Readiness false; maturity loop skips reconciliation until connected and out of IBD |
| Template poll error | Last error exposed in status; existing job remains; no invented template |
| `submitblock` rejected | Candidate persisted as rejected; no block or balance credit |
| Database unhealthy | Health reports degraded; readiness false; API errors remain enveloped |
| API unavailable in browser | Every page renders an explicit error state; values are not replaced with invented data |
| Public Stratum host unset | API returns `endpoint: null`; pages show “Not configured” |
| Shutdown | Template and maturity tasks cancelled; TCP server closed; clients disconnected; API runner cleaned up |

## Security boundaries

- Read-only public API, no authentication or operator mutation endpoints.
- Deployment keeps the API on the private network; Caddy adds security headers
  and a restrictive Content Security Policy.
- RPC credentials live in the node volume's `bitcoin.conf` (mode 0600) and in
  the deployment environment, never in the repository.
- The node allows RPC only from the private Compose CIDR.
- Share accounting is transactional and duplicate-protected. Block credit
  requires a node-accepted submission.
- Payouts are not implemented. No key signing, transaction broadcast or
  withdrawal path exists.

## Non-goals

The pool does not define BTCS consensus, run an exchange, custody miner funds,
or provide a general wallet. L2 sequencing is not proof-of-work mining and is
out of scope. The repository does not operate a mainnet service.
