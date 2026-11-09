#!/usr/bin/env python3
"""Summarise a fastchess/cutechess PGN: W-D-L, score, Elo difference (95% CI).

    summarize.py games.pgn --engine Rust [--opp-elo 2000] [--json out.json]

With --opp-elo (SF19 under UCI_LimitStrength) it also prints an absolute Elo
estimate. NOTE: Stockfish's UCI_Elo scale is anchored to its own calibration
(CCRL-like, different time control), so treat the absolute number as a rough
guide, not a rating. Differences between our own versions are what we trust.
Also flags results that are statistically meaningless (too few games).
"""
import argparse, json, math, sys
import chess.pgn


def elo_from_score(s):
    s = min(max(s, 1e-6), 1 - 1e-6)
    return -400.0 * math.log10(1.0 / s - 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn")
    ap.add_argument("--engine", default="Rust")
    ap.add_argument("--opp-elo", type=float, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    w = d = l = 0
    reasons = {}
    with open(a.pgn) as f:
        while True:
            g = chess.pgn.read_game(f)
            if g is None:
                break
            res = g.headers.get("Result", "*")
            white, black = g.headers.get("White", ""), g.headers.get("Black", "")
            if res not in ("1-0", "0-1", "1/2-1/2"):
                continue
            ours_white = white == a.engine
            if not (ours_white or black == a.engine):
                continue
            if res == "1/2-1/2":
                d += 1
            elif (res == "1-0") == ours_white:
                w += 1
            else:
                l += 1
                t = g.headers.get("Termination", "?")
                reasons[t] = reasons.get(t, 0) + 1

    n = w + d + l
    if n == 0:
        print("no finished games")
        return 1
    s = (w + 0.5 * d) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * s ** 2) / n  # trinomial
    se = math.sqrt(var / n)
    lo, hi = s - 1.96 * se, s + 1.96 * se
    elo = elo_from_score(s)
    out = {
        "games": n, "wins": w, "draws": d, "losses": l, "score": round(s, 4),
        "elo_diff": round(elo, 1),
        "elo_diff_lo": round(elo_from_score(lo), 1),
        "elo_diff_hi": round(elo_from_score(hi), 1),
        "loss_terminations": reasons, "reliable": n >= 100,
    }
    if a.opp_elo is not None:
        out["opp_elo"] = a.opp_elo
        out["est_elo"] = round(a.opp_elo + elo)
        out["est_elo_lo"] = round(a.opp_elo + out["elo_diff_lo"])
        out["est_elo_hi"] = round(a.opp_elo + out["elo_diff_hi"])
    print(f"{a.engine}: +{w} ={d} -{l}  ({n} games)  score {s*100:.1f}%")
    print(f"Elo diff vs opponent: {elo:+.0f}  [{out['elo_diff_lo']:+.0f}, {out['elo_diff_hi']:+.0f}] 95%")
    if a.opp_elo is not None:
        print(f"Estimated Elo (vs UCI_Elo {a.opp_elo:.0f}): {out['est_elo']}  [{out['est_elo_lo']}, {out['est_elo_hi']}]")
    if not out["reliable"]:
        print(f"WARNING: only {n} games - error bars are wide; do not draw conclusions from this alone.")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
