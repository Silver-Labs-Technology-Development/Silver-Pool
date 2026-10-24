from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from btcs_pool.block import encode_height, varint, dsha256

def test_encode_height_1():
    assert encode_height(1)==b'\x01\x01'

def test_varint():
    assert varint(252)==bytes([252])
    assert varint(253)==b'\xfd\xfd\x00'

def test_dsha256():
    assert len(dsha256(b'abc'))==32
