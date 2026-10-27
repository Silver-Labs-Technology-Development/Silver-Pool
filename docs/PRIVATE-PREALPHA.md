# Silver Pool — Private Pre-Alpha Readiness

**Status**: Private pre-alpha on Bitcoin Silver (BTCS) mainnet. Not a paying pool. No withdrawals. No automatic payouts.

This document establishes the security boundaries, invitation-only access rules, operator responsibilities, and operational checklist for the Silver Pool private pre-alpha deployment on BTCS mainnet.

---

# 1. Purpose and Scope

The goal of this pre-alpha is to verify:
- Mainnet connectivity: BTCS Core node synchronised and reachable on mainnet.
- Mining job flow: Stratum V1 → share validation → block template → submitblock.
- Share accounting: PPLNS per-round weighting, fee split, maturity, orphan handling.
- Private API and Stratum: Access limited to invited testers only.
- Dashboard honesty: UI clearly identifies state as private pre-alpha, disables payout implications.
- Database persistence: SQLite accounting survives restart, retains accepted shares and blocks.

This is **not** a public pool. There will be no on-chain payments, no automatic payouts, and no withdrawal functionality. Miners participate to verify the pool software stack and provide feedback on the operator experience.

---

## 2. Security Boundaries

| Boundary | Rule |
|---|---|
| **RPC access** | BTCS RPC (port 10567) must **never** be published to the internet. Access only via private Docker network or SSH tunnel. |
| **HTTP API** | Pool API (port 8765) must **never** be published to the internet. Bind to loopback (`127.0.0.1`) or private IP only. |
| **Stratum** | Stratum V1 (port 3333) must **never** be exposed to the public internet until DNS, firewall, and TCP reachability are verified for the invited group only. |
| **Website** | GitHub Pages hosts the static frontend only. It must point to the deployed backend API, not `127.0.0.1` or a developer machine. |
| **Administrative controls** | All operator controls (payout execution, wallet management, node shutdown) must be unavailable to any public visitor. |
| **Credentials** | RPC usernames/passwords, wallet secrets, and private keys must **never** appear in API responses, logs, or Git history. |
| **Coinbase destination** | The pool operator must document which BTCS address receives coinbase rewards and how the wallet is backed up. |

---

## 3. Invitation-Only Access

- The pool operator provides **explicit access credentials** (e.g., an allowlist of IP addresses, SSH tunnels, or VPN accounts) to invited testers.
- **Do not** publish a Stratum address on public forums or social media.
- **Do not** expose `BTCS_PUBLIC_STRATUM_HOST` or `BTCS_PUBLIC_STRATUM_PORT` in the UI unless TCP reachability has been verified for the invited group.
- The UI must display **"Stratum: Not configured"** when `BTCS_PUBLIC_STRATUM_HOST` is blank, and **must not invent** an address.

### Adding a Tester Miner

1. The operator adds the tester's IP or credentials to the allowlist (via `BTCS_TRUSTED_PROXIES` or firewall rules).
2. The tester runs a Stratum-compatible miner pointing to the private endpoint.
3. The miner's shares are recorded in the SQLite database and visible via the API.
4. The tester **must not** be promised, expected, or able to withdraw any BTCS.

---

## 5. Mainnet Preflight Checklist

Before starting the pool, run the following checks. Every item must pass.

| # | Check | Command / API | Expected |
|---|---|---|---|
| 1 | **Node network identity** | `bitcoinsilverd getnetworkinfo` → `chain` | `"main"` |
| 2 | **Node synchronization** | `bitcoinsilverd getblockchaininfo` → `blocks`, `initialblockdownload` | `initialblockdownload=False`, `blocks` is a large, growing number |
| 3 | **RPC reachability** | `curl http://127.0.0.1:10567/api/health` (or via Compose DNS `http://node:10567/api/health`) | `200 OK` |
| 4 | **Chain consistency (wait-for-node)** | `python -m btcs_pool.wait-for-node` (or run via Compose) | Exit code `0`, output shows `chain=main` |
| 5 | **Template freshness** | `bitcoinsilverd getblocktemplate` | Returns a valid block template with current height |
| 6 | **Database writability** | `python -c "from btcs_pool.db import Database; db = Database('/data/pool.sqlite3'); print('OK')"` | Creates/opens database without error |
| 7 | **Payouts disabled** | Config: `BTCS_AUTO_PAYOUTS=false` | Confirmed in `.env` and `docker-compose.yml` |
| 8 | **Fee configuration** | `BTCS_POOL_FEE=2.0` | Confirmed in `.env` |
| 9 | **Maturity confirmations** | `BTCS_MATURITY_CONFIRMATIONS=200` | Confirmed in `.env` |
| 10 | **Stratum listener** | `curl http://127.0.0.1:8765/api/stratum-status` (if available) | Listener active, no errors |

**Fail-fast**: If any check in rows 1–3 fails, **do not start the pool**. Fix the underlying issue first.

### 5.1 Forcing Network Agreement

The `wait-for-node.py` script (included in the pool Docker image) explicitly refuses to start if `BTCS_NETWORK` does not match the node's reported chain:

```
BTCS_NETWORK=main expects chain "main", but the node reports testnet3
```

---

## 7. Known Limitations (Pre-Alpha)

- ✅ **Regtest development** is fully supported for automated tests and local prototyping.
- ✅ **Mainnet configuration** is implemented (ports, RPC, Stratum, accounting).
- ✅ **Safety chain validation** via `wait-for-node.py` prevents mainnet/regtest mismatch.
- ❌ **Mainnet node synchronization** — requires ~1–8 hours depending on hardware and network.
- ❌ **Live block discoveries** — will not submit blocks to mainnet during pre-alpha.
- ❌ **Automatic payouts** — disabled. No signing, broadcasting, or confirmation workflow exists.
- ❌ **Miner withdrawals** — not operational. Balances are accounting-only.
- ❌ **Docker image builds and runtime healthchecks** — unverified in this environment (Docker socket not available).
- ❌ **Caddy TLS runtime** — Caddy is not installed; TLS termination must be provided externally (e.g., a reverse proxy or load balancer).
- ❌ **Public Stratum endpoint** — not yet reachable from outside the private network.
- ❌ **Security audit** — do not use real funds.

---

## 9. Test Commands (Run Before Pre-Alpha)

```bash
# Python unit, API, Stratum, persistence, and regtest E2E tests
python3 -m pytest -q tests/

# Website static checks, browser navigation, and build
cd site
npm ci
npm test
npm run test:browser
npm run build
cd ..

# Docker Compose config validation (base)
docker compose -f deploy/docker-compose.yml config >/dev/null

# Docker Compose config validation (production overlay)
SILVER_POOL_SITE_ADDRESS=pool.invalid docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml config >/dev/null
```

---

## 6. Accounting and Payout Boundary

- **`BTCS_AUTO_PAYOUTS` must remain `false`** until reward signing, broadcast, confirmation, idempotency, and recovery lifecycles are fully implemented and tested.
- **Shares and accounting records** are tracked and visible via the API, but **no on-chain payment is initiated**.
- **Internal reward allocations** (0.5% development + 1.5% planned staking) are **not equivalent** to completed on-chain payments.
- **Block rewards** are initially directed according to the configured coinbase destination (`BTCS_POOL_ADDRESS` or wallet-derived address). The pool records the allocation but does not distribute it to miners.
- **Miners must not be promised, expected, or able to withdraw** any BTCS. The UI must make this unambiguous.

### UI Disclosure Requirements

The website must display, at minimum:

- **Network**: `mainnet` (prominent, not hidden).
- **Payout status**: `Disabled — automatic payouts not operational. This is a private pre-alpha. No withdrawals.`
- **Stratum**: `Not configured` or the private endpoint (if verified for the invited group only).
- **Pre-alpha badge**: The page must visibly identify itself as **private pre-alpha**, not a launched or paying public pool.

---

---
## 8. Rollback and Recovery

| Situation | Action |
|---|---|
| **Node fails to sync** | Stop the stack, delete `node-data` volume, re-run `docker compose up -d --build node`. Mainnet sync will take hours. |
| **Pool crashes on startup** | Review `docker compose logs pool` for RPC/auth errors. Fix `.env` credentials. Restart. |
| **Database corruption** | Restore from the most recent backup of `/data/pool.sqlite3`. Do not manually edit the SQLite file. |
| **Accidental mainnet/regtest mismatch** | Verify `BTCS_NETWORK` in `.env` matches the node's `chain` field from `getnetworkinfo`. Use `wait-for-node.py` to validate before restart. |
| **TLS certificate expiry** | Renew via Caddy or your TLS terminator. The Caddyfile in `deploy/web/` is a reference only. |

---
## 10. PASS / FAIL / BLOCKED Report (Operator-Filled)

After completing the preflight checklist, fill in the following:

```
PASS / FAIL / BLOCKED: ____________

Tested URLs/ports:
  - API health:        http://127.0.0.1:8765/api  → ______
  - Stratum endpoint:  stratum+tcp://<HOST>:3333   → ______
  - Website (HTTPS):   https://<SILVER_POOL_SITE>/ → ______

Launch commands:
  docker compose -f deploy/docker-compose.yml up -d --build   (node first, then pool+web)

Remaining manual prerequisites:
  1. ________________________________
  2. ________________________________
  3. ________________________________
```

---
## 11. Contact and Questions

- **Repository**: https://github.com/Silver-Labs-Technology-Development/Silver-Pool
- **Operator**: Direct via the Silver Labs communication channel.
- **Security**: Report vulnerabilities privately; do not open public issues with credentials or wallet data.

---
*This document is version 0.1. Pre-alpha boundaries and procedures will be updated as the specification matures. Operators must re-read this document before each launch cycle.*
