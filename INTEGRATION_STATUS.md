# Silver Pool — integration and verification status

**Last verified:** 2026-10-26

## Classification

**Local regtest prototype.** A real Bitcoin Silver Core `v31.1.3` regtest node,
the integrated Stratum/API process and the persistent SQLite database were
exercised end to end on this machine. The static frontend is deployed to GitHub
Pages, but the pool backend has **not** been deployed to a cloud host or
verified as a testnet, regtest-hosted, or mainnet public pool. Payouts are
disabled.

### Coin Support Status

- **Bitcoin Silver (BTCS):** Verified implementation on regtest network — the pool
  runs a real BTCS Core node, Stratum server, and API with full share accounting
  and block submission handling.
- **Other coins:** "Integration not yet available" — BTCS is the initial and primary
  supported coin. Silver Pool is designed as a multi-coin platform, but each
  additional coin requires its own verified protocol, node integration, algorithms,
  accounting rules, and operational tests before it can be advertised as supported.

## Verified locally and in CI

| Area | Evidence |
|---|---|
| Real node connectivity | `getblockchaininfo`, `getblocktemplate ["segwit"]`, wallet creation/loading, `getblockhash` |
| Block template | Height, previous hash, version, bits, coinbase value, transaction list |
| Stratum V1 | Subscribe, authorize, difficulty, notify, submit, reconnect, per-session `extranonce1`, miner `extranonce2` |
| Share handling | Accepted, invalid target, duplicate, stale job, authorization failure, unknown method |
| Block submission | Real `submitblock` accepted; canonical block hash matched the node at the submitted height |
| Accounting | Difficulty-weighted per-round PPLNS, exact fee split, immature balance, maturity, orphan reversal, fee ledger |
| Persistence | New `Database` instance after shutdown still sees the accepted block and rejected stale share |
| API | Envelopes, request IDs, CORS, rate limiting with trusted-proxy handling, validation, 404/405/500, health/readiness, OpenAPI |
| Website | Ten direct-load routes, titles/headings/nav, live values, miner search, back/forward/reload, mobile menu, API-error states |
| Build | Vite production build emits all ten routes and hashed assets, for root and `/Silver-Pool/` bases |
| Deployment files | Base and production Compose configurations pass `docker compose config`; pinned BTCS release SHA256 is checked |
| CI | GitHub Actions CI run `40299896414` passed for commit `a8f0071` |
| Static deployment | GitHub Pages run `40300316286` passed; all ten live routes and assets return HTTP 200 at <https://silver-labs-technology-development.github.io/Silver-Pool/> |

The last full Python run was **100 passed** (including the real-node E2E).
The static website suite was **8 passed** and the Chrome/CDP browser suite was
**7 passed**. Exact commands and limitations are in
[`docs/IMPLEMENTATION-STATUS.md`](docs/IMPLEMENTATION-STATUS.md).

## Not verified / blocked

| Item | Blocker |
|---|---|
| Docker image build and container runtime | The Docker socket is owned by `root:docker`; the current user is not in the `docker` group and `sudo` requires a password. Compose config validation only. |
| Caddyfile runtime validation | Caddy is not installed; the apt package download timed out/incomplete. |
| Live pool backend deployment | No provider credentials, host, DNS or firewall access for the node/pool/API stack. GitHub Pages cannot run it. |
| Public Stratum endpoint | `BTCS_PUBLIC_STRATUM_HOST` is unset; no externally reachable TCP endpoint exists. |
| Mainnet pool | No mainnet node, funding, operational review or public infrastructure. |
| Payouts | Signing, broadcasting, confirmation policy, operator authorization and recovery are not implemented. |

## Reproduce the verification

```sh
python3 -m pytest -q tests

cd site
npm ci
npm test
npm run test:browser
npm run build

cd ..

docker compose --env-file .env.example -f deploy/docker-compose.yml config >/dev/null
SILVER_POOL_SITE_ADDRESS=pool.invalid docker compose --env-file .env.example \
  -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml config >/dev/null
```

The real-node E2E test skips only when `bitcoinsilverd` is unavailable. It
creates a throwaway datadir and random loopback ports; it does not touch
developer chain data, wallets or credentials.
