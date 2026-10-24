# Silver Pool architecture

> **Status: candidate design note.** The scope and decisions in
> [`README.md`](../README.md) remain authoritative. This document does not
> authorize implementation.


This document describes the intended boundary and data flow. It is a design
note, not a description of running software. No component below is implemented
yet.

## Design principles

1. **The node is authoritative.** Templates, chain tips, and block acceptance
   come from BTCS Core. The pool never guesses consensus.
2. **Shares are not blocks.** A valid share is accounting evidence, not proof
   that a block was accepted. Keep the two records separate.
3. **Money paths are explicit.** Every payout batch has an operator decision,
   a limit, a dry-run result, and a reconciliation report.
4. **Fail closed.** If template freshness, share validation, or accounting
   state is uncertain, stop accepting work rather than credit unverified
   shares.

## Proposed data flow

```text
miner
  │  subscribe / authorize / submit share
  ▼
stratum endpoint ──► share validator ──► round accounting ──► payout ledger
  ▲                     │                      │
  │  job / difficulty   │  accepted share      │  operator approval
  │                     ▼                      ▼
job manager ◄──── BTCS Core RPC ────► block submission ──► payout batch
```

## Components

### Stratum endpoint

Terminates miner connections, tracks subscriptions and difficulty, and
forwards shares. Protocol parsing must be bounded and rate-limited. Miner
credentials are per-connection secrets and must never be logged in full.

### Job manager

Polls or subscribes to `getblocktemplate`, caches the current template, derives
the share target, and invalidates jobs on a new chain tip. A job identifier
must be unambiguous across restarts.

### Share validator

Checks proof-of-work against the assigned target, rejects duplicates and stale
jobs, and records the result. Target arithmetic needs fixed-width integer
tests, including boundary and overflow cases.

### Round accounting

Maintains per-miner share totals for the current round. The accounting model
(PPLNS, proportional, or fee-based) is an open decision and must be documented
before implementation.

### Payout ledger

Stores obligations separately from transactions. A payout batch is a proposal;
it becomes a transaction only after operator approval and a passing dry run.

### Read-only API

Exposes pool health, round status, and miner-facing statistics. It must not
mutate accounting state.

## Open decisions

- Stratum V1 only, or V1 plus a V2 path?
- PPLNS versus proportional accounting, and the fee policy.
- Whether the pool ever holds keys, or only produces unsigned payout proposals.
- Database choice and restart/reconciliation strategy.
- How to expose hashrate and luck without implying a share is a block.

## Threat model (initial)

| Risk | Impact | Initial control |
| --- | --- | --- |
| Share flooding | Resource exhaustion | Rate limits, connection quotas, bounded queues |
| Duplicate or stale shares | Overpayment | Job expiry and idempotent share records |
| Template race | Invalid block submission | Invalidate jobs on tip change; re-fetch before submit |
| Payout error | Loss of funds | Dry run, limits, second approval, reconciliation |
| Credential leak | Miner account takeover | Hashed credentials, no full-value logging, secret scanning |
| Public exposure of dev node | Unauthorized mining or payout | Loopback-only development defaults |

## Non-goals

The pool does not define L1 consensus, run an exchange, custody user funds, or
provide a wallet. Those boundaries belong to `btcs-core`, `SilvEx-*`,
`SilverPay`, and `SilverForge-Studio` respectively.
