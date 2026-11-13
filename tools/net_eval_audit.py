#!/usr/bin/env python3
"""Pre-gate net audit: how well does a net's *static* eval agree with Stockfish 19?

Cheap (about 2 minutes, no games) sanity check to run BEFORE spending gate games on a net.
It cannot prove a net is strong, but a net that agrees with the teacher worse than the
HCE does is almost certainly defective (training/packaging bug) and should be rejected.

Positions: sampled from the PGNs given with --pgn (ply >= 8, every 5th ply, not in check,
not game over), de-duplicated, seeded shuffle. Labels: Stockfish at fixed --depth, side-to-move
perspective, mate scores mapped to +-(10000-|mate|). Both sides are clipped to +-CLIP.
Labels are cached (--cache) so a second net costs only the net's own evals.

Reported per eval source: Pearson r, regression slope (sf ~ x, ~1.0 means the scale matches),
MAE, sign agreement on |sf| >= 100, and mean bias (net - sf) per game phase by men count
(<=12 / 13-24 / >24), which exposes endgame over-optimism.

  tools/net_eval_audit.py --engine target/release/chess-rust-engine --stockfish ./stockfish \
      --pgn run1/games.pgn --pgn run2/games.pgn --net lb=nets/a.nnue --net tl=nets/b.nnue

Requires: python-chess. The engine must support the `eval` UCI debug command (it prints
`info string eval_hce <cp> eval_nnue <cp|none>`).
"""
import argparse, json, math, os, random, subprocess, sys

import chess
import chess.pgn


class Uci:
    def __init__(self, cmd, env=None):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                  env={**os.environ, **(env or {})})

    def send(self, s):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()

    def until(self, prefix):
        out = []
        while True:
            line = self.p.stdout.readline()
            if not line:
                return out
            out.append(line.strip())
            if line.startswith(prefix):
                return out

    def close(self):
        try:
            self.send("quit"); self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def sample_fens(pgns, n, seed):
    rng = random.Random(seed)
    fens = set()
    for path in pgns:
        with open(path) as fh:
            while (g := chess.pgn.read_game(fh)) is not None:
                b = g.board()
                for i, m in enumerate(g.mainline_moves()):
                    b.push(m)
                    if i >= 8 and i % 5 == 0 and not b.is_check() and not b.is_game_over() and b.fullmove_number < 120:
                        fens.add(b.fen())
    fens = sorted(fens)
    rng.shuffle(fens)
    return fens[:n]


def label(fens, stockfish, depth, cache):
    lab = json.load(open(cache)) if cache and os.path.exists(cache) else {}
    key = lambda f: f"{depth}|{f}"
    sf = Uci([stockfish]); sf.send("uci"); sf.until("uciok"); sf.send("setoption name Hash value 64")
    for fen in fens:
        if key(fen) in lab:
            continue
        sf.send("position fen " + fen); sf.send(f"go depth {depth}")
        sc = None
        for line in sf.until("bestmove"):
            t = line.split()
            if "score" in t and "lowerbound" not in t and "upperbound" not in t:
                k = t.index("score"); sc = (t[k + 1], int(t[k + 2]))
        kind, v = sc
        lab[key(fen)] = (10000 - abs(v)) * (1 if v > 0 else -1) if kind == "mate" else v
    sf.close()
    if cache:
        json.dump(lab, open(cache, "w"))
    return [lab[key(f)] for f in fens]


def engine_evals(engine, fens, net):
    env = {"CRE_NNUE_FILE": net} if net else {}
    e = Uci([engine], env); e.send("uci"); e.until("uciok"); e.send("setoption name UseNNUE value true")
    hce, nn = [], []
    for fen in fens:
        e.send("position fen " + fen); e.send("eval")
        line = e.until("info string eval_hce")[-1].split()
        hce.append(int(line[3])); nn.append(None if line[5] == "none" else int(line[5]))
    e.close()
    return hce, nn


def report(name, x, y, men, clip):
    c = lambda v: max(-clip, min(clip, v))
    X = [c(v) for v in x]; Y = [c(v) for v in y]; m = len(X)
    mx, my = sum(X) / m, sum(Y) / m
    cov = sum((a - mx) * (b - my) for a, b in zip(X, Y))
    vx = sum((a - mx) ** 2 for a in X); vy = sum((b - my) ** 2 for b in Y)
    r = cov / math.sqrt(vx * vy) if vx and vy else float("nan")
    slope = cov / vx if vx else float("nan")
    mae = sum(abs(a - b) for a, b in zip(X, Y)) / m
    big = [(a, b) for a, b in zip(X, Y) if abs(b) >= 100]
    sgn = sum(1 for a, b in big if a * b > 0) / max(1, len(big))
    bias = []
    for lo, hi, tag in ((0, 12, "<=12"), (13, 24, "13-24"), (25, 99, ">24")):
        d = [a - b for a, b, k in zip(X, Y, men) if lo <= k <= hi]
        bias.append(f"{tag}:{sum(d) / len(d):+.0f}(n={len(d)})" if d else f"{tag}:n/a")
    print(f"{name:22s} r={r:.3f} slope={slope:.2f} MAE={mae:.0f} sign={sgn:.3f}(n={len(big)})  bias {' '.join(bias)}")
    return {"name": name, "r": r, "slope": slope, "mae": mae, "sign": sgn}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", required=True); ap.add_argument("--stockfish", required=True)
    ap.add_argument("--pgn", action="append", required=True)
    ap.add_argument("--net", action="append", default=[], help="NAME=path.nnue (repeatable)")
    ap.add_argument("--n", type=int, default=1200); ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--seed", type=int, default=5); ap.add_argument("--clip", type=int, default=800)
    ap.add_argument("--cache", default="net_audit_labels.json"); ap.add_argument("--json", default="")
    a = ap.parse_args()
    fens = sample_fens(a.pgn, a.n, a.seed)
    men = [bin(chess.Board(f).occupied).count("1") for f in fens]
    print(f"{len(fens)} positions, SF depth {a.depth}, clip +-{a.clip}")
    sfv = label(fens, a.stockfish, a.depth, a.cache)
    hce, _ = engine_evals(a.engine, fens, "")
    rows = [report("HCE", hce, sfv, men, a.clip)]
    for spec in a.net:
        name, _, path = spec.partition("=")
        _, nn = engine_evals(a.engine, fens, path)
        if None in nn:
            print(f"{name}: net failed to load (HCE fallback)"); continue
        rows.append(report(name, nn, sfv, men, a.clip))
    hce_r = rows[0]["r"]
    for r in rows[1:]:
        if r["r"] < hce_r:
            print(f"WARNING {r['name']}: r={r['r']:.3f} < HCE r={hce_r:.3f} -> do not spend gate games on this net")
    if a.json:
        json.dump({"n": len(fens), "depth": a.depth, "rows": rows}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
