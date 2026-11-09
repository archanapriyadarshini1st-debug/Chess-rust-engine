#!/usr/bin/env python3
"""Generate a balanced, varied EPD opening set.

Random 6-10 ply lines from startpos, each position kept only if Stockfish
(depth 12) says it is within +-60 cp, so neither colour starts with an edge.
Usage: make_openings.py --stockfish PATH --count 200 --out tools/openings.epd
"""
import argparse, random
import chess, chess.engine

ap = argparse.ArgumentParser()
ap.add_argument("--stockfish", required=True)
ap.add_argument("--count", type=int, default=200)
ap.add_argument("--out", default="tools/openings.epd")
ap.add_argument("--seed", type=int, default=2026)
ap.add_argument("--window", type=int, default=60)
a = ap.parse_args()

rng = random.Random(a.seed)
eng = chess.engine.SimpleEngine.popen_uci(a.stockfish)
eng.configure({"Threads": 1, "Hash": 64})
seen, out = set(), []
while len(out) < a.count:
    b = chess.Board()
    for _ in range(rng.choice([6, 7, 8, 9, 10])):
        moves = list(b.legal_moves)
        if not moves:
            break
        b.push(rng.choice(moves))
    if b.is_game_over() or b.is_check():
        continue
    key = b.epd()
    if key in seen:
        continue
    seen.add(key)
    info = eng.analyse(b, chess.engine.Limit(depth=12))
    cp = info["score"].white().score(mate_score=10000)
    if abs(cp) <= a.window:
        out.append(key)
eng.quit()
open(a.out, "w").write("\n".join(out) + "\n")
print(f"wrote {len(out)} openings to {a.out}")
