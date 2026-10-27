# Silver Pool — native mainnet launch

**Status:** local mainnet deployment verified; public connectivity **not** verified.
**Payouts:** disabled. **Public Stratum endpoint:** not configured.

This is the launch path for the existing synced BTCS mainnet node on this host.
It does **not** use the Compose `node` service, which creates a separate node
with a fresh datadir. The live node remains an independent, read-only service:

```text
/home/user/.local/share/silver-pool-mainnet/node   (live node, do not move)
/home/user/Silver-Labs/btcs-core/build/bin/bitcoinsilverd
127.0.0.1:10567                                    (private RPC)
```

The pool runs as two systemd **user** services:

- `silver-pool.service` — integrated Stratum + HTTP API process
- `silver-pool-web.service` — static site and `/api` reverse proxy

The API and website bind to loopback. Stratum binds to the configured host;
this host is currently configured with `0.0.0.0:3333` for LAN access, but no
public port-forward, DNS name, TLS terminator or external reachability test
exists.

## What was verified on 2026-10-26

| Check | Evidence |
|---|---|
| Live node identity | BTCS Core `/BitcoinSilver:31.1.3/`, chain `main`, 10 peers |
| Node sync | height 234,209, headers 234,209, `verificationprogress=1`, IBD false |
| RPC authentication | authenticated from the active node datadir config, loopback only |
| Mainnet template | height 234,210, `bits=192f033c`, coinbase 2,500,002,270 sat, 1 tx |
| Coinbase output | valid 22-byte P2WPKH script in the configured pool wallet |
| Stratum auth | subscribe, `extranonce1`, difficulty, authorize, notify |
| Valid share | accepted once and credited to the intended miner |
| Duplicate share | rejected as `duplicate-share`, not credited twice |
| Invalid share | rejected as `low-difficulty` |
| Stale share | rejected as `stale-job` after a simulated tip change |
| Unauthorized submit | rejected as `not authorized` |
| Wrong password | rejected as `unauthorized` |
| API | health, readiness, status, miner, shares, blocks and config verified |
| Restart | shares and rejections persisted; replay after restart rejected |
| Block submission | **0** attempts; the smoke harness refuses `submitblock` |
| Production DB | initialized empty; no test shares or blocks written |
| Backup / restore | online backup, SHA-256 manifest, integrity check, isolated restore |
| Website | all ten routes HTTP 200; live page read real node height 234,211 |
| Payouts | `BTCS_AUTO_PAYOUTS=false`; public API reports disabled |

The mainnet smoke uses an isolated temporary database and ephemeral ports. It
never writes to `data/mainnet/pool.sqlite3`, never submits a block and never
moves funds. It is **not** a substitute for a real third-party miner or an
external connectivity test.

## Requirements

- Existing synced BTCS mainnet node with RPC on loopback
- Python 3.12+
- Node.js 22+ and npm
- `systemd --user` session (or a system service if you adapt the units)
- `curl` and `jq` for the status examples
- ~1 GiB free disk for the pool database and backups (the node has its own disk)
- A firewall/port-forward decision before advertising a public Stratum endpoint

The runtime Python dependencies are pinned in `requirements.lock`. The site
uses `site/package-lock.json` and `npm ci`.

## Clean install

From a fresh clone:

```sh
cd ~/Silver-Labs/Silver-Pool
cp .env.native.example .env.native
chmod 600 .env.native
${EDITOR:-vi} .env.native
./deploy/native/install.sh --install-units
./deploy/native/preflight.sh
./deploy/native/verify-mainnet.sh
./deploy/native/start.sh
```

`install.sh` creates `.venv`, installs `requirements.lock`, runs
`npm ci`/`npm run build`, creates `data/mainnet`, `logs`, `run` and `backups`
with mode 700, renders the systemd user units with absolute paths, enables
them and runs preflight. It does not edit the environment file, start a node,
change DNS/firewall settings or write a payout.

### Environment

Copy `.env.native.example`; never commit `.env.native`. The important values:

| Variable | Launch value | Notes |
|---|---|---|
| `BTCS_NETWORK` | `main` | Preflight refuses any other network |
| `BTCS_RPC_URL` | `http://127.0.0.1:10567` | Loopback only; never expose RPC |
| `BTCS_RPC_USER` / `BTCS_RPC_PASSWORD` | active node credentials | Read from the node config; do not print or commit |
| `BTCS_RPC_WALLET` | `pool` | Existing wallet; not used for payouts |
| `BTCS_POOL_ADDRESS` or `BTCS_POOL_SCRIPT_PUBKEY` | one valid mainnet output | The configured address/script is the coinbase destination |
| `BTCS_POOL_FEE` | `2.0` | Accounting fee; no payout path |
| `BTCS_AUTO_PAYOUTS` | `false` | Must remain false |
| `BTCS_STRATUM_HOST` | `127.0.0.1` or `0.0.0.0` | `0.0.0.0` exposes Stratum on local interfaces |
| `BTCS_STRATUM_PORT` | `3333` | TCP, not HTTP |
| `BTCS_STRATUM_PASSWORD` | long random value | Miners must use it; never publish it |
| `BTCS_PUBLIC_STRATUM_HOST` | empty | Set only after an external TCP test |
| `BTCS_POOL_DIFFICULTY` | `1.0` | Static per-session difficulty; no vardiff |
| `BTCS_POOL_DB` | `data/mainnet/pool.sqlite3` | Separate from the legacy `data/pool.sqlite3` |
| `BTCS_POOL_API_HOST` / `BTCS_POOL_API_PORT` | `127.0.0.1` / `8765` | Keep loopback |
| `SILVER_POOL_HTTP_BIND` / `SILVER_POOL_HTTP_PORT` | `127.0.0.1` / `8080` | Local site only |

The current ignored `.env.native` was populated from the active node's
`bitcoinsilver.conf`, with a pool address created in the existing `pool` wallet
and a generated Stratum password. No secret value is in Git.

## Start, stop, status, logs

```sh
./deploy/native/start.sh
./deploy/native/status.sh
./deploy/native/logs.sh tail 200
./deploy/native/logs.sh follow
./deploy/native/stop.sh
```

`start.sh` waits for `/api/ready` before starting the website. The services are
enabled for the current user session. To survive logout/reboot without an
active login session, an administrator must enable linger:

```sh
sudo loginctl enable-linger "$USER"
```

That is a manual host change and was not performed. A system-wide unit is an
alternative but requires root.

## Health checks

```sh
curl -fsS http://127.0.0.1:8765/api/health | jq .
curl -fsS http://127.0.0.1:8765/api/ready | jq .
curl -fsS http://127.0.0.1:8765/api/status | jq .
curl -fsS http://127.0.0.1:8080/api/pool/config | jq .
```

`/api/ready` returns 503 until the database, node sync, Stratum listener, a
current job and a fresh template all pass. The website at
<http://127.0.0.1:8080/> proxies `/api`; it is not a separate backend.

## Miner connection

The website only advertises a public endpoint when `BTCS_PUBLIC_STRATUM_HOST`
is non-empty. It is empty, so the site correctly says “Not configured.”

Verified local endpoint (this host only):

```text
stratum+tcp://127.0.0.1:3333
```

Current LAN endpoint (tethered private address; subject to DHCP changes, use
`ip -brief addr` to read the current value):

```text
stratum+tcp://<private-lan-address>:3333
```

Miner username format: `account` or `account.worker`. The account owns
balances; the worker is the suffix after the final dot. The Stratum password
is the value of `BTCS_STRATUM_PASSWORD` in `.env.native` (read it locally; do
not paste it into a public page).

Example, using a SHA256d-capable miner:

```sh
miner -a sha256d \
  -o stratum+tcp://127.0.0.1:3333 \
  -u myaccount.rig1 \
  -p '<BTCS_STRATUM_PASSWORD from .env.native>'
```

The pool difficulty is static at `1.0`. That is suitable for SHA256d ASIC
hardware; a CPU miner would need roughly 2^32 hashes per share and is not a
practical launch test. No third-party miner is installed on this host; the
mainnet smoke uses a controlled protocol harness at a temporary, much easier
test difficulty.

## Public connectivity: not configured

Current host facts:

- LAN interface: tethered private address (check `ip -brief addr`; subject to
  DHCP changes)
- Public IPv4/IPv6: observed by the host but redacted from this public document
- No inbound TCP forwarding, public DNS record, TLS certificate or public
  hostname has been configured or verified
- Stratum is raw TCP; a Cloudflare Worker/Pages HTTP endpoint cannot proxy it

Do **not** set `BTCS_PUBLIC_STRATUM_HOST` until a real external client can
reach the endpoint. Passing a local `nc`/`curl` test is not external evidence.
For a public launch you need one of:

1. A public host/VPS with inbound TCP 3333 (or a chosen port) and a firewall
   rule limited to that port.
2. A TCP relay/port-forward from the public host to this pool, plus a DNS name.
3. A router/NAT port-forward and ISP that permits inbound TCP, plus a DNS name.

The HTTP API/site can be exposed separately behind a TLS reverse proxy; that
does not create a Stratum endpoint. RPC port 10567 must never be exposed.

## Backup and restore

Online backup (safe while the pool is running):

```sh
./deploy/native/backup.sh
# writes backups/pool-YYYYmmddTHHMMSSZ.sqlite3 and .json
```

Restore (stops both services first; writes a `pre-restore-*.sqlite3` safety
copy):

```sh
./deploy/native/restore.sh backups/pool-YYYYmmddTHHMMSSZ.sqlite3 --yes
./deploy/native/start.sh
```

The restore verifies SQLite `integrity_check` before replacing the database.
Payouts are disabled, so backup/restore does not involve wallet keys or
outbound transactions. The node wallet/datadir is not part of the pool backup;
back it up separately with the node's own procedures.

## Upgrade and rollback

Plan-only:

```sh
./deploy/native/upgrade.sh
```

Apply (refuses a dirty tree, backs up, fetches, fast-forwards only, installs,
tests, preflights and restarts):

```sh
./deploy/native/upgrade.sh --apply
```

It never runs `git reset --hard`, `git clean` or a rebase. If an upgrade fails,
the previous database backup path is printed by the backup step; revert the
upgrade commit with `git revert <commit>` (a new commit, not a history rewrite),
reinstall, and restore the backup only if accounting data is affected.

## Security boundaries

- Node RPC: loopback `127.0.0.1:10567`, authenticated; never publish it.
- API: loopback `127.0.0.1:8765`; read-only, no admin or payout endpoint.
- Website: loopback `127.0.0.1:8080`; proxies `/api` only.
- Stratum: `0.0.0.0:3333` in the current ignored env; reachable on local
  interfaces, not externally verified. Add a firewall rule before any public
  forwarding and restrict it to the intended port.
- Payouts: disabled in config, API, database state and operator tooling.
- Secrets: `.env.native` mode 600 and Git-ignored; systemd reads it directly.
- Service hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, explicit `ReadWritePaths` for `data`, `logs`, `run`.
- Secret scan: `./deploy/native/check-secrets.sh` scans tracked files and
  optional release archives.

## Known limitations

- No external/public Stratum endpoint or external test.
- No public API/site deployment or TLS terminator.
- No third-party miner test; no real miner has connected.
- Payouts are intentionally not implemented; do not advertise a paying pool.
- SQLite is single-process/single-node, not HA.
- Static difficulty; no vardiff or rolling PPLNS window.
- The node itself is not supervised by these units and was not restarted,
  moved or reconfigured.
- User services stop at logout unless linger is enabled by an administrator.
- No security audit.
