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

### Pool Fee Model (documented for future PoW-S design)

**Total pool fee: 2.0%**

- **0.5%** — Silver Labs development allocation. Covers ongoing development, maintenance, and operational costs of the pool.
- **1.5%** — Planned PoW-staking rewards allocation. Intended for distribution among eligible stakers in proportion to their eligible stake. **Not yet active** — no staking payouts, claim distribution, or live balances are operational. This allocation is documented for future PoW-S design and SilvEx fee integration.

#### Fee arithmetic

- Fee basis is explicitly defined as a percentage point value of the block reward (coinbase value + transaction fees), calculated per round using exact `Decimal` arithmetic with `ROUND_DOWN` rounding.
- The `BTCS_POOL_FEE` environment variable (default `2.0`) represents the total pool fee in percentage points.
- Internal accounting uses `Decimal` values to avoid floating-point rounding that can misallocate funds.
- Rounding and remainder handling are deterministic: `fee_satoshi = (gross_satoshi * pool_fee_percent / 100).quantize(1, rounding=ROUND_DOWN)`.

#### How the future staking share would work

When the PoW-staking allocation becomes active, the 1.5% pool fee will be divided among eligible stakers proportionally to their eligible stake:

```
staker share_i = 1.5% × eligible_stake_i / total_eligible_stake
```

- With only one eligible staker, that staker receives 100% of the designated 1.5% allocation for the applicable reward period.
- As eligible stake changes, each participant's proportion changes.
- Reward eligibility, stake snapshots, reward periods, lockups, minimums, slashing or penalties, withdrawals, rounding and claim rules remain subject to PoW-S design decisions.
- The 0.5% development allocation remains distinct from the staking allocation.

#### SilvEx connection (future)

Eligible SilvEx trading-fee revenue attributable to defined BTCS markets may contribute to the PoW-staking reward pool. The exact SilvEx contribution, fee-source accounting, conversion method, and settlement process are to be defined in the PoW-S specification. Implementation will remain separate from the current pool fee path until the specification is approved.

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
