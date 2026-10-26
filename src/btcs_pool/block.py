"""BTCS block construction primitives.

The functions here deliberately mirror Bitcoin/BTCS serialization rules:
internal byte order for hashes, little-endian header fields, SegWit coinbase
with a witness commitment, and a merkle root built from the coinbase plus every
template transaction.
"""
from __future__ import annotations

import hashlib
import struct
from decimal import Decimal, ROUND_DOWN, localcontext

DIFF1_TARGET = int(
    "00000000ffff0000000000000000000000000000000000000000000000000000", 16
)
MAX_TARGET = (1 << 256) - 1
WITNESS_RESERVED_VALUE = b"\x00" * 32


def dsha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def reverse_bytes(h: str) -> bytes:
    return bytes.fromhex(h)[::-1]


def reverse_hex(h: str) -> str:
    return bytes.fromhex(h)[::-1].hex()


def encode_height(n: int) -> bytes:
    """Encode a BIP34 coinbase height exactly as Bitcoin Core's
    ``CScript() << height`` does.

    Core pushes OP_0 for zero and the small-integer opcodes OP_1..OP_16 for
    heights 1..16. Larger heights use a length-prefixed little-endian
    CScriptNum. Using length-prefixed values for heights 1..16 produces
    ``bad-cb-height`` rejections from the node.
    """
    value = int(n)
    if value < 0:
        raise ValueError("height cannot be negative")
    if value == 0:
        return b"\x00"
    if value <= 16:
        return bytes([0x50 + value])
    encoded = bytearray()
    while value > 0:
        encoded.append(value & 0xFF)
        value >>= 8
    if encoded[-1] & 0x80:
        encoded.append(0)
    return bytes([len(encoded)]) + bytes(encoded)


def varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def target_from_bits(bits_hex: str) -> int:
    bits = int(bits_hex, 16)
    exponent = bits >> 24
    mantissa = bits & 0x00FFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa * (1 << (8 * (exponent - 3)))


def difficulty_to_target(difficulty: float) -> int:
    if difficulty <= 0:
        raise ValueError("difficulty must be positive")
    # A 256-bit target has up to 78 decimal digits. The default Decimal
    # context (28 digits) would silently truncate low-order bytes, so use an
    # explicit precision high enough for the full target range.
    with localcontext() as ctx:
        ctx.prec = 100
        target = int(
            (Decimal(DIFF1_TARGET) / Decimal(str(difficulty))).to_integral_value(
                rounding=ROUND_DOWN
            )
        )
    if target < 1:
        return 1
    if target > MAX_TARGET:
        return MAX_TARGET
    return target


def header_hash(header: bytes) -> str:
    return dsha256(header)[::-1].hex()


def hash_meets_target(block_hash: str, target: int) -> bool:
    return int(block_hash, 16) <= target


def _coinbase_outputs(template: dict, pool_script_pubkey_hex: str) -> tuple[bytes, int]:
    coinbase_value = int(template["coinbasevalue"])
    pool_script = bytes.fromhex(pool_script_pubkey_hex)
    outputs = struct.pack("<q", coinbase_value) + varint(len(pool_script)) + pool_script
    count = 1
    commitment = template.get("default_witness_commitment")
    if commitment:
        script = bytes.fromhex(commitment)
        outputs += struct.pack("<q", 0) + varint(len(script)) + script
        count = 2
    return outputs, count


def _coinbase_parts(
    template: dict,
    pool_script_pubkey_hex: str,
    script_prefix: bytes,
    extranonce2_size: int,
) -> tuple[bytes, bytes, int, int]:
    """Return (legacy_tx, segwit_tx, legacy_offset, segwit_offset)."""
    if extranonce2_size < 1 or extranonce2_size > 32:
        raise ValueError("extranonce2_size must be between 1 and 32")
    outputs, output_count = _coinbase_outputs(template, pool_script_pubkey_hex)
    script_sig = script_prefix + (b"\x00" * extranonce2_size)
    version = struct.pack("<I", 2)
    vin_count = varint(1)
    prevout = b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    script_len = varint(len(script_sig))
    sequence = struct.pack("<I", 0xFFFFFFFE)
    vout_count = varint(output_count)
    locktime = struct.pack("<I", 0)
    witness = varint(1) + varint(len(WITNESS_RESERVED_VALUE)) + WITNESS_RESERVED_VALUE

    legacy_prefix = version + vin_count + prevout + script_len + script_prefix
    legacy_offset = len(legacy_prefix)
    legacy = legacy_prefix + (b"\x00" * extranonce2_size) + sequence + vout_count + outputs + locktime

    segwit_prefix = version + b"\x00\x01" + vin_count + prevout + script_len + script_prefix
    segwit_offset = len(segwit_prefix)
    segwit = (
        segwit_prefix
        + (b"\x00" * extranonce2_size)
        + sequence
        + vout_count
        + outputs
        + witness
        + locktime
    )
    return legacy, segwit, legacy_offset, segwit_offset


def build_coinbase_parts(
    template: dict,
    pool_script_pubkey_hex: str,
    extranonce1: bytes,
    extranonce2_size: int,
) -> dict:
    script_prefix = encode_height(int(template["height"])) + extranonce1
    legacy, segwit, legacy_offset, segwit_offset = _coinbase_parts(
        template, pool_script_pubkey_hex, script_prefix, extranonce2_size
    )
    return {
        "coinb1": segwit[:segwit_offset].hex(),
        "coinb2": segwit[segwit_offset + extranonce2_size :].hex(),
        "extranonce2_size": extranonce2_size,
        "legacy_prefix": legacy[:legacy_offset],
        "script_prefix": script_prefix,
    }


def build_coinbase_tx(
    template: dict,
    pool_script_pubkey_hex: str,
    extranonce_prefix: bytes = b"",
    extranonce2: bytes = b"\x00\x00\x00\x00",
) -> tuple[bytes, str]:
    script_prefix = encode_height(int(template["height"])) + extranonce_prefix
    legacy, segwit, legacy_offset, segwit_offset = _coinbase_parts(
        template, pool_script_pubkey_hex, script_prefix, len(extranonce2)
    )
    # Replace the zero placeholder with the real extranonce2.
    legacy = (
        legacy[:legacy_offset]
        + extranonce2
        + legacy[legacy_offset + len(extranonce2) :]
    )
    segwit = (
        segwit[:segwit_offset]
        + extranonce2
        + segwit[segwit_offset + len(extranonce2) :]
    )
    txid = dsha256(legacy)[::-1].hex()
    return segwit, txid


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return b"\x00" * 32
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [dsha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_branch(leaves: list[bytes], index: int) -> list[str]:
    branch: list[str] = []
    level = list(leaves)
    idx = index
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sibling = idx ^ 1
        branch.append(level[sibling].hex())
        level = [dsha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return branch


def template_txids(template: dict) -> list[bytes]:
    return [reverse_bytes(tx["txid"]) for tx in template.get("transactions", [])]


def build_block(
    template: dict,
    coinbase_txid_hex: str,
    coinbase_tx: bytes,
    nonce: int,
    ntime: int | None = None,
) -> tuple[bytes, bytes, str]:
    if ntime is None:
        ntime = int(template["curtime"])
    txids = [reverse_bytes(coinbase_txid_hex)] + template_txids(template)
    root = merkle_root(txids)
    header = (
        struct.pack("<I", int(template["version"]))
        + reverse_bytes(template["previousblockhash"])
        + root
        + struct.pack("<I", int(ntime))
        + struct.pack("<I", int(template["bits"], 16))
        + struct.pack("<I", int(nonce))
    )
    transactions = [coinbase_tx] + [
        bytes.fromhex(tx["data"]) for tx in template.get("transactions", [])
    ]
    block = header + varint(len(transactions)) + b"".join(transactions)
    return block, header, header_hash(header)


def build_block_bytes(template, coinbase_txid_hex, coinbase_tx_bytes, nonce, ntime):
    """Compatibility wrapper returning ``(block, header)``."""
    block, header, _hash = build_block(
        template, coinbase_txid_hex, coinbase_tx_bytes, nonce, ntime
    )
    return block, header


def block_hash(header_bytes: bytes) -> str:
    return header_hash(header_bytes)
