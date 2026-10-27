# Silver Pool launch checklist

**Status:** `NOT READY` for public/mainnet mining; locally verified backend.
**Last verified:** 2026-10-26.
**Deployment:** native systemd user services against the existing BTCS mainnet node.
**Payouts:** disabled. **Public Stratum endpoint:** not configured.

A checked item was exercised on this host. It is not evidence of public
availability, third-party miner compatibility, payout capability or an
independent security review. Labels follow the final readiness report:

- `NOT READY` — launch gate not met.
- `TESTED LOCALLY` — verified on this host only.
- `EXTERNAL CONNECTIVITY VERIFIED` — a real external client reached the service.
- `MAINNET MINING VERIFIED` — a real third-party miner produced an accepted
  mainnet share/block through the public endpoint.

## A. Packaging and reproducibility

- [x] Python runtime dependencies pinned in `requirements.lock`; installed into
      an isolated `.venv`.
- [x] `site/package-lock.json` used by `npm ci`; production build emits ten
      routes.
- [x] `install.sh` creates `.venv`, installs pins, builds the site, creates
      mode-700 runtime directories and renders units with absolute paths.
- [x] No Docker runtime required for this path. Compose remains an alternative.
- [x] Native deployment tests cover env placeholders, executable scripts, unit
      hardening, Git ignore rules and the secret scan.
- [ ] Reproducible release archive with checksums published. Not produced.

## B. Node and RPC integration

- [x] Existing BTCS Core `31.1.3` mainnet node authenticated over loopback RPC.
- [x] Node fully synced: `verificationprogress=1`, IBD false, peers present at
      verification time.
- [x] `getblocktemplate` returns a current height, `bits`, coinbase value,
      witness commitment and transaction list.
- [x] Template height and previous hash match the live chain tip.
- [x] Coinbase output is a valid 22-byte P2WPKH script from the existing `pool`
      wallet.
- [x] Node RPC remains on `127.0.0.1:10567`; the preflight rejects public RPC
      hosts.
- [ ] Node RPC exposed through an authenticated private network for a separate
      pool host. Not performed; the pool runs on the node host.

## C. Stratum connectivity and share handling

- [x] Stratum V1 subscribe returns `extranonce1` and the configured
      `extranonce2` size.
- [x] Difficulty and job notification are delivered after authorization.
- [x] Valid mainnet-difficulty share accepted and credited.
- [x] Duplicate share rejected as `duplicate-share`; no double credit.
- [x] Low-difficulty share rejected as `low-difficulty`.
- [x] Stale share rejected as `stale-job` after a simulated tip change.
- [x] Unauthorized submit rejected as `not authorized`.
- [x] Wrong Stratum password rejected as `unauthorized`.
- [x] Reconnect after restart receives a fresh job; replay is rejected.
- [x] LAN listener accepted a TCP connection and Stratum subscribe on
      `172.20.10.13:3333`.
- [x] Live production password check passed without creating a miner row; an
      isolated auth test confirmed `account.s9i` receives a job.
- [ ] Third-party miner application connected. None installed; only the
      controlled protocol harness and LAN probes have connected.
- [ ] Public Stratum TCP reachability. No public host/port/DNS exists.
- [ ] Firewall rule and port-forward approved. Not configured.

## D. Accounting and persistence

- [x] Production SQLite database initialized at
      `data/mainnet/pool.sqlite3` with ordered migrations.
- [x] Production DB is empty of miners, shares, blocks and payouts (only round
      lifecycle rows exist); the temporary `canary` authorization row was
      removed after confirming zero shares.
- [x] Isolated mainnet smoke recorded accepted and rejected shares and exposed
      them through the API.
- [x] Restart persistence: reopened DB retained shares and rejections.
- [x] Replay after restart rejected without double credit.
- [x] Duplicate prevention enforced by a database unique constraint.
- [x] Fee split, maturity and orphan reversal covered by Python tests.
- [ ] Real-chain reorganization exercised. Unit-level reconciliation only.
- [ ] Rolling-window PPLNS and vardiff. Current model is per-round, static
      difficulty.

## E. Website and API

- [x] Backend `/api/health`, `/api/ready`, `/api/status` return healthy/ready
      with the live node height.
- [x] Public config reports `auto_payouts=false`, `payouts_enabled=false` and
      Stratum `configured=false`.
- [x] API accounting endpoints expose the smoke miner's accepted/rejected
      shares and no blocks.
- [x] All ten site routes return HTTP 200 from the local server.
- [x] Headless Chrome renders live node height and readiness from the API.
- [x] Offline/error states are explicit; no fake hashrate, blocks or endpoint.
- [ ] Public API/site deployment with TLS. Not provisioned.
- [ ] External uptime and latency monitoring. Not configured.

## F. Block handling

- [x] SegWit coinbase, BIP34 height, merkle branch and 80-byte header assembly
      covered by tests.
- [x] Real block found and accepted by a regtest node in the E2E suite;
      canonical hash matched.
- [x] Mainnet smoke refuses all `submitblock` calls and treats a
      network-target hash as a failure.
- [x] Mainnet smoke recorded **0 block submissions**.
- [ ] A real mainnet block candidate submitted and accepted. Deliberately not
      attempted with payouts disabled and no external miner.

## G. Backup, restore and upgrade

- [x] Online SQLite backup with SHA-256 manifest and `integrity_check=ok`.
- [x] Isolated restore verified with matching table counts and integrity.
- [x] Restore refuses without `--yes`, stops services first and writes a
      pre-restore safety copy.
- [x] Upgrade script is plan-only by default, refuses a dirty tree and uses
      fast-forward-only Git.
- [ ] Scheduled off-host backups and retention policy. Not configured.
- [ ] Full upgrade/rollback rehearsal against a published release. Not possible
      until a release is published.

## H. Security and secrets

- [x] `.env.native` is mode `0600` and Git-ignored; live values were not
      printed or committed.
- [x] Secret scan passes for all tracked files.
- [x] Systemd units use `NoNewPrivileges`, `PrivateTmp`,
      `ProtectSystem=strict`, `ProtectHome=read-only` and explicit write paths.
- [x] API is read-only; there is no admin, mutation or payout endpoint.
- [x] CORS allowlist and rate limiting are configured; trusted proxies are
      explicit.
- [x] Payouts are disabled in config, API, database state and operator tools.
- [ ] Independent security review and public-operation threat model. Not
      performed.
- [ ] Durable services across logout/reboot. `Linger=no`; requires
      `sudo loginctl enable-linger`.

## I. External launch and payouts

- [ ] Public Stratum endpoint verified from an external network. **Blocked:**
      production `3333` is not externally verified, the current test password
      must not be exposed, and no stable public DNS name exists. A temporary
      IPv6 probe on `3334` did accept an external connection.
- [ ] Third-party miner verified against a public endpoint. **Blocked:** no
      public endpoint and no miner binary installed.
- [ ] Public API/site with TLS. **Blocked:** no public host or reverse proxy.
- [ ] Payout signing, broadcasting, confirmations, idempotency, operator
      authorization and recovery. **Not implemented; intentionally disabled.**
- [ ] Operational monitoring, alerting and on-call runbook. Not implemented.

## Launch decision

| Label | Applies to |
|---|---|
| `NOT READY` | Public launch, external mining, paying-pool operation |
| `TESTED LOCALLY` | Packaging, node RPC, templates, Stratum protocol, share accounting, API, persistence, backup/restore |
| `EXTERNAL CONNECTIVITY VERIFIED` | **No** |
| `MAINNET MINING VERIFIED` | **No** |

The backend is running locally on mainnet with real templates and an empty
production ledger. It can accept LAN miners on its current private address while
the DHCP lease holds, but it must not be announced as a public pool. Do not
enable payouts or advertise payouts. The minimum remaining work is an externally
reachable Stratum endpoint, a real third-party miner test, public TLS hosting,
payout implementation and an independent security review.
