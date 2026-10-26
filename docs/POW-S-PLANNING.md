# PoW-S Technical Planning

**Status:** Draft planning document for future Silver Labs Proof-of-Work staking (PoW-S) design. Separate from the current pool fee path. No code changes are implemented until the specification is approved.

## Requirements and Threat Model

- **Stake representation**: Eligible stake is tracked per-miner, snapshot at round boundaries. Total eligible stake is the sum of all miners' eligible stake for the current period.
- **Eligibility rules**: Define which miners/stakers qualify for PoW-staking rewards. Default: any registered miner with `auto_payouts=false` and sufficient stake minimum.
- **Reward periods**: Fixed-duration periods (e.g., per-round or per-day) during which the 1.5% allocation is accumulated and then distributed.
- **Threat model**: Prevent double-counting between pool fee and SilvEx fee sources. Prevent stake manipulation (e.g., inflating eligible stake right before snapshot). Ensure no negative balances or underflow.

## Stake and Eligibility Representation

- **Eligible stake per miner**: `Decimal` integer number of "stake units" (e.g., satoshis allocated to the pool by the miner, or a separate stake address balance).
- **Total eligible stake**: Sum of all eligible miners' stake for the current period.
- **Stake snapshot**: Taken at the start of each reward period; shares recorded after the snapshot are not counted for that period.
- **Minimum stake**: Configurable threshold (e.g., 0.01 BTCS) below which a miner's stake is not counted.

## Reward Snapshots and Periods

1. At the start of each round (or configurable period), take a stake snapshot.
2. Accumulate the 1.5% fee portion during the period.
3. At period end, distribute the accumulated fee proportionally among eligible stakers.
4. Reset stakes for the next period.

### Proportional distribution formula

```
period_total_fee_satoshi = accumulated_1.5%_fee_satoshi
eligible_stake_total = sum(miner.eligible_stake_satoshi for miner in eligible_miners)

staker_i_share = period_total_fee_satoshi * miner_i.eligible_stake_satoshi / eligible_stake_total
```

- Round each staker's share down to the nearest satoshi.
- Any remainder (from rounding down) carried forward to the next period or allocated to development.

## Fee-Source Ledger and Reconciliation

- **Development allocation (0.5%)**: Tracked in `reward_allocations` with `allocation_type = "development"`. Distributed to the designated development address.
- **Staking allocation (1.5%)**: Tracked in `reward_allocations` with `allocation_type = "staking"`. Distributed proportionally to eligible stakers.
- **Fee collection**: Per-round, the pool fee (2.0% total) is collected from block rewards and split:
  - 0.5% → development allocation accumulator
  - 1.5% → staking allocation accumulator
- **Reconciliation**: At period end, distribute accumulated staking fees to eligible stakers. Move development allocation to the development address ledger.

## Reward Claims and Payout Authorization

- **Claim**: A miner/staker submits a claim for their proportional share of the accumulated staking allocation for a completed period.
- **Authorization**: Claim must be signed or authorized via the pool's operator key (to prevent unauthorized claims).
- **Payout**: After claim approval, the specified amount is moved from the allocation ledger to the miner's available balance.
- **Recovery**: Unclaimed allocations after N periods are rolled back or reclaimed by the development allocation.

## Withdrawal and Recovery Handling

- **Withdrawal**: Miners can request to withdraw their available balance (future feature, not yet implemented).
- **Recovery**: If a period ends and some allocations remain unclaimed, the remainder is either:
  - Carried forward to the next period.
  - Rolled into the development allocation.
  - Burned (configured via `BTCS_POOL_FEE_REMAINDER_STRATEGY`).

## Confirmed Decisions (from current code)

- `BTCS_POOL_FEE` defaults to `2.0` percent, validated between 0 and 5.
- Fee arithmetic uses `Decimal` with `ROUND_DOWN` rounding.
- `BTCS_AUTO_PAYOUTS` must stay `false` until reward signing, confirmations, recovery and payment tests are complete.
- Payouts are intentionally disabled per config.

## Open Design Questions

- What defines "eligible stake" — miner's total balance, a separate stake address, or something else?
- What is the reward period duration (round, day, week)?
- What is the minimum stake threshold?
- Which SilvEx trading fees qualify, and how are they converted to BTCS?
- What is the remainder-handling strategy (carry forward, roll to development, burn)?
- What authorization mechanism is used for claims (operator key, signed message, etc.)?

## API and UI Requirements (planning)

### API (planning)

- `GET /api/pool/fee-split` returns:
  ```json
  {
    "total_fee_percent": 2.0,
    "development_allocation_percent": 0.5,
    "staking_allocation_percent": 1.5,
    "development_allocated_satoshi": "0",
    "staking_allocated_satoshi": "0",
    "development_available_satoshi": "0",
    "staking_available_satoshi": "0"
  }
```
- Staking endpoints are **not** deployed until the PoW-S specification is approved.

### UI wording (planning)

- "Pool fee: 2.0% (0.5% development + 1.5% planned staking)"
- "Staking: Not yet active — allocation documented for future PoW-S design"
- Development allocation is always shown; staking is marked "planned/not yet active"