from __future__ import annotations

import struct

import pytest

from btcs_pool.block import (
    DIFF1_TARGET,
    MAX_TARGET,
    block_hash,
    build_block,
    build_coinbase_parts,
    build_coinbase_tx,
    difficulty_to_target,
    dsha256,
    encode_height,
    hash_meets_target,
    header_hash,
    merkle_branch,
    merkle_root,
    reverse_bytes,
    reverse_hex,
    target_from_bits,
    template_txids,
    varint,
)


def test_varint_boundaries():
    assert varint(0) == b"\x00"
    assert varint(252) == b"\xfc"
    assert varint(253) == b"\xfd\xfd\x00"
    assert varint(0xFFFF) == b"\xfd\xff\xff"
    assert varint(0x10000) == b"\xfe\x00\x00\x01\x00"
    assert varint(0xFFFFFFFF) == b"\xfe\xff\xff\xff\xff"
    assert varint(0x100000000) == b"\xff\x00\x00\x00\x00\x01\x00\x00\x00"


@pytest.mark.parametrize(
    ("height", "encoded"),
    [
        (0, b"\x00"),
        (1, b"\x51"),
        (11, b"\x5b"),
        (16, b"\x60"),
        (17, b"\x01\x11"),
        (127, b"\x01\x7f"),
        (128, b"\x02\x80\x00"),
        (255, b"\x02\xff\x00"),
        (256, b"\x02\x00\x01"),
        (0x8000, b"\x03\x00\x80\x00"),
    ],
)
def test_encode_height_bip34(height, encoded):
    assert encode_height(height) == encoded


def test_hash_byte_order_helpers():
    assert reverse_hex("00" * 31 + "01") == "01" + "00" * 31
    assert reverse_bytes("0102") == b"\x02\x01"
    assert header_hash(b"abc") == dsha256(b"abc")[::-1].hex()
    assert block_hash(b"abc") == header_hash(b"abc")


def test_regtest_bits_and_targets():
    target = target_from_bits("207fffff")
    assert target == int(
        "7fffff0000000000000000000000000000000000000000000000000000000000", 16
    )
    assert difficulty_to_target(1.0) == DIFF1_TARGET
    assert difficulty_to_target(0.5) > difficulty_to_target(1.0)
    assert difficulty_to_target(2.0) < difficulty_to_target(1.0)
    assert difficulty_to_target(1e30) > 1
    assert difficulty_to_target(1e80) == 1
    assert difficulty_to_target(1e-30) == MAX_TARGET
    with pytest.raises(ValueError):
        difficulty_to_target(0)


def test_hash_meets_target_boundary():
    assert hash_meets_target("00" * 32, 0)
    assert not hash_meets_target("00" * 31 + "01", 0)
    assert hash_meets_target("00" * 31 + "01", 1)


def _leaf(value: int) -> bytes:
    return dsha256(bytes([value]))


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 8])
def test_merkle_branch_reconstructs_root(count):
    leaves = [_leaf(index) for index in range(count)]
    root = merkle_root(leaves)
    for index in range(count):
        branch = merkle_branch(leaves, index)
        value = leaves[index]
        idx = index
        for sibling_hex in branch:
            sibling = bytes.fromhex(sibling_hex)
            if idx % 2 == 0:
                value = dsha256(value + sibling)
            else:
                value = dsha256(sibling + value)
            idx //= 2
        assert value == root


def test_merkle_empty_root():
    assert merkle_root([]) == b"\x00" * 32


def test_template_txids_reverse_internal_order():
    raw = "11" * 32
    template = {"transactions": [{"txid": raw, "data": "00"}]}
    assert template_txids(template) == [bytes.fromhex(raw)[::-1]]


def _template(previous: str = "22" * 32) -> dict:
    return {
        "version": 0x20000000,
        "previousblockhash": previous,
        "transactions": [
            {"txid": "33" * 32, "data": "0100000001" + "00" * 8},
        ],
        "coinbasevalue": 5_000_000_000,
        "default_witness_commitment": "6a24aa21a9ed" + "44" * 32,
        "bits": "207fffff",
        "height": 150,
        "curtime": 1_700_000_000,
    }


def test_coinbase_split_matches_extranonce_substitution():
    template = _template()
    script = "0014" + "ab" * 20
    extranonce1 = b"\x01\x02\x03\x04"
    parts = build_coinbase_parts(template, script, extranonce1, 4)
    rebuilt = bytes.fromhex(parts["coinb1"]) + b"\xaa\xbb\xcc\xdd" + bytes.fromhex(
        parts["coinb2"]
    )
    expected, expected_txid = build_coinbase_tx(
        template, script, extranonce1, b"\xaa\xbb\xcc\xdd"
    )
    assert rebuilt == expected
    assert expected_txid != build_coinbase_tx(
        template, script, extranonce1, b"\xaa\xbb\xcc\xde"
    )[1]
    assert parts["extranonce2_size"] == 4
    assert parts["script_prefix"] == encode_height(150) + extranonce1


def test_build_block_header_and_transactions():
    template = _template()
    script = "0014" + "ab" * 20
    coinbase, txid = build_coinbase_tx(template, script, b"\x01\x02\x03\x04", b"\x00" * 4)
    block, header, digest = build_block(template, txid, coinbase, nonce=7)
    assert len(header) == 80
    assert header[:4] == struct.pack("<I", template["version"])
    assert header[4:36] == reverse_bytes(template["previousblockhash"])
    assert header[36:68] == merkle_root(
        [reverse_bytes(txid)] + template_txids(template)
    )
    assert header[68:72] == struct.pack("<I", template["curtime"])
    assert header[72:76] == struct.pack("<I", int(template["bits"], 16))
    assert header[76:80] == struct.pack("<I", 7)
    assert digest == header_hash(header)
    assert block.startswith(header)
    # Two transactions, and the template transaction data is included verbatim.
    assert block[len(header) : len(header) + 1] == b"\x02"
    assert block.endswith(bytes.fromhex(template["transactions"][0]["data"]))
