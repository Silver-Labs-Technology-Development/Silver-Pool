from __future__ import annotations

from decimal import Decimal

import pytest

from btcs_pool.accounting import (
    Accounting,
    calculate_pplns_reward,
    parse_identity,
    sum_allocations,
)


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("alice", ("alice", "default")),
        ("alice.rig1", ("alice", "rig1")),
        ("wallet.worker.2", ("wallet.worker", "2")),
        ("a:b+c@d-e_f", ("a:b+c@d-e_f", "default")),
    ],
)
def test_parse_identity(username, expected):
    assert parse_identity(username) == expected


@pytest.mark.parametrize(
    "username",
    ["", "   ", "a b", "alice.", ".rig", "x" * 161, "alice\nrig"],
)
def test_parse_identity_rejects_invalid(username):
    with pytest.raises(ValueError):
        parse_identity(username)


def test_calculate_pplns_reward_is_exact():
    result = calculate_pplns_reward(1, 4, 5_000_000_000, 2.0)
    assert result["gross_satoshi"] == Decimal("1250000000")
    assert result["fee_satoshi"] == Decimal("25000000")
    assert result["net_satoshi"] == Decimal("1225000000")
    zero = calculate_pplns_reward(0, 0, 5_000_000_000, 2.0)
    assert zero == {
        "gross_satoshi": Decimal("0"),
        "fee_satoshi": Decimal("0"),
        "net_satoshi": Decimal("0"),
    }


def test_registration_workers_and_duplicate_shares(accounting: Accounting):
    identity = accounting.register_miner("alice.rig1")
    assert identity["miner"] == "alice"
    assert identity["worker"] == "rig1"
    accounting.register_miner("alice.rig2")
    assert accounting.get_miner("alice")["workers"] == 2
    assert accounting.start_round("round-1", 100) is True
    assert accounting.start_round("round-1", 100) is False

    recorded, duplicate, share_id = accounting.record_share(
        "alice.rig1", "job-1", "aabbccdd", "01020304", "00000001", 1.0, True,
        round_id="round-1",
    )
    assert recorded is True
    assert duplicate is False
    assert share_id is not None
    recorded, duplicate, share_id = accounting.record_share(
        "alice.rig1", "job-1", "aabbccdd", "01020304", "00000001", 1.0, True,
        round_id="round-1",
    )
    assert recorded is False
    assert duplicate is True
    assert share_id is None
    round_row = accounting.current_round()
    assert round_row["total_shares"] == 1
    assert round_row["total_difficulty"] == 1.0

    # Rejected shares are retained for audit but do not increase round work.
    accounting.record_share(
        "alice.rig2", "job-1", "aabbccdd", "01020304", "00000002", 1.0, False,
        round_id="round-1", reject_reason="low-difficulty",
    )
    round_row = accounting.current_round()
    assert round_row["total_shares"] == 1
    assert accounting.share_count("alice") == 1
    assert accounting.share_count("alice", accepted=False) == 1


def test_pplns_allocation_maturity_and_orphan(accounting: Accounting):
    accounting.register_miner("alice.rig1")
    accounting.register_miner("bob.rig1")
    accounting.start_round("round-1", 100)
    accounting.record_share(
        "alice.rig1", "job-1", "00000000", "01020304", "00000001", 1.0, True,
        round_id="round-1",
    )
    accounting.record_share(
        "bob.rig1", "job-1", "00000000", "01020304", "00000002", 3.0, True,
        round_id="round-1",
    )
    block_id = accounting.record_block(
        height=100,
        block_hash="aa" * 32,
        coinbase_value_satoshi=5_000_000_000,
        fee_satoshi=100_000_000,
        net_reward_satoshi=4_900_000_000,
        miner_username="alice.rig1",
        round_id="round-1",
        header_hex="00",
        block_hex="00",
        job_id="job-1",
        node_result=None,
    )
    assert block_id

    alice = accounting.get_miner("alice")
    bob = accounting.get_miner("bob")
    assert alice["accepted_shares"] == 1
    assert alice["immature_satoshi"] == 1_225_000_000
    assert bob["immature_satoshi"] == 3_675_000_000
    assert alice["available_satoshi"] == 0
    assert alice["recent_blocks"][0]["height"] == 100

    stats = accounting.pool_stats()
    assert stats["total_blocks"] == 1
    assert stats["immature_blocks"] == 1
    assert stats["mature_blocks"] == 0
    assert stats["accepted_shares"] == 2
    assert stats["estimated_hashrate_24h"] == pytest.approx(
        4 * 2**32 / 86400
    )

    allocations = accounting.db.fetchall(
        "SELECT * FROM reward_allocations ORDER BY miner_id"
    )
    assert len(allocations) == 2
    assert sum_allocations([dict(row) for row in allocations]) == 4_900_000_000
    assert sum(row["fee_satoshi"] for row in allocations) == 100_000_000
    assert all(row["status"] == "pending" for row in allocations)

    # A block matures when it has `maturity` confirmations. Height 100 at chain
    # height 299 has 200 confirmations.
    canonical = lambda height: "aa" * 32 if height == 100 else "00" * 32
    assert accounting.reconcile_blocks(298, 200, canonical)["matured"] == 0
    assert accounting.get_miner("alice")["available_satoshi"] == 0
    result = accounting.reconcile_blocks(299, 200, canonical)
    assert result == {"matured": 1, "orphaned": 0, "checked": 1}
    alice = accounting.get_miner("alice")
    assert alice["available_satoshi"] == 1_225_000_000
    assert alice["immature_satoshi"] == 0
    assert accounting.recent_blocks(1)[0]["status"] == "mature"
    assert accounting.recent_blocks(1)[0]["confirmations"] == 200
    fee = accounting.fee_ledger(1)[0]
    assert fee["status"] == "allocated"

    # Confirmation counters keep advancing.
    accounting.reconcile_blocks(349, 200, canonical)
    assert accounting.recent_blocks(1)[0]["confirmations"] == 250

    # A block that is not canonical becomes orphaned and its immature credit is
    # reversed. Orphaned blocks cannot be paid.
    accounting.start_round("round-2", 200)
    accounting.record_share(
        "alice.rig1", "job-2", "00000000", "01020304", "00000003", 1.0, True,
        round_id="round-2",
    )
    accounting.record_block(
        height=200,
        block_hash="bb" * 32,
        coinbase_value_satoshi=5_000_000_000,
        fee_satoshi=100_000_000,
        net_reward_satoshi=4_900_000_000,
        miner_username="alice.rig1",
        round_id="round-2",
        header_hex="00",
        block_hex="00",
        job_id="job-2",
        node_result=None,
    )
    assert accounting.get_miner("alice")["immature_satoshi"] == 4_900_000_000
    orphan = accounting.reconcile_blocks(
        399, 200, lambda height: "aa" * 32 if height == 100 else "cc" * 32
    )
    assert orphan == {"matured": 0, "orphaned": 1, "checked": 1}
    alice = accounting.get_miner("alice")
    assert alice["immature_satoshi"] == 0
    assert alice["available_satoshi"] == 1_225_000_000
    assert accounting.recent_blocks(1)[0]["status"] == "orphaned"
    assert accounting.fee_ledger(1)[0]["status"] == "orphaned"


def test_hashrate_history_and_validation(accounting: Accounting):
    accounting.register_miner("alice")
    accounting.start_round("round-1", 100)
    accounting.record_share(
        "alice", "job-1", "00000000", "01020304", "00000001", 2.0, True,
        round_id="round-1",
    )
    history = accounting.hashrate_history("1h")
    assert history["range"] == "1h"
    assert history["bucket_seconds"] == 60
    assert len(history["history"]) >= 60
    assert history["history"][-1]["shares"] == 1
    assert history["history"][-1]["difficulty"] == 2.0
    assert history["history"][-1]["hashrate"] == pytest.approx(2 * 2**32 / 60)
    with pytest.raises(ValueError):
        accounting.hashrate_history("2h")


def test_payout_boundary_and_reversal(accounting: Accounting):
    accounting.register_miner("alice.rig1")
    accounting.start_round("round-1", 100)
    accounting.record_share(
        "alice.rig1", "job-1", "00000000", "01020304", "00000001", 1.0, True,
        round_id="round-1",
    )
    accounting.record_block(
        height=100,
        block_hash="aa" * 32,
        coinbase_value_satoshi=5_000_000_000,
        fee_satoshi=100_000_000,
        net_reward_satoshi=4_900_000_000,
        miner_username="alice.rig1",
        round_id="round-1",
        header_hex="00",
        block_hex="00",
        job_id="job-1",
    )
    accounting.reconcile_blocks(299, 200, lambda height: "aa" * 32)
    balance = accounting.get_miner("alice")["available_satoshi"]
    assert balance == 4_900_000_000

    assert accounting.request_payout("alice.rig1", balance + 1, "bcrt1qtest") is None
    assert accounting.request_payout("alice.rig1", 100_000_000, "") is None
    payout_id = accounting.request_payout("alice.rig1", 100_000_000, "bcrt1qtest")
    assert payout_id
    assert accounting.get_miner("alice")["available_satoshi"] == balance - 100_000_000
    assert accounting.cancel_payout(payout_id) is True
    assert accounting.get_miner("alice")["available_satoshi"] == balance
    assert accounting.cancel_payout(payout_id) is False

    payout_id = accounting.request_payout("alice.rig1", 100_000_000, "bcrt1qtest")
    assert accounting.mark_payout_sent(payout_id, "txid-1") is True
    assert accounting.mark_payout_sent(payout_id, "txid-1") is False
    payout = accounting.db.fetchone("SELECT * FROM payouts WHERE id=?", (payout_id,))
    assert payout["status"] == "sent"
    assert payout["txid"] == "txid-1"


def test_direct_block_without_shares_allocates_to_finder(accounting: Accounting):
    accounting.register_miner("solo.rig")
    accounting.start_round("round-1", 500)
    accounting.record_block(
        height=500,
        block_hash="dd" * 32,
        coinbase_value_satoshi=5_000_000_000,
        fee_satoshi=100_000_000,
        net_reward_satoshi=4_900_000_000,
        miner_username="solo.rig",
        round_id="round-1",
        header_hex="00",
        block_hex="00",
        job_id="job-1",
    )
    allocations = accounting.db.fetchall("SELECT * FROM reward_allocations")
    assert len(allocations) == 1
    assert allocations[0]["net_satoshi"] == 4_900_000_000
    assert accounting.get_miner("solo")["immature_satoshi"] == 4_900_000_000
