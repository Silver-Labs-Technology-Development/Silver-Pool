# Security policy

## Scope

This repository is a **planned development scaffold** for a BTCS L1 mining
pool. There is no runnable service yet, no production deployment, and no
authorization for real-value mining or payouts.

## Reporting

Do not open a public issue containing exploit details, credentials, wallet
data, or a working payout bypass. Report privately to the Silver Labs
maintainers through the organization account
<https://github.com/Silver-Labs-Technology-Development> and allow time for a
fix before disclosure.

## Security boundaries for future work

- The pool must never custody miner funds without an explicit, reviewed design.
- Miner credentials and payout destinations are secrets; never commit or log
  them in full.
- Every payout path requires an operator approval, a limit, and a dry run.
- Development nodes, pools, and dashboards bind to loopback by default.
- Share validation and accounting must fail closed.

## Known limitations

- No implementation, test suite, or audit exists.
- No threat model has been validated against a running system.
