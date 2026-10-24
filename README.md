# BTCS Mining Pool

Mining pool and Stratum services for Bitcoin Silver (BTCS) L1.

**Status: planned — scaffold only.** No pool, Stratum listener, share
accountant, or payout implementation exists in this repository yet. This
checkout defines the project boundary so pool work does not leak into the
consensus node or the exchange projects.

## Purpose

Provide a pool service that lets miners submit work for BTCS L1 while the pool
operator validates shares, accounts for them, and submits blocks through a
BTCS Core node. The pool is an operator-run service, not part of L1 consensus.

## Scope

Planned work, in dependency order:

1. **Stratum endpoint** — miner subscription and authorization, job
   distribution, difficulty adjustment, and share submission.
2. **Job construction** — build work from BTCS Core `getblocktemplate` and
   submit candidate blocks with `submitblock`.
3. **Share validation** — verify share hashes against the assigned target and
   reject stale, duplicate, or malformed shares.
4. **Accounting** — per-miner share records, round tracking, PPLNS or
   fee-based accounting, and an auditable payout ledger.
5. **Payouts** — operator-approved payout batches with explicit limits,
   dry-run mode, and reconciliation.
6. **Operations** — health and metrics endpoints, structured logs, restart
   recovery, and a read-only status page.

## Out of scope

- Changes to BTCS L1 consensus, block validation, or the mining RPC.
- Custody of miner funds or a hosted wallet service.
- Exchange, DEX, explorer, or payment functionality.
- Real-value pool operation before an independent security and operations
  review.

## Planned components

| Component | Responsibility | Depends on |
| --- | --- | --- |
| `stratum/` | Miner-facing TCP/WebSocket protocol | None yet |
| `jobs/` | Template fetch, job cache, block submission | BTCS Core RPC |
| `shares/` | Target math, duplicate and stale-share checks | `jobs/` |
| `accounting/` | Round and miner ledgers | `shares/` |
| `payouts/` | Operator-approved payout batches | `accounting/` |
| `api/` | Read-only pool status and metrics | `accounting/` |

The directory names are a proposed layout. They are not created yet.

## Integration points

- [btcs-core](https://github.com/Silver-Labs-Technology-Development/Silver-Labs-Bitcoin-Silver-Development)
  — JSON-RPC for `getblocktemplate`, `submitblock`, and chain state.
- [Silver-Scan](https://github.com/Silver-Labs-Technology-Development/Silver-Scan)
  — optional public statistics and block visibility.
- [silver-labs-platform](https://github.com/Silver-Labs-Technology-Development/silver-labs-platform)
  — shared schemas and service conventions where they fit.

The pool must treat the node as the authority for templates, chain tips, and
block acceptance. It must not maintain a competing view of consensus.

## Local development

There is no runnable code yet. When implementation starts, the expected local
setup is:

```sh
# Terminal 1: disposable BTCS Core regtest node with mining RPC enabled
# Terminal 2: pool service against 127.0.0.1
# Terminal 3: a local test miner or share generator
```

Do not point a development pool at a public node or use wallet data from
`archive/local-only/`.

## Safety and release status

This is a research and development scaffold. It is **not** production-ready and
has no security review. Pool software handles payout accounting and miner
credentials, so the following rules apply from the first commit:

- Never commit wallet data, private keys, seed phrases, `.env` files, or node
  cookies.
- Never enable real payouts without an operator-approved limit and a dry run.
- Treat share accounting and payout reconciliation as money-critical code.
- Do not expose a development node or pool endpoint to the public internet.

See [`SECURITY.md`](SECURITY.md) for the reporting policy.

## Repository layout

```text
.
├── README.md
├── LICENSE
├── SECURITY.md
├── .gitignore
└── docs/
    └── ARCHITECTURE.md
```

## License

No open-source license is granted. See [`LICENSE`](LICENSE). The repository is
public for review and development, not for reuse or redistribution.

## Related repositories

- [BTCS Core](https://github.com/Silver-Labs-Technology-Development/Silver-Labs-Bitcoin-Silver-Development)
- [BTCS L2](https://github.com/Silver-Labs-Technology-Development/btcs-l2)
- [POW-S](https://github.com/Silver-Labs-Technology-Development/POW-S)
- [Silver Labs workspace](https://github.com/orgs/Silver-Labs-Technology-Development/repositories)
