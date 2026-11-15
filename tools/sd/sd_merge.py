#!/usr/bin/env python3
"""Merge `datagen-bin` shards for EXP-SD1 (Agent SD).

Guarantees (each is asserted, not hoped for):
  * identical shards are rejected (sha256 of file bytes)  -- the parallel-duplication failure mode
  * every shard has a `.gid` sidecar of the right length  -- games stay identifiable
  * validation is GAME-disjoint: whole games are held out to `--holdout`; the trainer never sees them
  * training positions identical to any holdout position are removed (no cross-split leakage)
  * exact duplicate positions are removed (same identity as tools/nnue/train.py::pos_hash)
  * the cap is a seeded random subsample, so it does not bias toward early shards/openings

Output: merged train records (28 B), holdout records, and `<out>.stats.json`.
"""
import argparse, glob, hashlib, json, sys
import numpy as np

REC = np.dtype([("occ", "<u8"), ("pcs", "u1", (16,)), ("stm", "u1"), ("score", "<i2"), ("wdl", "u1")])
assert REC.itemsize == 28
M = np.uint64


def pos_hash(recs):  # byte-for-byte the same function as tools/nnue/train.py::pos_hash
    pcs = np.ascontiguousarray(recs["pcs"]).view("<u8").reshape(len(recs), 2)
    h = recs["occ"].astype(M) * M(0x9E3779B97F4A7C15)
    h ^= pcs[:, 0] * M(0xC2B2AE3D27D4EB4F)
    h ^= pcs[:, 1] * M(0x165667B19E3779F9)
    h ^= recs["stm"].astype(M) * M(0x27D4EB2F165667C5)
    h ^= h >> M(31)
    h *= M(0xBF58476D1CE4E5B9)
    h ^= h >> M(29)
    return h


def mix64(x):
    x = x.astype(M)
    x ^= x >> M(33)
    x *= M(0xFF51AFD7ED558CCD)
    x ^= x >> M(33)
    x *= M(0xC4CEB9FE1A85EC53)
    x ^= x >> M(33)
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", required=True, help="glob of shard .bin files (recursive)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--max-records", type=int, default=20_000_000)
    ap.add_argument("--holdout-mod", type=int, default=40, help="1 game in N is held out")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    files = sorted(f for f in glob.glob(a.inp, recursive=True) if f.endswith(".bin"))
    if not files:
        sys.exit("no shard files")
    seen, parts, gkeys, per_file = {}, [], [], []
    for i, f in enumerate(files):
        raw = open(f, "rb").read()
        sha = hashlib.sha256(raw).hexdigest()
        if sha in seen:
            sys.exit(f"IDENTICAL SHARDS: {f} == {seen[sha]} (sha256 {sha[:16]}); refusing to merge")
        seen[sha] = f
        recs = np.frombuffer(raw, dtype=REC)
        gid = np.fromfile(f + ".gid", dtype="<u4")
        if len(gid) != len(recs):
            sys.exit(f"{f}: {len(recs)} records but {len(gid)} game ids")
        parts.append(recs)
        gkeys.append((np.uint64(i) << M(32)) | gid.astype(M))
        per_file.append({"file": f, "records": int(len(recs)), "sha256": sha[:16], "games": int(len(np.unique(gid)))})
    recs = np.concatenate(parts)
    gk = np.concatenate(gkeys)
    del parts, gkeys
    raw_n = len(recs)

    held = (mix64(gk ^ M(a.seed * 0x9E3779B1)) % M(a.holdout_mod)) == 0
    hold, train = recs[held], recs[~held]
    n_games = int(len(np.unique(gk)))
    n_hold_games = int(len(np.unique(gk[held])))
    del recs, gk

    hh = pos_hash(hold)
    _, hfirst = np.unique(hh, return_index=True)
    hold, hh = hold[np.sort(hfirst)], hh[np.sort(hfirst)]

    th = pos_hash(train)
    _, first = np.unique(th, return_index=True)
    first.sort()
    train, th = train[first], th[first]
    after_dedupe = len(train)
    leak = np.isin(th, hh)
    train = train[~leak]
    after_leak = len(train)
    if len(train) > a.max_records:
        sel = np.random.default_rng(a.seed).choice(len(train), a.max_records, replace=False)
        sel.sort()
        train = train[sel]

    train.tofile(a.out)
    hold.tofile(a.holdout)
    stats = {
        "shards": per_file, "raw_records": int(raw_n), "games": n_games, "holdout_games": n_hold_games,
        "train_after_dedupe": int(after_dedupe), "removed_as_holdout_duplicates": int(after_dedupe - after_leak),
        "train_final": int(len(train)), "holdout_unique": int(len(hold)), "max_records": a.max_records,
        "wdl_stm_loss_draw_win_train": np.bincount(train["wdl"], minlength=3).tolist(),
        "abs_score_lt50_frac": float((np.abs(train["score"]) < 50).mean()),
        "dedupe_removed_frac": float(1 - after_dedupe / max(1, raw_n - int(held.sum()))),
        "seed": a.seed,
    }
    json.dump(stats, open(a.out + ".stats.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "shards"}, indent=1))


if __name__ == "__main__":
    main()
