import hashlib
import struct


def dsha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def reverse_bytes(h: str) -> bytes:
    return bytes.fromhex(h)[::-1]


def encode_height(n: int) -> bytes:
    if n == 0:
        return b"\x00"
    res = bytearray()
    while n > 0:
        res.append(n & 0xFF)
        n >>= 8
    if res[-1] & 0x80:
        res.append(0)
    return bytes([len(res)]) + bytes(res)


def varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def build_coinbase_tx(template: dict, pool_script_pubkey_hex: str, extranonce: bytes):
    height = template["height"]
    coinbasevalue = template["coinbasevalue"]
    commitment = template.get("default_witness_commitment")
    script_sig = encode_height(height) + extranonce
    tx_in = (
        b"\x00" * 32
        + struct.pack("<I", 0xFFFFFFFF)
        + varint(len(script_sig)) + script_sig
        + struct.pack("<I", 0xFFFFFFFE)
    )
    pool_script = bytes.fromhex(pool_script_pubkey_hex)
    outs = struct.pack("<q", coinbasevalue) + varint(len(pool_script)) + pool_script
    nout = 1
    if commitment:
        cscript = bytes.fromhex(commitment)
        outs += struct.pack("<q", 0) + varint(len(cscript)) + cscript
        nout = 2
    # legacy serialization for txid
    legacy = (
        struct.pack("<I", 2)
        + varint(1)
        + tx_in
        + varint(nout)
        + outs
        + struct.pack("<I", 0)
    )
    txid = dsha256(legacy)[::-1].hex()
    # witness
    witness = varint(1) + varint(32) + (b"\x00" * 32)
    segwit_tx = (
        struct.pack("<I", 2)
        + b"\x00\x01"
        + varint(1)
        + tx_in
        + varint(nout)
        + outs
        + witness
        + struct.pack("<I", 0)
    )
    return segwit_tx, txid


def build_block_bytes(template, coinbase_txid_hex, coinbase_tx_bytes, nonce, ntime):
    version = template["version"]
    prevhash = reverse_bytes(template["previousblockhash"])
    merkle = reverse_bytes(coinbase_txid_hex)
    bits = int(template["bits"], 16)
    bits_bytes = struct.pack("<I", bits)
    header = (
        struct.pack("<I", version)
        + prevhash
        + merkle
        + struct.pack("<I", ntime)
        + bits_bytes
        + struct.pack("<I", nonce)
    )
    block = header + varint(1) + coinbase_tx_bytes
    return block, header


def block_hash(header_bytes: bytes) -> str:
    return dsha256(header_bytes)[::-1].hex()


def target_from_bits(bits_hex: str) -> int:
    bits = int(bits_hex, 16)
    exponent = bits >> 24
    mantissa = bits & 0x00FFFFFF
    target = mantissa * (1 << (8 * (exponent - 3)))
    return target
