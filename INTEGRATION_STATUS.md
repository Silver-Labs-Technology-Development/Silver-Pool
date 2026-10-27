# Silver Pool — integration and verification status

**Last verified:** 2026-10-26

## Classification

**Locally deployed BTCS mainnet backend.** The backend and website run as native
systemd user services against the existing synced Bitcoin Silver Core `v31.1.3`
mainnet node. Real mainnet templates, Stratum authentication, the complete share
lifecycle, API accounting, restart persistence and backup/restore were exercised
on this machine with an isolated database. The static frontend is deployed to
GitHub Pages, but the pool backend has **not** been deployed to a public host or
verified as a publicly reachable mainnet pool. Public Stratum, a third-party
miner test, public TLS hosting and payouts are not verified or implemented.
Payouts are disabled.

### Coin Support Status

- **Bitcoin Silver (BTCS):** Verified implementation on regtest and locally
  deployed against BTCS mainnet — the pool runs a real BTCS Core node, Stratum
  server, and API with full share accounting and block submission handling. The
  public endpoint is not verified.
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
| Real node connectivity | Mainnet `getblockchaininfo`, `getblocktemplate ["segwit"]`, wallet/address validation; regtest wallet create/load, `getblockhash` |
| Block template | Current mainnet height, previous hash, bits, coinbase value, transaction list, witness commitment |
| Native deployment | systemd user services, hardened units, readiness gate, loopback API/site, backups and isolated restore |
| Stratum V1 | Subscribe, authorize, difficulty, notify, submit, reconnect, per-session `extranonce1`, miner `extranonce2` |
| Share handling | Mainnet accepted, invalid target, duplicate, stale job, authorization failure and wrong password; regtest block submission |
| Block submission | Regtest `submitblock` accepted with matching canonical hash; mainnet smoke made **0** submissions by design |
| Accounting | Difficulty-weighted per-round PPLNS, exact fee split, immature balance, maturity, orphan reversal, fee ledger; live API accounting after restart |
| Persistence | New `Database` instance after shutdown sees accepted shares/blocks and rejected shares; replay is rejected |
| API | Envelopes, request IDs, CORS, rate limiting with trusted-proxy handling, validation, 404/405/500, health/readiness, OpenAPI |
| Website | Ten direct-load routes, titles/headings/nav, live values, miner search, back/forward/reload, mobile menu, API-error states |
| Backup / restore | Online SQLite backup with SHA-256 manifest, `integrity_check=ok`, isolated restore with matching counts |
| Build | Vite production build emits all ten routes and hashed assets, for root and `/Silver-Pool/` bases |
| Deployment files | Base and production Compose configurations pass `docker compose config`; pinned BTCS release SHA256 is checked |
| CI | GitHub Actions CI run `40299896414` passed for commit `a8f0071` |
| Static deployment | GitHub Pages run `40300316286` passed; all ten live routes and assets return HTTP 200 at <https://silver-labs-technology-development.github.io/Silver-Pool/> |

The last full Python run was **112 passed** (including the real-node regtest
E2E and native deployment tests), plus a **33-check** mainnet smoke against the
live node. The static website suite was **8 passed** and the Chrome/CDP browser
suite was **7 passed**. Exact commands and limitations are in
[`docs/IMPLEMENTATION-STATUS.md`](docs/IMPLEMENTATION-STATUS.md) and
[`LAUNCH-CHECKLIST.md`](LAUNCH-CHECKLIST.md).

## Not verified / blocked

| Item | Blocker |
|---|---|
| Public Stratum endpoint | `BTCS_PUBLIC_STRATUM_HOST` is unset; host is NAT/tethered and no inbound TCP forwarding or external test exists. |
| Third-party miner | No external endpoint and no cgminer/BFGMiner/cpuminer installed; only the controlled protocol harness has connected. |
| Public API/site and TLS | No public host, DNS or reverse proxy; the native services bind to loopback. |
| Durable user services | `Linger=no`; enabling linger requires administrator action. |
| Payouts | Signing, broadcasting, confirmation policy, operator authorization and recovery are not implemented. |
| Docker image build and container runtime | The Docker socket is owned by `root:docker`; the current user is not in the `docker` group and `sudo` requires a password. Compose config validation only. |
| Caddyfile runtime validation | Caddy is not installed; the apt package download timed out/incomplete. |
| Live reorg and public operations | No public infrastructure, monitoring or on-call runbook; reorg handling is unit-tested only. |

## Reproduce the verification

```sh
python3 -m pytest -q tests

# Native mainnet services against the existing synced node
./deploy/native/preflight.sh
./deploy/native/verify-mainnet.sh
./deploy/native/status.sh
./deploy/native/check-secrets.sh

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

The real-node regtest E2E test skips only when `bitcoinsilverd` is unavailable.
It creates a throwaway datadir and random loopback ports; it does not touch
developer chain data, wallets or credentials. The native mainnet smoke uses a
throwaway database, ephemeral ports and a wrapper that refuses every
`submitblock` call; it does not touch the production ledger or the node wallet.
