# Offline multi-coin staging

Silver Pool currently implements one BTCS SHA256d mining pool. The operator
tool in `scripts/coins.py` prepares reviewable, isolated **regtest** plans for
future integrations. It does not change the backend or website, install
software, download a blockchain, create a wallet, start a process, submit a
block, enable an explorer or send a payout.

The candidate list is a planning example, not a selected download list. The
operator still needs to choose coins and confirm the target drive. No storage
path is inferred from this repository or the machine's home directory.

## Candidate capabilities

| Coin | Work algorithm | Backend adapter | This staging profile |
|---|---|---|---|
| BTCS | SHA256d | Existing single-coin implementation | Disabled; separate test profile |
| BTC | SHA256d | Not integrated/tested here | Disabled candidate |
| BCH | SHA256d | Not integrated/tested here | Disabled candidate |
| LTC | Scrypt | Not implemented | Disabled candidate |
| DOGE | Scrypt with AuxPoW | Not implemented | Disabled candidate |

Running a node provides blockchain access; it does not itself earn mining
rewards. Additional coins require their own consensus/template/share validation
and accounting tests. An SHA256d-only miner cannot mine Scrypt. Dogecoin also
requires the AuxPoW integration used for merged mining. See the official
[Dogecoin mining guide](https://dogecoin.com/dogepedia/how-tos/mining-dogecoin/).

## Validate or produce a plan

Run these from the repository root. Python's standard library is sufficient.

```sh
python3 scripts/coins.py validate

# Print an offline BTC + LTC regtest plan. The storage directory is not created.
# Replace the example path with the operator-confirmed drive location later.
python3 scripts/coins.py plan --coin btc --coin ltc \
  --storage-root /absolute/path/on/selected-drive/silver-pool-tests

# Optionally write plan.json and per-coin .conf review artifacts separately.
python3 scripts/coins.py plan --coin btc --coin ltc \
  --storage-root /absolute/path/on/selected-drive/silver-pool-tests \
  --write-dir /absolute/path/to/review-artifacts
```

Omitting `--coin` includes every candidate in the registry. Select specific
coins when preparing an operator review. `--registry` may point at a copy of
`config/coins.example.json`; all safety flags must remain `false`. The tool
rejects unknown coins/fields, duplicate JSON keys, duplicate coins, colliding
or privileged ports, invalid genesis hashes, unsafe paths, unsupported
algorithms and unavailable adapter declarations. It accepts only `regtest`.
There are only `validate` and `plan` commands; no download, start, mine or payout
command exists.

`validate` reports schema validity, not readiness to run. Every plan reports
`storage_confirmed: false`, `node_runtime_verified: false` and
`pool_integration_verified: false`. Those values cannot be changed with CLI
flags. This tool does not check running services or connect to an RPC server.

With `--write-dir`, review files are created with mode `0600`. Existing files
are not overwritten. Review artifacts must be outside the planned storage
root. The node datadirs and pool databases are never created by the
tool. A plan is rejected if the selected node datadir or pool database already
exists, so it cannot quietly reuse a live or historical chain/wallet/ledger.

## Isolation and conservative test settings

For a storage root chosen by the operator, each coin reserves:

```text
<root>/nodes/<coin>/regtest/           node datadir argument
<root>/nodes/<coin>/regtest/regtest/   daemon-created chain subdirectory
<root>/pools/<coin>/regtest/pool.sqlite3
```

The extra `regtest` directory reflects how Bitcoin-family daemons append their
network directory to an explicit datadir. It is intentional. See
[Bitcoin Core's filesystem documentation](https://github.com/bitcoin/bitcoin/blob/master/doc/files.md).
Never point a second daemon at an existing node's data directory or combine
coins in the current SQLite schema, which has no asset identifier.

RPC, API and Stratum addresses in the plan are loopback-only. P2P listening,
discovery, DNS seeds and automatic peer connections are disabled in the
generated node config. RPC uses the daemon's local cookie authentication; no
username, password, wallet or key is generated. API and Stratum ports are
reservations for future tests, not running listeners. Configs reserve four
distinct ports per coin and use 64 MiB database cache, 32 MB mempool and four
maximum peer connections as conservative test settings. These are daemon
settings, not operating-system memory/CPU limits, and must be checked against
the selected daemon version before use. [Core memory settings](https://github.com/bitcoin/bitcoin/blob/master/doc/reduce-memory.md).

No generated file is a ready-to-run service definition. The pool metadata
keeps `enabled`, `auto_payouts` and `payouts_enabled` false and is **not read by
the existing backend**. The tool cannot upgrade a candidate into an integrated
pool by editing a JSON flag. It does not replace the existing BTCS deployment.

## Chain identity is a separate gate

Each candidate includes an expected `getblockhash(0)` value and an official
source reference. Before any future service is enabled, verify:

1. The selected official binary's release, signature/checksum and implementation.
2. `getblockchaininfo.chain` is the intended network.
3. `getblockhash(0)` matches the expected genesis hash.
4. RPC/template/consensus behavior matches the intended coin and adapter.

Genesis hashes are **not unique across all forks**: the BTC, BCH and BTCS
regtest examples share a genesis hash. A match cannot establish the coin's
identity alone. The source refs below document hash expectations; their version
tags are source references, not recommendations to install those versions.
BTCS's reference is a moving branch and must be checked again against a pinned
release before use. No binary version or release download has been selected.

- [BTCS chain parameters](https://github.com/bitcoin-silver/core/blob/master/src/kernel/chainparams.cpp)
- [BTC chain parameters](https://github.com/bitcoin/bitcoin/blob/v30.0/src/kernel/chainparams.cpp)
- [BCH chain parameters](https://github.com/bitcoin-cash-node/bitcoin-cash-node/blob/v28.0.1/src/chainparams.cpp)
- [LTC chain parameters](https://github.com/litecoin-project/litecoin/blob/v0.21.4/src/chainparams.cpp)
- [DOGE chain parameters](https://github.com/dogecoin/dogecoin/blob/v1.14.9/src/chainparams.cpp)

## Future explorer/exchange storage

Choose the archive/indexing requirements before downloading a production
chain. Test profiles use `prune=0` and `txindex=0`; this is not an archive-node
configuration or an explorer implementation. Historical explorers may need
retained blocks plus a transaction/indexer database. Bitcoin Core's `txindex`
does not permit pruning. [Core transaction index](https://github.com/bitcoin/bitcoin/blob/master/src/index/txindex.h).

Initial sync and indexes can consume significant disk, RAM, CPU and bandwidth.
Confirm free space and reserve room for growth, the pool ledger and backups;
schedule one initial sync at a time. Future exchange wallets need separate
key-management and recovery design. Do not reuse a mining pool hot wallet as
an exchange custody system. The current payout implementation remains
disabled and does not sign or broadcast payments.

## Offline checks

```sh
python3 -m pytest -q tests/test_coin_profiles.py
```

These checks exercise rejection of unsafe registry changes, isolated paths
and port reservations, absence of data-directory creation, refusal to overwrite
state, artifact permissions and CLI rejection of execution/mainnet commands.
No real node or network is required.
