#!/usr/bin/env python3
"""Pre-ship gate: run a candidate against the last-known-good (LKG) binary FIVE independent times.

Why this exists
---------------
PR #5 (pawn corrhist) merged with `bench` node-identical to the previous commit and "green CI", yet it
lost 0-4-204 to the commit before it (Agent Q, EXP-Q1).  Perft, unit tests and bench cannot see a
strength collapse; only games can.  This gate is the cheap, fast, *independent-repeats* check that sits
BEFORE the expensive SPRT.  It answers one question: "does this candidate make the engine worse
(or break something) in any way we can detect in ~200 games?"

What it checks (every stage is recorded in ship_gate.json)
----------------------------------------------------------
 1. determinism   candidate `bench` run twice -> identical node count (else BLOCK: search is racy/stateful)
 2. node contract with --expect node-identical, candidate nodes must equal LKG nodes (else BLOCK)
 3. speed         7 interleaved bench repeats each; best-of-7 nps ratio cand/base (median also recorded).  node-identical: BLOCK < 0.95.
                  behavior-change: BLOCK < 0.85 (pathological), WARN < 0.97 (cost is reported, games must pay for it)
 4. games         N independent runs (default 5) x G games (default 40); every run uses its own seed and
                  its own DISJOINT slice of the opening book, colours reversed within every opening pair
 5. per-run       a run whose LOS (cand better than base) is < 0.5% is a collapse -> BLOCK
 6. pooled        pooled LOS < 2.5% -> BLOCK (cand is worse with >= 97.5% confidence)
 7. consistency   Cochran Q across the runs; p < 0.01 means the runs disagree -> HOLD (not reproducible)
    pooled LOS < 10% (cand probably worse, not yet proven) -> HOLD
 8. engine health illegal moves / disconnects / stalls attributed to the candidate -> BLOCK

Verdicts / exit codes
---------------------
  0 SMOKE-PASS  no evidence of harm.  This is NOT permission to merge.  It means "go spend SPRT games".
  1 BLOCK       evidence of harm or a broken contract.  Do not ship; find the cause.
  3 HOLD        inconsistent runs, or candidate probably worse (pooled LOS < --hold-los).  Investigate.
  4 ERROR       infrastructure failure (binary missing, fastchess crashed, unparsable output)

Statistical honesty
-------------------
5 x 40 = 200 games has a +-35 Elo 95% CI.  This gate detects COLLAPSES and large regressions
(roughly >= 50 Elo).  It cannot detect or prove a -5 Elo patch; that is SPRT's job.  A SMOKE-PASS must
never be quoted as an Elo gain.  `--selftest` measures the false-BLOCK rate of the decision rule by
simulation so the cost of the gate is a number, not a guess.

Pure stdlib.  Written by Agent T2 (ship-gate lane).  No src/ changes.
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import time

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# ----------------------------------------------------------------------------- statistics


def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def chi2_sf(x, df):
    """Survival function of chi-square (exact closed forms)."""
    if x <= 0:
        return 1.0
    if df % 2 == 0:
        h = x / 2.0
        return math.exp(-h) * sum(h ** k / math.factorial(k) for k in range(df // 2))
    total = math.erfc(math.sqrt(x / 2.0))
    t = math.sqrt(2.0 * x / math.pi) * math.exp(-x / 2.0)
    k = 3
    while k <= df:
        total += t
        t *= x / k
        k += 2
    return total


def elo_of(score):
    score = min(max(score, 1e-9), 1 - 1e-9)
    return -400.0 * math.log10(1.0 / score - 1.0)


def wdl_stats(w, d, l):
    """Score, trinomial standard error, logistic Elo with 95% CI, LOS for (w, d, l) from the cand's view."""
    n = w + d + l
    if n == 0:
        return dict(n=0, score=0.5, se=1.0, elo=0.0, lo=-1e9, hi=1e9, los=0.5)
    s_raw = (w + 0.5 * d) / n
    # half-game continuity clamp so 0-x-n / n-x-0 give finite numbers instead of +-inf
    s = min(max(s_raw, 0.5 / n), 1 - 0.5 / n)
    var = (w * (1 - s_raw) ** 2 + d * (0.5 - s_raw) ** 2 + l * (0 - s_raw) ** 2) / n
    se = max(math.sqrt(var / n), 0.25 / n)
    lo_s, hi_s = max(s - 1.96 * se, 0.5 / n), min(s + 1.96 * se, 1 - 0.5 / n)
    los = norm_cdf((w - l) / math.sqrt(w + l)) if (w + l) > 0 else 0.5
    return dict(n=n, score=s_raw, se=se, elo=elo_of(s), lo=elo_of(lo_s), hi=elo_of(hi_s), los=los)


def cochran_q(runs):
    """Heterogeneity of the per-run scores. Returns (Q, df, p)."""
    pts = []
    for r in runs:
        if sum(r) > 0:
            st = wdl_stats(*r)
            pts.append((st["score"], st["se"]))
    if len(pts) < 2:
        return 0.0, 0, 1.0
    ws = [1.0 / (se * se) for _, se in pts]
    mean = sum(w * s for w, (s, _) in zip(ws, pts)) / sum(ws)
    q = sum(w * (s - mean) ** 2 for w, (s, _) in zip(ws, pts))
    df = len(pts) - 1
    return q, df, chi2_sf(q, df)


def decide(runs, run_los_block=0.005, pooled_los_block=0.025, hetero_p=0.01, hold_los=0.10):
    """Pure decision rule over [(w,d,l), ...] (cand point of view). Returns (verdict, reasons, detail)."""
    reasons, verdict = [], "SMOKE-PASS"
    per = [wdl_stats(*r) for r in runs]
    tot = (sum(r[0] for r in runs), sum(r[1] for r in runs), sum(r[2] for r in runs))
    pooled = wdl_stats(*tot)
    q, df, p = cochran_q(runs)
    for i, st in enumerate(per, 1):
        if st["n"] and st["los"] < run_los_block:
            verdict = "BLOCK"
            reasons.append(f"run {i}: collapse, LOS {st['los']*100:.2f}% < {run_los_block*100:.1f}% "
                           f"(score {st['score']*100:.1f}% over {st['n']} games)")
    if pooled["n"] and pooled["los"] < pooled_los_block:
        verdict = "BLOCK"
        reasons.append(f"pooled: candidate worse with {100*(1-pooled['los']):.1f}% confidence "
                       f"(Elo {pooled['elo']:+.0f}, 95% CI [{pooled['lo']:+.0f}, {pooled['hi']:+.0f}], {pooled['n']} games)")
    if verdict != "BLOCK":
        if df >= 1 and p < hetero_p:
            verdict = "HOLD"
            reasons.append(f"runs disagree (Cochran Q={q:.1f}, df={df}, p={p:.4f}): result is not reproducible")
        if pooled["n"] and pooled["los"] < hold_los:
            verdict = "HOLD"
            reasons.append(f"pooled: candidate probably worse (LOS {pooled['los']*100:.1f}% < {hold_los*100:.0f}%, "
                           f"Elo {pooled['elo']:+.0f} [{pooled['lo']:+.0f}, {pooled['hi']:+.0f}]); get more games before trusting it")
    return verdict, reasons, dict(per_run=per, pooled=pooled, q=q, df=df, p=p, totals=tot)


# ----------------------------------------------------------------------------- selftest


def selftest(trials=3000):
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + name)
        ok &= bool(cond)

    v, _, _ = decide([(0, 1, 39)] * 5)
    check("known-bad (PR #5 shape: ~0 wins) -> BLOCK", v == "BLOCK")
    v, _, _ = decide([(10, 20, 10)] * 5)
    check("even runs -> SMOKE-PASS", v == "SMOKE-PASS")
    v, _, _ = decide([(20, 15, 5)] * 5)
    check("clear improvement -> SMOKE-PASS", v == "SMOKE-PASS")
    v, _, _ = decide([(10, 20, 10)] * 4 + [(30, 10, 0)])
    check("one run wildly different from the rest -> not a pass", v != "SMOKE-PASS")
    check("chi2_sf(13.277, 4) ~ 0.01", abs(chi2_sf(13.2767, 4) - 0.01) < 5e-4)
    check("chi2_sf(3.841, 1) ~ 0.05", abs(chi2_sf(3.841, 1) - 0.05) < 5e-4)
    check("chi2_sf(7.815, 3) ~ 0.05", abs(chi2_sf(7.815, 3) - 0.05) < 5e-4)
    check("60-40 -> +70 Elo", abs(wdl_stats(60, 0, 40)["elo"] - 70.4) < 1.0)

    rng = random.Random(20261110)

    def sim(pw, pd, g):
        w = d = l = 0
        for _ in range(g):
            u = rng.random()
            if u < pw:
                w += 1
            elif u < pw + pd:
                d += 1
            else:
                l += 1
        return (w, d, l)

    def rates(score, draw, runs=5, games=40):
        pw = score - draw / 2.0
        c = {"SMOKE-PASS": 0, "HOLD": 0, "BLOCK": 0}
        for _ in range(trials):
            v, _, _ = decide([sim(pw, draw, games) for _ in range(runs)])
            c[v] += 1
        return {k: round(v / trials, 3) for k, v in c.items()}

    aa = rates(0.50, 0.40)
    print(f"     A/A (equal strength, 40% draws, 5x40): {aa}")
    check("false-BLOCK rate on equal engines <= 8%", aa["BLOCK"] <= 0.08)
    check("false-BLOCK+HOLD rate on equal engines <= 20%", aa["BLOCK"] + aa["HOLD"] <= 0.20)
    el = lambda elo: 1.0 / (1.0 + 10 ** (-elo / 400.0))
    for elo in (-30, -60, -100):
        r = rates(el(elo), 0.40)
        print(f"     true {elo:+d} Elo regression: {r}")
        if elo == -100:
            check("-100 Elo regression flagged (BLOCK or HOLD) >= 95%", r["BLOCK"] + r["HOLD"] >= 0.95)
            check("-100 Elo regression BLOCKed >= 85%", r["BLOCK"] >= 0.85)
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- engine plumbing


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bench(binary, depth, timeout=300):
    out = subprocess.run([os.path.abspath(binary), "bench", str(depth)], capture_output=True, text=True, timeout=timeout)
    text = out.stdout + out.stderr
    m = re.findall(r"(\d+)\s+nodes\s+(\d+)\s+nps", text)
    if not m:
        raise RuntimeError(f"cannot parse bench output of {binary}: {text[-300:]!r}")
    return int(m[-1][0]), int(m[-1][1])


def run_games(args, run_idx, seed, book_slice, out_dir):
    epd = os.path.join(out_dir, f"book_run{run_idx}.epd")
    with open(epd, "w") as f:
        f.write("\n".join(book_slice) + "\n")
    pgn = os.path.join(out_dir, f"run{run_idx}.pgn")
    log = os.path.join(out_dir, f"run{run_idx}.log")
    cmd = [args.fastchess,
           "-engine", f"cmd={os.path.abspath(args.cand)}", "name=cand", "option.Hash=16", "option.Threads=1",
           "-engine", f"cmd={os.path.abspath(args.base)}", "name=base", "option.Hash=16", "option.Threads=1",
           "-each", f"tc={args.tc}",
           "-rounds", str(len(book_slice)), "-games", "2", "-repeat", "-concurrency", str(args.conc),
           "-openings", f"file={epd}", "format=epd", "order=sequential",
           "-srand", str(seed),
           "-draw", "movenumber=40", "movecount=8", "score=10",
           "-resign", "movecount=4", "score=800", "twosided=true",
           "-maxmoves", "300", "-recover", "-pgnout", f"file={pgn}"]
    with open(log, "w") as lf:
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    text = ANSI.sub("", open(log, errors="replace").read())
    g = None
    for g in re.finditer(r"Games:\s*(\d+),\s*Wins:\s*(\d+),\s*Losses:\s*(\d+),\s*Draws:\s*(\d+)", text):
        pass
    if g is None:
        raise RuntimeError(f"run {run_idx}: no result line in {log} (fastchess rc={proc.returncode})")
    n, w, l, d = (int(g.group(i)) for i in (1, 2, 3, 4))
    if n != 2 * len(book_slice):
        raise RuntimeError(f"run {run_idx}: expected {2*len(book_slice)} games, fastchess reports {n}")
    bad = {"illegal": 0, "disconnect": 0, "stall": 0, "time": 0}
    for line in text.splitlines():
        low = line.lower()
        if "illegal" in low:
            bad["illegal"] += 1
        if "disconnect" in low or "crash" in low:
            bad["disconnect"] += 1
        if "stall" in low:
            bad["stall"] += 1
        if "loses on time" in low or "time forfeit" in low:
            bad["time"] += 1
    return (w, d, l), n, bad


# ----------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cand")
    ap.add_argument("--base", help="last-known-good binary")
    ap.add_argument("--runs", type=int, default=5, help="independent repeats (default 5)")
    ap.add_argument("--games", type=int, default=40, help="games per run (even; default 40)")
    ap.add_argument("--tc", default="10+0.1", help="floor 5+0.05; no 100 ms games")
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--book", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "openings_book.epd"))
    ap.add_argument("--fastchess", default=os.environ.get("FASTCHESS", "fastchess"))
    ap.add_argument("--expect", choices=["node-identical", "behavior-change"], default="behavior-change")
    ap.add_argument("--bench-depth", type=int, default=10)
    ap.add_argument("--min-nps-ratio", type=float, default=0.95, help="node-identical patches: BLOCK below this")
    ap.add_argument("--min-nps-ratio-behavior", type=float, default=0.85,
                    help="behavior-change patches: BLOCK only below this (they may add per-node work on purpose)")
    ap.add_argument("--hold-los", type=float, default=0.10,
                    help="HOLD when pooled LOS (cand better than base) falls below this (default 10%%)")
    ap.add_argument("--out", default="ship_out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skip-games", action="store_true", help="only stages 1-3 (fast local pre-check)")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.cand or not a.base:
        ap.error("--cand and --base are required")
    b, _, inc = a.tc.partition("+")
    try:
        bt, it = float(b.split("/")[-1]), float(inc or 0)
    except ValueError:
        ap.error(f"bad tc {a.tc!r}")
    if bt < 5 or (bt + 40 * it) < 7:
        ap.error(f"refusing tc {a.tc}: floor is 5+0.05 (no rushed games)")
    if a.games % 2:
        ap.error("--games must be even (colour-reversed pairs)")

    os.makedirs(a.out, exist_ok=True)
    rec = dict(tool="ship_gate.py", cand=os.path.abspath(a.cand), base=os.path.abspath(a.base),
               cand_sha256=sha256(a.cand), base_sha256=sha256(a.base), tc=a.tc, runs=a.runs,
               games_per_run=a.games, seed=a.seed, expect=a.expect, threads=1, hash_mb=16,
               book=os.path.basename(a.book), book_sha256=sha256(a.book), stages={})
    reasons, verdict = [], "SMOKE-PASS"

    def downgrade(v, why):
        nonlocal verdict
        order = {"SMOKE-PASS": 0, "HOLD": 1, "BLOCK": 2}
        if order[v] > order[verdict]:
            verdict = v
        reasons.append(f"[{v}] {why}")

    try:
        c1, _ = bench(a.cand, a.bench_depth)
        c2, _ = bench(a.cand, a.bench_depth)
        b1, _ = bench(a.base, a.bench_depth)
        rec["stages"]["determinism"] = dict(cand_nodes=[c1, c2], base_nodes=b1, depth=a.bench_depth)
        print(f"[1] determinism: cand bench {a.bench_depth} = {c1}, {c2}   base = {b1}")
        if c1 != c2:
            downgrade("BLOCK", f"candidate bench is not deterministic ({c1} vs {c2})")
        if a.expect == "node-identical" and c1 != b1:
            downgrade("BLOCK", f"declared node-identical but nodes differ: cand {c1} vs base {b1}")
        if a.expect == "behavior-change" and c1 == b1:
            reasons.append("[note] bench nodes equal base: bench is blind to eval/correction-history effects, "
                           "do not read this as 'safe'")
        print(f"    nodes-to-depth ratio cand/base = {c1 / b1:.3f}")

        cn, bn = [], []
        for _ in range(7):
            cn.append(bench(a.cand, a.bench_depth)[1])
            bn.append(bench(a.base, a.bench_depth)[1])
        ratio = max(cn) / max(bn)  # best-of-N: contention only ever slows a run, so max is the robust estimator
        med_ratio = statistics.median(cn) / statistics.median(bn)
        spread = (max(cn) - min(cn)) / statistics.median(cn)
        rec["stages"]["speed"] = dict(cand_nps=cn, base_nps=bn, best_of_ratio=ratio, median_ratio=med_ratio, cand_spread=spread,
                                      expect=a.expect)
        print(f"[2] speed: best nps cand {max(cn)} base {max(bn)} -> ratio {ratio:.3f} "
              f"(median ratio {med_ratio:.3f}; cand min-max spread {spread*100:.1f}%)")
        if a.expect == "node-identical":
            # Same search, so any slowdown is pure loss.
            if ratio < a.min_nps_ratio:
                downgrade("BLOCK", f"node-identical patch is {100*(1-ratio):.1f}% slower (ratio {ratio:.3f} < {a.min_nps_ratio})")
            elif ratio < 0.98:
                downgrade("HOLD", f"node-identical patch ratio {ratio:.3f} < 0.98; re-measure before shipping")
        else:
            # Behaviour-changing patches may add work per node on purpose (e.g. correction history).
            # Only a pathological slowdown blocks; otherwise the cost is reported and the games must pay for it.
            if ratio < a.min_nps_ratio_behavior:
                downgrade("BLOCK", f"nps ratio {ratio:.3f} < {a.min_nps_ratio_behavior} (pathological slowdown)")
            elif ratio < 0.97:
                reasons.append(f"[WARN] costs {100*(1-ratio):.1f}% nps (ratio {ratio:.3f}); the strength games below "
                               f"must offset it, and the SPRT must confirm it")

        if not a.skip_games:
            lines = [x.strip() for x in open(a.book) if x.strip()]
            rounds = a.games // 2
            if rounds * a.runs > len(lines):
                ap.error("book too small for disjoint slices")
            random.Random(a.seed).shuffle(lines)
            results, health = [], []
            for i in range(a.runs):
                sl = lines[i * rounds:(i + 1) * rounds]
                wdl, n, bad = run_games(a, i + 1, a.seed + 1000 * (i + 1), sl, a.out)
                st = wdl_stats(*wdl)
                results.append(wdl)
                health.append(bad)
                print(f"[3.{i+1}] run {i+1}/{a.runs}: +{wdl[0]} ={wdl[1]} -{wdl[2]} ({n} games) "
                      f"score {st['score']*100:.1f}% Elo {st['elo']:+.0f} LOS {st['los']*100:.1f}%  health {bad}", flush=True)
            v, why, det = decide(results, hold_los=a.hold_los)
            for r in why:
                downgrade(v, r)
            if any(h["illegal"] or h["disconnect"] or h["stall"] for h in health):
                downgrade("BLOCK", f"engine-health events in logs: {health}")
            rec["stages"]["games"] = dict(results=results, health=health, pooled=det["pooled"],
                                          per_run=det["per_run"], cochran_q=det["q"], df=det["df"], p=det["p"])
            p = det["pooled"]
            if p["n"] < 100:
                reasons.append(f"[WARN] only {p['n']} games: PRELIMINARY. Verdicts below ~100 games are dominated by noise "
                               f"(identical binaries routinely score HOLD at 20 games); use the 5 x 40 default")
            print(f"[4] pooled {det['totals']} over {p['n']} games: score {p['score']*100:.1f}% "
                  f"Elo {p['elo']:+.0f} [{p['lo']:+.0f}, {p['hi']:+.0f}] LOS {p['los']*100:.1f}%  "
                  f"Cochran p={det['p']:.3f}")
    except Exception as e:  # infrastructure failure must never look like a pass
        rec["error"] = repr(e)
        rec["verdict"] = "ERROR"
        json.dump(rec, open(os.path.join(a.out, "ship_gate.json"), "w"), indent=1)
        print("ERROR:", e, file=sys.stderr)
        return 4

    rec["verdict"], rec["reasons"] = verdict, reasons
    rec["disclaimer"] = ("SMOKE-PASS detects collapse/large regression only (5x40 games ~ +-35 Elo). "
                         "It is not an Elo claim and not a merge approval; run SPRT next.")
    json.dump(rec, open(os.path.join(a.out, "ship_gate.json"), "w"), indent=1)
    md = [f"### Ship gate: **{verdict}**", f"cand `{rec['cand_sha256'][:12]}` vs LKG `{rec['base_sha256'][:12]}` "
          f"- {a.runs} x {a.games} games @ {a.tc}, book `{rec['book_sha256'][:12]}`", ""]
    md += [f"- {r}" for r in reasons] or ["- no stage raised a concern"]
    md += ["", f"_{rec['disclaimer']}_"]
    open(os.path.join(a.out, "ship_gate.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    return {"SMOKE-PASS": 0, "BLOCK": 1, "HOLD": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
