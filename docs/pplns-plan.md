# PPLNS accounting: implemented model and remaining work

**Status:** the per-round, difficulty-weighted reward accounting described here
is implemented and tested. Payouts remain disabled.

This document replaces an earlier planning note. It describes what the code
actually does and what is still required before a paying pool could be
considered.

## Implemented model

### Rounds

- A round is created when the block-template height changes.
- Round ID format: `<height>-<8 random hex chars>`.
- Starting a new round marks the previous active round completed.
- Accepted shares are attached to the round of the job they were submitted
  against.
- A round closes when a block from that round is accepted. Its fee total is
  recorded on the round and in the pool fee ledger.

### Share weighting

Only shares with `accepted=1 AND stale=0` count toward a block's allocation.
Each miner's weight is:

```text
weight(miner) = SUM(difficulty) over qualifying shares in the round
```

This is **PPLNS in the sense of pay-per-last-N-shares within a round**, with
difficulty weighting, but the current implementation uses the whole round, not
a rolling N-share window. It should not be described as a sliding-window PPLNS
implementation.

If the round has no qualifying shares, the block finder receives the full
allocation weight (1.0). This covers a direct block submission and keeps the
accounting total correct.

### Reward split

For a node-accepted block:

```text
gross = template.coinbasevalue
fee   = floor(gross * BTCS_POOL_FEE / 100)
net   = gross - fee
```

Each miner receives:

```text
gross_i = floor(gross * weight_i / total_weight)
net_i   = floor(net   * weight_i / total_weight)
fee_i   = gross_i - net_i
```

The last miner in deterministic `miner_id` order receives the remainder of
gross, net and fee. This guarantees:

```text
SUM(gross_i) = gross
SUM(net_i)   = net
SUM(fee_i)   = fee
```

All arithmetic is integer satoshis and runs inside one `BEGIN IMMEDIATE`
transaction with the block, candidate, allocations, balances, fee ledger and
round update. A failure rolls the whole transition back.

### Maturity

- A new block is `immature`.
- Allocations are `pending`.
- Net rewards are added to `miner_balances.immature_satoshi`.
- The maturity loop runs every 120 seconds.
- Maturity rule: `current_height - maturity + 1 >= block.height`, using
  `BTCS_MATURITY_CONFIRMATIONS` (default 200).
- On maturity, allocations become `confirmed`, the block becomes `mature`,
  the fee ledger becomes `allocated`, and net amounts move from immature to
  available.

### Orphans

For each immature block, the reconciler asks the node for the canonical hash at
that height.

- Matching hash: mature.
- Different hash or missing height: mark the block `orphaned`, allocations
  `orphaned`, fee ledger `orphaned`, and subtract pending net amounts from
  immature balances.
- The reconciler does not run while the node is disconnected or in initial
  block download.

### Duplicate and stale handling

- Unique share key:
  `(miner_id, job_id, extranonce2, ntime, nonce)`.
- Rejected and stale shares are retained for audit but do not increase round
  totals or receive allocation weight.
- A duplicate submission returns `duplicate-share` and is not counted twice.
- A job whose previous hash no longer matches the current template returns
  `stale-job` and is recorded with `stale=1`.

### Fee accounting

- Pool fee is bounded to 0–5%; default 2%.
- Fees are recorded per block in `pool_fee_ledger` with the block height, hash,
  satoshi amount and status (`pending`, `allocated`, `orphaned`).
- Fees are not added to miner balances.
- There is no fee payout transaction.

## What is tested

`tests/test_accounting.py` covers:

- exact PPLNS helper arithmetic,
- registration and duplicate share rejection,
- allocation by difficulty weight,
- fee split reconciliation,
- maturity moving immature to available,
- orphan reversal,
- fee ledger statuses,
- hashrate history windows,
- payout boundary transitions,
- finder fallback when a block has no shares.

`tests/test_e2e_regtest.py` additionally submits a real regtest block through
Stratum, confirms the node accepted it, and checks the immature miner balance
equals `coinbasevalue - fee`.

## Payout boundary (not implemented)

The `payouts` table and three accounting methods exist for state-machine tests:

- `request_payout` — validates a positive amount, minimum threshold and
  available balance, then creates a `pending` row.
- `cancel_payout` — pending → cancelled.
- `mark_payout_sent` — pending → sent with a txid.

These are **not** a payout system. There is no API, operator authentication,
signing, transaction construction, broadcast, confirmation tracking, retry
policy, idempotency key across process crashes, or reconciliation report.

Before payouts could be enabled, at minimum:

1. Define custody and key-management boundaries; prefer unsigned proposals or
   an external signer over a hot wallet.
2. Add operator authentication and authorization for every payout action.
3. Implement idempotent payout batches with limits, dry runs and a second
   approval.
4. Build and sign BTCS transactions, broadcast them, and track confirmations.
5. Handle reorgs, stuck transactions, fee bumps, replacement and recovery.
6. Reconcile miner balances, fee balances and on-chain transactions exactly.
7. Add failure-injection, restart and duplicate-payment tests.
8. Complete an independent security review.
9. Keep `BTCS_AUTO_PAYOUTS=false` until all of the above pass.

Until then the API reports `auto_payouts: false` and `payouts_enabled: false`,
and the container entrypoint refuses to start with auto payouts enabled.

## Remaining accounting work

- Optional rolling N-share PPLNS window instead of whole-round weighting.
- Per-worker hashrate history rather than miner-level share history only.
- A database backup/restore procedure and tested restore drill.
- Retention policy for rejected-share and candidate audit rows.
- Multi-process/multi-host design if SQLite becomes a bottleneck.
- Public documentation of any future fee change before it takes effect.

None of these block the current read-only regtest prototype, but they do block
operating a paying public pool.
