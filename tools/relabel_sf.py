#!/usr/bin/env python3
"""Relabel FENs with Stockfish 19 at a real movetime (≥500 ms). Never 120 ms."""
from __future__ import annotations

import argparse
import sys
import time

import chess
import chess.engine

MIN_S = 0.5


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("--stockfish", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--movetime", type=float, default=0.5)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--hash-mb", type=int, default=64)
    args = p.parse_args()
    if args.movetime < MIN_S:
        print(f"refusing movetime {args.movetime}s < {MIN_S}", file=sys.stderr)
        return 2
    eng = chess.engine.SimpleEngine.popen_uci(args.stockfish)
    eng.configure({"Hash": args.hash_mb, "Threads": 1, "UCI_LimitStrength": False})
    n = 0
    t0 = time.time()
    try:
        with open(args.src, encoding="utf-8") as inf, open(args.out, "w", encoding="utf-8") as out:
            for line in inf:
                line = line.strip()
                if not line:
                    continue
                fen = line.split("|")[0].strip()
                wdl = 0.5
                parts = [x.strip() for x in line.split("|")]
                if len(parts) > 2:
                    try:
                        wdl = float(parts[2])
                    except ValueError:
                        pass
                try:
                    board = chess.Board(fen)
                except ValueError:
                    continue
                if board.is_check() or board.is_game_over():
                    continue
                info = eng.analyse(board, chess.engine.Limit(time=args.movetime))
                sc = info.get("score")
                if sc is None:
                    continue
                cp = sc.white().score(mate_score=15000)
                if cp is None:
                    continue
                if board.turn == chess.BLACK:
                    cp = -cp
                out.write(f"{fen} | {cp} | {wdl:.1f}\n")
                n += 1
                if n % 25 == 0:
                    print(f"relabel {n}  {n/(time.time()-t0+1e-6):.2f} pos/s", flush=True)
                if args.limit and n >= args.limit:
                    break
    finally:
        eng.quit()
    print(f"wrote {n} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
