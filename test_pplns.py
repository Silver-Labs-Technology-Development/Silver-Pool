#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')
from btcs_pool.accounting import Accounting
import tempfile, os

db = tempfile.mktemp(suffix='.sqlite')
a = Accounting(db)

# Test round tracking
print('Testing round tracking...')
a.start_round('round-1', 100)
r = a.get_round('round-1')
print('Round started:', r)
assert r['round_id'] == 'round-1'
assert r['status'] == 'active'

# Submit some shares
for i in range(5):
    result = a.record_share_round('miner1', 'job1', 100+i, True, round_id='round-1')
    print(f'Share {i}: accepted={result}')

print('Share count for miner1:', a.share_count('miner1'))
r = a.get_round('round-1')
print('Round after shares:', r)
assert r['total_shares'] == 5

# Test duplicate share rejection
dup = a.record_share_round('miner1', 'job1', 100, True, round_id='round-1')
print(f'Duplicate share: {dup}')
assert dup is False

# End the round
a.end_round('round-1', 101, 50000)
r = a.get_round('round-1')
print('Round after end:', r)
assert r['status'] == 'completed'
assert r['height_end'] == 101
assert r['pool_fee_satoshi'] == 50000

# Test PPLNS reward calculation
from btcs_pool.accounting import calculate_pplns_reward
reward = calculate_pplns_reward(miner_shares=5, round_total_shares=5, coinbase_value=5000000000, pool_fee_percent=2.0)
print(f'PPLNS reward: {reward}')
assert reward['net_satoshi'] > 0
assert reward['fee_satoshi'] > 0

# Test miner status (miner1 needs to be registered first for balance)
a.register_miner('miner1')
status = a.get_miner_status('miner1')
print('Miner status:', status)

a.close()
os.remove(db)
print('\nAll PPLNS tests passed!')