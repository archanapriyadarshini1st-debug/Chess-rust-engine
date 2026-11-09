#!/usr/bin/env python3
"""Merge 28-byte teacher shards, dedupe on (occ, pieces, stm), print stats."""
import glob, sys, struct, collections
out = sys.argv[1]; pats = sys.argv[2:]
seen = set(); n_in = 0; wdl = collections.Counter()
with open(out, "wb") as f:
    for pat in pats:
        for p in sorted(glob.glob(pat)):
            b = open(p, "rb").read()
            for i in range(0, len(b) - 27, 28):
                r = b[i:i + 28]; n_in += 1
                k = r[:25]
                if k in seen:
                    continue
                seen.add(k); f.write(r); wdl[r[27]] += 1
print(f"in={n_in} unique={len(seen)} loss/draw/win={wdl[0]}/{wdl[1]}/{wdl[2]}")
