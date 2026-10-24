import asyncio, json, sys, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from btcs_pool.block import dsha256, reverse_bytes, target_from_bits, build_block_bytes, block_hash

HOST='127.0.0.1'; PORT=3333

async def main():
    reader, writer = await asyncio.open_connection(HOST, PORT)
    # subscribe
    writer.write((json.dumps({"id":1,"method":"mining.subscribe","params":[]})+"\n").encode())
    await writer.drain()
    # read until authorized response? We'll just read lines
    extranonce1=None; en2_size=0
    job=None
    # authorize
    writer.write((json.dumps({"id":2,"method":"mining.authorize","params":["miner1","x"]})+"\n").encode())
    await writer.drain()
    async def read_lines():
        nonlocal job
        while True:
            line=await reader.readline()
            if not line: break
            line=line.decode().strip()
            if not line: continue
            msg=json.loads(line)
            if msg.get('method')=='mining.notify':
                job=msg['params']
                print('job received', job[0])
                await mine_and_submit(writer, job)
            else:
                # print responses
                pass
    await read_lines()

async def mine_and_submit(writer, job):
    job_id, prevhash_hex, coinb1, coinb2, _, version_hex, nbits, ntime_hex, clean = job
    coinbase=bytes.fromhex(coinb1)+bytes.fromhex(coinb2)
    # txid legacy: recompute by stripping segwit marker if present? coinbase segwit; txid requires legacy. We'll compute from pool? Instead use block hash validation target only; txid unknown. Need txid to build merkle. We can compute txid by parsing coinbase segwit -> legacy. Simpler: txid = dsha256 of legacy serialization. But we only have segwit bytes. Let's convert: if coinbase contains marker 00 01 after version, parse. We'll just compute txid by removing marker/flag and witness.
    # Parse segwit tx to legacy
    import struct
    def read_varint(data,i):
        first=data[i]
        if first<0xfd: return first,i+1
        if first==0xfd: return struct.unpack('<H',data[i+1:i+3])[0],i+3
        if first==0xfe: return struct.unpack('<I',data[i+1:i+5])[0],i+5
        return struct.unpack('<Q',data[i+1:i+9])[0],i+9
    off=0
    ver=struct.unpack('<I',coinbase[off:off+4])[0]; off+=4
    marker=coinbase[off]; flag=coinbase[off+1]
    segwit = (marker==0 and flag==1)
    if segwit: off+=2
    nin,off=read_varint(coinbase,off)
    # read inputs
    inputs_start=off
    for _ in range(nin):
        off+=32+4
        sl,off=read_varint(coinbase,off)
        off+=sl+4
    nout,off=read_varint(coinbase,off)
    outs_start=off
    for _ in range(nout):
        off+=8
        sl,off=read_varint(coinbase,off)
        off+=sl
    # witness skip
    if segwit:
        for _ in range(nin):
            nw,off=read_varint(coinbase,off)
            for _ in range(nw):
                wl,off=read_varint(coinbase,off)
                off+=wl
    lock=coinbase[off:off+4]; off+=4
    # legacy reassembly
    # inputs bytes: from inputs_start? need capture; redo simpler: rebuild not needed. Instead compute txid by hashing legacy serialization constructed from parsed parts? Too much.
    # Alternative: txid = dsha256 of coinbase with marker/flag/witness removed. We'll just remove the 2 marker bytes and witness data by reconstructing legacy from segwit using offsets recorded.
    # We have offsets; legacy = version + varint(nin)+inputs_bytes + varint(nout)+outs_bytes + locktime
    # Need inputs_bytes and outs_bytes; re-slice
    # find inputs start offset (after marker)
    # Recompute offsets from start
    off=4
    if segwit: off+=2
    incount_off=off
    nin2,off=read_varint(coinbase,off)
    inputs_off=off
    for _ in range(nin2):
        off+=32+4
        sl,off=read_varint(coinbase,off)
        off+=sl+4
    inputs_bytes=coinbase[inputs_off:off]
    # wait off now after inputs; nout
    nout_off=off
    nout2,off=read_varint(coinbase,off)
    outs_off=off
    for _ in range(nout2):
        off+=8
        sl,off=read_varint(coinbase,off)
        off+=sl
    outs_bytes=coinbase[outs_off:off]
    # skip witness
    if segwit:
        for _ in range(nin2):
            nw,off=read_varint(coinbase,off)
            for _ in range(nw):
                wl,off=read_varint(coinbase,off)
                off+=wl
    lock_bytes=coinbase[off:off+4]
    import struct as s
    legacy = s.pack('<I',ver) + varint_bytes(nin2) + inputs_bytes + varint_bytes(nout2) + outs_bytes + lock_bytes
    txid = dsha256(legacy)[::-1].hex()
    target=target_from_bits(nbits)
    ntime=int(ntime_hex,16)
    version=int(version_hex,16)
    prevhash=prevhash_hex
    # mine
    nonce=0
    while True:
        block,header=build_block_bytes({'version':version,'previousblockhash':reverse_bytes(prevhash).hex() if False else prevhash,'bits':nbits,'curtime':ntime}, txid, coinbase, nonce, ntime)
        # Wait build_block_bytes expects previousblockhash hex and reverses it. Our prevhash_hex from job is already reversed? Job prevhash is reversed hex (stratum). Need pass original? Let's handle: build_block_bytes reverses input. If we pass reversed again, wrong. We'll just compute header manually? Use template style: previousblockhash should be original (big-endian) for reversal. Stratum prevhash is little-endian reversed. So original = reverse of prevhash_hex.
        break
    # Redo properly:
    orig_prev = bytes.fromhex(prevhash_hex)[::-1].hex()
    tpl={'version':version,'previousblockhash':orig_prev,'bits':nbits,'curtime':ntime}
    nonce=0
    while True:
        block,header=build_block_bytes(tpl, txid, coinbase, nonce, ntime)
        h=block_hash(header)
        if int(h,16) <= target:
            print('found nonce',nonce,h)
            break
        nonce+=1
    # submit
    msg={"id":3,"method":"mining.submit","params":["miner1",job_id,"",f"{ntime:08x}",f"{nonce:08x}"]}
    writer.write((json.dumps(msg)+"\n").encode())
    await writer.drain()
    await asyncio.sleep(1)
    print('submitted')

def varint_bytes(n):
    import struct
    if n<0xFD: return bytes([n])
    if n<=0xFFFF: return b'\xfd'+struct.pack('<H',n)
    if n<=0xFFFFFFFF: return b'\xfe'+struct.pack('<I',n)
    return b'\xff'+struct.pack('<Q',n)

asyncio.run(main())
