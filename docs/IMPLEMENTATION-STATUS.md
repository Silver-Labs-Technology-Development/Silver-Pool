# Silver Pool — implementation status

**Last updated:** 2026-10-26
**Version:** `0.2.0`

## Classification

| Field | Value |
|---|---|
| Product | Silver Pool |
| Chain | Bitcoin Silver (BTCS), SHA256d |
| Verified stage | Local regtest prototype |
| Real node used | Bitcoin Silver Core `v31.1.3` |
| Production / mainnet | **No** |
| Pool backend deployment | **No** |
| Static frontend deployment | GitHub Pages (verified) |
| Payouts | **Disabled** |
| Repository | `https://github.com/Silver-Labs-Technology-Development/Silver-Pool` |

The pool verification below was performed on this machine against a throwaway
regtest datadir. It is not evidence of cloud-hosted, testnet, regtest-hosted, or
mainnet pool operation. The static website is deployed separately to GitHub
Pages and has no API, Stratum or node behind it.

## Implemented backend

| Module | Implemented behavior |
|---|---|
| `config.py` | `PoolConfig` dataclass; environment and optional JSON overrides; network-port defaults; fee 0–5%; positive difficulty/min payout; extranonce2 size 1–32; public redacted view |
| `rpc.py` | Authenticated JSON-RPC for base and wallet endpoints; `getblocktemplate`, `submitblock`, `getblockchaininfo`, network/mempool info, `getblockhash`, wallet create/load/address, `validateaddress`/`getaddressinfo` |
| `node.py` | Five-second cached snapshot; connected/synced/IBD/progress/connections/mempool/warnings/error; failures returned as data, not raised to API callers |
| `block.py` | BIP34 height encoding including `OP_0`/`OP_1`–`OP_16`; varint; coinbase with witness commitment; merkle root/branch; internal/display byte order; header/block assembly; bits and difficulty targets; target boundary check |
| `db.py` | SQLite WAL, foreign keys, busy timeout, ordered migrations, short `BEGIN IMMEDIATE` transactions, backup, legacy-table quarantine and import; no in-memory fallback |
| `accounting.py` | Miner/worker registration; share insert with duplicate detection; round rotation; difficulty-weighted per-round PPLNS; exact integer fee split; immature/available balances; maturity and orphan reconciliation; fee ledger; payout ledger state transitions |
| `stratum.py` | Stratum V1 subscribe/authorize/suggest-difficulty/notify/configure/submit; per-session extranonce1; miner extranonce2; stale and duplicate rejection; block assembly and real `submitblock`; rejected-candidate audit; reconnect; shutdown |
| `api.py` | 17 routes (15 data endpoints plus `/api/docs` and `/api/openapi.json`); envelopes; request IDs; CORS; rate limiting; trusted-proxy handling; validation; 404/405/500; health/readiness; OpenAPI |
| `server.py` | Coinbase script resolution (address, script or wallet); API and Stratum startup; template polling; maturity loop; signal handling; orderly shutdown |

## HTTP endpoints

All data endpoints except `/api/openapi.json` use the common envelope.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Liveness; database health; HTTP 200 even when degraded |
| GET | `/api/ready` | HTTP 503 until database, node, job and template checks pass |
| GET | `/api/status` | Combined checks, node, Stratum, pool totals |
| GET | `/api/pool/status` | Overview plus recent blocks/shares/round/config |
| GET | `/api/pool/statistics` | Totals and 24-hour hashrate estimate |
| GET | `/api/pool/history/hashrate` | `range=1h`, `6h`, `24h` (default), `7d` |
| GET | `/api/pool/miners` | `limit` 1–200 (default 50), `search` ≤ 80 chars |
| GET | `/api/pool/miner/{username}` | Miner, workers, balances, recent blocks |
| GET | `/api/pool/miner/{username}/shares` | `limit` 1–200 |
| GET | `/api/pool/shares/recent` | `limit` 1–200 |
| GET | `/api/pool/blocks` | `limit`, `status=all\|immature\|mature\|orphaned` |
| GET | `/api/pool/blocks/recent` | `limit` |
| GET | `/api/pool/fee-ledger` | `limit` |
| GET | `/api/pool/rounds/current` | Current active round or `null` |
| GET | `/api/pool/config` | Public configuration; no secrets |
| GET | `/api/docs` | Enveloped endpoint index |
| GET | `/api/openapi.json` | Raw OpenAPI 3.0.3 document |

There is no authentication, mutation endpoint, admin endpoint or payout
endpoint. Deployment exposes the API only through the private Caddy proxy.

## Persistence

The initial migration creates:

- `schema_migrations`
- `miners`, `workers`
- `rounds`, `jobs`
- `shares` with unique `(miner_id, job_id, extranonce2, ntime, nonce)`
- `block_candidates`
- `blocks`
- `reward_allocations`
- `miner_balances`
- `pool_fee_ledger`
- `payouts`

All monetary columns are integer satoshis. Legacy databases without a
`schema_migrations` table are quarantined as `legacy_*`, migrated, and compatible
rows imported. `PRAGMA foreign_key_check` is covered by tests.

SQLite is a single-node store. The design is safe for one integrated pool
process with WAL and short write transactions, not for horizontal scaling or
high availability.

## Accounting and payout boundary

- PPLNS weights are `SUM(difficulty)` of accepted, non-stale shares in the
  current template-height round.
- If a block round has no shares, the finder receives the full reward.
- The last allocation receives the integer remainder, so allocations reconcile
  exactly to the block value.
- Rewards are immature until the configured maturity (default 200
  confirmations).
- Orphans reverse pending allocations and immature balances and mark the fee
  ledger entry orphaned.
- The fee ledger is separate from miner balances.
- `payouts` supports `request_payout`, `cancel_payout` and `mark_payout_sent`
  for accounting tests. It does **not** construct, sign or broadcast a
  transaction, and no API exposes it.
- `BTCS_AUTO_PAYOUTS` must remain `false`. The container entrypoint exits
  non-zero for any other value, and the public API always reports
  `auto_payouts: false` and `payouts_enabled: false`.

## Website

Ten independently built HTML routes:

| Route | Content |
|---|---|
| `/` | Overview and live pool summary |
| `/statistics/` | Totals, hashrate chart/history |
| `/miners/` | Miner list, search, live values |
| `/miner/` | Miner detail by query, workers and blocks |
| `/blocks/` | Recent blocks and status |
| `/getting-started/` | Real endpoint when configured; “Not configured” otherwise |
| `/pool/` | Fees, reward method, payout policy, disabled status |
| `/api-docs/` | Endpoint reference and OpenAPI link |
| `/status/` | API, database, node, Stratum and readiness state |
| `/help/` | Troubleshooting and honest diagnostics |

The site uses shared ES modules, relative `/api` fetch, accessible single `h1`
per page, responsive navigation and explicit loading/empty/error states. It
never substitutes sample miners, hashrate, blocks, balances, uptime or payouts
when the API is unavailable.

The Vite build uses `SITE_BASE` (default `/`). The Pages workflow uses
`/Silver-Pool/`. The development server proxies `/api` to `127.0.0.1:8765` and
returns an explicit JSON 502 when the backend is unreachable.

## Verification evidence

### Python

Command:

```sh
python3 -m pytest -q tests
```

Result: **100 passed, 0 failed, 0 skipped** in 34.85 seconds (2026-10-26).
The real-node E2E ran because `bitcoinsilverd` was available.

Coverage by file:

| File | Covered behavior |
|---|---|
| `test_block.py` | Varint boundaries; BIP34 heights 0/1/16/17/…; byte order; regtest targets; hash boundary; merkle roots/branches; coinbase split; full header/block assembly |
| `test_db.py` | Fresh migrations/WAL; reopen/idempotence; rollback; backup; legacy quarantine/import; foreign keys; explicit path |
| `test_accounting.py` | Identity parsing; exact PPLNS math; registration/workers/duplicates; allocation/maturity/orphan; hashrate history; payout boundary; finder fallback |
| `test_config.py` | Loopback defaults; payouts disabled; env overrides; network port defaults; invalid values; secret redaction; JSON config |
| `test_rpc.py` | Auth, wallet path, `getblocktemplate` rules, domain errors, HTTP auth errors, connection failure, missing wallet |
| `test_node.py` | Snapshot/caching; IBD not synced; RPC failure as data; cache TTL; dataclass |
| `test_stratum.py` | Subscribe/authorize/job/extranonce; authorization failures and unknown methods; difficulty/share/duplicate; invalid share classes; stale after tip change; accepted block submission; rejected `submitblock`; shutdown; reconnect |
| `test_api.py` | Envelopes/request IDs/headers; online status and payout flags; readiness success/failure; degraded liveness; miners/detail/search; statistics/blocks/hashrate/round/fee ledger; secret-free config; CORS; rate limit; trusted proxy; 404/405/500 |
| `test_deployment.py` | Compose services/volumes/ordering/healthchecks/restart; RPC/API not published; production overlay; pinned checksum; non-root images; Caddy routing/headers; placeholder env; `.dockerignore` |
| `test_e2e_regtest.py` | Real daemon, 10 generated blocks, real template, Stratum subscribe/authorize/notify, block found and accepted at height 11, canonical hash match, immature accounting, duplicate, stale, API visibility, restart persistence |

### Website

```sh
cd site
npm ci
npm test             # 8 passed
npm run test:browser # 7 passed
npm run build
```

- Static suite: every route has one `h1`, unique title/description, full
  navigation, resolvable internal assets, no fake endpoints or payout claims,
  no deleted single-page references, built-output integrity, Vite inputs and
  package scripts.
- Browser suite: all ten direct loads, titles/headings/active nav, live API
  values, miner search/detail, navigation, back/forward, reload, mobile menu
  without horizontal overflow, and API-error states on every page.
- Build: all ten `index.html` pages plus hashed assets in `site/_site`.

Browser tests use installed Chrome through a small CDP client because
Playwright was unavailable in this environment.

### Deployment files

```sh
docker compose --env-file .env.example -f deploy/docker-compose.yml config
SILVER_POOL_SITE_ADDRESS=pool.invalid docker compose --env-file .env.example \
  -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml config
```

Both pass. This validates interpolation and schema, not container runtime.

### CI and static hosting

- GitHub Actions CI run
  [`40299896414`](https://github.com/Silver-Labs-Technology-Development/Silver-Pool/actions/runs/40299896414)
  passed for commit `a8f0071`: Python tests, static site tests, browser tests,
  production build and both Compose config validations.
- GitHub Pages run
  [`40300316286`](https://github.com/Silver-Labs-Technology-Development/Silver-Pool/actions/runs/40300316286)
  built with `SITE_BASE=/Silver-Pool/` and deployed successfully.
- Live URL: <https://silver-labs-technology-development.github.io/Silver-Pool/>.
  All ten routes returned HTTP 200 with the expected page titles, and the
  hashed JS/CSS assets returned HTTP 200. Because Pages cannot run the backend,
  the live site requests `/api` from the Pages origin, receives no API, and
  renders the same explicit offline states covered by the browser suite.

## Deployment state

The Compose stack is complete in the repository:

- official BTCS Core `31.1.3` release URL and SHA256
- persistent named volumes for chain, pool DB and Caddy state
- node healthcheck and pool startup ordering
- chain/network verification before the pool starts
- private RPC; private API
- non-root pool image; dropped capabilities; `no-new-privileges`
- Caddy static MPA, `/api` reverse proxy, security headers, clean-route
  redirects, TLS overlay
- `.env.example` with placeholders only; payouts disabled

No Compose image was built or started here. The Docker socket is `root:docker`,
the current user is not in the `docker` group, and `sudo` requires a password.
Caddy is not installed; the package download timed out and the partial `.deb`
could not be extracted. Therefore container startup, healthchecks, volume
permissions, RPC connectivity from the pool container, Caddy routing and TLS
remain unverified.

The static frontend, by contrast, is deployed and verified on GitHub Pages. That
is a static-only deployment: it has no pool backend, database, API or Stratum
listener. The site therefore shows offline states rather than live pool data.

## Not implemented / blockers

| Item | State |
|---|---|
| Live pool backend deployment | Blocked: no provider credentials, host, DNS or firewall access |
| Public Stratum endpoint | Blocked: no public host/port; `BTCS_PUBLIC_STRATUM_HOST` unset |
| Mainnet pool | Blocked: no mainnet node, funding, operations or public infrastructure |
| Docker build/runtime | Blocked by socket permissions |
| Caddy runtime | Blocked: Caddy unavailable |
| Payouts | Disabled by design; signing/broadcast/confirmation/recovery not implemented |
| Rolling-window PPLNS | Not implemented; current model is per-round difficulty-weighted |
| Vardiff | Not implemented; static per-session difficulty with optional miner suggestion |
| HA / multi-node database | Not supported; SQLite single-writer design |
| Security audit | Not performed |

## Historical documents

`docs/AUDIT-REPORT.md` and `docs/REPOSITORY-AUDIT.md` are snapshots from
2026-10-24. Their counts, endpoint lists and “missing” classifications are
historical and have been superseded by this document.
