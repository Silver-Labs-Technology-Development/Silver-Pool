# Native BTCS mainnet deployment

This directory contains the native (non-Docker) launch path for Silver Pool. It
runs the backend and website as systemd **user** services against an existing,
already-synced BTCS mainnet node. It does not create, restart or reconfigure the
node.

For the full runbook, evidence table, security boundaries and external
connectivity blockers, read [`docs/MAINNET-LAUNCH.md`](../../docs/MAINNET-LAUNCH.md).
For the release gate status, read [`LAUNCH-CHECKLIST.md`](../../LAUNCH-CHECKLIST.md).

## Safety defaults

- Payouts are disabled. `BTCS_AUTO_PAYOUTS=false` is required and checked.
  Nothing in this directory signs or broadcasts a transaction.
- Node RPC stays on loopback. The preflight rejects a non-private RPC host.
- The API and website bind to loopback by default.
- Stratum is raw TCP. A public endpoint is advertised only when
  `BTCS_PUBLIC_STRATUM_HOST` is set after a real external test.
- `.env.native` is Git-ignored and must be mode `0600`.

## Files

| Path | Purpose |
|---|---|
| `install.sh` | Create `.venv`, install `requirements.lock`, build the site, create runtime directories, optionally install units, run preflight |
| `start.sh` / `stop.sh` | Start or stop both user services |
| `status.sh` | Service state, health/readiness, website reachability and DB counts |
| `logs.sh` | `follow` (default) or `tail [lines]` journal output |
| `preflight.sh` | Read-only env/node/template/coinbase/port/payout checks |
| `verify-mainnet.sh` | Isolated mainnet Stratum/share/API/restart smoke test; never submits a block |
| `backup.sh` | Online SQLite backup with SHA-256 manifest and integrity check |
| `restore.sh` | Stop, safety-copy, restore and verify a backup |
| `upgrade.sh` | Plan by default; `--apply` backs up, fast-forwards, tests and restarts |
| `check-secrets.sh` | Scan tracked files and optional archives for secrets |
| `systemd/*.service.in` | Hardened user-unit templates rendered with absolute paths |
| `tools/` | Python implementations of the preflight, smoke, backup, restore and scan tools |

## Quick start

```sh
cd ~/Silver-Labs/Silver-Pool
cp .env.native.example .env.native
chmod 600 .env.native
${EDITOR:-vi} .env.native

./deploy/native/install.sh --install-units
./deploy/native/verify-mainnet.sh
./deploy/native/start.sh
./deploy/native/status.sh
```

`install.sh` does not start the node, edit `.env.native`, change DNS/firewall
rules or write a payout.

## Required environment

See [`.env.native.example`](../../.env.native.example) for every value and
comment. The minimum launch values are:

- `BTCS_NETWORK=main`
- `BTCS_RPC_URL=http://127.0.0.1:10567` (loopback only)
- `BTCS_RPC_USER` / `BTCS_RPC_PASSWORD` from the existing node config
- Exactly one of `BTCS_POOL_ADDRESS` or `BTCS_POOL_SCRIPT_PUBKEY`
- `BTCS_AUTO_PAYOUTS=false`
- `BTCS_STRATUM_PASSWORD` (long random value)
- `BTCS_POOL_DB=data/mainnet/pool.sqlite3`

The current host uses `BTCS_STRATUM_HOST=10.42.0.1` to restrict Stratum to the
direct S9i LAN. That is not a public endpoint and is not advertised by the
API/site because `BTCS_PUBLIC_STRATUM_HOST` is empty.

## Verification boundary

`verify-mainnet.sh` proves real mainnet template construction, Stratum
authentication, accepted/duplicate/invalid/stale/unauthorized share handling,
API accounting, restart persistence and replay rejection. It uses a temporary
database and ephemeral ports, and its RPC wrapper refuses every `submitblock`
call. A hash that meets the network target is treated as a test failure and is
never submitted.

It does **not** prove:

- that an external miner can reach Stratum;
- that a third-party miner application works;
- that block submission or payouts work on mainnet;
- that the site/API is publicly deployed with TLS.

Those are tracked in [`LAUNCH-CHECKLIST.md`](../../LAUNCH-CHECKLIST.md).

## Persistence and supervision

The backend service writes only to `data/`, `logs/` and `run/` under the
repository. The units set `NoNewPrivileges`, `PrivateTmp`,
`ProtectSystem=strict`, `ProtectHome=read-only` and explicit `ReadWritePaths`.

User services stop at logout unless an administrator enables linger:

```sh
sudo loginctl enable-linger "$USER"
```

That host change has **not** been made. A system-wide unit is the alternative
if root access is available.

## Troubleshooting

```sh
./deploy/native/status.sh
./deploy/native/logs.sh tail 200
./deploy/native/preflight.sh --strict-ports
systemctl --user status silver-pool.service silver-pool-web.service
```

If `/api/ready` is 503, check in order: database health, node sync, Stratum
listener, current job and template freshness. The readiness payload names the
failing component; the site deliberately shows an offline state instead of
stale data.
