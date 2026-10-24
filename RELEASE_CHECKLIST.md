# Silver Pool v1.0.0 Release Checklist

## Gate 1 — Accounting
- [x] Fee configuration and validation pass (2.00% default, 0-5% range, BTCS_POOL_FEE env var)
- [x] Reward accounting reconciles exactly (gross reward → fee → miner allocations)
- [ ] Miner balances and operator fees remain separate
- [x] Duplicate processing is prevented
- [ ] Restart and reorganization tests pass

## Gate 2 — Mining
- [ ] A real regtest miner connects
- [ ] Valid and invalid shares are correctly classified
- [ ] A candidate block reaches the node
- [ ] The node accepts a block
- [ ] Accounting reflects the correct block state

## Gate 3 — Payouts
- [ ] Immature and orphaned rewards cannot be paid
- [ ] Mature balances can enter the payout queue
- [ ] Signing and submission are tested end to end before automatic payouts can be enabled
- [ ] Duplicate payments are prevented
- [ ] Recovery and reconciliation are demonstrated

## Gate 4 — Security and UI
- [ ] No secret leakage
- [ ] Operator endpoints are protected
- [ ] Dashboard values reflect real backend state
- [ ] User-facing fees, thresholds, and payout rules match configuration

## Gate 5 — Deployment
- [ ] Beta website and compatible services deploy successfully if credentials are available
- [ ] The persistent Stratum service has a reachable, documented endpoint
- [ ] Health checks and rollback instructions work
- [ ] Production remains protected until all production-specific gates pass

## Gate 6 — v1.0.0
- [ ] Release notes, version identifiers, configuration reference, operator guide, miner setup guide, security notes, and known limitations are complete
- [ ] All required automated tests pass
- [ ] Every blocked gate is explicit and justified
- [ ] The production release is not marked complete if a critical gate remains unverified

### Economics
- Default pool fee: 2.00%
- Allowed fee range: 0.00% – 5.00%
- Fee configurable via BTCS_POOL_FEE environment variable
- Fee paid to dedicated BTCS_POOL_FEE_ADDRESS
- Minimum miner payout: 0.01 BTCS
- Payout check interval: 300 seconds (5 min)
- Automatic payouts: disabled until verified

### Key Files Changed
- src/btcs_pool/config.py — pool fee config, validation, payout settings
- src/btcs_pool/accounting.py — complete payout accounting system with SQLite backend
- src/btcs_pool/stratum.py — pool fee calculation on block submission
- RELEASE_CHECKLIST.md — this file

### Remaining Work (highest priority first)
1. Complete payout accounting end-to-end tests (share → work → block → reward → fee → miner credits → payouts)
2. Real miner-to-block end-to-end testing on regtest
3. Payout security: state machine, idempotency, atomic reservations, threshold/dust checks
4. Cloudflare deployment readiness: Stratum service hostname/port configuration
5. API and dashboard: operator endpoints, miner status, dashboard panels
6. Merged mining investigation (VERIFIED/UNVERIFIED/INCOMPATIBLE statuses)
7. Staking status documentation (disabled for v1.0.0)
8. Deployment configuration and environment separation