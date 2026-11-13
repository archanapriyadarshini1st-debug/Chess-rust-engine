#!/usr/bin/env python3
"""Material-odds calibration probe for NNUE nets (EXP-MS1).

Takes balanced positions (an EPD book), removes ONE piece from the side that is NOT to move
(so the side to move is up by that piece), keeps only legal results, and asks the engine for
its static `eval` with a given net / options. A net that has never seen lopsided material in
training (e.g. `nnue/ft-43234452295`) shows up as a large shortfall vs the HCE reference.

Reference = the engine's own HCE (`eval_hce` in the `info string eval` line): it is material-
correct by construction, independent of the net, and costs nothing. This is a *sanity gate*,
not a strength claim: it is meant to reject blind nets before an expensive match.

  python3 tools/material_probe.py --engine target/release/chess-rust-engine \
      --net nets/default.nnue --epd tools/openings_book.epd --n 200 [--option NnueGuard=150] [--json out.json]

Exit status 1 if any class fails (mean NNUE/HCE ratio < --min-ratio, default 0.70, or more than
2% of positions where the side to move, being up a piece, is not scored as ahead).
"""
import argparse, json, os, random, re, subprocess, sys
import chess

CLASSES = {"minor": (chess.KNIGHT, chess.BISHOP), "rook": (chess.ROOK,), "queen": (chess.QUEEN,)}

def odds_positions(epd, n, seed):
    rng = random.Random(seed)
    lines = [l for l in open(epd) if l.strip()]
    rng.shuffle(lines)
    out = {c: [] for c in CLASSES}
    for l in lines:
        fen = " ".join(l.split()[:4]) + " 0 1"
        for cls, types in CLASSES.items():
            if len(out[cls]) >= n:
                continue
            b = chess.Board(fen)
            victims = [s for s in chess.SQUARES
                       if (p := b.piece_at(s)) and p.color != b.turn and p.piece_type in types]
            if not victims:
                continue
            b.remove_piece_at(rng.choice(victims))
            b.castling_rights = b.clean_castling_rights()
            if b.is_valid() and not b.is_check():
                out[cls].append(b.fen())
        if all(len(v) >= n for v in out.values()):
            break
    return out

def engine_eval(engine, net, options, fens):
    env = dict(os.environ)
    if net:
        env["CRE_NNUE_FILE"] = net
    cmds = [f"setoption name {k} value {v}" for k, v in options]
    for f in fens:
        cmds += [f"position fen {f}", "eval"]
    cmds.append("quit")
    out = subprocess.run([engine], input="\n".join(cmds) + "\n", text=True, capture_output=True, env=env).stdout
    res = []
    for m in re.finditer(r"info string eval_hce (-?\d+) eval_nnue (none|-?\d+)", out):
        h = int(m.group(1)); nn = m.group(2)
        res.append((h, h if nn == "none" else int(nn)))
    # the engine prints `eval_hce .. eval_nnue ..` AFTER the combined line; the combined
    # (guarded) score is the preceding `info string eval X cp` line.
    comb = [int(x) for x in re.findall(r"info string eval (-?\d+) cp", out)]
    if len(res) != len(fens) or len(comb) != len(fens):
        sys.exit(f"engine output mismatch: {len(res)}/{len(comb)} vs {len(fens)}")
    return [(h, c) for (h, _), c in zip(res, comb)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--net", default=None, help="CRE_NNUE_FILE (omit = embedded)")
    ap.add_argument("--epd", default="tools/openings_book.epd")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--option", action="append", default=[], help="NAME=VALUE (repeatable)")
    ap.add_argument("--min-ratio", type=float, default=0.70)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    opts = [tuple(o.split("=", 1)) for o in a.option]
    pos = odds_positions(a.epd, a.n, a.seed)
    report, fail = {"net": a.net, "options": a.option, "seed": a.seed, "classes": {}}, False
    for cls, fens in pos.items():
        ev = engine_eval(a.engine, a.net, opts, fens)
        # side to move is up material: positive is correct. Normalise by the HCE reference.
        ratios = [c / h for h, c in ev if h > 50]
        wrong = sum(1 for h, c in ev if c <= 0)
        mean_h = sum(h for h, _ in ev) / len(ev)
        mean_c = sum(c for _, c in ev) / len(ev)
        r = sum(ratios) / max(1, len(ratios))
        ok = r >= a.min_ratio and wrong <= max(1, int(0.02 * len(ev)))
        fail |= not ok
        report["classes"][cls] = {"n": len(ev), "mean_hce": round(mean_h), "mean_eval": round(mean_c),
                                  "mean_ratio": round(r, 3), "sign_wrong": wrong, "pass": ok}
        print(f"{cls:6s} n={len(ev):3d} HCE={mean_h:7.0f} engine={mean_c:7.0f} ratio={r:5.2f} "
              f"side-to-move-not-ahead={wrong:3d}  {'PASS' if ok else 'FAIL'}")
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
