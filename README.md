# Silver Pool

Silver Pool is a Bitcoin Silver (BTCS) SHA256d mining pool. It runs a Stratum V1
listener and a read-only HTTP API in one Python process, persists accounting in
SQLite, serves a ten-page static website, and ships a Docker Compose stack that
runs BTCS Core, the pool and Caddy.

> **Status as of 2026-10-26: local regtest prototype, not a production or
> mainnet pool. Payouts are disabled.**
>
> The complete Stratum → share → block → `submitblock` flow has been verified
> locally against a real Bitcoin Silver Core `v31.1.3` regtest node. A real
> block was accepted and persisted; after shutdown, a reopened database still
> contained the accepted block and the rejected stale share. No cloud host, public DNS name, public Stratum endpoint or mainnet node has
> been provisioned or verified. The Compose files validate, but the images could
> not be built in this environment because the Docker daemon socket is not
> accessible to the current user. See
> [`docs/IMPLEMENTATION-STATUS.md`](docs/IMPLEMENTATION-STATUS.md) for the full
> evidence and blockers.

## What is implemented

| Component | Status |
|---|---|
| Stratum V1 | `mining.subscribe`, `mining.authorize`, `mining.set_difficulty`, `mining.notify`, `mining.submit`; per-session `extranonce1`; miner-supplied `extranonce2`; duplicate and stale-share rejection |
| Block assembly | SegWit `getblocktemplate`, coinbase with witness commitment, BIP34 height, merkle branch, 80-byte header, network target check |
| Block submission | Real `submitblock`; status and rejection reason recorded; block candidate audit trail |
| Accounting | SQLite WAL with ordered migrations; miner/worker records; difficulty-weighted per-round PPLNS; fee ledger; maturity and orphan reconciliation |
| HTTP API | Consistent `{"ok": ...}` envelope, request IDs, CORS allowlist, per-client rate limiting, validation, health and readiness |
| Website | Ten real pages: Overview, Statistics, Miners, Miner detail, Blocks, Getting Started, Pool, API Docs, Status, Help |
| Deployment | Three-service Compose stack, pinned and checksum-verified official BTCS release, persistent volumes, healthchecks, restart policies, private RPC, Caddy TLS overlay |

The pool never invents statistics. If the API or node is unavailable, the site
shows an explicit offline/unknown state. If no public Stratum host is
configured, every page reports “Not configured” instead of displaying a fake
endpoint.

## Requirements

- Python 3.12+
- Node.js 22+ and npm
- Bitcoin Silver Core `v31.1.3` binaries (`bitcoinsilverd`,
  `bitcoinsilver-cli`) for a real node and the end-to-end test

## Quick start (local regtest)

### 1. Start a throwaway BTCS regtest node

```sh
mkdir -p /tmp/btcs-regtest
bitcoinsilverd -regtest -datadir=/tmp/btcs-regtest -server=1 \
  -rpcuser=pool-local -rpcpassword=change-this-local-password \
  -rpcport=18443 -port=18444 -fallbackfee=0.0001
```

In another shell, create the wallet the pool will use:

```sh
bitcoinsilver-cli -regtest -datadir=/tmp/btcs-regtest \
  -rpcuser=pool-local -rpcpassword=change-this-local-password \
  createwallet pool
```

Generate a few regtest blocks so `getblocktemplate` has a chain tip:

```sh
address=$(bitcoinsilver-cli -regtest -datadir=/tmp/btcs-regtest \
  -rpcuser=pool-local -rpcpassword=change-this-local-password \
  -rpcwallet=pool getnewaddress)
bitcoinsilver-cli -regtest -datadir=/tmp/btcs-regtest \
  -rpcuser=pool-local -rpcpassword=change-this-local-password \
  generatetoaddress 10 "$address"
```

### 2. Start the integrated pool

Install the backend dependency and run the integrated API + Stratum process:

```sh
python3 -m pip install -r requirements.txt

export BTCS_NETWORK=regtest
export BTCS_RPC_URL=http://127.0.0.1:18443
export BTCS_RPC_USER=pool-local
export BTCS_RPC_PASSWORD=change-this-local-password
export BTCS_RPC_WALLET=pool
export BTCS_POOL_DB=/tmp/silver-pool/pool.sqlite3
export BTCS_POOL_API_PORT=8765
export BTCS_STRATUM_PORT=3333

PYTHONPATH=src python3 -m btcs_pool.server
```

The process starts:

- HTTP API on `http://127.0.0.1:8765`
- Stratum V1 on `127.0.0.1:3333`
- SQLite database at the configured `BTCS_POOL_DB`
- Template polling and maturity reconciliation tasks

### 3. Start the website

In a second shell:

```sh
cd site
npm ci
npm run dev
```

Open `http://127.0.0.1:4173`. The development server proxies `/api` to
`http://127.0.0.1:8765` by default; override with `API_PROXY`.

For a production build:

```sh
cd site
npm run build       # writes site/_site
SITE_BASE=/Silver-Pool/ npm run build   # subpath build for GitHub Pages
```

## Connect a miner

Stratum V1 is the only mining protocol implemented. Any miner that supports
SHA256d Stratum V1 can connect, using the host and port shown on the
`/getting-started/` page.

The website only advertises an endpoint when `BTCS_PUBLIC_STRATUM_HOST` is set:

```sh
export BTCS_PUBLIC_STRATUM_HOST=pool.your-domain.example
export BTCS_PUBLIC_STRATUM_PORT=3333
```

Without that variable, the API returns `stratum.endpoint: null` and the site
shows “Not configured”. This checkout does **not** configure a public endpoint.

Miner usernames use `account` or `account.worker`. The account is the unit that
owns balances; the worker is the suffix after the final dot. If
`BTCS_STRATUM_PASSWORD` is set, miners must use it as the Stratum password.
Otherwise any non-empty password is accepted for authorization.

```sh
# Use the host and port configured for your deployment, not a placeholder host.
miner -o stratum+tcp://<configured-host>:<configured-port> -u account.worker -p <password>
```

## HTTP API

The API is read-only and unauthenticated; the deployment keeps it on the private
Compose network behind Caddy. It uses one envelope for success and error
responses:

```json
{"ok": true, "data": {}, "meta": {"timestamp": 0, "request_id": "..."}}
{"ok": false, "error": {"code": "not_found", "message": "...", "details": null}, "meta": {"timestamp": 0, "request_id": "..."}}
```

Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness; database health only |
| GET | `/api/ready` | Readiness; node sync, template freshness, Stratum state |
| GET | `/api/status` | Combined node, Stratum, database and pool status |
| GET | `/api/pool/status` | Overview, recent blocks/shares, current round, public config |
| GET | `/api/pool/statistics` | Pool totals and 24-hour hashrate estimate |
| GET | `/api/pool/history/hashrate?range=1h\|6h\|24h\|7d` | Bucketed hashrate history |
| GET | `/api/pool/miners?limit=50&search=` | Miner list |
| GET | `/api/pool/miner/{username}` | Miner detail, workers, recent blocks |
| GET | `/api/pool/miner/{username}/shares?limit=50` | Miner shares |
| GET | `/api/pool/shares/recent?limit=20` | Recent shares |
| GET | `/api/pool/blocks?limit=50&status=all\|immature\|mature\|orphaned` | Blocks |
| GET | `/api/pool/blocks/recent?limit=20` | Recent blocks |
| GET | `/api/pool/fee-ledger?limit=50` | Pool fee ledger |
| GET | `/api/pool/rounds/current` | Current round |
| GET | `/api/pool/config` | Public configuration (no secrets) |
| GET | `/api/docs` | Machine-readable endpoint index |
| GET | `/api/openapi.json` | OpenAPI 3.0 document |

`/api/status` does **not** include pool configuration;
`/api/pool/status` does. The OpenAPI document is returned as raw OpenAPI JSON,
the one documented exception to the envelope.

Rate limiting defaults to 240 requests per minute per client. When the direct
peer is in `BTCS_TRUSTED_PROXIES`, `X-Forwarded-For` is honored; otherwise it is
ignored so clients cannot spoof new buckets. CORS is an explicit allowlist via
`BTCS_API_CORS_ORIGINS`.

## Configuration

The full deployment template is [`.env.example`](.env.example). Important
variables:

| Variable | Default | Notes |
|---|---|---|
| `BTCS_NETWORK` | `regtest` in code, `main` in `.env.example` | `main`, `test`, `testnet4`, `signet`, `regtest` |
| `BTCS_RPC_URL` | `http://127.0.0.1:<network RPC port>` | Never expose RPC publicly |
| `BTCS_RPC_USER` / `BTCS_RPC_PASSWORD` | `test` / `test` in code | Always override outside disposable tests |
| `BTCS_RPC_WALLET` | `pool` | Creates/loads a wallet if no address/script is supplied |
| `BTCS_POOL_ADDRESS` / `BTCS_POOL_SCRIPT_PUBKEY` | empty | Either can define the coinbase output; otherwise the wallet is used |
| `BTCS_POOL_FEE` | `2.0` | Percent, allowed range 0–5 |
| `BTCS_MIN_PAYOUT` | `0.01` | Advertised threshold; payouts are disabled |
| `BTCS_AUTO_PAYOUTS` | `false` | The shipped entrypoint refuses any value other than `false` |
| `BTCS_MATURITY_CONFIRMATIONS` | `200` | BTCS coinbase maturity |
| `BTCS_PUBLIC_STRATUM_HOST` | empty | Empty means “Not configured” everywhere |
| `BTCS_POOL_API_HOST` / `BTCS_POOL_API_PORT` | `127.0.0.1` / `8765` | Keep loopback unless behind a private proxy |
| `BTCS_STRATUM_HOST` / `BTCS_STRATUM_PORT` | `127.0.0.1` / `3333` | Bind address and port |
| `BTCS_POOL_DIFFICULTY` | `1.0` | Static per-session difficulty; no vardiff |
| `BTCS_EXTRANONCE2_SIZE` | `4` | Miner-controlled extranonce2 bytes |
| `BTCS_POOL_DB` | `data/pool.sqlite3` | Parent directory is created; no in-memory fallback |
| `BTCS_API_CORS_ORIGINS` | loopback dev origins | Comma-separated allowlist |
| `BTCS_API_RATE_LIMIT_PER_MINUTE` | `240` | `0` disables |
| `BTCS_TRUSTED_PROXIES` | empty | CIDRs allowed to supply `X-Forwarded-For` |

Payouts remain disabled. A payout ledger and state transitions exist for
accounting tests, but there is no payout API, signing, broadcasting, operator
authorization, confirmation policy or recovery procedure. Do not advertise or
operate this pool as a paying pool.

## Deployment

The stack is in [`deploy/`](deploy):

- `node`: official BTCS Core `v31.1.3`, pinned tarball SHA256, persistent
  `node-data` volume, P2P published, RPC private to the Compose network.
- `pool`: integrated API + Stratum process, persistent `pool-data` volume,
  Stratum published, API reachable only through Caddy.
- `web`: Caddy serving the built multi-page site, proxying `/api` to `pool:8765`.

```sh
cp .env.example .env
# Edit .env: RPC credentials, pool address/wallet, network, public Stratum host.
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
```

For automatic TLS, point a DNS name at the host and use the production overlay:

```sh
# .env: SILVER_POOL_SITE_ADDRESS=pool.your-domain.example
docker compose --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.prod.yml up -d --build
```

Both Compose configurations pass `docker compose config`. The images have not
been built or run here because `/var/run/docker.sock` requires membership in the
`docker` group, which this environment lacks. Caddy is not installed, so the
Caddyfile has not been runtime-validated. See
[`docs/IMPLEMENTATION-STATUS.md`](docs/IMPLEMENTATION-STATUS.md) for the exact
blockers.

GitHub Pages can host only the static frontend. It has no API or Stratum
service; without a same-origin `/api` reverse proxy the deployed site will show
honest offline states. The Pages workflow builds with `SITE_BASE=/Silver-Pool/`
and runs the static and browser tests, but no workflow run or live Pages
deployment has been verified from this environment.

## Tests

```sh
# Python unit, API, Stratum, persistence, deployment and real-node E2E tests
python3 -m pytest -q tests

# Website static checks, browser navigation/error-state tests and build
cd site
npm ci
npm test
npm run test:browser
npm run build
```

The real-node E2E test starts `bitcoinsilverd` with a throwaway regtest datadir.
It auto-detects `bitcoinsilverd` on `PATH`, then falls back to
`/home/user/Silver-Labs/btcs-core/build/bin/bitcoinsilverd`; override with
`BTCS_DAEMON`. It skips only when no daemon is available. Current verified
results are recorded in
[`docs/IMPLEMENTATION-STATUS.md`](docs/IMPLEMENTATION-STATUS.md).

## Repository layout

```text
.
├── src/btcs_pool/          # block, RPC, node monitor, DB, accounting, Stratum, API, server
├── tests/                  # unit, integration, deployment and real-regtest E2E tests
├── site/                   # ten-page Vite website, shared JS/CSS, static and browser tests
├── deploy/                 # node, pool and web images, Compose files, Caddy config
├── docs/                   # architecture, implementation status, PPLNS notes, audits
├── .github/workflows/      # CI and static Pages build
├── .env.example            # deployment template; placeholders only
├── requirements.txt
└── package.json            # root test/build aliases
```

## Known limitations

- **No live deployment.** No cloud credentials, DNS, firewall or public
  Stratum TCP endpoint has been provisioned or verified.
- **No mainnet operation.** The verified chain is a temporary local regtest
  node. Mainnet would additionally require operational review, monitoring,
  backups and a public endpoint.
- **Payouts are disabled.** Reward accounting and maturity accounting are
  tested, but signing, broadcasting, confirmations, recovery and payment tests
  are not implemented.
- **PPLNS is per round.** All accepted, non-stale shares in the round are
  weighted by difficulty. There is no rolling N-share PPLNS window and no
  per-miner vardiff.
- **Single-node SQLite.** WAL and short `BEGIN IMMEDIATE` transactions make one
  pool process safe, but this is not a horizontally scalable HA database.
- **No security audit.** Do not use real funds.
- **Docker and Caddy runtime unverified.** Compose syntax is validated; image
  builds, container startup, healthchecks and TLS are not.
- **The static site is not a backend host.** GitHub Pages alone cannot serve
  `/api` or Stratum.

## Security

See [`SECURITY.md`](SECURITY.md). Report vulnerabilities privately; do not open
a public issue with credentials, wallet data or exploit details.

## Historical documents

- [`docs/AUDIT-REPORT.md`](docs/AUDIT-REPORT.md) and
  [`docs/REPOSITORY-AUDIT.md`](docs/REPOSITORY-AUDIT.md) are historical audits
  from 2026-10-24. They are retained for provenance and are superseded by the
  current implementation status.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) describes the current system.
- [`docs/pplns-plan.md`](docs/pplns-plan.md) describes the implemented
  accounting model and remaining payout work.

## License

See [`LICENSE`](LICENSE). The repository is public for review and development.
