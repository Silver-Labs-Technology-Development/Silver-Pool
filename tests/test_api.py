import asyncio
import sqlite3
from pool_api_server import _unavailable, _ok, health_check
from pool_api import get_pool_status, get_miner_status, POOL_DB as POOL_DB_API
from btcs_pool.accounting import Accounting, calculate_pplns_reward


class MockRequest:
    def __init__(self):
        self.match_info = {}


def test_unavailable_and_ok_helpers():
    result = _unavailable('test reason')
    assert result['available'] is False
    assert result['reason'] == 'test reason'
    assert 'timestamp' in result

    result = _ok({'key': 'value'})
    assert result['available'] is True
    assert result['key'] == 'value'
    assert 'timestamp' in result


def test_pool_status_without_database(tmp_path):
    import pool_api
    original_db = pool_api.POOL_DB
    pool_api.POOL_DB = tmp_path / 'nonexistent.sqlite3'
    try:
        result = asyncio.run(get_pool_status())
        assert result == {'error': 'Database not found'}
    finally:
        pool_api.POOL_DB = original_db


def test_health_check_without_database(tmp_path):
    import pool_api_server
    import pool_api
    original_db_server = pool_api_server.POOL_DB
    original_db_api = pool_api.POOL_DB
    pool_api_server.POOL_DB = tmp_path / 'nonexistent.sqlite3'
    pool_api.POOL_DB = tmp_path / 'nonexistent.sqlite3'
    try:
        req = MockRequest()
        result = asyncio.run(health_check(req))
        import json
        data = json.loads(result.body)
        assert data['database'] is False
        assert data['status'] == 'degraded'
    finally:
        pool_api_server.POOL_DB = original_db_server
        pool_api.POOL_DB = original_db_api


def test_health_check_with_database(tmp_path):
    import pool_api_server
    import pool_api
    db = tmp_path / 'pool.sqlite3'
    # Use Accounting to create the schema properly
    acc = Accounting(str(db))
    acc.close()
    original_db_server = pool_api_server.POOL_DB
    original_db_api = pool_api.POOL_DB
    pool_api_server.POOL_DB = db
    pool_api.POOL_DB = db
    try:
        req = MockRequest()
        result = asyncio.run(health_check(req))
        import json
        data = json.loads(result.body)
        assert data['database'] is True
        assert data['status'] == 'ok'
    finally:
        pool_api_server.POOL_DB = original_db_server
        pool_api.POOL_DB = original_db_api


def test_get_pool_status_structure(tmp_path):
    import pool_api
    import sqlite3
    db = tmp_path / 'pool.sqlite3'
    # Use Accounting to create the schema properly
    acc = Accounting(str(db))
    acc.close()
    conn = sqlite3.connect(str(db))
    conn.execute('INSERT INTO miners (username, created_at) VALUES (?, ?)', ('testminer', 1000000.0))
    conn.execute('INSERT INTO shares (miner, job_id, nonce, accepted, difficulty, created_at) VALUES (?, ?, ?, ?, ?, ?)', ('testminer', 'job1', 123, 1, 1, 1000000.0))
    conn.execute('INSERT INTO blocks (height, hash, coinbase_value, fee_amount, net_reward, status, miner, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 'abc123', 5000000000, 100000000, 4900000000, 'mature', 'testminer', 1000000.0))
    conn.commit()
    conn.close()
    original_db = pool_api.POOL_DB
    pool_api.POOL_DB = db
    try:
        result = asyncio.run(get_pool_status())
        assert result['database_healthy'] is True
        assert result['total_miners'] == 1
        assert result['total_shares'] == 1
        assert result['accepted_shares'] == 1
        assert result['total_blocks'] == 1
        assert result['mature_blocks'] == 1
        assert len(result['recent_blocks']) == 1
        assert result['recent_blocks'][0]['height'] == 1
        assert result['recent_blocks'][0]['miner'] == 'testminer'
        assert len(result['recent_shares']) == 1
        assert result['recent_shares'][0]['miner'] == 'testminer'
        assert result['recent_shares'][0]['accepted'] == 1
    finally:
        pool_api.POOL_DB = original_db


def test_get_miner_status(tmp_path):
    import pool_api
    db = tmp_path / 'pool.sqlite3'
    # Use Accounting to create the schema properly
    acc = Accounting(str(db))
    acc.close()
    conn = sqlite3.connect(str(db))
    conn.execute('INSERT INTO miners (username, created_at) VALUES (?, ?)', ('testminer', 1000000.0))
    conn.execute('INSERT INTO miner_balances (miner, balance_satoshi, immature_satoshi) VALUES (?, ?, ?)', ('testminer', 50000000, 10000000))
    conn.commit()
    conn.close()
    original_db = pool_api.POOL_DB
    pool_api.POOL_DB = db
    try:
        result = asyncio.run(get_miner_status('testminer'))
        assert result is not None
        assert 'available_satoshi' in result
        assert 'immature_satoshi' in result
        assert 'total_satoshi' in result

        result = asyncio.run(get_miner_status('nonexistent'))
        assert result is None
    finally:
        pool_api.POOL_DB = original_db


def test_calculate_pplns_reward():
    result = calculate_pplns_reward(100, 1000, 5000000000, 2.0)
    assert result['gross_satoshi'] > 0
    assert result['fee_satoshi'] > 0
    assert result['net_satoshi'] == result['gross_satoshi'] - result['fee_satoshi']
    assert result['net_satoshi'] > 0

    result = calculate_pplns_reward(0, 0, 5000000000, 2.0)
    assert result['gross_satoshi'] == 0
    assert result['fee_satoshi'] == 0
    assert result['net_satoshi'] == 0
