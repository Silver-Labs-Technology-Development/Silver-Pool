# PPLNS Implementation Plan for Silver Pool

## Current State
- Accounting module has basic share tracking with duplicate detection
- Tables: miners, shares, blocks, pool_fee_ledger, miner_balances, payouts, rounds
- `rounds` table exists but lacks PPLNS functionality
- No PPLNS reward calculation or round-based eligibility

## Required Additions

### 1. Round Tracking
- `start_round(round_id, height_start)` - Begin a new PPLNS round
- `end_round(round_id, height_end, total_shares, total_difficulty)` - Close round and calculate fees
- `get_round(round_id)` - Get round details

### 2. PPLNS Share Eligibility
- PPLNS window: typically last N shares or last M blocks
- Track shares per round with difficulty
- Calculate eligibility based on round participation

### 3. Reward Calculation
- PPLNS reward = (round_total_reward * miner_shares / round_total_shares) * (1 - fee%)
- Fee applied once to distributable rewards
- Handle immature blocks, maturity, and confirmed payouts

### 4. Database Changes
- Update `rounds` table to track PPLNS data
- Add share counting per round
- Track fee allocation per round

## Implementation Priority

### Phase 1: Round Management (HIGH)
- Add `start_round()`, `end_round()`, `get_round()` to Accounting
- Update rounds table schema if needed
- Test round start/end cycle

### Phase 2: PPLNS Reward Calculation (HIGH)
- Implement `calculate_pplns_reward(miner, round_id)`
- Apply 2% fee to distributable rewards
- Test fee boundaries and rounding

### Phase 3: Share Eligibility Window (MEDIUM)
- Track shares within PPLNS window
- Handle worker disconnections/restarts
- Test edge cases

### Phase 4: Integration with Stratum (MEDIUM)
- Connect round tracking to stratum validate_submit
- Ensure shares are assigned to correct rounds
- Test full miner lifecycle

### Phase 5: End-to-End Testing (MEDIUM)
- Full regtest mining scenario
- Verify PPLNS calculations against expected results
- Test reorganizations and immature reward handling