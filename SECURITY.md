# Security policy

## Scope

This repository is a **local regtest prototype** of Silver Pool. It has been
tested against a real Bitcoin Silver Core regtest node, but it has no production
deployment, no public Stratum endpoint and no authorization for real-value
mining or payouts.

Do not use real funds with this software.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, wallet
material or a working payout bypass. Report privately to the Silver Labs
maintainers through the organization account:

<https://github.com/Silver-Labs-Technology-Development>

Allow time for investigation and a fix before disclosure. Include the affected
commit, configuration, reproduction steps and impact. Redact secrets and wallet
data.

## Security boundaries in the current implementation

- **Read-only public API.** There is no authentication, mutation, admin or
  payout endpoint. The API exposes aggregate pool and miner statistics only.
- **Private RPC.** In Compose, BTCS RPC is reachable only on the private
  network. Port `10567`/`18443` is never published. The node writes
  `bitcoin.conf` with mode `0600` inside the node volume.
- **Private API.** The pool API is not published. Caddy reaches `pool:8765` on
  the Compose network and exposes only `/api` under the site origin.
- **Rate limiting and CORS.** API requests are rate-limited per client. CORS is
  an allowlist. `X-Forwarded-For` is trusted only when the direct peer matches
  `BTCS_TRUSTED_PROXIES`.
- **Share validation.** Shares are checked against the assigned target and
  current job. Duplicate and stale shares are rejected and audited.
- **Block credit.** A block is credited only after `submitblock` returns
  acceptance (or a duplicate result whose canonical hash matches). Rejected
  candidates do not create balances.
- **Transactional accounting.** Share and block accounting use short SQLite
  transactions with foreign keys and unique constraints.
- **Payouts disabled.** There is no signing, transaction construction,
  broadcasting, confirmation policy, recovery path or operator authorization
  for payouts. `BTCS_AUTO_PAYOUTS` must remain `false`; the container
  entrypoint refuses any other value.
- **Loopback defaults.** The code binds API and Stratum to `127.0.0.1` by
  default. The base Compose stack publishes only the web UI on loopback and the
  Stratum port; the production overlay is an explicit TLS deployment.
- **No secret logging.** RPC credentials and the Stratum password are not
  included in the public configuration endpoint. Public request logs should
  still be reviewed before production use.

## Secrets and repository hygiene

Never commit:

- `.env` files or real RPC credentials,
- wallet files, descriptors, private keys or seed phrases,
- node datadirs, chainstate or blockchain data,
- TLS private keys or provider tokens,
- database files containing miner or payout data.

`.gitignore` and `.dockerignore` exclude these paths. `.env.example` contains
placeholders only. Replace every placeholder before any deployment and keep the
resulting `.env` out of Git.

## Known limitations

- No independent security audit or production threat-model review.
- No live pool backend deployment, public API endpoint, Stratum endpoint, DNS,
  TLS or firewall verification. Only the static frontend is deployed to GitHub
  Pages.
- Docker images and the Caddyfile have not been runtime-validated in this
  environment.
- SQLite is a single-node store; there is no HA or multi-writer design.
- PPLNS is per-round, not a rolling N-share window.
- No vardiff; difficulty is static per session unless a miner suggests a value.
- No payout implementation.
- No tested backup/restore or disaster-recovery procedure.
- The deployed static GitHub Pages site cannot host the API or Stratum; without
  a same-origin proxy it intentionally shows offline states.

## Safe development practice

- Use a throwaway regtest datadir and non-production credentials.
- Keep RPC and API ports on loopback or a private network.
- Use long, unique RPC passwords; do not reuse them.
- Treat the pool database and node datadir as sensitive operational data.
- Run the test suite before publishing changes:

```sh
python3 -m pytest -q tests
cd site && npm test && npm run test:browser && npm run build
```

- Review `git diff` and staged files for secrets before every commit.
