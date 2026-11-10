#!/usr/bin/env python3
"""Agent K: turn SF19-MAX fixed-node odds-ladder PGNs into an honest report.

Input : a directory with files named odds_<nodes>.pgn (fastchess PGN output).
Output: markdown table (stdout) + JSON (--json). Nothing here is a CCRL claim.

Method
------
For each rung N (SF19 full strength, UCI_LimitStrength OFF, `go nodes N`) we
count W/D/L of the tested engine, compute score, logistic Elo difference
(tested - SF19@N) and a 95% trinomial confidence interval.  Because SF19 at a
fixed node count is deterministic and hardware independent, the rungs form a
*reproducible ruler*.  `node_equiv` is the node count at which the tested
engine would score 50%, by linear interpolation of Elo vs log2(nodes) between
the two rungs that bracket Elo = 0.  It is reported only if the rungs bracket 0;
otherwise we print "< lowest rung" / "> highest rung" and nothing else.
"""
import argparse, glob, json, math, os, re, sys

TAG = re.compile(r'^\[(\w+)\s+"(.*)"\]\s*$')


def parse_pgn(path, name):
    w = d = l = 0
    cur = {}

    def flush():
        nonlocal w, d, l
        res = cur.get('Result')
        if res not in ('1-0', '0-1', '1/2-1/2'):
            return
        white, black = cur.get('White'), cur.get('Black')
        if name not in (white, black):
            return
        if res == '1/2-1/2':
            d += 1
        elif (res == '1-0') == (white == name):
            w += 1
        else:
            l += 1

    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = TAG.match(line)
            if m:
                if m.group(1) == 'Event' and cur:
                    flush()
                    cur = {}
                cur[m.group(1)] = m.group(2)
    flush()
    return w, d, l


def elo_from_score(s):
    s = min(max(s, 1e-6), 1 - 1e-6)
    return -400.0 * math.log10(1.0 / s - 1.0)


def stats(w, d, l):
    n = w + d + l
    if n == 0:
        return dict(n=0, score=None, elo=None, lo=None, hi=None)
    # small pseudo-counts so 0% / 100% do not give infinities
    w2, d2, l2 = w + 0.25, d + 0.5, l + 0.25
    n2 = w2 + d2 + l2
    s = (w2 + 0.5 * d2) / n2
    var = (w2 * (1 - s) ** 2 + d2 * (0.5 - s) ** 2 + l2 * (0 - s) ** 2) / n2
    se = math.sqrt(var / n2)
    return dict(n=n, score=(w + 0.5 * d) / n, elo=elo_from_score(s),
                lo=elo_from_score(s - 1.96 * se), hi=elo_from_score(s + 1.96 * se))


def node_equiv(rows):
    pts = sorted((math.log2(r['nodes']), r['elo']) for r in rows if r['elo'] is not None)
    for (x0, e0), (x1, e1) in zip(pts, pts[1:]):
        if e0 * e1 <= 0 and e0 != e1:
            x = x0 + (0 - e0) * (x1 - x0) / (e1 - e0)
            return 2 ** x
    if pts and all(e > 0 for _, e in pts):
        return '> highest rung'
    if pts and all(e < 0 for _, e in pts):
        return '< lowest rung'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--engine', default='Rust')
    ap.add_argument('--json')
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    rows = []
    for p in sorted(glob.glob(os.path.join(a.dir, '**', 'odds_*.pgn'), recursive=True)):
        m = re.search(r'odds_(\d+)\.pgn$', p)
        if not m:
            continue
        w, d, l = parse_pgn(p, a.engine)
        rows.append(dict(nodes=int(m.group(1)), w=w, d=d, l=l, **stats(w, d, l)))
    rows.sort(key=lambda r: r['nodes'])
    ne = node_equiv(rows)
    print(f'### SF19 MAX odds ladder {a.label}'.rstrip())
    print()
    print('| SF19 MAX nodes/move | games | W-D-L | score | Elo vs SF19@N | 95% CI |')
    print('|---:|---:|:---:|---:|---:|:---:|')
    for r in rows:
        if r['n'] == 0:
            continue
        print(f"| {r['nodes']:,} | {r['n']} | {r['w']}-{r['d']}-{r['l']} | {100*r['score']:.1f}% | "
              f"{r['elo']:+.0f} | {r['lo']:+.0f} .. {r['hi']:+.0f} |")
    print()
    if isinstance(ne, float):
        print(f'**node_equiv ~ {ne:,.0f} SF19-MAX nodes/move** (50% crossing, linear in log2 nodes; '
              'rung CIs above bound the uncertainty; not a CCRL Elo).')
    elif ne:
        print(f'**node_equiv: {ne}** (rungs do not bracket 50%).')
    else:
        print('node_equiv: not computable.')
    total = sum(r['n'] for r in rows)
    print(f'\nTotal games: {total}. Rungs with fewer than ~100 games have CIs wider than +/-70 Elo.')
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(dict(rows=rows, node_equiv=ne), f, indent=1)


if __name__ == '__main__':
    sys.exit(main())
