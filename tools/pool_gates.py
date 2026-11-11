#!/usr/bin/env python3
"""Pool replicated fastchess gate logs (EXP-KB1 / any 'test it 5 times' gate).

  tools/pool_gates.py LOG [LOG ...]       each LOG contains a final line
      "Score of A vs B: W - L - D  [..] N"   (fastchess; A = first engine)

Prints per-replicate and pooled W-D-L, score, logistic Elo with a trinomial 95% CI, LOS, and a
heterogeneity chi-square across replicates (df = k-1). A replicate set that disagrees with
itself (chi2 above the 95% critical value) must be treated as inconclusive, not averaged away.
Exit code 0 always: this is a reporter, the decision rule lives in the experiment record.
"""
import math, re, sys

CHI2_95 = {1: 3.84, 2: 5.99, 3: 7.81, 4: 9.49, 5: 11.07, 6: 12.59, 7: 14.07, 8: 15.51, 9: 16.92}
PAT = re.compile(r"Score of (\S+) vs (\S+):\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")


def parse(path):
    m = None
    for m in PAT.finditer(open(path, errors="replace").read()):
        pass
    if not m:
        raise SystemExit(f"{path}: no 'Score of A vs B' line")
    a, b, w, l, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5))
    return a, b, w, d, l


def elo(score):
    score = min(max(score, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / score - 1)


def stats(w, d, l):
    n = w + d + l
    s = (w + 0.5 * d) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * (0 - s) ** 2) / n
    se = math.sqrt(var / n)
    lo, hi = elo(s - 1.96 * se), elo(s + 1.96 * se)
    los = 0.5 * (1 + math.erf((s - 0.5) / (se * math.sqrt(2)))) if se > 0 else 0.5
    return n, s, elo(s), lo, hi, los


def main(paths):
    rows, names = [], None
    for p in paths:
        a, b, w, d, l = parse(p)
        names = names or (a, b)
        rows.append((p, w, d, l))
        n, s, e, lo, hi, los = stats(w, d, l)
        print(f"{p}: {a} vs {b}  {w}-{d}-{l} / {n}  score {100*s:.1f}%  Elo {e:+.0f} [{lo:+.0f}, {hi:+.0f}]")
    W, D, L = (sum(r[i] for r in rows) for i in (1, 2, 3))
    n, s, e, lo, hi, los = stats(W, D, L)
    print(f"POOLED {names[0]} vs {names[1]}  {W}-{D}-{L} / {n}  score {100*s:.1f}%  Elo {e:+.1f} [{lo:+.1f}, {hi:+.1f}]  LOS {100*los:.1f}%")
    if len(rows) > 1:
        # heterogeneity: each replicate's score vs the pooled score, using the pooled per-game variance
        var = (W * (1 - s) ** 2 + D * (0.5 - s) ** 2 + L * s ** 2) / n
        chi2 = sum((((w + 0.5 * d) / (w + d + l)) - s) ** 2 * (w + d + l) / var for _, w, d, l in rows)
        crit = CHI2_95.get(len(rows) - 1, float("nan"))
        verdict = "consistent" if chi2 <= crit else "REPLICATES DISAGREE -> inconclusive"
        print(f"heterogeneity chi2 {chi2:.2f} (df {len(rows)-1}, 95% crit {crit}) -> {verdict}")
    # single-run noise floor, so nobody over-reads one replicate
    n1 = n / len(rows)
    print(f"(per-replicate n={n1:.0f}: one run alone resolves only about +-{ (400/math.log(10))*4*1.96*math.sqrt(var_per_game(W,D,L)/n1):.0f} Elo)")


def var_per_game(W, D, L):
    n = W + D + L
    s = (W + 0.5 * D) / n
    return (W * (1 - s) ** 2 + D * (0.5 - s) ** 2 + L * s ** 2) / n


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
