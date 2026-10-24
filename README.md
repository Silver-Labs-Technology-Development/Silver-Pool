# BTCS Mining Pool

> **Status: Planned — repository and scope only.**
> No pool server, Stratum listener, share validator, payout ledger, or
> operational service exists here.

## Purpose

BTCS Mining Pool is the mining-pool product boundary for Silver Labs. It is
intended to cover pool-facing Stratum services, share validation, block-template
handling, and miner payout accounting for Bitcoin Silver.

Pool mining is distinct from BTCS L2 sequencing. L2 block production is not
proof-of-work mining and must not be described as such.

## Proposed scope

- Stratum connection handling and miner authorization.
- Job/template distribution and stale-share handling.
- Share validation against the configured BTCS network target.
- Block submission and confirmation tracking.
- Payout accounting with an explicit scheme and audit trail.
- Pool operations: health, logging, restart, and reconciliation.

## Explicitly out of scope until reviewed and approved

- Real-fund payouts or custody of miner balances.
- Mainnet pool operations.
- Claims of uptime, hashrate, or profitability.
- Copying GPL or other upstream code without preserving notices and meeting
  license obligations.

## Integration points

- **BTCS Core** — `getblocktemplate`, `submitblock`, chain state, and mining RPC.
- **Silver Scan** — block and payout visibility.
- **SilverPay** — future payout-account boundary, if justified.
- **silver-labs-platform** — shared schemas where applicable.

## Decisions required before implementation

1. Build or adapt an upstream pool, with a license and security review.
2. Payout scheme, minimums, fees, and accounting invariants.
3. Stratum protocol version and miner compatibility targets.
4. Share-validation and difficulty-adjustment behavior.
5. Operating model, jurisdiction, and real-fund controls.

CKPool has been identified only as a source-level candidate. It is GPL-3.0 and
has **not** been runtime-tested against BTCS or copied into this repository.

## First milestone

A local regtest pool that accepts a test miner, validates shares, submits a
block through BTCS Core, and produces a reconciled test payout ledger. No real
funds.

## Repository facts

- Local workspace path: `~/Silver-Labs/BTCS-Mining-Pool`
- Default branch: `main`
- Implementation: none
- Tests run: none (no code)
- License: no license selected; no reuse rights are granted
- Visibility: public planning repository

This repository is labeled planned so that its existence is not mistaken for an
operating pool.
