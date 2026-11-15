#!/usr/bin/env python3
"""Mix two SF19-labelled record sets into one training file with cross-set holdout exclusion (Agent CH, EXP-CH1).

Inputs  : 28-byte records (occ u64 | 16 B nibbles | stm u8 | score i16 | wdl u8), the layout of tools/nnue/train.py.
Output  : `--out` = all `--a` parts (in order) then all `--b` parts (in order), minus every record whose position
          identity (train.py's pos_hash) appears in EITHER evaluation holdout sample (`--hold` files).
Why     : the two sources (SD1 HCE self-play, IV gen-2 NNUE self-play) are different game sets, so each already has a
          game-disjoint holdout. But the same position can occur in both sources (openings, simple endgames). A
          position that sits in a holdout used for evaluation must never be trained on, whichever source it came from.
Never   : touches `score` or `wdl`. Teacher scores and game results stay separate supervision signals.
Report  : JSON with per-source counts, how many were removed as holdout positions, and the share of each source.
"""
import argparse, glob, json, os, sys, tempfile
import numpy as np

REC = np.dtype([("occ", "<u8"), ("pcs", "u1", (16,)), ("stm", "u1"), ("score", "<i2"), ("wdl", "u1")])
assert REC.itemsize == 28


def pos_hash(recs):
    """Identical to tools/nnue/train.py::pos_hash (kept in sync by --selftest)."""
    M = np.uint64
    pcs = np.ascontiguousarray(recs["pcs"]).view("<u8").reshape(len(recs), 2)
    h = recs["occ"].astype(M) * M(0x9E3779B97F4A7C15)
    h ^= pcs[:, 0] * M(0xC2B2AE3D27D4EB4F)
    h ^= pcs[:, 1] * M(0x165667B19E3779F9)
    h ^= recs["stm"].astype(M) * M(0x27D4EB2F165667C5)
    h ^= h >> M(31)
    h *= M(0xBF58476D1CE4E5B9)
    h ^= h >> M(29)
    return h


def stream(paths, hold_keys, fout, tag):
    kept = removed = 0
    for p in paths:
        a = np.fromfile(p, dtype=REC)
        if len(hold_keys):
            bad = np.isin(pos_hash(a), hold_keys)
            removed += int(bad.sum())
            a = a[~bad]
        a.tofile(fout)
        kept += len(a)
    print(f"{tag}: kept {kept} removed_as_holdout {removed} from {len(paths)} files", flush=True)
    return kept, removed


def mix(a_glob, b_glob, holds, out, report):
    pa, pb = sorted(glob.glob(a_glob, recursive=True)), sorted(glob.glob(b_glob, recursive=True))
    assert pa and pb, f"empty input: a={len(pa)} b={len(pb)}"
    assert not set(pa) & set(pb)
    keys = [pos_hash(np.fromfile(h, dtype=REC)) for h in holds]
    hold_keys = np.unique(np.concatenate(keys)) if keys else np.zeros(0, np.uint64)
    with open(out, "wb") as f:
        ka, ra = stream(pa, hold_keys, f, "A")
        kb, rb = stream(pb, hold_keys, f, "B")
    rep = {"a_files": len(pa), "b_files": len(pb), "a_kept": ka, "a_removed_as_holdout": ra, "b_kept": kb,
           "b_removed_as_holdout": rb, "total": ka + kb, "b_share": kb / max(1, ka + kb),
           "holdout_unique_keys": int(len(hold_keys))}
    json.dump(rep, open(report, "w"), indent=1)
    print(json.dumps(rep))
    return rep


def selftest():
    rng = np.random.default_rng(5)
    d = tempfile.mkdtemp()

    def mk(n):
        r = np.zeros(n, REC)
        r["occ"] = rng.integers(1, 2**62, n, dtype=np.uint64)
        r["pcs"] = rng.integers(0, 255, (n, 16), dtype=np.uint8)
        r["stm"] = rng.integers(0, 2, n)
        r["score"] = rng.integers(-500, 500, n)
        r["wdl"] = rng.integers(0, 3, n)
        return r

    a1, a2, b1, h1, h2 = mk(1000), mk(500), mk(800), mk(50), mk(50)
    b1[:10] = h1[:10]          # b contains 10 holdout-1 positions
    a2[:5] = h2[:5]            # a contains 5 holdout-2 positions
    b1[100:110] = a1[100:110]  # cross-source duplicate NOT in a holdout: must be kept (train.py dedupes later)
    for n, x in (("a1", a1), ("a2", a2), ("b1", b1), ("h1", h1), ("h2", h2)):
        x.tofile(os.path.join(d, n + ".bin"))
    rep = mix(os.path.join(d, "a?.bin"), os.path.join(d, "b?.bin"),
              [os.path.join(d, "h1.bin"), os.path.join(d, "h2.bin")], os.path.join(d, "out.bin"), os.path.join(d, "rep.json"))
    out = np.fromfile(os.path.join(d, "out.bin"), dtype=REC)
    assert rep["a_removed_as_holdout"] == 5 and rep["b_removed_as_holdout"] == 10, rep
    assert len(out) == 1000 + 495 + 790 == rep["total"], (len(out), rep)
    hk = np.unique(np.concatenate([pos_hash(h1), pos_hash(h2)]))
    assert not np.isin(pos_hash(out), hk).any(), "a holdout position leaked into the training mix"
    assert (out[:1000] == a1).all() and (out["score"][1000:1495] == a2["score"][5:]).all(), "order or score changed"
    src = open("tools/nnue/train.py").read()          # the identity must match train.py's split hash
    for c in ("0x9E3779B97F4A7C15", "0xC2B2AE3D27D4EB4F", "0x165667B19E3779F9", "0x27D4EB2F165667C5", "0xBF58476D1CE4E5B9"):
        assert c in src, c
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("trainer", "tools/nnue/train.py")
        T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
        assert (T.pos_hash(a1) == pos_hash(a1)).all(), "pos_hash diverged from train.py"
        print("pos_hash == train.py::pos_hash (executed)")
    except ModuleNotFoundError as e:
        print("train.py import skipped:", e)
    print("SELFTEST OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a"); ap.add_argument("--b"); ap.add_argument("--hold", nargs="*", default=[])
    ap.add_argument("--out"); ap.add_argument("--report", default="mix.json"); ap.add_argument("--selftest", action="store_true")
    x = ap.parse_args()
    if x.selftest:
        selftest()
    else:
        assert x.a and x.b and x.out
        mix(x.a, x.b, x.hold, x.out, x.report)
