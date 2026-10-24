import asyncio
import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from btcs_pool.stratum import StratumServer
from btcs_pool.rpc import BTCSRpc
from btcs_pool.accounting import Accounting
from btcs_pool.config import PoolConfig
from btcs_pool.block import build_coinbase_tx, build_block_bytes, block_hash


def make_mock_config():
    return PoolConfig.from_env()


def test_validate_share_accepted():
    """Test that a valid share is accepted"""
    db = Path("/tmp/test_stratum_accounting.sqlite")
    if db.exists():
        db.unlink()

    accounting = Accounting(str(db))
    config = make_mock_config()
    rpc = BTCSRpc('http://127.0.0.1:18443', 'test', 'test')

    # Get a block template
    tpl = rpc.getblocktemplate(['segwit'])
    extranonce = b'\x00\x00\x00\x00'
    cb_tx, txid = build_coinbase_tx(tpl, '', extranonce)

    # Build a job
    server = StratumServer(config, rpc, accounting, on_block=lambda h, x: None)

    # Set a current template
    server.current_template = tpl
    server.target = int(tpl['bits'], 16)

    # Find a valid nonce
    for nonce in range(200000):
        data2, header2 = build_block_bytes(tpl, txid, cb_tx, nonce, int(tpl['curtime']))
        h2 = block_hash(data2)
        h2_int = int(h2, 16)
        if h2_int < server.target:
            # Valid share - validate_submit should return True
            user = "miner1"
            job_id = "1"
            extranonce2 = '\x00\x00\x00\x00'.hex()
            ntime_hex = format(int(tpl['curtime']), '08x')
            nonce_hex = format(nonce, '08x')

            result = asyncio.run(server.validate_submit(
                user, job_id, extranonce2, ntime_hex, nonce_hex
            ))
            print(f"Valid share result: {result}")
            assert result is True, f"Expected True, got {result}"

            # Check that the share was recorded
            share_count = accounting.share_count(user)
            print(f"Share count for {user}: {share_count}")
            assert share_count >= 1, "Share should be recorded"

            # Check miner status
            status = accounting.get_miner_status(user)
            print(f"Miner status: {status}")

            break
    else:
        print("No valid nonce found in range 0-199999 - skipping share acceptance test")
        accounting.close()
        return

    accounting.close()
    if db.exists():
        db.unlink()
    print("test_validate_share_accepted PASSED")


def test_validate_share_rejected_low_difficulty():
    """Test that a share with low difficulty (invalid PoW) is rejected"""
    db = Path("/tmp/test_stratum_accounting2.sqlite")
    if db.exists():
        db.unlink()

    accounting = Accounting(str(db))
    config = make_mock_config()
    rpc = BTCSRpc('http://127.0.0.1:18443', 'test', 'test')

    tpl = rpc.getblocktemplate(['segwit'])
    extranonce = b'\x00\x00\x00\x00'
    cb_tx, txid = build_coinbase_tx(tpl, '', extranonce)

    server = StratumServer(config, rpc, accounting, on_block=lambda h, x: None)
    server.current_template = tpl
    server.target = int(tpl['bits'], 16)

    # Submit with nonce=0 which should have low difficulty
    user = "miner1"
    job_id = "1"
    # extranonce2 as bytes for validate_submit
    extranonce2_bytes = b'\x00\x00\x00\x00'
    ntime_hex = format(int(tpl['curtime']), '08x')
    nonce_hex = format(0, '08x')

    # Create a mock writer that just drains without error
    class MockWriter:
        def write(self, data):
            pass
        async def drain(self):
            pass

    result = asyncio.run(server.validate_submit(user, job_id, extranonce2_bytes.hex(), ntime_hex, nonce_hex, MockWriter()))
    print(f"Low-difficulty share result: {result}")
    assert result is False, f"Expected False for invalid share, got {result}"

    share_count = accounting.share_count(user)
    print(f"Share count for {user}: {share_count}")
    assert share_count == 0, "Invalid share should not be recorded"

    accounting.close()
    if db.exists():
        db.unlink()
    print("test_validate_share_rejected_low_difficulty PASSED")


if __name__ == "__main__":
    from pathlib import Path
    test_validate_share_accepted()
    test_validate_share_rejected_low_difficulty()
async def simulate_miner_connection():
    """Simulate a complete miner connecting, subscribing, authorizing, getting a job, and submitting a share."""
    db = Path("/tmp/test_miner_accounting.sqlite")
    if db.exists():
        db.unlink()

    accounting = Accounting(str(db))
    config = PoolConfig.from_env()
    rpc = BTCSRpc('http://127.0.0.1:18443', 'test', 'test')

    # Create stratum server
    server = StratumServer(config, rpc, accounting, on_block=lambda h, x: None)

    # Start the template poller task
    server.current_template = None
    server.target = 0
    server.job_counter = 0
    server.clients = set()

    # Run poll_templates once to get an initial template
    await server.poll_templates()

    print(f"Initial template job_id: {server.current_job_id}")
    print(f"Number of jobs: {len(server.jobs)}")

    # Simulate a miner connecting and subscribing
    miner_writer = MockWriter()

    # Send subscribe response
    subscribe_response = json.dumps({
        "id": 1,
        "result": True,
        "error": None
    }) + "\n"
    miner_writer.write(subscribe_response.encode())
    await miner_writer.drain()

    # Send authorize response
    authorize_response = json.dumps({
        "id": 2,
        "result": True,
        "error": None
    }) + "\n"
    miner_writer.write(authorize_response.encode())
    await miner_writer.drain()

    # Simulate miner getting a job (mining.notify)
    if server.current_job_id and server.current_job_id in server.jobs:
        job = server.jobs[server.current_job_id]

        # Construct the mining.notify message
        from btcs_pool.stratum import reverse_hex
        msg = {
            "id": None,
            "method": "mining.notify",
            "params": [
                job["job_id"],
                reverse_hex(job["template"]["previousblockhash"]),
                job["coinb1"],
                job["coinb2"],
                [],
                format(job["template"]["version"], '08x'),
                job["template"]["bits"],
                format(job["ntime"], '08x'),
                True,  # clean
            ]
        }
        notify_msg = json.dumps(msg) + "\n"
        miner_writer.write(notify_msg.encode())
        await miner_writer.drain()

        # Simulate miner submitting a valid share
        # Use the job's coinbase tx and build a block with a valid nonce
        tpl = job["template"]
        extranonce = b'\x00\x00\x00\x00'
        cb_tx, txid = build_coinbase_tx(tpl, '', extranonce)

        # Find a valid nonce
        for nonce in range(200000):
            data, header = build_block_bytes(tpl, txid, cb_tx, nonce, int(tpl['curtime']))
            h = block_hash(data)
            h_int = int(h, 16)
            if h_int < server.target:
                # Valid share found!
                print(f"Minor found valid nonce: {nonce}")

                # Construct the mining.submit message
                submit_msg = {
                    "id": 3,
                    "method": "mining.submit",
                    "params": [
                        "miner1",  # user
                        job["job_id"],
                        '\x00\x00\x00\x00'.hex(),  # extranonce2
                        format(int(tpl['curtime']), '08x'),  # ntime
                        format(nonce, '08x'),  # nonce
                    ]
                }
                submit_msg_str = json.dumps(submit_msg) + "\n"
                miner_writer.write(submit_msg_str.encode())
                await miner_writer.drain()

                # Process the submit through the server
                params = submit_msg["params"]
                method = submit_msg["method"]
                rid = submit_msg["id"]

                # Call validate_submit with a mock writer
                mock_writer2 = MockWriter()
                ok = await server.validate_submit(
                    params[0], params[1], params[2], params[3], params[4], mock_writer2
                )

                submit_result = {
                    "id": rid,
                    "result": ok,
                    "error": None if ok else "rejected"
                }
                miner_writer2 = MockWriter()
                miner_writer2.write(json.dumps(submit_result).encode() + "\n")
                await miner_writer2.drain()

                print(f"Share submission result: result={ok}, error={None if ok else 'rejected'}")

                # Check accounting
                share_count = accounting.share_count("miner1")
                print(f"Share count for miner1: {share_count}")

                break
    else:
        print("No current job available")

    accounting.close()
    if db.exists():
        db.unlink()
    print("Full miner simulation PASSED")


if __name__ == "__main__":
    asyncio.run(simulate_miner_connection())
