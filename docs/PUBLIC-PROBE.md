# Silver Pool — external reachability probe

This is an **operator verification tool**, not a public launch certificate.

The pool's native local tests can pass even while public HTTPS or TCP access is
unavailable. The read-only probe in `scripts/public_readiness.py` is intended to
run from an **independent network outside the pool host and its LAN**, after the
operator has configured a public HTTPS site/API reverse proxy and a Stratum TCP
port. It uses only the Python standard library.

## Run from an external network

```sh
python3 scripts/public_readiness.py \
  --api-base https://pool.example.com \
  --stratum-host mine.example.com \
  --stratum-port 3333
```

Replace both example domains with the actual deployed names. Do not run the
command with the placeholders. The `--api-base` argument must be the **HTTPS
origin** serving the actual pool API under `/api/`, not the GitHub Pages
static-only site. HTTPS certificates are validated using the platform's
normal CA trust store. The Stratum TCP port is separate from HTTPS and is not
proxied through ordinary Cloudflare Workers/Pages.

The probe checks:

1. `GET /api/health`: correct service identity and healthy database.
2. `GET /api/ready`: connected/synced node, active Stratum process, fresh
   template and a current job.
3. `GET /api/pool/config`: BTCS mainnet, disabled payouts and a public
   advertised Stratum host/port matching the requested endpoint.
4. A **single Stratum V1 `mining.subscribe`** over TCP: validates the response
   shape without providing credentials, authorizing a miner or submitting a
   share. No wallet commands, mining submissions or admin routes are called.

Output uses `PASS` or `FAIL` for each check. The process exits with code 0
only when all four pass and exits nonzero when any check fails. A successful
result proves a limited external connection **from that testing network at
that time**. TCP subscription does not demonstrate actual mining, block
submission, sustained service reliability or payouts.

## Before calling the pool ready

- [ ] Independently verify external DNS/HTTPS, valid TLS and external TCP.
- [ ] Confirm the pool is actually reachable by a third-party ASIC miner,
      authorizes the intended worker and records an accepted share.
- [ ] Confirm rate limits, DDoS controls, logging, uptime monitoring, off-host
      backup/restore and operator response procedures.
- [ ] Obtain an independent security review before using real funds.
- [ ] Keep payouts disabled. Signing, confirmation, idempotency, recovery and
      payout operations are **not implemented** in the current release.

Do **not** set `BTCS_PUBLIC_STRATUM_HOST` based only on a local check. Configure
a strong private Stratum password and have an external operator verify the
actual port before publishing a miner address. The probe deliberately never
prints or asks for a password.

## Testing without a live network

```sh
python3 -m pytest -q tests/test_public_readiness.py
```

These tests mock TCP connections and exercise the pure response validators;
they do not connect to the pool or validate your deployment. For the existing
local mainnet node harness and security preflight, see
[`MAINNET-LAUNCH.md`](MAINNET-LAUNCH.md).
