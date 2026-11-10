#!/usr/bin/env python3
"""Convert `fen | cp | wdl` text lines (engine `datagen` output) into the 28-byte
records that tools/nnue/train.py reads:
    occ u64 | 16 nibble bytes (color*6+type, ascending square) | stm u8 | score i16 | wdl u8
score is side-to-move POV centipawns, wdl is stm POV (0 loss, 1 draw, 2 win).
Pure stdlib (no python-chess). Malformed lines are skipped and counted.
Usage: selfplay_to_bin.py out.bin in1.txt [in2.txt ...]
"""
import struct, sys

REC = struct.Struct("<Q16sBhB")
assert REC.size == 28
PIECE = {c: i for i, c in enumerate("PNBRQKpnbrqk")}  # white 0..5, black 6..11 (P N B R Q K)


def encode(fen: str, cp: int, wdl_f: float):
    f = fen.split()
    rows = f[0].split("/")
    if len(rows) != 8:
        return None
    occ, nib = 0, []
    for r, row in enumerate(rows):  # rank 8 first
        file = 0
        rank = 7 - r
        for ch in row:
            if ch.isdigit():
                file += int(ch)
            else:
                sq = rank * 8 + file          # a1 = 0, matching python-chess / engine
                occ |= 1 << sq
                nib.append((sq, PIECE[ch]))
                file += 1
        if file != 8:
            return None
    nib.sort()
    n = [p for _, p in nib]
    if len(n) > 32:
        return None
    n += [0] * (32 - len(n))
    packed = bytes(n[2 * i] | (n[2 * i + 1] << 4) for i in range(16))
    stm = 0 if f[1] == "w" else 1
    cp = max(-32000, min(32000, cp))
    return REC.pack(occ, packed, stm, cp, int(round(wdl_f * 2)))


def main():
    out, ins = sys.argv[1], sys.argv[2:]
    ok = bad = 0
    with open(out, "wb") as o:
        for path in ins:
            for line in open(path):
                try:
                    fen, cp, w = [x.strip() for x in line.split("|")]
                    r = encode(fen, int(cp), float(w))
                except Exception:
                    r = None
                if r is None:
                    bad += 1
                else:
                    o.write(r)
                    ok += 1
    print(f"wrote {ok} records to {out} ({bad} skipped)")


if __name__ == "__main__":
    main()
