#!/usr/bin/env python3
"""EXP-NV1 report: recompute W/D/L, score, Elo, 95% CI, LOS and the PRE-REGISTERED verdict
from raw fastchess logs (does not trust any pre-computed summary).

Input layout:  <dir>/<candidate>/rep<k>.log   (fastchess stdout, last "Games: N, Wins: W, Losses: L, Draws: D")
Candidates:    aa (HCE vs HCE harness control), stage0 (existing reference net), lam1.0 / lam0.6 (new nets).

Verdict rules (fixed BEFORE any game was played, see experiments/EXP-NV1-volume-selfplay.md):
  * A/A control is VALID iff |Elo| < 2.576 * se.  If invalid, every verdict is INVALID.
  * candidate ADVANCE  : pooled score >= 50% and >= 3 of 5 replicates >= 50% and pooled 95% CI lower bound > -40 Elo
  * candidate KILL     : pooled 95% CI upper bound < 0 Elo
  * otherwise          : INCONCLUSIVE (needs more games; never promoted on this evidence)
ADVANCE only earns a 10+0.1 time-control gate. It never earns a merge.
"""
import glob, json, math, os, re, sys

LINE = re.compile(r"Games:\s*(\d+),\s*Wins:\s*(\d+),\s*Losses:\s*(\d+),\s*Draws:\s*(\d+)")


def parse(path):
    last = None
    for m in LINE.finditer(open(path, errors="replace").read()):
        last = m
    if not last:
        return None
    n, w, l, d = map(int, last.groups())
    return w, d, l


def elo(s):
    s = min(max(s, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / s - 1)


def stats(w, d, l):
    n = w + d + l
    s = (w + d / 2) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * s ** 2) / n
    se = math.sqrt(var / n)
    lo, hi = elo(s - 1.96 * se), elo(s + 1.96 * se)
    se_elo = (elo(s + se) - elo(s - se)) / 2
    los = 0.5 * (1 + math.erf((w - l) / math.sqrt(2 * max(w + l, 1)))) if (w + l) else 0.5
    return dict(n=n, w=w, d=d, l=l, score=s, elo=elo(s), lo=lo, hi=hi, se_elo=se_elo, los=los)


def main(root):
    out, md = {}, []
    for cdir in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(cdir):
            continue
        name = os.path.basename(cdir)
        reps = []
        for f in sorted(glob.glob(os.path.join(cdir, "rep*.log"))):
            r = parse(f)
            if r:
                reps.append((os.path.basename(f), r))
        if not reps:
            continue
        W = sum(r[0] for _, r in reps); D = sum(r[1] for _, r in reps); L = sum(r[2] for _, r in reps)
        pooled = stats(W, D, L)
        per = [dict(rep=f, **stats(*r)) for f, r in reps]
        pos = sum(1 for p in per if p["score"] >= 0.5)
        out[name] = dict(pooled=pooled, reps=per, reps_ge_50=pos)
    aa = out.get("aa")
    aa_valid = aa is not None and abs(aa["pooled"]["elo"]) < 2.576 * aa["pooled"]["se_elo"]
    md.append("### EXP-NV1 results (fixed nodes, NET vs HCE; colours swapped; disjoint opening slices)\n")
    md.append(f"A/A control: {'VALID' if aa_valid else 'INVALID or missing'}"
              + (f" (pooled {aa['pooled']['score']*100:.1f}%, Elo {aa['pooled']['elo']:+.1f} +/- {2.576*aa['pooled']['se_elo']:.1f} at 99%)" if aa else "") + "\n")
    md.append("| candidate | games | W-D-L | score | Elo [95% CI] | LOS | reps>=50% | verdict |\n|---|---|---|---|---|---|---|---|")
    for name, v in out.items():
        p = v["pooled"]
        if name == "aa":
            verdict = "control"
        elif not aa_valid:
            verdict = "INVALID (A/A control failed)"
        elif name == "stage0":
            verdict = "reference"
        elif p["hi"] < 0:
            verdict = "KILL"
        elif p["score"] >= 0.5 and v["reps_ge_50"] >= 3 and p["lo"] > -40:
            verdict = "ADVANCE to 10+0.1 gate (no merge)"
        else:
            verdict = "INCONCLUSIVE"
        v["verdict"] = verdict
        md.append(f"| {name} | {p['n']} | {p['w']}-{p['d']}-{p['l']} | {p['score']*100:.1f}% | {p['elo']:+.0f} [{p['lo']:+.0f},{p['hi']:+.0f}] | {p['los']*100:.0f}% | {v['reps_ge_50']}/{len(v['reps'])} | {verdict} |")
    md.append("\nPer-replicate scores:\n")
    for name, v in out.items():
        md.append(f"- {name}: " + ", ".join(f"{p['w']}-{p['d']}-{p['l']} ({p['score']*100:.0f}%)" for p in v["reps"]))
    text = "\n".join(md)
    print(text)
    json.dump(out, open(os.path.join(root, "results.json"), "w"), indent=1)
    open(os.path.join(root, "results.md"), "w").write(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gate_all")
