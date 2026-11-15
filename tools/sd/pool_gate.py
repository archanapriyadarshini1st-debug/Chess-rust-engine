#!/usr/bin/env python3
"""Pool replicated fastchess gates (net vs HCE) and print a verdict with an honest CI.

Parses the last `Score of A vs B: W - L - D  [x] N` line in each log.  Reports each replicate, the pooled
W-D-L, pooled score, logistic Elo with a trinomial 95% CI, LOS, and whether the replicates agree in sign.
No replicate is dropped or reordered.  An A/A log (same engine both sides) can be passed with --aa to expose
the colour/book bias of the harness itself.
"""
import argparse, json, math, re, sys

PAT = re.compile(r"Score of (\S+) vs (\S+): (\d+) - (\d+) - (\d+)")  # interim line: W - L - D
FINAL = re.compile(r"Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)")  # final fastchess summary


def last_score(path):
    """(W, D, L) from the final fastchess summary if present, else from the last interim `Score of` line."""
    txt = open(path, errors="replace").read()
    f = None
    for f in FINAL.finditer(txt):
        pass
    if f:
        return int(f.group(2)), int(f.group(4)), int(f.group(3))
    m = None
    for m in PAT.finditer(txt):
        pass
    if not m:
        return None
    return int(m.group(3)), int(m.group(5)), int(m.group(4))


def stats(w, d, l):
    n = w + d + l
    if n == 0:
        return None
    s = (w + 0.5 * d) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * (0 - s) ** 2) / n
    se = math.sqrt(var / n)
    elo = lambda x: -400 * math.log10(1 / min(max(x, 1e-6), 1 - 1e-6) - 1)
    los = 0.5 * (1 + math.erf((s - 0.5) / (se * math.sqrt(2)))) if se > 0 else float("nan")
    return {"games": n, "W": w, "D": d, "L": l, "score": s, "elo": elo(s),
            "ci95": [elo(s - 1.96 * se), elo(s + 1.96 * se)], "los": los}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--aa", nargs="*", default=[])
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    reps, tw, td, tl = [], 0, 0, 0
    for p in a.logs:
        r = last_score(p)
        if r is None:
            print(f"{p}: NO SCORE LINE (counted as missing, not as a loss)")
            continue
        reps.append({"log": p, **stats(*r)})
        tw, td, tl = tw + r[0], td + r[1], tl + r[2]
    pooled = stats(tw, td, tl)
    out = {"replicates": reps, "pooled": pooled}
    if reps:
        out["replicates_positive"] = sum(1 for r in reps if r["score"] > 0.5)
        out["replicates_total"] = len(reps)
    aa = [last_score(p) for p in a.aa]
    aa = [x for x in aa if x]
    if aa:
        out["aa_control"] = stats(sum(x[0] for x in aa), sum(x[1] for x in aa), sum(x[2] for x in aa))
    for r in reps:
        print(f"  {r['log']}: {r['W']}-{r['D']}-{r['L']}  {100*r['score']:.1f}%  Elo {r['elo']:+.0f}")
    if pooled:
        print(f"POOLED {pooled['W']}-{pooled['D']}-{pooled['L']} / {pooled['games']}: {100*pooled['score']:.1f}%  "
              f"Elo {pooled['elo']:+.0f} [{pooled['ci95'][0]:+.0f}, {pooled['ci95'][1]:+.0f}]  LOS {100*pooled['los']:.1f}%  "
              f"replicates>50%: {out.get('replicates_positive')}/{out.get('replicates_total')}")
    if "aa_control" in out:
        c = out["aa_control"]
        print(f"A/A CONTROL {c['W']}-{c['D']}-{c['L']}: {100*c['score']:.1f}%  Elo {c['elo']:+.0f} [{c['ci95'][0]:+.0f}, {c['ci95'][1]:+.0f}]")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
