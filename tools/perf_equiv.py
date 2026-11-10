#!/usr/bin/env python3
"""Node-identity + NPS check for PRs that claim "bench-identical" (perf, refactors).

Why this exists
---------------
`bench` is ONE position set at ONE depth.  Agent A's corrhist bug showed that
"bench identical" can hide a real search change (PR #5 and main both read 178914
at d8 while one of them played 12.5% vs UCI_Elo 2400).  A pure-performance patch
must produce, for every position, the SAME node count, score and best move as the
base.  This checks that over many positions, and at several depths, then measures
speed with interleaved repeats so thermal drift / noisy neighbours cancel.

What it does
------------
1. DETERMINISM CONTROL: base is run twice on the same positions.  If base != base
   the engine is not deterministic here (threads, time-based limits) and a
   TEST-vs-BASE comparison would be meaningless; we stop and say so.
2. EQUIVALENCE: for each FEN and each depth, TEST must equal BASE on
   (nodes, score, bestmove).  Any difference is listed; exit status 1.
3. SPEED: `--rounds` (default 5) interleaved rounds of base/test over the same
   positions.  Reports per-round NPS, median ratio and worst-case ratio.  A patch
   that is faster on average but slower in a round is flagged, not hidden.

Usage
-----
  python3 tools/perf_equiv.py --base ./bin_main --test ./bin_pr --book tools/openings_book.epd \
      --positions 60 --depths 6,8,10 --rounds 5 --seed 1

No Elo is claimed here.  Node-identical + faster is *necessary* for a perf patch.
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time

TACTICAL = [
    # sharp / endgame positions on top of the opening book (quiet != tactical)
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
    "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
    "8/8/4k3/8/2p5/2K5/8/8 w - - 0 1",
]


def load_fens(book, n, seed):
    fens = []
    with open(book) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(";")[0].split()
            if len(parts) == 4:
                parts += ["0", "1"]
            fens.append(" ".join(parts[:6]))
    random.Random(seed).shuffle(fens)
    return TACTICAL + fens[: max(0, n - len(TACTICAL))]


def run_one(binary, fen, depth, hash_mb=16, extra=None):
    """Fresh process per position: no state can leak between positions."""
    cmds = ["uci", f"setoption name Hash value {hash_mb}"]
    for k, v in (extra or {}).items():
        cmds.append(f"setoption name {k} value {v}")
    cmds += ["isready", "ucinewgame", f"position fen {fen}", f"go depth {depth}"]
    p = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    t0 = time.perf_counter()
    p.stdin.write("\n".join(cmds) + "\n")
    p.stdin.flush()
    nodes = score = None
    best = None
    for line in p.stdout:
        if line.startswith("info") and " nodes " in line and " depth " in line:
            tok = line.split()
            try:
                nodes = int(tok[tok.index("nodes") + 1])
                i = tok.index("score")
                score = tok[i + 1] + " " + tok[i + 2]
            except (ValueError, IndexError):
                pass
        elif line.startswith("bestmove"):
            best = line.split()[1]
            break
    dt = time.perf_counter() - t0
    try:
        p.stdin.write("quit\n")
        p.stdin.flush()
    except Exception:
        pass
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
    return {"nodes": nodes, "score": score, "best": best, "secs": dt}


def sweep(binary, fens, depths, extra=None):
    out = {}
    for d in depths:
        for fen in fens:
            out[(d, fen)] = run_one(binary, fen, d, extra=extra)
    return out


def sig(r):
    return (r["nodes"], r["score"], r["best"])


def diff(a, b):
    return [(k, sig(a[k]), sig(b[k])) for k in a if sig(a[k]) != sig(b[k])]


def nps(res):
    n = sum(r["nodes"] or 0 for r in res.values())
    s = sum(r["secs"] for r in res.values())
    return n / s if s > 0 else 0.0


def run_bench(binary, depth):
    """Engine's own `bench`: returns (nodes, nps).  Excludes process start-up."""
    out = subprocess.run([binary, "bench", str(depth)], capture_output=True, text=True, timeout=600)
    for line in (out.stdout + out.stderr).splitlines()[::-1]:
        t = line.split()
        if len(t) >= 4 and t[1] == "nodes" and t[3] == "nps":
            return int(t[0]), float(t[2])
    raise RuntimeError(f"cannot parse bench output of {binary}: {out.stdout[-200:]}")


def finish(a, report):
    if a.json:
        with open(a.json, "w") as f:
            json.dump(report, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--book", default="tools/openings_book.epd")
    ap.add_argument("--positions", type=int, default=40)
    ap.add_argument("--depths", default="6,8")
    ap.add_argument("--speed-depth", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", default="")
    ap.add_argument("--test-opt", action="append", default=[], help="NAME=VALUE for TEST only")
    a = ap.parse_args()

    depths = [int(x) for x in a.depths.split(",")]
    fens = load_fens(a.book, a.positions, a.seed)
    test_extra = dict(o.split("=", 1) for o in a.test_opt)
    report = {"base": a.base, "test": a.test, "positions": len(fens), "depths": depths,
              "rounds": a.rounds, "seed": a.seed, "book": a.book,
              "book_bytes": os.path.getsize(a.book)}

    print(f"[1/3] determinism control: base x2 on {len(fens)} positions, depths {depths}")
    b1 = sweep(a.base, fens, depths)
    b2 = sweep(a.base, fens, depths)
    d0 = diff(b1, b2)
    report["determinism_mismatches"] = len(d0)
    if d0:
        print(f"  ABORT: base disagrees with itself on {len(d0)} searches (e.g. {d0[0]}).")
        print("  The engine is not deterministic here; node-identity cannot be judged.")
        report["verdict"] = "ABORT-nondeterministic-base"
        finish(a, report)
        sys.exit(2)
    print("  base == base on every search: deterministic.")

    print("[2/3] equivalence: test vs base")
    t1 = sweep(a.test, fens, depths, extra=test_extra)
    dd = diff(b1, t1)
    report["equivalence_mismatches"] = len(dd)
    report["searches"] = len(b1)
    print(f"  {len(b1) - len(dd)}/{len(b1)} searches identical (nodes, score, bestmove)")
    for k, sb, st in dd[:15]:
        print(f"  MISMATCH d{k[0]} {k[1]}\n    base={sb}\n    test={st}")

    print(f"[3/3] speed: {a.rounds} interleaved rounds of `bench {a.speed_depth}` (engine-reported nodes/nps)")
    rb, rt, ratios, bn = [], [], [], set()
    for r in range(a.rounds):
        order = [("base", a.base), ("test", a.test)]
        if r % 2:
            order.reverse()
        got = {}
        for name, binary in order:
            n, v = run_bench(binary, a.speed_depth)
            got[name] = v
            if name == "test":
                bn.add(n)
            else:
                bn.add(("base", n))
        rb.append(got["base"])
        rt.append(got["test"])
        ratios.append(got["test"] / got["base"])
        print(f"  round {r + 1}: base {got['base'] / 1e6:.3f} Mnps  test {got['test'] / 1e6:.3f} Mnps  ratio {ratios[-1]:.3f}")
    med = statistics.median(ratios)
    best_ratio = max(rt) / max(rb)          # peak vs peak: least sensitive to noisy neighbours
    med_ratio = statistics.median(rt) / statistics.median(rb)
    spread = max(statistics.pstdev(rb) / statistics.mean(rb), statistics.pstdev(rt) / statistics.mean(rt))
    report.update({"nps_ratio_best_of_n": best_ratio, "nps_ratio_median_of_medians": med_ratio,
                   "nps_ratio_per_round_median": med, "nps_ratio_min": min(ratios), "nps_ratio_max": max(ratios),
                   "nps_base": rb, "nps_test": rt, "nps_cv": spread})
    print(f"  best-of-{a.rounds} ratio {best_ratio:.3f} | median ratio {med_ratio:.3f} | per-round min {min(ratios):.3f} max {max(ratios):.3f} | CV {spread * 100:.1f}%")
    if spread > 0.05:
        print("  NOTE: >5% run-to-run spread; machine is noisy.  Speed verdict uses best-of-N; rerun on quiet hardware for a number to quote.")

    ok_eq = not dd
    ok_speed = best_ratio >= 0.98
    report["verdict"] = "PASS" if (ok_eq and ok_speed) else ("FAIL-search-changed" if not ok_eq else "FAIL-slower")
    print(f"VERDICT: {report['verdict']}  (equivalence={'ok' if ok_eq else 'BROKEN'}, "
          f"speed(best-of-N) {'ok' if ok_speed else 'REGRESSED'})")
    finish(a, report)
    sys.exit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
