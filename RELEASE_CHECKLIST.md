# Silver Pool release readiness checklist

**Status:** not approved for release as a paying or public pool.
**Last verified:** 2026-10-26.
**Stage:** local regtest prototype against real BTCS Core `v31.1.3`.

This checklist records verified evidence and open gates. A checked box means the
item was exercised locally, not that production infrastructure exists.

## Gate 1 — Accounting

- [x] Fee configuration validates: 0–5%, default 2.00%, `BTCS_POOL_FEE`.
- [x] Fees are recorded separately from miner balances in `pool_fee_ledger`.
- [x] Reward allocation reconciles exactly: gross, fee and net remainders are
      assigned so totals equal the block value.
- [x] Duplicate shares are rejected by a unique constraint and are not
      double-counted.
- [x] Maturity moves pending allocations and immature balances to available.
- [x] Orphan reconciliation reverses pending allocations and fee entries.
- [x] Database restart persistence is verified by the real-node E2E and DB
      tests.
- [ ] Reorganization handling verified against a real chain reorg. Unit-level
      canonical-hash reconciliation is tested; a live regtest reorg is not.
- [ ] Payout batch accounting, idempotency and recovery. Not implemented.

## Gate 2 — Mining

- [x] A real BTCS Core regtest node serves `getblocktemplate`.
- [x] A protocol-level Stratum client subscribes, authorizes and receives a job.
- [x] Valid, invalid, duplicate and stale shares are classified correctly.
- [x] A valid block candidate is assembled and sent through `submitblock`.
- [x] The real node accepts the block; canonical hash matches at the submitted
      height.
- [x] Accounting records the immature reward and the fee split.
- [x] API exposes the accepted block, miner share counts and Stratum status.
- [x] Reconnect after disconnect receives the current job.
- [x] Shutdown disconnects clients and stops the status listener.
- [ ] A third-party miner application (for example cgminer/BFGMiner) has been
      connected. The E2E uses an in-repo Stratum protocol client, not an
      external miner binary.
- [ ] Public Stratum TCP reachability. No public endpoint exists.

## Gate 3 — Payouts

- [ ] Immature and orphaned rewards cannot be paid. The accounting boundary is
      tested, but no payout executor exists.
- [ ] Mature balances can enter a payout queue. Queue/executor not implemented.
- [ ] Signing and submission are tested end to end. Not implemented.
- [ ] Duplicate payments are prevented across crashes/retries. Not implemented.
- [ ] Recovery and reconciliation are demonstrated. Not implemented.
- [ ] Operator authentication and authorization. Not implemented.
- [x] Automatic payouts are disabled by default.
- [x] The deployment entrypoint refuses `BTCS_AUTO_PAYOUTS` values other than
      `false`.
- [x] The public API reports `auto_payouts: false` and `payouts_enabled: false`.

## Gate 4 — Security and UI

- [x] Public API exposes no RPC credentials or Stratum password.
- [x] API is read-only; there are no mutation or payout endpoints.
- [x] CORS is an explicit allowlist and rate limiting is enforced.
- [x] `X-Forwarded-For` is honored only from configured trusted proxies.
- [x] Dashboard values come from the live API; offline/error states are
      explicit.
- [x] Fees, reward method and payout-disabled status match configuration.
- [x] No fake Stratum endpoint is rendered. Unconfigured means “Not configured”.
- [x] Node RPC and pool API ports are not published by the Compose stack.
- [ ] Independent security review. Not performed.
- [ ] Threat model validated for public, real-value operation. Not performed.
- [ ] Caddy security headers/TLS verified at runtime. Caddy is unavailable here.

## Gate 5 — Deployment

- [x] Base Compose configuration validates with `docker compose config`.
- [x] Production TLS overlay validates with `docker compose config`.
- [x] BTCS release is pinned to `31.1.3` with an official SHA256.
- [x] Persistent volumes, healthchecks, startup ordering and restart policies
      are defined.
- [x] Pool and web images are configured to run non-root; node capabilities are
      dropped.
- [x] Static frontend deploys to GitHub Pages with `SITE_BASE=/Silver-Pool/`;
      all ten live routes and assets return HTTP 200.
- [ ] Images build successfully. Blocked: Docker socket permission.
- [ ] Containers start and pass healthchecks. Blocked: Docker socket
      permission.
- [ ] Caddyfile validates and serves routes/TLS. Blocked: Caddy unavailable.
- [ ] A public Stratum endpoint resolves and accepts TCP connections. Blocked:
      no host/DNS/firewall access.
- [ ] Live pool backend deployment exists. Blocked: no credentials or
      infrastructure for the node/pool/API stack. GitHub Pages is static-only.
- [ ] Rollback procedure exercised. Not possible without a backend deployment.
- [ ] Backups and restore drill for the pool database and node data. Not
      exercised.

## Gate 6 — Release

- [ ] Versioned release notes and operator guide.
- [ ] Miner setup guide verified against a third-party miner.
- [ ] All payout gates pass.
- [ ] All deployment gates pass.
- [ ] Every blocked gate is either resolved or explicitly accepted by the
      maintainers.
- [ ] Public site does not imply live mining, uptime, payouts or mainnet
      operation.

## Evidence summary

| Check | Result |
|---|---|
| `python3 -m pytest -q tests` | **100 passed** in 34.85s, including real-node E2E |
| `cd site && npm test` | **8 passed** |
| `cd site && npm run test:browser` | **7 passed** |
| `cd site && npm run build` | all ten routes built for `/` and `/Silver-Pool/` |
| GitHub Actions CI | **passed** (run `40299896414`) |
| GitHub Pages static deployment | **passed** (run `40300316286`); 10 live routes and assets HTTP 200 |
| Base `docker compose config` | passed |
| Production overlay `docker compose config` | passed |
| Docker image build/run | **blocked** (socket permission) |
| Caddy runtime validation | **blocked** (Caddy unavailable) |
| Public pool backend deployment / DNS / TLS | **not performed** |
| Payout signing/broadcast/recovery | **not implemented** |

## Economics disclosed by the implementation

- Algorithm: SHA256d.
- Reward method: difficulty-weighted, per-round PPLNS. No rolling window.
- Default pool fee: 2.00%; allowed 0.00–5.00%.
- Minimum payout setting: 0.01 BTCS (advertised only; payouts disabled).
- Payout interval setting: 300 seconds (advertised only; no executor).
- Coinbase maturity: 200 confirmations.
- Automatic payouts: disabled.

## Decision

**Do not release as a paying, public or mainnet pool.** Only the static frontend
is deployed (GitHub Pages). The minimum remaining work is a real third-party
miner test, a pool backend deployment with runtime healthchecks and TLS, a
public Stratum endpoint, payout implementation and security review.
