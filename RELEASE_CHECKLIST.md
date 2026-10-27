# Silver Pool release readiness checklist

**Status:** not approved for release as a paying or public pool; local mainnet
backend verified (`TESTED LOCALLY`).
**Last verified:** 2026-10-26.
**Stage:** native systemd deployment against the existing BTCS Core `v31.1.3`
mainnet node. External connectivity, a third-party miner and payouts remain
unverified or unimplemented.

This checklist records verified evidence and open gates. A checked box means the
item was exercised locally, not that public production infrastructure exists.

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
- [x] The existing synced BTCS Core mainnet node serves a current template with
      matching height, previous hash, bits and coinbase value.
- [x] A protocol-level Stratum client subscribes, authorizes and receives a job.
- [x] Valid, invalid, duplicate, stale and unauthorized mainnet shares are
      classified correctly.
- [x] Wrong Stratum password is rejected.
- [x] A valid block candidate is assembled and sent through `submitblock` on
      regtest.
- [x] The real regtest node accepts the block; canonical hash matches at the
      submitted height.
- [x] Accounting records the immature reward and the fee split.
- [x] API exposes accepted blocks/shares and Stratum status.
- [x] Reconnect after disconnect/restart receives the current job and replay is
      rejected.
- [x] Shutdown disconnects clients and stops the status listener.
- [x] Mainnet smoke `verify-mainnet.sh` passed with **0** block submissions.
- [ ] A third-party miner application (for example cgminer/BFGMiner) has been
      connected. The E2E and mainnet smoke use in-repo Stratum protocol clients,
      not an external miner binary.
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
- [x] Native units enforce `NoNewPrivileges`, `PrivateTmp`,
      `ProtectSystem=strict`, `ProtectHome=read-only` and explicit write paths.
- [x] `.env.native` is mode `0600` and Git-ignored; tracked-tree secret scan
      passes.
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
- [x] Native systemd user services install, enable, start and become ready
      against the existing mainnet node.
- [x] Native preflight validates env mode, chain, sync, template, coinbase,
      ports, payout lock and public-endpoint honesty.
- [x] Online backup, integrity check and isolated restore drill passed.
- [x] Upgrade script is plan-only by default, refuses a dirty tree and uses
      fast-forward-only Git.
- [ ] Images build successfully. Blocked: Docker socket permission.
- [ ] Containers start and pass healthchecks. Blocked: Docker socket
      permission.
- [ ] Caddyfile validates and serves routes/TLS. Blocked: Caddy unavailable.
- [ ] A public Stratum endpoint resolves and accepts TCP connections. Blocked:
      no host/DNS/firewall access.
- [ ] Public API/site deployment with TLS. Blocked: no public host or reverse
      proxy.
- [ ] Durable services across logout/reboot. `Linger=no`; requires
      administrator action.
- [ ] Scheduled off-host backups and retention. Not configured.
- [ ] Rollback rehearsed against a published release. No release exists yet.

## Gate 6 — Release

- [x] Operator guide and launch checklist exist:
      `docs/MAINNET-LAUNCH.md`, `deploy/native/README.md`,
      `LAUNCH-CHECKLIST.md`.
- [ ] Versioned release notes published.
- [ ] Miner setup guide verified against a third-party miner.
- [ ] All payout gates pass.
- [ ] All deployment gates pass.
- [ ] Every blocked gate is either resolved or explicitly accepted by the
      maintainers.
- [x] Public static site does not imply live mining, uptime, payouts or mainnet
      operation; it shows explicit offline states without a backend.

## Evidence summary

| Check | Result |
|---|---|
| `python3 -m pytest -q tests` | **112 passed** in 42.36s, including real-node regtest E2E and native deployment tests |
| `./deploy/native/verify-mainnet.sh` | **33 checks passed**, 0 block submissions, isolated DB |
| `cd site && npm test` | **8 passed** |
| `cd site && npm run test:browser` | **7 passed** |
| `cd site && npm run build` | all ten routes built for `/` and `/Silver-Pool/` |
| Native preflight | passed: mainnet, synced, template, coinbase, loopback RPC, payouts disabled |
| Native services | `silver-pool.service` and `silver-pool-web.service` active; API ready; ten routes HTTP 200 |
| Production database | initialized empty; no miners, shares, blocks or payouts |
| Backup / restore | online backup, SHA-256 manifest, `integrity_check=ok`, isolated restore passed |
| Secret scan | passed for tracked files |
| GitHub Actions CI | **passed** (run `40299896414`) |
| GitHub Pages static deployment | **passed** (run `40300316286`); 10 live routes and assets HTTP 200 |
| Base `docker compose config` | passed |
| Production overlay `docker compose config` | passed |
| Docker image build/run | **blocked** (socket permission) |
| Caddy runtime validation | **blocked** (Caddy unavailable) |
| Public Stratum / third-party miner / public TLS | **not performed** |
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

**Do not release as a paying, public or mainnet pool.** The backend is running
locally on mainnet against the existing synced node with an empty production
ledger and payouts disabled. It is `TESTED LOCALLY`, not externally reachable.
The minimum remaining work is a real third-party miner test through an
externally reachable Stratum endpoint, public TLS hosting for the API/site,
payout implementation, durable supervision (linger or system units), scheduled
off-host backups and an independent security review.
